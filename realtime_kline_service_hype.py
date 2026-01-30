"""
实时K线分析服务 - HYPE/PURR 配对专用版 (Realtime Kline Analysis Service - HYPE/PURR Pair)

核心功能：
- WebSocket 实时数据接收（6个订阅: 2个币种(HYPE/PURR) × 3周期(5m/1h/4h)）
- 直接订阅交易所原生 1h/4h K线（精度优于本地聚合）
- 异步批量写入数据库（1000-2000条或5秒触发）
- 收到5m K线WebSocket推送时触发分析（受去重窗口保护）
- Z-score 异常检测 + 飞书告警
- 固定分析 HYPE/USDC:USDC 与 PURR/USDC:USDC 配对

去重保护机制：
- 入队去重窗口: 30秒（ENQUEUE_DEDUP_WINDOWS['5m']）
- 分析去重窗口: 60秒（DEDUP_WINDOWS['5m']）
- 注意: 去重窗口 < K线周期(300秒)，理论上一根K线可触发多次分析

推送时机依赖：
- 实际触发时机取决于Hyperliquid WebSocket的推送策略
- 代码假设交易所推送频率合理（理想: 仅在K线闭合时推送）
- 无显式闭合检测逻辑，完全依赖交易所数据质量

架构亮点：
- 直接订阅交易所 5m/1h/4h K线，数据精度与 REST API 一致
- 1h/4h 推送频率极低（额外网络开销 <2%），无需本地聚合
- Volume 与交易所原生数据完全一致，无聚合误差
- HYPE/USDC:USDC 作为基础货币，分析 PURR 与 HYPE 的配对关系

性能目标：
- 分析延迟: <5秒
- 告警延迟: <10秒
- 内存占用: <512MB
- CPU占用: <50%

Author: Claude Code
Date: 2026-01-19
"""

import os
import sys
import time
import queue
import threading
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from cachetools import TTLCache

from hyperliquid.info import Info
import hyperliquid.utils.constants as constants
import psycopg.errors

from utils.logging_config import get_logger
from utils.enhanced_ws_manager import EnhancedWebSocketManager, ConnectionState
from utils.timescaledb import (
    TimescaleDBClient,
    KlineRepository,
    SymbolMetadataRepository,
    AnalysisResultRepository
)
from utils.analysis_core import analyze_multi_period, prepare_price_series, calculate_correlation
from utils.lark_bot import sender_colourful
from utils.kline_data_filler_lazy import KlineDataFillerLazy
from utils.alert_formatter import AlertFormatter
from utils.config import (
    # 飞书配置
    lark_bot_id,
    lark_webhook_url,
    # HYPE 专用配置
    HYPE_BASE_SYMBOL,
    HYPE_SYMBOLS,
    HYPE_CORR_THRESHOLD,
    # 服务配置
    DEFAULT_TIMEFRAMES,
    DEFAULT_BATCH_SIZE,
    DEFAULT_BATCH_TIMEOUT,
    # 队列配置（HYPE 专用）
    QUEUE_CONFIG_HYPE,
    # 分析参数
    MIN_4H_DATA_POINTS,
    MIN_DATA_POINTS,
    DATA_WINDOW_CONFIG,
    BETA_WINDOW,
    ZSCORE_WINDOW,
    COINTEGRATION_THRESHOLD,
    ZSCORE_THRESHOLDS,
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
    CPU_CHECK_INTERVAL,
    DB_QUERY_LIMIT,
    # 工作线程配置（HYPE 专用）
    ANALYSIS_WORKERS_HYPE,
    # 批量写入配置
    ANALYSIS_RESULT_BATCH_SIZE,
    ANALYSIS_RESULT_BATCH_TIMEOUT,
    ANALYSIS_USE_COPY_METHOD,
    # 监控配置
    QUEUE_MONITOR_INTERVAL,
    QUEUE_WARNING_THRESHOLD,
)

logger = get_logger(__name__)


# =====================================================
# 实时K线分析服务 - HYPE/PURR 配对专用版
# =====================================================

