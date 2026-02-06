"""
实时K线分析服务基类 (Realtime Kline Analysis Service Base)

本模块提供实时K线分析服务的抽象基类，包含90%的共同逻辑。
子类通过实现4个抽象方法来定制特定的行为差异。

核心功能：
- WebSocket 实时数据接收
- 异步批量写入数据库
- 多周期分析与告警
- 队列健康监控

架构设计：
- 抽象方法：定义子类必须实现的接口
- 模板方法：使用抽象方法的公共逻辑
- 配置参数化：通过 ServiceConfig 传递差异化配置

Author: Claude Code
Date: 2026-01-30
"""

import time
import queue
import threading
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Type
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from cachetools import TTLCache

import psycopg.errors

from src.utils.websocket.enhanced_ws_manager import EnhancedWebSocketManager, ConnectionState
from src.utils.database.timescaledb import (
    TimescaleDBClient,
    KlineRepository,
    SymbolMetadataRepository,
    AnalysisResultRepository
)
from src.utils.analysis.analysis_core import analyze_multi_period, prepare_price_series, calculate_correlation
from src.utils.monitoring.lark_bot import sender_colourful
from src.utils.monitoring.alert_formatter import AlertFormatter
from src.utils.core.config import (
    # 服务配置
    DEFAULT_TIMEFRAMES,
    DEFAULT_BATCH_SIZE,
    DEFAULT_BATCH_TIMEOUT,
    # 分析参数
    MIN_4H_DATA_POINTS,
    MIN_DATA_POINTS,
    DATA_WINDOW_CONFIG,
    BETA_WINDOW,
    ZSCORE_WINDOW,
    COINTEGRATION_THRESHOLD,
    # 去重配置
    ENQUEUE_DEDUP_WINDOWS,
    DEDUP_WINDOWS,
    CLEANUP_INTERVAL,
    MAX_RECENT_TASKS,
    # WebSocket配置
    WS_TIMEOUT,
    WS_MAX_RETRIES,
    WS_ALERT_THRESHOLD,
    # 服务线程超时配置
    QUEUE_GET_TIMEOUT,
    WORKER_THREAD_SHUTDOWN_TIMEOUT,
    MAIN_THREAD_SHUTDOWN_TIMEOUT,
    DB_QUERY_LIMIT,
    # 批量写入配置
    ANALYSIS_RESULT_BATCH_SIZE,
    ANALYSIS_RESULT_BATCH_TIMEOUT,
    ANALYSIS_USE_COPY_METHOD,
    # 监控配置
    QUEUE_MONITOR_INTERVAL,
    QUEUE_WARNING_THRESHOLD,
)


@dataclass
class ServiceConfig:
    """服务配置参数数据类"""
    base_symbol: str                    # 基准币种
    corr_threshold: float              # 相关系数阈值
    queue_config: Dict[str, int]       # 队列配置
    analysis_workers: int              # 工作线程数
    data_filler_class: Type            # 数据填充器类
    logger_module: str                 # logger 模块标识（'logger' 或 'get_logger'）