class RealtimeKlineServiceHypePurr:
    """
    实时K线分析服务 - HYPE/PURR 配对专用版

    架构（直接订阅版）：
    ┌─────────────────────────────────────────────────┐
    │ Hyperliquid WebSocket API                       │
    │ (订阅 5m/1h/4h K线，订阅数=2币种×3=6)           │
    └──────────────────┬──────────────────────────────┘
                       ↓
    ┌─────────────────────────────────────────────────┐
    │ EnhancedWebSocketManager                        │
    │ (假活检测 + 自动重连)                            │
    └──────────────────┬──────────────────────────────┘
                       ↓
              on_message() 回调
                       ↓
         ┌─────────────┴─────────────┐
         ↓                           ↓
    5m/1h/4h K线 →          5m推送触发 _analyze_and_alert()
    kline_buffer                (受去重窗口保护: 30s入队/60s分析)
    (Queue队列)                 (实时分析引擎)
         ↓                           ↓
    _batch_writer()                飞书告警
    (批量写入线程)
         ↓
    TimescaleDB (UPSERT)
    """

    def __init__(
        self,
        base_symbol: str = None,
        timeframes: List[str] = None,
        batch_size: int = None,
        batch_timeout: float = None
    ):
        """
        初始化实时K线分析服务（HYPE/PURR 配对专用）

        Args:
            base_symbol: 基准币种，默认从配置读取（HYPE/USDC:USDC）
            timeframes: 订阅周期列表，默认从配置读取
            batch_size: 批量写入大小，默认从配置读取
            batch_timeout: 批量写入超时，默认从配置读取
        """
        # 基础配置（从配置文件读取 HYPE 专用默认值）
        self.base_symbol = base_symbol or HYPE_BASE_SYMBOL
        self.timeframes = timeframes or DEFAULT_TIMEFRAMES
        self.batch_size = batch_size or DEFAULT_BATCH_SIZE
        self.batch_timeout = batch_timeout or DEFAULT_BATCH_TIMEOUT

        # 数据库客户端
        self.db_client = TimescaleDBClient()
        self.kline_repo = KlineRepository(self.db_client)
        self.symbol_repo = SymbolMetadataRepository(self.db_client)
        self.analysis_repo = AnalysisResultRepository(self.db_client)

        # K线数据校验与补充器（使用延迟加载版本）
        self.data_filler = KlineDataFillerLazy(kline_repo=self.kline_repo)

        # 飞书告警配置（从配置导入）
        self.lark_webhook_url = lark_webhook_url

        if not self.lark_webhook_url:
            logger.error("❌ 未配置飞书告警，LARK_WEBHOOK_URL 或 LARKBOT_ID 环境变量未设置")
            logger.error("程序终止：飞书告警是必需功能，请配置环境变量后重试")
            sys.exit(1)

        # 固定币种列表：只分析 HYPE 和 PURR（从配置读取）
        self.symbols = HYPE_SYMBOLS
        logger.info(f"活跃币种数量: {len(self.symbols)} (固定: HYPE, PURR)")

        # 修复竞态条件: 添加线程锁保护symbols列表
        self.symbols_lock = threading.RLock()

        # 构建订阅列表（每个币种订阅所有配置的时间周期）
        self.subscriptions = self._build_subscriptions()
        logger.info(f"订阅数量: {len(self.subscriptions)}")

        # 修复PERF-01: 使用TTLCache防止内存泄漏
        # 入队去重字典（线程安全，避免重复入队）
        self.recent_enqueue = TTLCache(maxsize=10000, ttl=1800)  # 30分钟TTL
        self.recent_enqueue_lock = threading.Lock()

        # 分析去重字典（跨线程共享，避免重复分析）
        # TTL = 最大去重窗口 × 2 = 900s × 2 = 1800s
        self.recent_analysis = TTLCache(
            maxsize=10000,
            ttl=max(DEDUP_WINDOWS.values()) * 2
        )
        self.recent_analysis_lock = threading.Lock()

        # K线缓冲队列（从配置读取 HYPE 专用大小）
        self.kline_buffer = queue.Queue(maxsize=QUEUE_CONFIG_HYPE['kline_buffer_size'])

        # 分析任务队列（从配置读取 HYPE 专用大小）
        self.analysis_queue = queue.Queue(maxsize=QUEUE_CONFIG_HYPE['analysis_queue_size'])

        # 分析结果缓冲队列（从配置读取 HYPE 专用大小）
        self.analysis_result_buffer = queue.Queue(maxsize=QUEUE_CONFIG_HYPE['analysis_result_buffer_size'])

        # 新币过滤器：内存黑名单（数据不足的币种）
        self.new_coin_blacklist = set()  # 数据不足的新币黑名单
        self.blacklist_lock = threading.Lock()  # 保护黑名单的线程锁
        self.MIN_4H_DATA_POINTS = MIN_4H_DATA_POINTS  # 从配置读取最小4H数据量

        # 停止事件
        self.stop_event = threading.Event()

        # 分析工作线程（从配置读取 HYPE 专用线程数）
        num_workers = ANALYSIS_WORKERS_HYPE
        self.analysis_workers = []
        for i in range(num_workers):
            worker = threading.Thread(
                target=self._analysis_worker,
                daemon=True,
                name=f"analysis-worker-{i}"
            )
            worker.start()
            self.analysis_workers.append(worker)

        logger.info(f"✅ 启动{num_workers}个分析工作线程（ANALYSIS_WORKERS_HYPE={num_workers}）")

        # 批量写入线程
        self.batch_writer_thread = threading.Thread(
            target=self._batch_writer,
            daemon=True,
            name="batch-writer"
        )

        # 分析结果批量写入线程
        self.analysis_result_writer_thread = threading.Thread(
            target=self._analysis_result_batch_writer,
            daemon=True,
            name="analysis-result-writer"
        )

        # 队列健康监控线程
        self.queue_monitor_thread = threading.Thread(
            target=self._monitor_queue_health,
            daemon=True,
            name="queue-monitor"
        )

        # WebSocket 管理器（从配置读取参数）
        self.ws_manager = EnhancedWebSocketManager(
            subscriptions=self.subscriptions,
            message_callback=self.on_message,
            on_state_change=self.on_state_change,
            timeout=WS_TIMEOUT,
            alert_callback=self._send_system_alert,
            max_retries=WS_MAX_RETRIES,
            alert_threshold=WS_ALERT_THRESHOLD
        )

        # 统计信息
        self.stats = {
            'messages_received': 0,
            'klines_written': 0,
            'analyses_performed': 0,
            'analyses_completed': 0,  # 新增：分析成功次数
            'analyses_failed': 0,     # 新增：分析失败次数
            'analysis_queue_drops': 0, # 新增：分析队列丢弃次数
            'alerts_sent': 0,
            'analysis_results_written': 0,      # 新增：分析结果成功写入数
            'analysis_results_deduped': 0,      # 新增：分析结果去重数
            'analysis_result_buffer_drops': 0,  # 新增：分析结果缓冲队列丢弃数
            'start_time': time.time()
        }

        logger.info("✅ 实时K线分析服务（HYPE/PURR 配对专用）初始化完成")

    def _batch_upsert_with_retry(self, batch, max_retries=5, on_conflict='update'):
        """
        K线批量写入数据库，带死锁重试机制

        Args:
            batch: 数据批次
            max_retries: 最大重试次数（默认5次，优化自3次）
            on_conflict: 冲突处理策略

        Returns:
            写入记录数

        Raises:
            Exception: 重试耗尽后抛出原始异常
        """
        import random
        for attempt in range(max_retries):
            try:
                return self.kline_repo.batch_upsert_copy(batch, on_conflict=on_conflict)
            except psycopg.errors.DeadlockDetected as e:
                if attempt < max_retries - 1:
                    # 指数退避 + 随机抖动：0.1s → 0.2s → 0.4s → 0.8s → 1.6s
                    base_delay = 0.1 * (2 ** attempt)
                    jitter = base_delay * 0.25  # ±25% 随机抖动
                    wait_time = base_delay + random.uniform(-jitter, jitter)
                    logger.warning(
                        f"K线写入死锁，{wait_time:.2f}秒后重试 "
                        f"({attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"K线写入死锁重试耗尽 ({max_retries}次)", exc_info=True)
                    raise
            except Exception as e:
                # 其他异常直接抛出
                logger.error(f"K线批量写入失败（非死锁）: {e}", exc_info=True)
                raise

    def _batch_insert_analysis_with_retry(self, batch, use_copy_method, max_retries=5):
        """
        分析结果批量写入数据库，带死锁重试机制

        Args:
            batch: 数据批次
            use_copy_method: 是否使用COPY方法
            max_retries: 最大重试次数（默认5次）

        Returns:
            写入记录数

        Raises:
            Exception: 重试耗尽后抛出原始异常
        """
        import random
        for attempt in range(max_retries):
            try:
                if use_copy_method:
                    return self.analysis_repo.batch_insert_copy(batch)
                else:
                    return self.analysis_repo.batch_insert(batch)
            except psycopg.errors.DeadlockDetected as e:
                if attempt < max_retries - 1:
                    # 指数退避 + 随机抖动：0.1s → 0.2s → 0.4s → 0.8s → 1.6s
                    base_delay = 0.1 * (2 ** attempt)
                    jitter = base_delay * 0.25  # ±25% 随机抖动
                    wait_time = base_delay + random.uniform(-jitter, jitter)
                    logger.warning(
                        f"分析结果写入死锁，{wait_time:.2f}秒后重试 "
                        f"({attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"分析结果写入死锁重试耗尽 ({max_retries}次)", exc_info=True)
                    raise
            except Exception as e:
                # 其他异常直接抛出
                logger.error(f"分析结果批量写入失败（非死锁）: {e}", exc_info=True)
                raise

    def _get_active_symbols(self) -> List[str]:
        """
        获取活跃币种列表（固定返回 HYPE 和 PURR）

        Returns:
            固定币种列表（从配置读取）
        """
        return HYPE_SYMBOLS

    def _build_subscriptions(self) -> List[Dict]:
        """
        构建 WebSocket 订阅列表

        直接订阅交易所 5m/1h/4h K线，获取原生精确数据。
        1h/4h 推送频率极低，额外网络开销 <2%。

        Returns:
            订阅列表 [{"type": "candle", "coin": "HYPE", "interval": "5m"}, ...]
        """
        subscriptions = []

        # 修复竞态条件: 使用锁保护symbols访问
        with self.symbols_lock:
            symbols_copy = list(self.symbols)

        for symbol in symbols_copy:
            # 提取基础币种: HYPE/USDC:USDC → HYPE
            coin = symbol.split('/')[0]

            # 订阅全部时间周期（5m/1h/4h）
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
        修复QUAL-01: 安全的float转换，带日志和默认值

        Args:
            value: 要转换的值
            field_name: 字段名称（用于日志）
            default: 转换失败时的默认值

        Returns:
            float值或默认值
        """
        try:
            if value is None or value == '':
                return default
            return float(value)
        except (ValueError, TypeError) as e:
            logger.error(f"类型转换失败: {field_name}={value} ({type(value).__name__}) | {e}")
            return default

    @staticmethod
    def _safe_int(value, field_name='unknown', default=0) -> int:
        """
        修复QUAL-01: 安全的int转换，带日志和默认值

        Args:
            value: 要转换的值
            field_name: 字段名称（用于日志）
            default: 转换失败时的默认值

        Returns:
            int值或默认值
        """
        try:
            if value is None or value == '':
                return default
            return int(value)
        except (ValueError, TypeError) as e:
            logger.error(f"类型转换失败: {field_name}={value} | {e}")
            return default

    def _parse_kline(self, msg: Dict) -> Optional[Dict]:
        """
        解析 Hyperliquid K线数据为标准格式

        Args:
            msg: WebSocket 消息
                {
                    "channel": "candle",
                    "data": {
                        "t": 1704067260000,  // 开盘时间（毫秒时间戳）
                        "T": 1704067319999,  // 收盘时间（毫秒时间戳）
                        "s": "HYPE",         // 币种符号
                        "i": "5m",           // 时间周期
                        "o": "2295.5",       // 开盘价
                        "c": "2296.3",       // 收盘价
                        "h": "2296.8",       // 最高价
                        "l": "2295.2",       // 最低价
                        "v": "1234.56",      // 成交量
                        "n": 45              // 交易笔数
                    }
                }

        Returns:
            标准K线数据 或 None（解析失败）
        """
        try:
            if msg.get("channel") != "candle":
                return None

            data = msg.get("data", {})

            # 提取字段（使用安全类型转换）
            coin = data.get('s')  # HYPE
            timeframe = data.get('i')  # 5m
            timestamp_ms = self._safe_int(data.get('t'), 'timestamp_ms')
            open_price = self._safe_float(data.get('o'), 'open')
            high_price = self._safe_float(data.get('h'), 'high')
            low_price = self._safe_float(data.get('l'), 'low')
            close_price = self._safe_float(data.get('c'), 'close')
            volume = self._safe_float(data.get('v'), 'volume')

            # 构建币种符号: HYPE → HYPE/USDC:USDC
            symbol = f"{coin}/USDC:USDC"

            # 转换时间戳 (UTC时区感知)
            kline_time = datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc)

            # 计算收益率
            return_pct = (close_price - open_price) / open_price if open_price > 0 else 0.0

            # 计算成交额（USD）
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
            logger.error(f"K线解析失败: {e} | 原始数据: {msg}", exc_info=True)
            return None

    def on_message(self, msg: Dict):
        """
        WebSocket 消息回调（核心处理逻辑）

        流程:
        1. 解析K线数据
        2. 放入缓冲队列（异步批量写入）
        3. 触发实时分析（仅5m周期，异步队列，受去重窗口保护）
           - 入队去重: 30秒内相同(symbol, timeframe)不重复入队
           - 分析去重: 60秒内相同(symbol, timeframe)不重复分析
           - 注意: 触发时机依赖WebSocket推送，无闭合检测

        Args:
            msg: WebSocket 消息
        """
        try:
            # 统计
            self.stats['messages_received'] += 1

            # 解析K线
            kline = self._parse_kline(msg)
            if not kline:
                return

            # 放入缓冲队列（异步批量写入）- 5m/1h/4h 均直接入队
            try:
                self.kline_buffer.put_nowait(kline)
            except queue.Full:
                logger.warning(f"缓冲队列已满，丢弃K线: {kline['symbol']} @ {kline['timeframe']}")

            # 【入队前去重检查】避免重复任务入队（从配置读取）
            task_key = (kline['symbol'], kline['timeframe'])
            dedup_window = ENQUEUE_DEDUP_WINDOWS.get(kline['timeframe'], 30)

            with self.recent_enqueue_lock:
                last_enqueue = self.recent_enqueue.get(task_key, 0)
                current_time = time.time()
                if current_time - last_enqueue < dedup_window:
                    # 跳过重复入队
                    logger.debug(
                        f"跳过分析任务: {kline['symbol']} @ {kline['timeframe']} "
                        f"(距上次分析 {current_time - last_enqueue:.0f}秒 < {dedup_window}秒冷却)"
                    )
                    return
                # 更新入队时间戳
                self.recent_enqueue[task_key] = current_time

            # 【只触发5m周期分析】其他周期仅写入数据库，不触发分析
            if kline['timeframe'] != '5m':
                logger.debug(f"跳过非5m周期分析: {kline['symbol']} @ {kline['timeframe']}")
                return

            # 【异步分析】放入分析队列（非阻塞，<0.1ms）
            # 包含完整 K 线数据，用于分析前同步写入
            analysis_task = {
                'symbol': kline['symbol'],
                'timeframe': kline['timeframe'],
                'timestamp': kline['time'],
                'kline': kline  # 包含完整 K 线数据，确保分析前数据已入库
            }
            try:
                self.analysis_queue.put_nowait(analysis_task)
            except queue.Full:
                queue_size = self.analysis_queue.qsize()
                queue_capacity = self.analysis_queue.maxsize
                utilization = (queue_size / queue_capacity * 100) if queue_capacity > 0 else 0
                logger.warning(
                    f"分析队列已满，跳过分析: {kline['symbol']} @ {kline['timeframe']} | "
                    f"队列: {queue_size}/{queue_capacity} ({utilization:.1f}%)"
                )
                self.stats.setdefault('analysis_queue_drops', 0)
                self.stats['analysis_queue_drops'] += 1

        except Exception as e:
            logger.error(f"消息处理失败: {e}", exc_info=True)

    def _batch_writer(self):
        """
        批量写入线程

        策略:
        - 达到 batch_size（从配置读取，默认1000条） 或 超时 batch_timeout（从配置读取，默认5秒） 触发写入
        - 使用 COPY 命令高性能批量插入

        修复: 正确跟踪从队列获取的元素数量，避免task_done计数不匹配
        """
        logger.info("批量写入线程已启动")

        batch = []
        items_to_mark_done = 0  # 跟踪需要标记完成的项数
        last_write_time = time.time()

        while not self.stop_event.is_set():
            try:
                # 获取K线数据（超时1秒）
                kline_fetched = False
                try:
                    kline = self.kline_buffer.get(timeout=QUEUE_GET_TIMEOUT)
                    batch.append(kline)
                    items_to_mark_done += 1  # 每次成功获取，计数+1
                    kline_fetched = True
                except queue.Empty:
                    pass

                # 判断是否触发写入（修复：停机时强制写入）
                should_write = (
                    len(batch) >= self.batch_size or  # 达到批量大小
                    (batch and time.time() - last_write_time >= self.batch_timeout) or  # 超时
                    (batch and self.stop_event.is_set())  # 停机时立即写入剩余批次
                )

                if should_write and batch:
                    # 去重：按主键 (time, symbol, timeframe) 去重，保留最新记录
                    dedup_dict = {}
                    batch_count = len(batch)
                    for kline in batch:
                        key = (kline['time'], kline['symbol'], kline['timeframe'])
                        dedup_dict[key] = kline  # 后来的覆盖之前的，保留最新

                    dedup_batch = list(dedup_dict.values())

                    # 批量写入数据库（带死锁重试）
                    try:
                        count = self._batch_upsert_with_retry(dedup_batch, on_conflict='update')
                        self.stats['klines_written'] += count

                        # 计算队列使用率
                        kline_queue_util = (self.kline_buffer.qsize() / self.kline_buffer.maxsize * 100)
                        analysis_queue_util = (self.analysis_queue.qsize() / self.analysis_queue.maxsize * 100)
                        result_queue_util = (self.analysis_result_buffer.qsize() / self.analysis_result_buffer.maxsize * 100)

                        logger.info(
                            f"批量写入: {count} 条K线 (去重前: {batch_count}) | "
                            f"K线队列: {self.kline_buffer.qsize()}/{self.kline_buffer.maxsize} ({kline_queue_util:.1f}%) | "
                            f"分析队列: {self.analysis_queue.qsize()}/{self.analysis_queue.maxsize} ({analysis_queue_util:.1f}%) | "
                            f"结果队列: {self.analysis_result_buffer.qsize()}/{self.analysis_result_buffer.maxsize} ({result_queue_util:.1f}%) | "
                            f"总写入: {self.stats['klines_written']}"
                        )

                        # 标记实际从队列获取的任务完成
                        for _ in range(items_to_mark_done):
                            self.kline_buffer.task_done()

                        # 重置批次和计数器
                        batch = []
                        items_to_mark_done = 0
                        last_write_time = time.time()

                    except Exception as e:
                        logger.error(f"批量写入失败: {e}", exc_info=True)
                        # 标记实际从队列获取的任务完成（即使失败）
                        for _ in range(items_to_mark_done):
                            self.kline_buffer.task_done()
                        # 清空批次和计数器，避免重复错误
                        batch = []
                        items_to_mark_done = 0
                        last_write_time = time.time()
                elif kline_fetched and not should_write:
                    # 已获取数据但不需要写入，等待批量写入时统一标记
                    pass

            except Exception as e:
                logger.error(f"批量写入线程异常: {e}", exc_info=True)

        # 停止前处理剩余批次
        if batch:
            try:
                dedup_dict = {}
                batch_count = len(batch)
                for kline in batch:
                    key = (kline['time'], kline['symbol'], kline['timeframe'])
                    dedup_dict[key] = kline

                dedup_batch = list(dedup_dict.values())
                count = self._batch_upsert_with_retry(dedup_batch, on_conflict='update')
                self.stats['klines_written'] += count

                logger.info(f"停止前最后批量写入: {count} 条K线")

                # 标记实际从队列获取的任务完成
                for _ in range(items_to_mark_done):
                    self.kline_buffer.task_done()
            except Exception as e:
                logger.error(f"停止前批量写入失败: {e}", exc_info=True)
                # 标记实际从队列获取的任务完成（即使失败）
                for _ in range(items_to_mark_done):
                    self.kline_buffer.task_done()

        logger.info("批量写入线程已停止")

    def _analysis_result_batch_writer(self):
        """
        分析结果批量写入线程

        策略:
        - 达到 batch_size（从配置 ANALYSIS_RESULT_BATCH_SIZE 读取，默认100条） 或 
          超时 batch_timeout（从配置 ANALYSIS_RESULT_BATCH_TIMEOUT 读取，默认2秒） 触发写入
        - 去重策略：分钟级时间 + symbol + base_symbol
        - 环境变量可配置批量大小和超时时间
        """
        logger.info("分析结果批量写入线程已启动")

        # 从配置读取批量写入参数
        batch_size = ANALYSIS_RESULT_BATCH_SIZE
        batch_timeout = ANALYSIS_RESULT_BATCH_TIMEOUT
        use_copy_method = ANALYSIS_USE_COPY_METHOD

        batch = []
        items_to_mark_done = 0  # 跟踪需要标记完成的项数
        last_write_time = time.time()

        while not self.stop_event.is_set():
            try:
                # 获取分析结果（超时1秒）
                result_fetched = False
                try:
                    analysis_record = self.analysis_result_buffer.get(timeout=QUEUE_GET_TIMEOUT)
                    batch.append(analysis_record)
                    items_to_mark_done += 1  # 每次成功获取，计数+1
                    result_fetched = True
                except queue.Empty:
                    pass

                # 判断是否触发写入（修复：停机时强制写入）
                should_write = (
                    len(batch) >= batch_size or  # 达到批量大小
                    (batch and time.time() - last_write_time >= batch_timeout) or  # 超时
                    (batch and self.stop_event.is_set())  # 停机时立即写入剩余批次
                )

                if should_write and batch:
                    # 去重：按 (分钟级时间, symbol, base_symbol) 去重
                    dedup_dict = {}
                    batch_count = len(batch)
                    for record in batch:
                        # 将时间精确到分钟
                        minute_time = record['analysis_time'].replace(
                            second=0, microsecond=0
                        )
                        key = (minute_time, record['symbol'], record['base_symbol'])
                        dedup_dict[key] = record  # 后来的覆盖之前的，保留最新

                    dedup_batch = list(dedup_dict.values())
                    dedup_count = batch_count - len(dedup_batch)

                    # 批量写入数据库（带死锁重试保护）
                    try:
                        count = self._batch_insert_analysis_with_retry(
                            dedup_batch,
                            use_copy_method=use_copy_method,
                            max_retries=5
                        )
                        self.stats['analysis_results_written'] += count
                        self.stats['analysis_results_deduped'] += dedup_count

                        # 计算队列使用率
                        result_queue_util = (self.analysis_result_buffer.qsize() / self.analysis_result_buffer.maxsize * 100)

                        logger.info(
                            f"批量写入分析结果: {count} 条 (去重前: {batch_count}, 去重: {dedup_count}) | "
                            f"结果队列: {self.analysis_result_buffer.qsize()}/{self.analysis_result_buffer.maxsize} ({result_queue_util:.1f}%)"
                        )

                        # 标记实际从队列获取的任务完成
                        for _ in range(items_to_mark_done):
                            self.analysis_result_buffer.task_done()

                        # 重置批次和计数器
                        batch = []
                        items_to_mark_done = 0
                        last_write_time = time.time()

                    except Exception as e:
                        logger.error(f"分析结果批量写入失败: {e}", exc_info=True)
                        # 标记实际从队列获取的任务完成（即使失败）
                        for _ in range(items_to_mark_done):
                            self.analysis_result_buffer.task_done()
                        # 清空批次和计数器，避免重复错误
                        batch = []
                        items_to_mark_done = 0
                        last_write_time = time.time()
                elif result_fetched and not should_write:
                    # 已获取数据但不需要写入，等待批量写入时统一标记
                    pass

            except Exception as e:
                logger.error(f"分析结果批量写入线程异常: {e}", exc_info=True)

        # 停止前处理剩余批次
        if batch:
            try:
                # 去重
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

                # 根据配置选择写入方法（带死锁重试保护）
                count = self._batch_insert_analysis_with_retry(
                    dedup_batch,
                    use_copy_method=use_copy_method,
                    max_retries=5
                )
                self.stats['analysis_results_written'] += count
                self.stats['analysis_results_deduped'] += dedup_count

                logger.info(f"停止前最后批量写入分析结果: {count} 条 (去重前: {batch_count}, 去重: {dedup_count})")

                # 标记实际从队列获取的任务完成
                for _ in range(items_to_mark_done):
                    self.analysis_result_buffer.task_done()
            except Exception as e:
                logger.error(f"停止前分析结果批量写入失败: {e}", exc_info=True)
                # 标记实际从队列获取的任务完成（即使失败）
                for _ in range(items_to_mark_done):
                    self.analysis_result_buffer.task_done()

        logger.info("分析结果批量写入线程已停止")

    def _analysis_worker(self):
        """
        分析工作线程主循环（Phase 1.5 优化版 - 共享去重）

        功能:
        1. 从队列取出分析任务
        2. 执行数据库查询 + 统计分析
        3. 检测异常并发送飞书告警
        4. 持久化分析结果到数据库

        去重策略（Phase 1.5 差异化优化 + 跨线程共享）:
        - 使用类级别 self.recent_analysis 字典实现跨线程去重
        - 5m周期: 60秒冷却（注意: 小于K线周期300秒，可能多次触发）
        - 1h周期: 300秒冷却（注意: 小于K线周期3600秒，可能多次触发）
        - 4h周期: 900秒冷却（注意: 小于K线周期14400秒，可能多次触发）
        - 实际触发次数取决于WebSocket推送频率，无显式闭合检测
        - 预期节省: 70-80%总体CPU资源
        """
        logger.info(f"[{threading.current_thread().name}] 分析工作线程已启动")

        # 从配置读取去重和清理参数
        last_cleanup_time = time.time()

        while not self.stop_event.is_set():
            try:
                # 阻塞获取任务（1秒超时，允许检查stop_event）
                try:
                    task = self.analysis_queue.get(timeout=QUEUE_GET_TIMEOUT)
                except queue.Empty:
                    # 修复CPU占用: 队列为空时使用wait等待，避免CPU空转
                    if self.stop_event.wait(0.1):  # 100ms检查一次
                        break
                    continue

                symbol = task['symbol']
                timeframe = task['timeframe']
                task_key = (symbol, timeframe)

                # 根据周期获取去重窗口
                dedup_window = DEDUP_WINDOWS.get(timeframe, 60)

                # 【跨线程去重检查】使用共享字典
                current_time = time.time()
                with self.recent_analysis_lock:
                    last_analysis_time = self.recent_analysis.get(task_key, 0)
                    time_since_last = current_time - last_analysis_time if last_analysis_time > 0 else 0

                    if last_analysis_time > 0 and time_since_last < dedup_window:
                        logger.debug(
                            f"跳过重复分析: {symbol} @ {timeframe} "
                            f"(距上次 {time_since_last:.0f}秒，窗口 {dedup_window}秒)"
                        )
                        self.analysis_queue.task_done()
                        continue

                # 【恢复：分析前同步写入】确保最新K线已入库
                kline_data = task.get('kline')
                if kline_data:
                    try:
                        self._batch_upsert_with_retry(
                            [kline_data],
                            on_conflict='update'
                        )
                        logger.debug(
                            f"分析前同步写入: {symbol} @ {timeframe} | "
                            f"time={kline_data.get('time')}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"分析前同步写入失败: {symbol} @ {timeframe} | {e}"
                        )
                        # 继续执行分析，使用批量写入的数据

                # 提取K线时间用于延迟监控
                kline_time = kline_data.get('time') if kline_data else None

                # 执行分析（原 _analyze_and_alert 逻辑）
                try:
                    self._analyze_and_alert(symbol, timeframe, kline_time)
                    self.stats['analyses_completed'] += 1

                    # 【记录分析时间戳】分析成功后更新共享字典
                    with self.recent_analysis_lock:
                        self.recent_analysis[task_key] = current_time

                    # Phase 1.5: 记录分析完成信息，用于监控
                    logger.debug(
                        f"分析完成: {symbol} @ {timeframe} | "
                        f"去重窗口: {dedup_window}秒 | "
                        f"距上次: {time_since_last:.0f}秒"
                    )
                except Exception as e:
                    logger.error(f"分析失败: {symbol} @ {timeframe} | {e}", exc_info=True)
                    self.stats['analyses_failed'] += 1

                # 标记任务完成
                self.analysis_queue.task_done()

                # 【内存泄漏修复】定时清理过期记录（使用共享字典）
                if current_time - last_cleanup_time > CLEANUP_INTERVAL:
                    max_window = max(DEDUP_WINDOWS.values())
                    cutoff_time = current_time - max_window * 2  # 保留2倍窗口时间的记录
                    with self.recent_analysis_lock:
                        old_count = len(self.recent_analysis)
                        self.recent_analysis = {k: v for k, v in self.recent_analysis.items() if v > cutoff_time}
                        new_count = len(self.recent_analysis)
                    last_cleanup_time = current_time
                    logger.debug(
                        f"定时清理任务缓存: {old_count} → {new_count} "
                        f"(清理了 {old_count - new_count} 条过期记录)"
                    )

                # 【内存泄漏修复】硬性上限检查（使用共享字典）
                with self.recent_analysis_lock:
                    if len(self.recent_analysis) > MAX_RECENT_TASKS:
                        # 移除最旧的50%记录
                        sorted_tasks = sorted(self.recent_analysis.items(), key=lambda x: x[1])
                        keep_count = MAX_RECENT_TASKS // 2
                        self.recent_analysis = dict(sorted_tasks[-keep_count:])
                        logger.warning(
                            f"任务缓存超限 ({MAX_RECENT_TASKS})，强制清理至 {len(self.recent_analysis)}"
                        )

            except Exception as e:
                logger.error(f"[{threading.current_thread().name}] 工作线程异常: {e}", exc_info=True)
                time.sleep(1)  # 避免异常循环

        logger.info(f"[{threading.current_thread().name}] 分析工作线程已停止")

    def _analyze_and_alert(self, symbol: str, timeframe: str, kline_time: Optional[datetime] = None):
        """
        实时多周期分析 + 飞书告警

        流程（新）：
        1. 检查新币黑名单（复用现有数据）
        2. 查询所有3个周期的K线数据（5m/7d, 1h/30d, 4h/60d）
        3. 验证4H数据充足性，不足则加入黑名单
        4. 调用 analyze_multi_period() 进行多周期验证
        5. 仅在通过多周期验证时才保存结果并告警

        Args:
            symbol: 目标币种（如 PURR/USDC:USDC）
            timeframe: 触发周期（如 5m）
        """
        # 新币过滤：检查黑名单（避免重复分析数据不足的币种）
        with self.blacklist_lock:
            if symbol in self.new_coin_blacklist:
                logger.debug(f"跳过新币分析（已在黑名单）：{symbol}")
                return

        # 开始计时（用于监控分析延迟）
        start_time = time.time()

        try:
            # 跳过基准币种自身
            if symbol == self.base_symbol:
                return

            # ===== 新增：查询所有3个周期的数据（从配置读取）=====
            window_map = {
                '5m': timedelta(days=DATA_WINDOW_CONFIG['5m']),
                '1h': timedelta(days=DATA_WINDOW_CONFIG['1h']),
                '4h': timedelta(days=DATA_WINDOW_CONFIG['4h'])
            }

            # 构建多周期数据缓存
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

                # === 新增：K线数据连续性校验与自动补充 ===
                need_refill = False
                min_data_points = MIN_DATA_POINTS

                # 1. 校验基准币种数据连续性和窗口长度
                base_continuous, base_missing = self.data_filler.validate_continuity(base_klines, tf)
                base_sufficient, base_count = self.data_filler.validate_window_length(
                    base_klines, tf, window.days, min_data_points
                )

                # 2. 校验目标币种数据连续性和窗口长度
                alt_continuous, alt_missing = self.data_filler.validate_continuity(alt_klines, tf)
                alt_sufficient, alt_count = self.data_filler.validate_window_length(
                    alt_klines, tf, window.days, min_data_points
                )

                # 3. 判断是否需要补充数据
                need_refill = (
                    not base_continuous or not alt_continuous or
                    not base_sufficient or not alt_sufficient
                )

                if need_refill:
                    logger.info(
                        f"数据不完整，尝试补充 | {symbol} @ {tf} | "
                        f"base: 连续={base_continuous}, 充足={base_sufficient}({base_count}) | "
                        f"alt: 连续={alt_continuous}, 充足={alt_sufficient}({alt_count})"
                    )

                    # 补充基准币种数据（如果需要）
                    if not base_continuous or not base_sufficient:
                        if base_missing:
                            # 有明确缺失点，使用精准补充（节省 95%+ API 请求）
                            base_filled = self.data_filler.fill_missing_data_precise(
                                self.base_symbol, tf, base_missing
                            )
                        else:
                            # 数据量不足（新币场景），使用完整范围补充
                            base_filled = self.data_filler.fill_missing_data(
                                self.base_symbol, tf, query_start_time, end_time
                            )
                        if base_filled > 0:
                            logger.info(f"基准币种数据补充完成 | {self.base_symbol} @ {tf} | 补充: {base_filled} 条")

                    # 补充目标币种数据（如果需要）
                    if not alt_continuous or not alt_sufficient:
                        if alt_missing:
                            # 有明确缺失点，使用精准补充（节省 95%+ API 请求）
                            alt_filled = self.data_filler.fill_missing_data_precise(
                                symbol, tf, alt_missing
                            )
                        else:
                            # 数据量不足（新币场景），使用完整范围补充
                            alt_filled = self.data_filler.fill_missing_data(
                                symbol, tf, query_start_time, end_time
                            )
                        if alt_filled > 0:
                            logger.info(f"目标币种数据补充完成 | {symbol} @ {tf} | 补充: {alt_filled} 条")

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

                    logger.info(
                        f"数据补充后重新查询 | {symbol} @ {tf} | "
                        f"base: {len(base_klines)} 条 | alt: {len(alt_klines)} 条"
                    )
                # === K线数据校验与补充结束 ===

                # 【新币过滤】：检查4H周期数据充足性（复用现有查询数据）
                if tf == '4h':
                    # 验证目标币种4H数据是否充足（补充后仍需检查）
                    if len(alt_klines) < self.MIN_4H_DATA_POINTS:
                        # 数据不足，加入黑名单
                        with self.blacklist_lock:
                            self.new_coin_blacklist.add(symbol)
                        logger.warning(
                            f"新币数据不足，加入黑名单 | {symbol} @ {tf} | "
                            f"获取: {len(alt_klines)} 条 | 需要: {self.MIN_4H_DATA_POINTS} 条 | "
                            f"此币种将不再进行分析"
                        )
                        # 直接返回，不继续后续分析
                        return

                # 数据验证（补充后仍需检查）
                if len(base_klines) < 100 or len(alt_klines) < 100:
                    logger.warning(
                        f"数据点不足（需要100个）：{symbol} @ {tf} | "
                        f"base: {len(base_klines)}, alt: {len(alt_klines)}"
                    )
                    continue

                # 转换为 pandas Series
                base_series = prepare_price_series(base_klines)
                alt_series = prepare_price_series(alt_klines)

                # 存入缓存
                period_key = (tf, f"{window.days}d")
                price_data_cache[period_key] = {
                    'base_prices': base_series,
                    'alt_prices': alt_series,
                    'base_klines': base_klines,
                    'alt_klines': alt_klines
                }

            # 数据验证：至少需要3个周期的数据
            if len(price_data_cache) < 3:
                logger.debug(
                    f"多周期数据不足，跳过分析: {symbol} | "
                    f"实际: {len(price_data_cache)}/3"
                )
                return

            # ===== 相关系数前置过滤（HYPE 专用阈值：更宽松）=====
            TARGET_CORR_THRESHOLD = HYPE_CORR_THRESHOLD

            period_key_4h_60d = ('4h', '60d')
            if period_key_4h_60d in price_data_cache:
                cache_data = price_data_cache[period_key_4h_60d]
                corr_4h_60d_pre = calculate_correlation(
                    cache_data['base_klines'], cache_data['alt_klines']
                )

                if corr_4h_60d_pre <= TARGET_CORR_THRESHOLD:
                    logger.info(
                        f"相关系数过滤未通过: {symbol} | "
                        f"4h/60d 相关系数: {corr_4h_60d_pre:.4f} <= {TARGET_CORR_THRESHOLD}"
                    )
                    return
                else:
                    logger.debug(
                        f"✅ 相关系数过滤通过: {symbol} | "
                        f"4h/60d 相关系数: {corr_4h_60d_pre:.4f} > {TARGET_CORR_THRESHOLD}"
                    )
            else:
                logger.warning(
                    f"缺少 4h/60d 数据，跳过相关系数过滤: {symbol}"
                )
                return

            # ===== 调用多周期验证（从配置读取参数）=====
            multi_period_result = analyze_multi_period(
                price_data_cache=price_data_cache,
                base_symbol=self.base_symbol,
                target_symbol=symbol,
                beta_window=BETA_WINDOW,
                zscore_window=ZSCORE_WINDOW,
                cointegration_threshold=COINTEGRATION_THRESHOLD,
                zscore_thresholds=ZSCORE_THRESHOLDS
            )

            # 统计
            self.stats['analyses_performed'] += 1

            # 验证失败，不告警
            if multi_period_result is None or not multi_period_result.get('passed', False):
                logger.debug(
                    f"多周期验证未通过: {symbol} @ {timeframe} | "
                    f"协整通过数: {multi_period_result.get('cointegration_count', 0) if multi_period_result else 0}"
                )
                return

            # ===== 健康状态约束检查 =====
            # 只有当短期窗口(100期)健康状态为 HEALTHY 时才发送告警
            health_state_passed = True
            health_state_reason = ""

            try:
                # 从 4h/60d 周期的详情中提取健康监控数据
                details_4h_60d = multi_period_result.get('details', {}).get(('4h', '60d'), {})
                health_monitor = details_4h_60d.get('health_monitor')

                if health_monitor is None:
                    # 健康监控数据不存在，记录警告但允许通过（向后兼容）
                    logger.warning(
                        f"健康监控数据不存在: {symbol} @ {timeframe} | "
                        f"跳过健康状态检查（向后兼容模式）"
                    )
                else:
                    short_window = health_monitor.get('short_window', {})
                    short_state = short_window.get('state', 'UNKNOWN')
                    short_score = short_window.get('health_score', 0)

                    if short_state != 'HEALTHY':
                        health_state_passed = False
                        health_state_reason = (
                            f"短期窗口(100期)状态: {short_state} (得分: {short_score:.1f}) | "
                            f"需要: HEALTHY (得分 >= 18)"
                        )

            except Exception as e:
                # 健康状态检查异常，记录错误但允许通过（容错处理）
                logger.error(
                    f"健康状态检查异常: {symbol} @ {timeframe} | {e}",
                    exc_info=True
                )

            # 健康状态不满足，不发送告警
            if not health_state_passed:
                logger.info(
                    f"协整健康约束未通过: {symbol} @ {timeframe} | {health_state_reason}"
                )
                return

            # ===== 通过验证，构建告警记录 =====
            # ✅ 从 details 中提取每个周期的相关系数（已在 analyze_pair_advanced 中计算）
            details = multi_period_result.get('details', {})
            corr_5m_7d = details.get(('5m', '7d'), {}).get('correlation')
            corr_1h_30d = details.get(('1h', '30d'), {}).get('correlation')
            corr_4h_60d = details.get(('4h', '60d'), {}).get('correlation')

            # 计算分析时刻和延迟 (UTC时区感知)
            analysis_now = datetime.now(timezone.utc)
            delay_seconds = (analysis_now - kline_time).total_seconds() if kline_time else 0

            # 注意：字段需与数据库表 analysis_results 结构一致
            analysis_record = {
                # ===== 时间链路字段 =====
                'kline_time': kline_time,                    # K线原始时间（新增）
                'analysis_time': analysis_now,               # 分析完成时间（系统本地时区）
                'analysis_delay_seconds': delay_seconds,     # 分析延迟（新增）

                # ===== 基本字段 =====
                'symbol': symbol,
                'base_symbol': self.base_symbol,

                # ✅ 相关系数（从多周期验证结果中提取，保证数据完整性）
                'corr_5m_7d': corr_5m_7d,      # 短周期相关系数（7天数据）
                'corr_1h_30d': corr_1h_30d,    # 中周期相关系数（30天数据）
                'corr_4h_60d': corr_4h_60d,    # 长周期相关系数（60天数据）

                # ✅ 多周期Z-score（表中存在）
                'zscore_5m': multi_period_result['zscore_list'][0],
                'zscore_1h': multi_period_result['zscore_list'][1],
                'zscore_4h': multi_period_result['zscore_list'][2],

                # ✅ 协整检验（表中存在，基于协整通过数量判断）
                'cointegration_passed': multi_period_result['cointegration_count'] >= 2,
                'adf_pvalue': None,  # 多周期验证无单一p值

                # ✅ 信号判断（表中存在）
                'is_anomaly': True,  # 通过多周期验证即为异常
                'trading_direction': multi_period_result['direction'],
                'signal_strength': 'strong',  # 多周期确认为强信号
            }

            # 注意：trigger_timeframe 和 cointegration_count 已在飞书告警中展示，无需持久化到数据库

            # 批量缓冲写入（非阻塞）
            try:
                self.analysis_result_buffer.put_nowait(analysis_record)
            except queue.Full:
                queue_size = self.analysis_result_buffer.qsize()
                queue_capacity = self.analysis_result_buffer.maxsize
                utilization = (queue_size / queue_capacity * 100) if queue_capacity > 0 else 0
                logger.warning(
                    f"分析结果缓冲队列已满，丢弃: {symbol} | "
                    f"队列: {queue_size}/{queue_capacity} ({utilization:.1f}%)"
                )
                self.stats['analysis_result_buffer_drops'] += 1

            # 发送飞书告警
            self._send_alert(symbol, timeframe, multi_period_result)

            # 性能监控
            elapsed = time.time() - start_time
            if elapsed > 15.0:  # 多周期验证允许更长延迟
                logger.warning(f"⚠️ 多周期分析延迟过高: {symbol} | {elapsed:.2f}秒")
            else:
                logger.info(f"✅ 多周期验证通过: {symbol} @ {timeframe} | {elapsed:.2f}秒")

        except Exception as e:
            logger.error(f"多周期分析失败: {symbol} @ {timeframe} | {e}", exc_info=True)
            self.stats['analyses_failed'] += 1

    def _send_alert(self, symbol: str, timeframe: str, multi_period_result: Dict):
        """
        发送多周期验证告警（丰富格式版）

        使用 AlertFormatter 生成包含风险评估和交易建议的结构化告警内容。

        Args:
            symbol: 币种
            timeframe: 触发周期
            multi_period_result: 多周期验证结果
        """
        try:
            # 构建告警标题
            direction_emoji = "📈" if multi_period_result['direction'] == 'long' else "📉"
            title = f"{direction_emoji} 多周期配对交易信号 🔥"

            # 使用 AlertFormatter 生成丰富格式的告警内容
            formatter = AlertFormatter()
            content = formatter.format_rich_alert(
                symbol=symbol,
                base_symbol=self.base_symbol,
                timeframe=timeframe,
                multi_period_result=multi_period_result
            )

            # 发送飞书消息（彩色卡片）
            sender_colourful(
                url=self.lark_webhook_url,
                content=content,
                title=title
            )

            # 统计
            self.stats['alerts_sent'] += 1

            # 提取Z-score用于日志
            zscore_list = multi_period_result.get('zscore_list', [0, 0, 0])
            zscore_5m, zscore_1h, zscore_4h = zscore_list

            logger.info(
                f"📢 多周期告警已发送: {symbol} @ {timeframe} | "
                f"{multi_period_result['direction']} | "
                f"Z-score: {zscore_5m:.2f}/{zscore_1h:.2f}/{zscore_4h:.2f}"
            )

        except Exception as e:
            logger.error(f"飞书告警发送失败: {e}", exc_info=True)

    def _monitor_queue_health(self):
        """
        队列健康监控线程

        策略:
        - 每60秒输出一次队列状态
        - 当队列使用率超过80%时发出警告
        - 提供队列趋势分析
        """
        logger.info("队列健康监控线程已启动")

        # 从配置读取监控参数
        monitor_interval = QUEUE_MONITOR_INTERVAL
        warning_threshold = QUEUE_WARNING_THRESHOLD

        while not self.stop_event.is_set():
            try:
                # 【入队去重字典清理】防止内存泄漏（Phase 1.5 优化）
                with self.recent_enqueue_lock:
                    cutoff = time.time() - 1800  # 保留30分钟内的记录
                    old_count = len(self.recent_enqueue)
                    self.recent_enqueue = {k: v for k, v in self.recent_enqueue.items() if v > cutoff}
                    new_count = len(self.recent_enqueue)
                    if old_count != new_count:
                        logger.debug(
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

                # 【增强监控信息】添加去重字典大小统计
                with self.recent_enqueue_lock:
                    enqueue_dict_size = len(self.recent_enqueue)
                with self.recent_analysis_lock:
                    analysis_dict_size = len(self.recent_analysis)

                # 获取新币黑名单大小
                with self.blacklist_lock:
                    blacklist_size = len(self.new_coin_blacklist)

                # 构建状态消息
                status_msg = (
                    f"📊 队列健康监控 | "
                    f"K线: {kline_size}/{kline_capacity} ({kline_util*100:.1f}%) | "
                    f"分析: {analysis_size}/{analysis_capacity} ({analysis_util*100:.1f}%) | "
                    f"结果: {result_size}/{result_capacity} ({result_util*100:.1f}%) | "
                    f"去重字典: 入队{enqueue_dict_size} 分析{analysis_dict_size} | "
                    f"丢弃统计: 分析队列{self.stats.get('analysis_queue_drops', 0)} 结果队列{self.stats.get('analysis_result_buffer_drops', 0)} | "
                    f"新币黑名单: {blacklist_size}"
                )

                # 根据使用率决定日志级别
                if analysis_util >= warning_threshold or result_util >= warning_threshold or kline_util >= warning_threshold:
                    logger.warning(f"⚠️ {status_msg}")

                    # 提供优化建议
                    if analysis_util >= warning_threshold:
                        logger.warning(
                            f"分析队列使用率过高 ({analysis_util*100:.1f}%)，建议："
                            f"1) 增加 ANALYSIS_WORKERS（当前: {len(self.analysis_workers)}）"
                            f"2) 检查数据库查询性能"
                        )
                    if result_util >= warning_threshold:
                        logger.warning(
                            f"结果队列使用率过高 ({result_util*100:.1f}%)，建议检查数据库写入性能"
                        )
                else:
                    logger.info(status_msg)

            except Exception as e:
                logger.error(f"队列健康监控异常: {e}", exc_info=True)

            # 等待下一个监控周期
            self.stop_event.wait(monitor_interval)

        logger.info("队列健康监控线程已停止")

    def _send_system_alert(self, title: str, content: str):
        """
        发送系统级飞书告警（P0-2增强）

        用于 WebSocket 重连失败等系统级告警，与交易信号告警区分。

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
            logger.info(f"📢 系统告警已发送: {title}")
        except Exception as e:
            logger.error(f"系统告警发送失败: {title} | {e}", exc_info=True)

    def on_state_change(self, state: ConnectionState, error: Optional[Exception] = None):
        """
        WebSocket 状态变化回调

        Args:
            state: 连接状态
            error: 错误信息（如果有）
        """
        logger.info(f"WebSocket 状态: {state.value}")

        if error:
            logger.error(f"WebSocket 错误: {error}")

        # P0-2增强：FAILED状态发送紧急飞书告警并退出服务
        if state == ConnectionState.FAILED:
            self._send_system_alert(
                "🚨 WebSocket服务彻底失败",
                f"WebSocket连接已彻底失败，服务即将退出。\n"
                f"错误信息: {error or '未知'}\n"
                f"请立即检查网络环境和服务状态，并重启服务！"
            )
            # 修复STAB-01: 主动停止服务并退出进程
            logger.critical("WebSocket彻底失败，主动停止服务")
            self.stop()  # 停止所有工作线程
            sys.exit(1)  # 退出进程，触发容器重启

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
            'analysis_queue_size': self.analysis_queue.qsize(),  # 新增：分析队列大小
            'analysis_result_buffer_size': self.analysis_result_buffer.qsize(),  # 新增：分析结果缓冲队列大小
            'ws_stats': self.ws_manager.get_stats(),
            'data_filler_stats': self.data_filler.get_stats()  # 数据补充器统计
        }

    def start(self):
        """
        启动服务（阻塞运行）

        流程:
        1. 启动批量写入线程
        2. 启动分析结果批量写入线程
        3. 启动队列健康监控线程
        4. 启动 WebSocket 服务（阻塞）
        """
        logger.info("🚀 启动实时K线分析服务（HYPE/PURR 配对专用）...")

        try:
            # 启动批量写入线程
            self.batch_writer_thread.start()
            logger.info("✅ 批量写入线程已启动")

            # 启动分析结果批量写入线程
            self.analysis_result_writer_thread.start()
            logger.info("✅ 分析结果批量写入线程已启动")

            # 启动队列健康监控线程
            self.queue_monitor_thread.start()
            logger.info("✅ 队列健康监控线程已启动")

            # 启动 WebSocket（阻塞）
            self.ws_manager.start()

        except KeyboardInterrupt:
            logger.info("接收到中断信号，停止服务...")
        except Exception as e:
            logger.error(f"服务异常: {e}", exc_info=True)
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
        logger.info("停止实时K线分析服务（HYPE/PURR 配对专用）...")

        # 1. 停止接收新消息
        self.ws_manager.stop()

        # 2. 等待kline_buffer清空
        if not self.kline_buffer.empty():
            buffer_size = self.kline_buffer.qsize()
            logger.info(f"等待kline_buffer清空: {buffer_size} 条K线")
            try:
                self.kline_buffer.join()
                logger.info("✅ kline_buffer已清空")
            except Exception as e:
                remaining = self.kline_buffer.qsize()
                logger.warning(f"⚠️ kline_buffer未完全清空（剩余 {remaining} 条），强制退出: {e}")

        # 3. 等待分析队列清空
        if not self.analysis_queue.empty():
            queue_size = self.analysis_queue.qsize()
            logger.info(f"等待分析队列清空: {queue_size} 个任务")
            try:
                self.analysis_queue.join()
                logger.info("✅ 分析队列已清空")
            except Exception as e:
                remaining = self.analysis_queue.qsize()
                logger.warning(f"⚠️ 分析队列未完全清空（剩余 {remaining} 个任务），强制退出: {e}")

        # 4. 等待分析结果缓冲队列清空
        if not self.analysis_result_buffer.empty():
            buffer_size = self.analysis_result_buffer.qsize()
            logger.info(f"等待分析结果缓冲队列清空: {buffer_size} 条记录")
            try:
                self.analysis_result_buffer.join()
                logger.info("✅ 分析结果缓冲队列已清空")
            except Exception as e:
                remaining = self.analysis_result_buffer.qsize()
                logger.warning(f"⚠️ 分析结果缓冲队列未完全清空（剩余 {remaining} 条），强制退出: {e}")

        # 5. 设置停止信号（工作线程将退出）
        self.stop_event.set()

        # 等待工作线程退出
        for worker in self.analysis_workers:
            if worker.is_alive():
                worker.join(timeout=WORKER_THREAD_SHUTDOWN_TIMEOUT)
                if worker.is_alive():
                    logger.warning(f"⚠️ 工作线程 {worker.name} 未能在5秒内退出")

        # 等待批量写入线程结束
        if self.batch_writer_thread.is_alive():
            self.batch_writer_thread.join(timeout=MAIN_THREAD_SHUTDOWN_TIMEOUT)

        # 等待队列健康监控线程结束
        if self.queue_monitor_thread.is_alive():
            self.queue_monitor_thread.join(timeout=MAIN_THREAD_SHUTDOWN_TIMEOUT)

        # 等待分析结果写入线程结束
        if self.analysis_result_writer_thread.is_alive():
            self.analysis_result_writer_thread.join(timeout=MAIN_THREAD_SHUTDOWN_TIMEOUT)

        # 输出统计信息
        stats = self.get_stats()
        logger.info(f"📊 服务统计:")
        logger.info(f"   - 消息接收: {stats['messages_received']}")
        logger.info(f"   - K线写入: {stats['klines_written']}")
        logger.info(f"   - 分析完成: {stats['analyses_completed']}")
        logger.info(f"   - 分析失败: {stats['analyses_failed']}")
        logger.info(f"   - 分析队列丢弃: {stats.get('analysis_queue_drops', 0)}")
        logger.info(f"   - 分析结果写入: {stats.get('analysis_results_written', 0)}")
        logger.info(f"   - 分析结果去重: {stats.get('analysis_results_deduped', 0)}")
        logger.info(f"   - 分析结果丢弃: {stats.get('analysis_result_buffer_drops', 0)}")
        logger.info(f"   - 告警发送: {stats['alerts_sent']}")
        logger.info(f"   - 运行时长: {stats['uptime_seconds']:.0f}秒")

        logger.info("✅ 服务已停止")


# =====================================================
# 主程序入口
# =====================================================

def main():
    """主程序入口"""
    # 创建服务实例（HYPE/PURR 配对专用，使用配置文件中的默认值）
    service = RealtimeKlineServiceHypePurr()

    # 启动服务
    service.start()


if __name__ == '__main__':
    main()