class RealtimeKlineServiceBase(ABC):
    """
    实时K线分析服务抽象基类

    包含 90% 的共同逻辑，通过 4 个抽象方法处理差异化逻辑：
    1. _get_active_symbols(): 获取活跃币种列表
    2. _get_config_params(): 获取服务配置参数
    3. _should_enable_symbol_monitoring(): 是否启用新币种监控线程
    4. _get_corr_threshold_for_analysis(): 获取分析用的相关系数阈值
    """

    def __init__(
        self,
        base_symbol: str = None,
        timeframes: List[str] = None,
        batch_size: int = None,
        batch_timeout: float = None
    ):
        """
        初始化实时K线分析服务（模板方法）

        Args:
            base_symbol: 基准币种（用于配对分析），默认从配置读取
            timeframes: 订阅周期列表，默认从配置读取
            batch_size: 批量写入大小，默认从配置读取
            batch_timeout: 批量写入超时，默认从配置读取
        """
        # 1. 获取子类配置
        self._config = self._get_config_params()

        # 2. 初始化基础配置
        self.base_symbol = base_symbol or self._config.base_symbol
        self.timeframes = timeframes or DEFAULT_TIMEFRAMES
        self.batch_size = batch_size or DEFAULT_BATCH_SIZE
        self.batch_timeout = batch_timeout or DEFAULT_BATCH_TIMEOUT

        # 3. 动态初始化 logger
        self.logger = self._init_logger(self._config.logger_module)

        # 4. 初始化数据库客户端
        self.db_client = TimescaleDBClient()
        self.kline_repo = KlineRepository(self.db_client)
        self.symbol_repo = SymbolMetadataRepository(self.db_client)
        self.analysis_repo = AnalysisResultRepository(self.db_client)

        # 5. 初始化数据填充器（使用配置指定的类）
        self.data_filler = self._config.data_filler_class(kline_repo=self.kline_repo)

        # 6. 飞书告警配置（从配置导入）
        from src.utils.core.config import lark_webhook_url
        self.lark_webhook_url = lark_webhook_url

        if not self.lark_webhook_url:
            self.logger.error("❌ 未配置飞书告警，LARK_WEBHOOK_URL 或 LARKBOT_ID 环境变量未设置")
            self.logger.error("程序终止：飞书告警是必需功能，请配置环境变量后重试")
            import sys
            sys.exit(1)

        # 7. 获取币种列表（调用子类实现）
        self.symbols_lock = threading.RLock()
        with self.symbols_lock:
            self.symbols = self._get_active_symbols()
            self.logger.info(f"活跃币种数量: {len(self.symbols)}")

        # 8. 构建订阅列表
        self.subscriptions = self._build_subscriptions()
        self.logger.info(f"订阅数量: {len(self.subscriptions)}")

        # 9. 初始化去重字典（使用 TTLCache 防止内存泄漏）
        self.recent_enqueue = TTLCache(maxsize=10000, ttl=1800)  # 30分钟TTL
        self.recent_enqueue_lock = threading.Lock()

        self.recent_analysis = TTLCache(
            maxsize=10000,
            ttl=max(DEDUP_WINDOWS.values()) * 2
        )
        self.recent_analysis_lock = threading.Lock()

        # 10. 初始化队列（使用配置参数）
        queue_config = self._config.queue_config
        self.kline_buffer = queue.Queue(maxsize=queue_config['kline_buffer_size'])
        self.analysis_queue = queue.Queue(maxsize=queue_config['analysis_queue_size'])
        self.analysis_result_buffer = queue.Queue(maxsize=queue_config['analysis_result_buffer_size'])

        # 11. 新币过滤器：内存黑名单
        self.new_coin_blacklist = set()
        self.blacklist_lock = threading.Lock()
        self.MIN_4H_DATA_POINTS = MIN_4H_DATA_POINTS

        # 12. 停止事件
        self.stop_event = threading.Event()

        # 13. 初始化工作线程（使用配置参数）
        num_workers = self._config.analysis_workers
        self.analysis_workers = []
        for i in range(num_workers):
            worker = threading.Thread(
                target=self._analysis_worker,
                daemon=True,
                name=f"analysis-worker-{i}"
            )
            worker.start()
            self.analysis_workers.append(worker)

        self.logger.info(f"✅ 启动{num_workers}个分析工作线程（ANALYSIS_WORKERS={num_workers}）")

        # 14. 批量写入线程
        self.batch_writer_thread = threading.Thread(
            target=self._batch_writer,
            daemon=True,
            name="batch-writer"
        )

        # 15. 分析结果批量写入线程
        self.analysis_result_writer_thread = threading.Thread(
            target=self._analysis_result_batch_writer,
            daemon=True,
            name="analysis-result-writer"
        )

        # 16. 队列健康监控线程
        self.queue_monitor_thread = threading.Thread(
            target=self._monitor_queue_health,
            daemon=True,
            name="queue-monitor"
        )

        # 17. 条件创建新币监控线程
        if self._should_enable_symbol_monitoring():
            self.symbol_monitor_thread = threading.Thread(
                target=self._monitor_new_symbols,
                daemon=True,
                name="symbol-monitor"
            )
        else:
            self.symbol_monitor_thread = None

        # 18. WebSocket 管理器
        self.ws_manager = EnhancedWebSocketManager(
            subscriptions=self.subscriptions,
            message_callback=self.on_message,
            on_state_change=self.on_state_change,
            timeout=WS_TIMEOUT,
            alert_callback=self._send_system_alert,
            max_retries=WS_MAX_RETRIES,
            alert_threshold=WS_ALERT_THRESHOLD
        )

        # 19. 统计信息
        self.stats = {
            'messages_received': 0,
            'klines_written': 0,
            'analyses_performed': 0,
            'analyses_completed': 0,
            'analyses_failed': 0,
            'analysis_queue_drops': 0,
            'alerts_sent': 0,
            'analysis_results_written': 0,
            'analysis_results_deduped': 0,
            'analysis_result_buffer_drops': 0,
            'start_time': time.time()
        }

        self.logger.info("✅ 实时K线分析服务初始化完成")

    # ============================================================
    # 抽象方法（子类必须实现）
    # ============================================================

    @abstractmethod
    def _get_active_symbols(self) -> List[str]:
        """
        获取活跃币种列表（抽象方法）

        Returns:
            活跃币种列表（格式: BTC/USDC:USDC）
        """
        pass

    @abstractmethod
    def _get_config_params(self) -> ServiceConfig:
        """
        获取服务配置参数（抽象方法）

        Returns:
            ServiceConfig 实例
        """
        pass

    @abstractmethod
    def _should_enable_symbol_monitoring(self) -> bool:
        """
        是否启用新币种监控线程（抽象方法）

        Returns:
            True 启用，False 禁用
        """
        pass

    @abstractmethod
    def _get_corr_threshold_for_analysis(self) -> float:
        """
        获取分析用的相关系数阈值（抽象方法）

        Returns:
            相关系数阈值
        """
        pass

    # ============================================================
    # 辅助方法
    # ============================================================

    def _init_logger(self, logger_module: str):
        """
        动态初始化 logger

        Args:
            logger_module: 'logger' 或 'get_logger'

        Returns:
            logger 实例
        """
        if logger_module == 'get_logger':
            from src.utils.core.logging_config import get_logger
            return get_logger(__name__)
        else:
            from src.utils.core.logging_config import logger
            return logger

    def _build_subscriptions(self) -> List[Dict]:
        """
        构建 WebSocket 订阅列表

        Returns:
            订阅列表 [{"type": "candle", "coin": "BTC", "interval": "5m"}, ...]
        """
        subscriptions = []

        with self.symbols_lock:
            symbols_copy = list(self.symbols)

        for symbol in symbols_copy:
            coin = symbol.split('/')[0]
            for interval in ['5m', '1h', '4h']:
                subscriptions.append({
                    "type": "candle",
                    "coin": coin,
                    "interval": interval
                })

        return subscriptions

    @staticmethod
    def _safe_float(value, field_name='unknown', default=0.0) -> float:
        """
        安全的 float 转换

        Args:
            value: 要转换的值
            field_name: 字段名称（用于日志）
            default: 转换失败时的默认值

        Returns:
            float 值或默认值
        """
        try:
            if value is None or value == '':
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_int(value, field_name='unknown', default=0) -> int:
        """
        安全的 int 转换

        Args:
            value: 要转换的值
            field_name: 字段名称（用于日志）
            default: 转换失败时的默认值

        Returns:
            int 值或默认值
        """
        try:
            if value is None or value == '':
                return default
            return int(value)
        except (ValueError, TypeError):
            return default

    # ============================================================
    # 数据库操作方法
    # ============================================================

    def _batch_upsert_with_retry(self, batch, max_retries=5, on_conflict='update'):
        """
        K线批量写入数据库，带死锁重试机制

        Args:
            batch: 数据批次
            max_retries: 最大重试次数
            on_conflict: 冲突处理策略

        Returns:
            写入记录数
        """
        import random
        for attempt in range(max_retries):
            try:
                return self.kline_repo.batch_upsert_copy(batch, on_conflict=on_conflict)
            except psycopg.errors.DeadlockDetected:
                if attempt < max_retries - 1:
                    base_delay = 0.1 * (2 ** attempt)
                    jitter = base_delay * 0.25
                    wait_time = base_delay + random.uniform(-jitter, jitter)
                    self.logger.warning(
                        f"K线写入死锁，{wait_time:.2f}秒后重试 ({attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    self.logger.error(f"K线写入死锁重试耗尽 ({max_retries}次)", exc_info=True)
                    raise
            except Exception as e:
                self.logger.error(f"K线批量写入失败（非死锁）: {e}", exc_info=True)
                raise

    def _batch_insert_analysis_with_retry(self, batch, use_copy_method, max_retries=5):
        """
        分析结果批量写入数据库，带死锁重试机制

        Args:
            batch: 数据批次
            use_copy_method: 是否使用COPY方法
            max_retries: 最大重试次数

        Returns:
            写入记录数
        """
        import random
        for attempt in range(max_retries):
            try:
                if use_copy_method:
                    return self.analysis_repo.batch_insert_copy(batch)
                else:
                    return self.analysis_repo.batch_insert(batch)
            except psycopg.errors.DeadlockDetected:
                if attempt < max_retries - 1:
                    base_delay = 0.1 * (2 ** attempt)
                    jitter = base_delay * 0.25
                    wait_time = base_delay + random.uniform(-jitter, jitter)
                    self.logger.warning(
                        f"分析结果写入死锁，{wait_time:.2f}秒后重试 ({attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    self.logger.error(f"分析结果写入死锁重试耗尽 ({max_retries}次)", exc_info=True)
                    raise
            except Exception as e:
                self.logger.error(f"分析结果批量写入失败（非死锁）: {e}", exc_info=True)
                raise

    # ============================================================
    # K线处理方法
    # ============================================================

    def _parse_kline(self, msg: Dict) -> Optional[Dict]:
        """
        解析 Hyperliquid K线数据为标准格式

        Args:
            msg: WebSocket 消息

        Returns:
            标准K线数据 或 None（解析失败）
        """
        try:
            if msg.get("channel") != "candle":
                return None

            data = msg.get("data", {})

            coin = data.get('s')
            timeframe = data.get('i')
            timestamp_ms = self._safe_int(data.get('t'), 'timestamp_ms')
            open_price = self._safe_float(data.get('o'), 'open')
            high_price = self._safe_float(data.get('h'), 'high')
            low_price = self._safe_float(data.get('l'), 'low')
            close_price = self._safe_float(data.get('c'), 'close')
            volume = self._safe_float(data.get('v'), 'volume')

            symbol = f"{coin}/USDC:USDC"
            kline_time = datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc)
            return_pct = (close_price - open_price) / open_price if open_price > 0 else 0.0
            volume_usd = close_price * volume

            return {
                'time': kline_time,
                'symbol': symbol,
                'timeframe': timeframe,
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': volume,
                'volume_usd': volume_usd,
                'return_pct': return_pct
            }

        except Exception as e:
            self.logger.error(f"K线解析失败: {e} | 原始数据: {msg}", exc_info=True)
            return None

    def on_message(self, msg: Dict):
        """
        WebSocket 消息回调（核心处理逻辑）

        Args:
            msg: WebSocket 消息
        """
        try:
            self.stats['messages_received'] += 1

            kline = self._parse_kline(msg)
            if not kline:
                return

            # 放入缓冲队列
            try:
                self.kline_buffer.put_nowait(kline)
            except queue.Full:
                self.logger.warning(f"缓冲队列已满，丢弃K线: {kline['symbol']} @ {kline['timeframe']}")

            # 入队前去重检查
            task_key = (kline['symbol'], kline['timeframe'])
            dedup_window = ENQUEUE_DEDUP_WINDOWS.get(kline['timeframe'], 30)

            with self.recent_enqueue_lock:
                last_enqueue = self.recent_enqueue.get(task_key, 0)
                current_time = time.time()
                if current_time - last_enqueue < dedup_window:
                    self.logger.debug(
                        f"跳过分析任务: {kline['symbol']} @ {kline['timeframe']} "
                        f"(距上次分析 {current_time - last_enqueue:.0f}秒 < {dedup_window}秒冷却)"
                    )
                    return
                self.recent_enqueue[task_key] = current_time

            # 只触发5m周期分析
            if kline['timeframe'] != '5m':
                self.logger.debug(f"跳过非5m周期分析: {kline['symbol']} @ {kline['timeframe']}")
                return

            # 异步分析
            analysis_task = {
                'symbol': kline['symbol'],
                'timeframe': kline['timeframe'],
                'timestamp': kline['time'],
                'kline': kline
            }
            try:
                self.analysis_queue.put_nowait(analysis_task)
            except queue.Full:
                queue_size = self.analysis_queue.qsize()
                queue_capacity = self.analysis_queue.maxsize
                utilization = (queue_size / queue_capacity * 100) if queue_capacity > 0 else 0
                self.logger.warning(
                    f"分析队列已满，跳过分析: {kline['symbol']} @ {kline['timeframe']} | "
                    f"队列: {queue_size}/{queue_capacity} ({utilization:.1f}%)"
                )
                self.stats.setdefault('analysis_queue_drops', 0)
                self.stats['analysis_queue_drops'] += 1

        except Exception as e:
            self.logger.error(f"消息处理失败: {e}", exc_info=True)

    # ============================================================
    # 批量写入线程
    # ============================================================

    def _batch_writer(self):
        """批量写入线程"""
        self.logger.info("批量写入线程已启动")

        batch = []
        items_to_mark_done = 0
        last_write_time = time.time()

        while not self.stop_event.is_set():
            try:
                kline_fetched = False
                try:
                    kline = self.kline_buffer.get(timeout=QUEUE_GET_TIMEOUT)
                    batch.append(kline)
                    items_to_mark_done += 1
                    kline_fetched = True
                except queue.Empty:
                    pass

                should_write = (
                    len(batch) >= self.batch_size or
                    (batch and time.time() - last_write_time >= self.batch_timeout) or
                    (batch and self.stop_event.is_set())
                )

                if should_write and batch:
                    dedup_dict = {}
                    batch_count = len(batch)
                    for kline in batch:
                        key = (kline['time'], kline['symbol'], kline['timeframe'])
                        dedup_dict[key] = kline

                    dedup_batch = list(dedup_dict.values())
                    dedup_batch = sorted(
                        dedup_batch,
                        key=lambda x: (x['time'], x['symbol'], x['timeframe'])
                    )

                    try:
                        count = self._batch_upsert_with_retry(dedup_batch, on_conflict='update')
                        self.stats['klines_written'] += count

                        kline_queue_util = (self.kline_buffer.qsize() / self.kline_buffer.maxsize * 100)
                        analysis_queue_util = (self.analysis_queue.qsize() / self.analysis_queue.maxsize * 100)
                        result_queue_util = (self.analysis_result_buffer.qsize() / self.analysis_result_buffer.maxsize * 100)

                        self.logger.info(
                            f"批量写入: {count} 条K线 (去重前: {batch_count}) | "
                            f"K线队列: {self.kline_buffer.qsize()}/{self.kline_buffer.maxsize} ({kline_queue_util:.1f}%) | "
                            f"分析队列: {self.analysis_queue.qsize()}/{self.analysis_queue.maxsize} ({analysis_queue_util:.1f}%) | "
                            f"结果队列: {self.analysis_result_buffer.qsize()}/{self.analysis_result_buffer.maxsize} ({result_queue_util:.1f}%) | "
                            f"总写入: {self.stats['klines_written']}"
                        )

                        for _ in range(items_to_mark_done):
                            self.kline_buffer.task_done()

                        batch = []
                        items_to_mark_done = 0
                        last_write_time = time.time()

                    except Exception as e:
                        self.logger.error(f"批量写入失败: {e}", exc_info=True)
                        for _ in range(items_to_mark_done):
                            self.kline_buffer.task_done()
                        batch = []
                        items_to_mark_done = 0
                        last_write_time = time.time()

            except Exception as e:
                self.logger.error(f"批量写入线程异常: {e}", exc_info=True)

        # 停止前处理剩余批次
        if batch:
            try:
                dedup_dict = {}
                batch_count = len(batch)
                for kline in batch:
                    key = (kline['time'], kline['symbol'], kline['timeframe'])
                    dedup_dict[key] = kline

                dedup_batch = list(dedup_dict.values())
                dedup_batch = sorted(
                    dedup_batch,
                    key=lambda x: (x['time'], x['symbol'], x['timeframe'])
                )

                count = self._batch_upsert_with_retry(dedup_batch, on_conflict='update')
                self.stats['klines_written'] += count
                self.logger.info(f"停止前最后批量写入: {count} 条K线")

                for _ in range(items_to_mark_done):
                    self.kline_buffer.task_done()
            except Exception as e:
                self.logger.error(f"停止前批量写入失败: {e}", exc_info=True)
                for _ in range(items_to_mark_done):
                    self.kline_buffer.task_done()

        self.logger.info("批量写入线程已停止")

    def _analysis_result_batch_writer(self):
        """分析结果批量写入线程"""
        self.logger.info("分析结果批量写入线程已启动")

        batch_size = ANALYSIS_RESULT_BATCH_SIZE
        batch_timeout = ANALYSIS_RESULT_BATCH_TIMEOUT
        use_copy_method = ANALYSIS_USE_COPY_METHOD

        batch = []
        items_to_mark_done = 0
        last_write_time = time.time()

        while not self.stop_event.is_set():
            try:
                result_fetched = False
                try:
                    analysis_record = self.analysis_result_buffer.get(timeout=QUEUE_GET_TIMEOUT)
                    batch.append(analysis_record)
                    items_to_mark_done += 1
                    result_fetched = True
                except queue.Empty:
                    pass

                should_write = (
                    len(batch) >= batch_size or
                    (batch and time.time() - last_write_time >= batch_timeout) or
                    (batch and self.stop_event.is_set())
                )

                if should_write and batch:
                    dedup_dict = {}
                    batch_count = len(batch)
                    for record in batch:
                        minute_time = record['analysis_time'].replace(
                            second=0, microsecond=0
                        )
                        key = (minute_time, record['symbol'], record['base_symbol'])
                        dedup_dict[key] = record

                    dedup_batch = list(dedup_dict.values())
                    dedup_count = batch_count - len(dedup_batch)

                    dedup_batch = sorted(
                        dedup_batch,
                        key=lambda x: (
                            x['analysis_time'].replace(second=0, microsecond=0),
                            x['symbol'],
                            x['base_symbol']
                        )
                    )

                    try:
                        count = self._batch_insert_analysis_with_retry(
                            dedup_batch,
                            use_copy_method=use_copy_method,
                            max_retries=5
                        )
                        self.stats['analysis_results_written'] += count
                        self.stats['analysis_results_deduped'] += dedup_count

                        result_queue_util = (self.analysis_result_buffer.qsize() / self.analysis_result_buffer.maxsize * 100)

                        self.logger.info(
                            f"批量写入分析结果: {count} 条 (去重前: {batch_count}, 去重: {dedup_count}) | "
                            f"结果队列: {self.analysis_result_buffer.qsize()}/{self.analysis_result_buffer.maxsize} ({result_queue_util:.1f}%)"
                        )

                        for _ in range(items_to_mark_done):
                            self.analysis_result_buffer.task_done()

                        batch = []
                        items_to_mark_done = 0
                        last_write_time = time.time()

                    except Exception as e:
                        self.logger.error(f"分析结果批量写入失败: {e}", exc_info=True)
                        for _ in range(items_to_mark_done):
                            self.analysis_result_buffer.task_done()
                        batch = []
                        items_to_mark_done = 0
                        last_write_time = time.time()

            except Exception as e:
                self.logger.error(f"分析结果批量写入线程异常: {e}", exc_info=True)

        # 停止前处理剩余批次
        if batch:
            try:
                dedup_dict = {}
                batch_count = len(batch)
                for record in batch:
                    minute_time = record['analysis_time'].replace(
                        second=0, microsecond=0
                    )
                    key = (minute_time, record['symbol'], record['base_symbol'])
                    dedup_dict[key] = record

                dedup_batch = list(dedup_dict.values())
                dedup_count = batch_count - len(dedup_batch)

                count = self._batch_insert_analysis_with_retry(
                    dedup_batch,
                    use_copy_method=use_copy_method,
                    max_retries=5
                )
                self.stats['analysis_results_written'] += count
                self.stats['analysis_results_deduped'] += dedup_count

                self.logger.info(f"停止前最后批量写入分析结果: {count} 条 (去重前: {batch_count}, 去重: {dedup_count})")

                for _ in range(items_to_mark_done):
                    self.analysis_result_buffer.task_done()
            except Exception as e:
                self.logger.error(f"停止前分析结果批量写入失败: {e}", exc_info=True)
                for _ in range(items_to_mark_done):
                    self.analysis_result_buffer.task_done()

        self.logger.info("分析结果批量写入线程已停止")

    # ============================================================
    # 分析工作线程
    # ============================================================

    def _analysis_worker(self):
        """分析工作线程主循环"""
        self.logger.info(f"[{threading.current_thread().name}] 分析工作线程已启动")

        last_cleanup_time = time.time()

        while not self.stop_event.is_set():
            try:
                try:
                    task = self.analysis_queue.get(timeout=QUEUE_GET_TIMEOUT)
                except queue.Empty:
                    if self.stop_event.wait(0.1):
                        break
                    continue

                symbol = task['symbol']
                timeframe = task['timeframe']
                task_key = (symbol, timeframe)

                dedup_window = DEDUP_WINDOWS.get(timeframe, 60)

                current_time = time.time()
                with self.recent_analysis_lock:
                    last_analysis_time = self.recent_analysis.get(task_key, 0)
                    time_since_last = current_time - last_analysis_time if last_analysis_time > 0 else 0

                    if last_analysis_time > 0 and time_since_last < dedup_window:
                        self.logger.debug(
                            f"跳过重复分析: {symbol} @ {timeframe} "
                            f"(距上次 {time_since_last:.0f}秒，窗口 {dedup_window}秒)"
                        )
                        self.analysis_queue.task_done()
                        continue

                # 分析前同步写入
                kline_data = task.get('kline')
                if kline_data:
                    try:
                        self._batch_upsert_with_retry(
                            [kline_data],
                            on_conflict='update'
                        )
                        self.logger.debug(
                            f"分析前同步写入: {symbol} @ {timeframe} | "
                            f"time={kline_data.get('time')}"
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"分析前同步写入失败: {symbol} @ {timeframe} | {e}"
                        )

                kline_time = kline_data.get('time') if kline_data else None

                # 执行分析
                try:
                    self._analyze_and_alert(symbol, timeframe, kline_time)
                    self.stats['analyses_completed'] += 1

                    with self.recent_analysis_lock:
                        self.recent_analysis[task_key] = current_time

                    self.logger.debug(
                        f"分析完成: {symbol} @ {timeframe} | "
                        f"去重窗口: {dedup_window}秒 | "
                        f"距上次: {time_since_last:.0f}秒"
                    )
                except Exception as e:
                    self.logger.error(f"分析失败: {symbol} @ {timeframe} | {e}", exc_info=True)
                    self.stats['analyses_failed'] += 1

                self.analysis_queue.task_done()

                # 定时清理过期记录
                if current_time - last_cleanup_time > CLEANUP_INTERVAL:
                    max_window = max(DEDUP_WINDOWS.values())
                    cutoff_time = current_time - max_window * 2
                    with self.recent_analysis_lock:
                        old_count = len(self.recent_analysis)
                        self.recent_analysis = {k: v for k, v in self.recent_analysis.items() if v > cutoff_time}
                        new_count = len(self.recent_analysis)
                    last_cleanup_time = current_time
                    self.logger.debug(
                        f"定时清理任务缓存: {old_count} → {new_count} "
                        f"(清理了 {old_count - new_count} 条过期记录)"
                    )

                # 硬性上限检查
                with self.recent_analysis_lock:
                    if len(self.recent_analysis) > MAX_RECENT_TASKS:
                        sorted_tasks = sorted(self.recent_analysis.items(), key=lambda x: x[1])
                        keep_count = MAX_RECENT_TASKS // 2
                        self.recent_analysis = dict(sorted_tasks[-keep_count:])
                        self.logger.warning(
                            f"任务缓存超限 ({MAX_RECENT_TASKS})，强制清理至 {len(self.recent_analysis)}"
                        )

            except Exception as e:
                self.logger.error(f"[{threading.current_thread().name}] 工作线程异常: {e}", exc_info=True)
                time.sleep(1)

        self.logger.info(f"[{threading.current_thread().name}] 分析工作线程已停止")

    def _analyze_and_alert(self, symbol: str, timeframe: str, kline_time: Optional[datetime] = None):
        """
        实时多周期分析 + 飞书告警

        Args:
            symbol: 目标币种
            timeframe: 触发周期
            kline_time: K线时间
        """
        # 检查黑名单
        with self.blacklist_lock:
            if symbol in self.new_coin_blacklist:
                self.logger.debug(f"跳过新币分析（已在黑名单）：{symbol}")
                return

        start_time = time.time()

        try:
            # 跳过基准币种自身
            if symbol == self.base_symbol:
                return

            # 查询所有3个周期的数据
            window_map = {
                '5m': timedelta(days=DATA_WINDOW_CONFIG['5m']),
                '1h': timedelta(days=DATA_WINDOW_CONFIG['1h']),
                '4h': timedelta(days=DATA_WINDOW_CONFIG['4h'])
            }

            price_data_cache = {}
            end_time = datetime.now(timezone.utc)

            for tf, window in window_map.items():
                query_start_time = end_time - window

                # 查询基准币种K线
                base_klines = self.kline_repo.query_range(
                    self.base_symbol,
                    tf,
                    query_start_time,
                    end_time,
                    limit=DB_QUERY_LIMIT
                )

                # 查询目标币种K线
                alt_klines = self.kline_repo.query_range(
                    symbol,
                    tf,
                    query_start_time,
                    end_time,
                    limit=DB_QUERY_LIMIT
                )

                # K线数据连续性校验与自动补充
                need_refill = False
                min_data_points = MIN_DATA_POINTS

                base_continuous, base_missing = self.data_filler.validate_continuity(base_klines, tf)
                base_sufficient, base_count = self.data_filler.validate_window_length(
                    base_klines, tf, window.days, min_data_points
                )

                alt_continuous, alt_missing = self.data_filler.validate_continuity(alt_klines, tf)
                alt_sufficient, alt_count = self.data_filler.validate_window_length(
                    alt_klines, tf, window.days, min_data_points
                )

                need_refill = (
                    not base_continuous or not alt_continuous or
                    not base_sufficient or not alt_sufficient
                )

                if need_refill:
                    self.logger.info(
                        f"数据不完整，尝试补充 | {symbol} @ {tf} | "
                        f"base: 连续={base_continuous}, 充足={base_sufficient}({base_count}) | "
                        f"alt: 连续={alt_continuous}, 充足={alt_sufficient}({alt_count})"
                    )

                    # 补充基准币种数据
                    if not base_continuous or not base_sufficient:
                        if base_missing:
                            base_filled = self.data_filler.fill_missing_data_precise(
                                self.base_symbol, tf, base_missing
                            )
                        else:
                            base_filled = self.data_filler.fill_missing_data(
                                self.base_symbol, tf, query_start_time, end_time
                            )
                        if base_filled > 0:
                            self.logger.info(f"基准币种数据补充完成 | {self.base_symbol} @ {tf} | 补充: {base_filled} 条")

                    # 补充目标币种数据
                    if not alt_continuous or not alt_sufficient:
                        if alt_missing:
                            alt_filled = self.data_filler.fill_missing_data_precise(
                                symbol, tf, alt_missing
                            )
                        else:
                            alt_filled = self.data_filler.fill_missing_data(
                                symbol, tf, query_start_time, end_time
                            )
                        if alt_filled > 0:
                            self.logger.info(f"目标币种数据补充完成 | {symbol} @ {tf} | 补充: {alt_filled} 条")

                    # 重新查询数据
                    base_klines = self.kline_repo.query_range(
                        self.base_symbol,
                        tf,
                        query_start_time,
                        end_time,
                        limit=DB_QUERY_LIMIT
                    )
                    alt_klines = self.kline_repo.query_range(
                        symbol,
                        tf,
                        query_start_time,
                        end_time,
                        limit=DB_QUERY_LIMIT
                    )

                    self.logger.info(
                        f"数据补充后重新查询 | {symbol} @ {tf} | "
                        f"base: {len(base_klines)} 条 | alt: {len(alt_klines)} 条"
                    )

                # 新币过滤：检查4H周期数据充足性
                if tf == '4h':
                    if len(alt_klines) < self.MIN_4H_DATA_POINTS:
                        with self.blacklist_lock:
                            if symbol in self.new_coin_blacklist:
                                self.logger.debug(
                                    f"币种已被其他线程加入黑名单，跳过处理: {symbol} @ {tf}"
                                )
                                return
                            self.new_coin_blacklist.add(symbol)

                        # 取消该币种的所有订阅（仅通用版）
                        if self._should_enable_symbol_monitoring():
                            coin = symbol.split('/')[0]
                            subscriptions_to_remove = [
                                {"type": "candle", "coin": coin, "interval": "5m"},
                                {"type": "candle", "coin": coin, "interval": "1h"},
                                {"type": "candle", "coin": coin, "interval": "4h"}
                            ]
                            unsubscribe_success = self.ws_manager.remove_subscriptions(subscriptions_to_remove)

                            self.logger.warning(
                                f"新币数据不足，加入黑名单并取消订阅 | {symbol} @ {tf} | "
                                f"获取: {len(alt_klines)} 条 | 需要: {self.MIN_4H_DATA_POINTS} 条 | "
                                f"取消订阅: {'✅ 成功' if unsubscribe_success else '❌ 失败'} | "
                                f"此币种将不再进行分析和接收数据"
                            )
                        else:
                            self.logger.warning(
                                f"新币数据不足，加入黑名单 | {symbol} @ {tf} | "
                                f"获取: {len(alt_klines)} 条 | 需要: {self.MIN_4H_DATA_POINTS} 条 | "
                                f"此币种将不再进行分析"
                            )
                        return

                # 数据验证
                if len(base_klines) < 100 or len(alt_klines) < 100:
                    self.logger.warning(
                        f"数据点不足（需要100个）：{symbol} @ {tf} | "
                        f"base: {len(base_klines)}, alt: {len(alt_klines)}"
                    )
                    continue

                # 转换为 pandas Series
                base_series = prepare_price_series(base_klines)
                alt_series = prepare_price_series(alt_klines)

                period_key = (tf, f"{window.days}d")
                price_data_cache[period_key] = {
                    'base_prices': base_series,
                    'alt_prices': alt_series,
                    'base_klines': base_klines,
                    'alt_klines': alt_klines
                }

            # 数据验证：至少需要3个周期的数据
            if len(price_data_cache) < 3:
                self.logger.debug(
                    f"多周期数据不足，跳过分析: {symbol} | "
                    f"实际: {len(price_data_cache)}/3"
                )
                return

            # 相关系数前置过滤（使用子类提供的阈值）
            TARGET_CORR_THRESHOLD = self._get_corr_threshold_for_analysis()

            period_key_4h_60d = ('4h', '60d')
            if period_key_4h_60d in price_data_cache:
                cache_data = price_data_cache[period_key_4h_60d]
                corr_4h_60d_pre = calculate_correlation(
                    cache_data['base_klines'], cache_data['alt_klines']
                )

                if corr_4h_60d_pre <= TARGET_CORR_THRESHOLD:
                    self.logger.info(
                        f"相关系数过滤未通过: {symbol} | "
                        f"4h/60d 相关系数: {corr_4h_60d_pre:.4f} <= {TARGET_CORR_THRESHOLD}"
                    )
                    return
                else:
                    self.logger.debug(
                        f"✅ 相关系数过滤通过: {symbol} | "
                        f"4h/60d 相关系数: {corr_4h_60d_pre:.4f} > {TARGET_CORR_THRESHOLD}"
                    )
            else:
                self.logger.warning(
                    f"缺少 4h/60d 数据，跳过相关系数过滤: {symbol}"
                )
                return

            # 调用多周期验证（Z-score验证）
            multi_period_result = analyze_multi_period(
                price_data_cache=price_data_cache,
                base_symbol=self.base_symbol,
                target_symbol=symbol,
                beta_window=BETA_WINDOW,
                zscore_window=ZSCORE_WINDOW,
                cointegration_threshold=COINTEGRATION_THRESHOLD,
            )

            self.stats['analyses_performed'] += 1

            # Z-score 计算失败，跳过
            if multi_period_result is None:
                self.logger.debug(
                    f"Z-score 计算失败，跳过分析: {symbol} @ {timeframe}"
                )
                return

            # 构建分析记录（无论验证是否通过）
            details = multi_period_result.get('details', {})
            detail_5m = details.get(('5m', '7d'), {})
            detail_1h = details.get(('1h', '30d'), {})
            detail_4h = details.get(('4h', '60d'), {})

            corr_5m_7d = detail_5m.get('correlation')
            corr_1h_30d = detail_1h.get('correlation')
            corr_4h_60d = detail_4h.get('correlation')

            # 提取 ADF p-value (优先使用双窗口方法,回退到全量方法)
            coint_new_4h = detail_4h.get('cointegration_new', {})
            coint_old_4h = detail_4h.get('cointegration_old', {})
            adf_pvalue = coint_new_4h.get('adf_pvalue') or coint_old_4h.get('adf_pvalue')

            # 提取信号强度 (使用4h长周期作为主要参考)
            signal_strength = detail_4h.get('signal_strength', 'none')

            analysis_now = datetime.now(timezone.utc)
            delay_seconds = (analysis_now - kline_time).total_seconds() if kline_time else 0

            # 记录验证状态（用于日志和告警判断）
            validation_passed = multi_period_result.get('passed', False)
            fail_reason = multi_period_result.get('fail_reason', '健康')

            analysis_record = {
                'kline_time': kline_time,
                'analysis_time': analysis_now,
                'analysis_delay_seconds': delay_seconds,
                'symbol': symbol,
                'base_symbol': self.base_symbol,
                'corr_5m_7d': corr_5m_7d,
                'corr_1h_30d': corr_1h_30d,
                'corr_4h_60d': corr_4h_60d,
                'zscore_5m': multi_period_result['zscore_list'][0],
                'zscore_1h': multi_period_result['zscore_list'][1],
                'zscore_4h': multi_period_result['zscore_list'][2],
                'cointegration_passed': multi_period_result['cointegration_count'] >= COINTEGRATION_THRESHOLD,
                'adf_pvalue': adf_pvalue,
                'is_anomaly': validation_passed,
                'trading_direction': multi_period_result['direction'],
                'signal_strength': signal_strength,
            }

            # 批量缓冲写入（无论验证是否通过，只要有 Z-score 就写入）
            try:
                self.analysis_result_buffer.put_nowait(analysis_record)
                self.logger.debug(
                    f"分析结果已写入缓冲 | {symbol} @ {timeframe} | "
                    f"验证通过: {validation_passed}"
                )
            except queue.Full:
                queue_size = self.analysis_result_buffer.qsize()
                queue_capacity = self.analysis_result_buffer.maxsize
                utilization = (queue_size / queue_capacity * 100) if queue_capacity > 0 else 0
                self.logger.warning(
                    f"分析结果缓冲队列已满，丢弃: {symbol} | "
                    f"队列: {queue_size}/{queue_capacity} ({utilization:.1f}%)"
                )
                self.stats['analysis_result_buffer_drops'] += 1

            # 提取目标币种最新价格（5m K线最新收盘价）
            latest_alt_price = None
            period_key_5m = ('5m', '7d')
            if period_key_5m in price_data_cache:
                alt_klines_5m = price_data_cache[period_key_5m]['alt_klines']
                if alt_klines_5m:
                    # query_range ORDER BY time DESC，第一条是最新的
                    latest_alt_price = alt_klines_5m[0].get('close')

            # 仅在所有验证通过时发送飞书告警
            if validation_passed:
                self._send_alert(symbol, timeframe, multi_period_result, latest_alt_price)
                elapsed = time.time() - start_time
                self.logger.info(f"✅ 多周期验证通过: {symbol} @ {timeframe} | {elapsed:.2f}秒")
            else:
                elapsed = time.time() - start_time
                self.logger.info(
                    f"⚠️ 多周期验证未通过（但Z-score已记录）: {symbol} @ {timeframe} | "
                    f"原因: {fail_reason} | {elapsed:.2f}秒"
                )

            # 性能监控
            if elapsed > 15.0:
                self.logger.warning(f"⚠️ 多周期分析延迟过高: {symbol} | {elapsed:.2f}秒")

        except Exception as e:
            self.logger.error(f"多周期分析失败: {symbol} @ {timeframe} | {e}", exc_info=True)
            self.stats['analyses_failed'] += 1

    def _send_alert(self, symbol: str, timeframe: str, multi_period_result: Dict, latest_alt_price: float = None):
        """
        发送多周期验证告警

        Args:
            symbol: 币种
            timeframe: 触发周期
            multi_period_result: 多周期验证结果
            latest_alt_price: 目标币种最新价格
        """
        try:
            direction_emoji = "📈" if multi_period_result['direction'] == 'long' else "📉"
            title = f"{direction_emoji} 多周期配对交易信号 🔥"

            formatter = AlertFormatter()
            content = formatter.format_rich_alert(
                symbol=symbol,
                base_symbol=self.base_symbol,
                timeframe=timeframe,
                multi_period_result=multi_period_result,
                latest_alt_price=latest_alt_price,
            )

            sender_colourful(
                url=self.lark_webhook_url,
                content=content,
                title=title
            )

            self.stats['alerts_sent'] += 1

            zscore_list = multi_period_result.get('zscore_list', [0, 0, 0])
            zscore_5m, zscore_1h, zscore_4h = zscore_list

            self.logger.info(
                f"📢 多周期告警已发送: {symbol} @ {timeframe} | "
                f"{multi_period_result['direction']} | "
                f"Z-score: {zscore_5m:.2f}/{zscore_1h:.2f}/{zscore_4h:.2f}"
            )

        except Exception as e:
            self.logger.error(f"飞书告警发送失败: {e}", exc_info=True)

    # ============================================================
    # 监控线程
    # ============================================================

    def _monitor_queue_health(self):
        """队列健康监控线程"""
        self.logger.info("队列健康监控线程已启动")

        monitor_interval = QUEUE_MONITOR_INTERVAL
        warning_threshold = QUEUE_WARNING_THRESHOLD

        while not self.stop_event.is_set():
            try:
                # 清理入队去重字典
                with self.recent_enqueue_lock:
                    cutoff = time.time() - 1800
                    old_count = len(self.recent_enqueue)
                    self.recent_enqueue = {k: v for k, v in self.recent_enqueue.items() if v > cutoff}
                    new_count = len(self.recent_enqueue)
                    if old_count != new_count:
                        self.logger.debug(
                            f"清理入队去重字典: {old_count} → {new_count} "
                            f"(清理了 {old_count - new_count} 条过期记录)"
                        )

                # 计算队列使用率
                kline_size = self.kline_buffer.qsize()
                kline_capacity = self.kline_buffer.maxsize
                kline_util = (kline_size / kline_capacity) if kline_capacity > 0 else 0

                analysis_size = self.analysis_queue.qsize()
                analysis_capacity = self.analysis_queue.maxsize
                analysis_util = (analysis_size / analysis_capacity) if analysis_capacity > 0 else 0

                result_size = self.analysis_result_buffer.qsize()
                result_capacity = self.analysis_result_buffer.maxsize
                result_util = (result_size / result_capacity) if result_capacity > 0 else 0

                with self.recent_enqueue_lock:
                    enqueue_dict_size = len(self.recent_enqueue)
                with self.recent_analysis_lock:
                    analysis_dict_size = len(self.recent_analysis)

                with self.blacklist_lock:
                    blacklist_size = len(self.new_coin_blacklist)

                status_msg = (
                    f"📊 队列健康监控 | "
                    f"K线: {kline_size}/{kline_capacity} ({kline_util*100:.1f}%) | "
                    f"分析: {analysis_size}/{analysis_capacity} ({analysis_util*100:.1f}%) | "
                    f"结果: {result_size}/{result_capacity} ({result_util*100:.1f}%) | "
                    f"去重字典: 入队{enqueue_dict_size} 分析{analysis_dict_size} | "
                    f"丢弃统计: 分析队列{self.stats.get('analysis_queue_drops', 0)} 结果队列{self.stats.get('analysis_result_buffer_drops', 0)} | "
                    f"新币黑名单: {blacklist_size}"
                )

                if analysis_util >= warning_threshold or result_util >= warning_threshold or kline_util >= warning_threshold:
                    self.logger.warning(f"⚠️ {status_msg}")

                    if analysis_util >= warning_threshold:
                        self.logger.warning(
                            f"分析队列使用率过高 ({analysis_util*100:.1f}%)，建议："
                            f"1) 增加 ANALYSIS_WORKERS（当前: {len(self.analysis_workers)}）"
                            f"2) 检查数据库查询性能"
                        )
                    if result_util >= warning_threshold:
                        self.logger.warning(
                            f"结果队列使用率过高 ({result_util*100:.1f}%)，建议检查数据库写入性能"
                        )
                else:
                    self.logger.info(status_msg)

            except Exception as e:
                self.logger.error(f"队列健康监控异常: {e}", exc_info=True)

            self.stop_event.wait(monitor_interval)

        self.logger.info("队列健康监控线程已停止")

    def _monitor_new_symbols(self):
        """新币种监控线程（仅通用版启用）"""
        self.logger.info("新币种监控线程已启动")

        while not self.stop_event.is_set():
            try:
                from hyperliquid.info import Info
                import hyperliquid.utils.constants as constants

                info = Info(constants.MAINNET_API_URL, skip_ws=True)
                meta = info.meta()

                exchange_symbols = set()
                for asset_info in meta.get('universe', []):
                    name = asset_info.get('name')
                    if name:
                        symbol = f"{name}/USDC:USDC"
                        exchange_symbols.add(symbol)

                with self.symbols_lock:
                    current_symbols = set(self.symbols)
                    new_symbols = exchange_symbols - current_symbols

                    if new_symbols:
                        self.logger.info(f"🆕 发现新币种: {len(new_symbols)} 个")

                        registered_symbols = []
                        new_subscriptions = []

                        for symbol in new_symbols:
                            base_asset = symbol.split('/')[0]
                            self.symbol_repo.upsert_symbol(
                                symbol=symbol,
                                base_asset=base_asset,
                                quote_asset='USDC',
                                is_active=True
                            )

                            self.symbols.append(symbol)
                            registered_symbols.append(symbol)

                            coin = symbol.split('/')[0]
                            for interval in ['5m', '1h', '4h']:
                                new_subscriptions.append({
                                    "type": "candle",
                                    "coin": coin,
                                    "interval": interval
                                })

                        self.logger.info(f"✅ 新币种已注册: {len(registered_symbols)} 个币种: {', '.join(registered_symbols)}")

                        if new_subscriptions:
                            success = self.ws_manager.add_subscriptions(new_subscriptions)
                            if success:
                                self.logger.info(f"🔄 动态订阅已添加: {len(new_subscriptions)} 个订阅（无需重启）")
                            else:
                                self.logger.warning("⚠️ 动态订阅失败，建议重启服务以更新订阅列表")

            except Exception as e:
                self.logger.error(f"新币种监控异常: {e}", exc_info=True)

            self.stop_event.wait(3600)

        self.logger.info("新币种监控线程已停止")

    def _send_system_alert(self, title: str, content: str):
        """
        发送系统级飞书告警

        Args:
            title: 告警标题
            content: 告警内容
        """
        try:
            sender_colourful(
                url=self.lark_webhook_url,
                content=content,
                title=title
            )
            self.logger.info(f"📢 系统告警已发送: {title}")
        except Exception as e:
            self.logger.error(f"系统告警发送失败: {title} | {e}", exc_info=True)

    def on_state_change(self, state: ConnectionState, error: Optional[Exception] = None):
        """
        WebSocket 状态变化回调

        Args:
            state: 连接状态
            error: 错误信息
        """
        self.logger.info(f"WebSocket 状态: {state.value}")

        if error:
            self.logger.error(f"WebSocket 错误: {error}")

        if state == ConnectionState.FAILED:
            self._send_system_alert(
                "🚨 WebSocket服务彻底失败",
                f"WebSocket连接已彻底失败，服务即将退出。\n"
                f"错误信息: {error or '未知'}\n"
                f"请立即检查网络环境和服务状态，并重启服务！"
            )
            self.logger.critical("WebSocket彻底失败，主动停止服务")
            self.stop()
            import sys
            sys.exit(1)

    def get_stats(self) -> Dict:
        """
        获取服务统计信息

        Returns:
            统计信息字典
        """
        uptime = time.time() - self.stats['start_time']

        return {
            **self.stats,
            'uptime_seconds': uptime,
            'buffer_size': self.kline_buffer.qsize(),
            'analysis_queue_size': self.analysis_queue.qsize(),
            'analysis_result_buffer_size': self.analysis_result_buffer.qsize(),
            'ws_stats': self.ws_manager.get_stats(),
            'data_filler_stats': self.data_filler.get_stats()
        }

    def start(self):
        """
        启动服务（阻塞运行）（模板方法）

        流程:
        1. 启动批量写入线程
        2. 条件启动新币种监控线程
        3. 启动分析结果批量写入线程
        4. 启动队列健康监控线程
        5. 启动 WebSocket 服务（阻塞）
        """
        self.logger.info("🚀 启动实时K线分析服务...")

        try:
            self.batch_writer_thread.start()
            self.logger.info("✅ 批量写入线程已启动")

            # 条件启动新币种监控线程
            if self.symbol_monitor_thread is not None:
                self.symbol_monitor_thread.start()
                self.logger.info("✅ 新币种监控线程已启动")

            self.analysis_result_writer_thread.start()
            self.logger.info("✅ 分析结果批量写入线程已启动")

            self.queue_monitor_thread.start()
            self.logger.info("✅ 队列健康监控线程已启动")

            self.ws_manager.start()

        except KeyboardInterrupt:
            self.logger.info("接收到中断信号，停止服务...")
        except Exception as e:
            self.logger.error(f"服务异常: {e}", exc_info=True)
        finally:
            self.stop()

    def stop(self):
        """
        停止服务（优雅关闭）

        流程:
        1. 停止接收新消息
        2. 等待kline_buffer清空
        3. 等待分析队列清空
        4. 等待分析结果缓冲队列清空
        5. 设置停止信号并等待线程退出
        """
        self.logger.info("停止实时K线分析服务...")

        # 停止接收新消息
        self.ws_manager.stop()

        # 等待kline_buffer清空
        if not self.kline_buffer.empty():
            buffer_size = self.kline_buffer.qsize()
            self.logger.info(f"等待kline_buffer清空: {buffer_size} 条K线")
            try:
                self.kline_buffer.join()
                self.logger.info("✅ kline_buffer已清空")
            except Exception as e:
                remaining = self.kline_buffer.qsize()
                self.logger.warning(f"⚠️ kline_buffer未完全清空（剩余 {remaining} 条），强制退出: {e}")

        # 等待分析队列清空
        if not self.analysis_queue.empty():
            queue_size = self.analysis_queue.qsize()
            self.logger.info(f"等待分析队列清空: {queue_size} 个任务")
            try:
                self.analysis_queue.join()
                self.logger.info("✅ 分析队列已清空")
            except Exception as e:
                remaining = self.analysis_queue.qsize()
                self.logger.warning(f"⚠️ 分析队列未完全清空（剩余 {remaining} 个任务），强制退出: {e}")

        # 等待分析结果缓冲队列清空
        if not self.analysis_result_buffer.empty():
            buffer_size = self.analysis_result_buffer.qsize()
            self.logger.info(f"等待分析结果缓冲队列清空: {buffer_size} 条记录")
            try:
                self.analysis_result_buffer.join()
                self.logger.info("✅ 分析结果缓冲队列已清空")
            except Exception as e:
                remaining = self.analysis_result_buffer.qsize()
                self.logger.warning(f"⚠️ 分析结果缓冲队列未完全清空（剩余 {remaining} 条），强制退出: {e}")

        # 设置停止信号
        self.stop_event.set()

        # 等待工作线程退出
        for worker in self.analysis_workers:
            if worker.is_alive():
                worker.join(timeout=WORKER_THREAD_SHUTDOWN_TIMEOUT)
                if worker.is_alive():
                    self.logger.warning(f"⚠️ 工作线程 {worker.name} 未能在5秒内退出")

        if self.batch_writer_thread.is_alive():
            self.batch_writer_thread.join(timeout=MAIN_THREAD_SHUTDOWN_TIMEOUT)

        # 条件等待新币种监控线程
        if self.symbol_monitor_thread is not None and self.symbol_monitor_thread.is_alive():
            self.symbol_monitor_thread.join(timeout=MAIN_THREAD_SHUTDOWN_TIMEOUT)

        if self.queue_monitor_thread.is_alive():
            self.queue_monitor_thread.join(timeout=MAIN_THREAD_SHUTDOWN_TIMEOUT)

        if self.analysis_result_writer_thread.is_alive():
            self.analysis_result_writer_thread.join(timeout=MAIN_THREAD_SHUTDOWN_TIMEOUT)

        # 输出统计信息
        stats = self.get_stats()
        self.logger.info(f"📊 服务统计:")
        self.logger.info(f"   - 消息接收: {stats['messages_received']}")
        self.logger.info(f"   - K线写入: {stats['klines_written']}")
        self.logger.info(f"   - 分析完成: {stats['analyses_completed']}")
        self.logger.info(f"   - 分析失败: {stats['analyses_failed']}")
        self.logger.info(f"   - 分析队列丢弃: {stats.get('analysis_queue_drops', 0)}")
        self.logger.info(f"   - 分析结果写入: {stats.get('analysis_results_written', 0)}")
        self.logger.info(f"   - 分析结果去重: {stats.get('analysis_results_deduped', 0)}")
        self.logger.info(f"   - 分析结果丢弃: {stats.get('analysis_result_buffer_drops', 0)}")
        self.logger.info(f"   - 告警发送: {stats['alerts_sent']}")
        self.logger.info(f"   - 运行时长: {stats['uptime_seconds']:.0f}秒")

        self.logger.info("✅ 服务已停止")
