"""
K线数据连续性校验与自动补充模块

功能：
- 校验K线数据时间连续性
- 检查数据是否满足分析窗口长度要求
- 自动从API获取缺失数据并写入数据库
- 冷却机制避免频繁API调用

设计决策：
- 执行模式：同步阻塞 - 补充完成后再执行分析
- 失败策略：跳过分析 - 数据不完整则不执行分析
- 冷却机制：10分钟冷却，避免频繁API调用

Author: Claude Code
Date: 2026-01-23
"""

import time
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta, timezone

import ccxt
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from utils.timescaledb import KlineRepository, TimescaleDBClient
from utils.logging_config import logger
from utils.config import (
    KLINE_FILLER_COOLDOWN_SECONDS,
    KLINE_FILLER_API_INTERVAL,
    KLINE_FILLER_MAX_RETRIES,
    KLINE_FILLER_API_LIMIT,
    KLINE_FILLER_CLEANUP_INTERVAL
)


class KlineDataFiller:
    """
    K线数据校验与自动补充器

    提供K线数据连续性校验和自动补充功能，确保分析前数据完整性。

    使用示例：
        filler = KlineDataFiller(kline_repo)
        is_continuous, missing = filler.validate_continuity(klines, '5m')
        is_sufficient, count = filler.validate_window_length(klines, '5m', 7, 100)
        if not is_continuous or not is_sufficient:
            filled = filler.fill_missing_data('BTC/USDC:USDC', '5m', start, end)
    """

    # 冷却时间配置（秒）
    COOLDOWN_SECONDS = KLINE_FILLER_COOLDOWN_SECONDS

    # API请求间隔（秒）
    API_REQUEST_INTERVAL = KLINE_FILLER_API_INTERVAL

    # 最大重试次数
    MAX_RETRIES = KLINE_FILLER_MAX_RETRIES

    # 单次API请求限制
    API_LIMIT = KLINE_FILLER_API_LIMIT

    # 周期到分钟的映射
    TIMEFRAME_MINUTES = {
        '1m': 1,
        '5m': 5,
        '15m': 15,
        '30m': 30,
        '1h': 60,
        '4h': 240,
        '1d': 1440,
    }

    def __init__(
        self,
        kline_repo: Optional[KlineRepository] = None,
        exchange_id: str = 'hyperliquid'
    ):
        """
        初始化K线数据补充器

        Args:
            kline_repo: K线数据仓库（可选，默认创建新实例）
            exchange_id: 交易所ID（默认 hyperliquid）
        """
        # 数据库仓库
        self.kline_repo = kline_repo or KlineRepository(TimescaleDBClient())

        # 初始化 ccxt 交易所
        self.exchange = self._init_exchange(exchange_id)

        # 冷却记录：{(symbol, timeframe): last_fill_timestamp}
        self.fill_cooldown: Dict[Tuple[str, str], float] = {}

        # 冷却记录清理计数器
        self._cleanup_counter = 0
        self._cleanup_interval = KLINE_FILLER_CLEANUP_INTERVAL

        logger.info(f"KlineDataFiller 初始化完成 | 交易所: {exchange_id}")

    def _init_exchange(self, exchange_id: str) -> ccxt.Exchange:
        """
        初始化 ccxt 交易所实例

        Args:
            exchange_id: 交易所ID

        Returns:
            ccxt.Exchange: 交易所实例
        """
        try:
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class({
                'enableRateLimit': True,
                'rateLimit': 1500,  # 1.5秒间隔
                'timeout': 30000,  # 增加超时到30秒（原默认10秒）
                'options': {
                    'defaultType': 'swap',
                    'recvWindow': 60000,  # 接收窗口60秒
                }
            })
            logger.info(f"交易所 {exchange_id} 初始化成功（超时: 30s）")
            return exchange
        except Exception as e:
            logger.error(f"交易所初始化失败: {e}")
            raise

    def _normalize_symbol_for_ccxt(self, symbol: str) -> str:
        """
        将符号规范化为 ccxt 认可的格式

        解决问题：Hyperliquid 原生 API 返回 kSHIB/kLUNC（小写k），
        但 ccxt 内部使用 KSHIB/KLUNC（大写K），导致符号不匹配。

        通过简单大写转换 base 币种来规范化（如 kSHIB -> KSHIB）。

        Args:
            symbol: 原始符号（如 'kSHIB/USDC:USDC'）

        Returns:
            规范化后的符号
        """
        parts = symbol.split('/')
        if len(parts) == 2:
            base = parts[0].upper()
            quote_settle = parts[1]
            normalized = f"{base}/{quote_settle}"
            if normalized != symbol:
                logger.debug(f"符号规范化: {symbol} -> {normalized}")
            return normalized
        return symbol

    def _timeframe_to_minutes(self, timeframe: str) -> int:
        """
        将时间周期转换为分钟数

        Args:
            timeframe: 时间周期（如 '5m', '1h', '4h'）

        Returns:
            int: 分钟数
        """
        if timeframe in self.TIMEFRAME_MINUTES:
            return self.TIMEFRAME_MINUTES[timeframe]

        # 解析自定义格式
        if timeframe.endswith('m'):
            return int(timeframe[:-1])
        elif timeframe.endswith('h'):
            return int(timeframe[:-1]) * 60
        elif timeframe.endswith('d'):
            return int(timeframe[:-1]) * 1440

        logger.warning(f"未知时间周期: {timeframe}，使用默认5分钟")
        return 5

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ccxt.RequestTimeout, ccxt.NetworkError)),
        reraise=True
    )
    def _fetch_ohlcv_with_retry(self, symbol, timeframe, since=None, limit=None):
        """
        带重试机制的 OHLCV 数据获取

        Args:
            symbol: 交易对符号
            timeframe: 时间周期
            since: 起始时间戳（毫秒）
            limit: 数据量限制

        Returns:
            OHLCV 数据列表

        Raises:
            ccxt.RequestTimeout: 超时后重试3次仍失败
            ccxt.NetworkError: 网络错误后重试3次仍失败
        """
        return self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)

    def validate_continuity(
        self,
        klines: List[Dict],
        timeframe: str
    ) -> Tuple[bool, List[datetime]]:
        """
        校验K线数据时间连续性

        检查K线数据是否存在时间缺口，识别缺失的时间点。

        Args:
            klines: K线数据列表，每条记录需包含 'time' 字段
            timeframe: 时间周期（如 '5m', '1h'）

        Returns:
            Tuple[bool, List[datetime]]:
                - is_continuous: 数据是否连续
                - missing_timestamps: 缺失的时间点列表
        """
        if len(klines) < 2:
            logger.debug(f"数据点不足（{len(klines)}条），无法校验连续性")
            return len(klines) > 0, []

        # 计算预期时间间隔
        interval_minutes = self._timeframe_to_minutes(timeframe)
        expected_interval = timedelta(minutes=interval_minutes)
        # 允许1分钟误差（处理时区和舍入问题）
        tolerance = timedelta(minutes=1)

        # 按时间排序（升序）
        sorted_klines = sorted(klines, key=lambda x: x['time'])

        missing_timestamps = []
        for i in range(1, len(sorted_klines)):
            current_time = sorted_klines[i]['time']
            prev_time = sorted_klines[i - 1]['time']

            # 确保时间是 datetime 类型
            if isinstance(current_time, str):
                current_time = datetime.fromisoformat(current_time.replace('Z', '+00:00'))
            if isinstance(prev_time, str):
                prev_time = datetime.fromisoformat(prev_time.replace('Z', '+00:00'))

            actual_interval = current_time - prev_time

            # 检查是否有缺失（实际间隔 > 预期间隔 + 容差）
            if actual_interval > expected_interval + tolerance:
                # 计算缺失的时间点数量
                gap_count = int(actual_interval / expected_interval) - 1

                for j in range(1, gap_count + 1):
                    missing_ts = prev_time + expected_interval * j
                    missing_timestamps.append(missing_ts)

        is_continuous = len(missing_timestamps) == 0

        if not is_continuous:
            # 输出缺失时间范围和关键时间点
            first_missing = missing_timestamps[0].isoformat()
            last_missing = missing_timestamps[-1].isoformat()

            # 少量缺失时显示全部，大量时显示摘要
            if len(missing_timestamps) <= 5:
                missing_detail = ", ".join(ts.strftime("%m-%d %H:%M") for ts in missing_timestamps)
            else:
                missing_detail = f"{first_missing} ~ {last_missing}"

            logger.debug(
                f"数据不连续 | 周期: {timeframe} | "
                f"缺失点数: {len(missing_timestamps)} | "
                f"缺失范围: {missing_detail} | "
                f"总数据点: {len(klines)}"
            )

        return is_continuous, missing_timestamps

    def validate_window_length(
        self,
        klines: List[Dict],
        timeframe: str,
        window_days: int,
        min_data_points: int = 100
    ) -> Tuple[bool, int]:
        """
        校验数据是否满足窗口长度要求

        检查K线数据是否覆盖足够的时间窗口和数据点数量。

        Args:
            klines: K线数据列表
            timeframe: 时间周期（如 '5m', '1h'）
            window_days: 期望的时间窗口（天）
            min_data_points: 最小数据点数量（默认100）

        Returns:
            Tuple[bool, int]:
                - is_sufficient: 数据是否充足
                - actual_data_points: 实际数据点数量
        """
        actual_count = len(klines)

        # 检查数据点数量
        if actual_count < min_data_points:
            logger.debug(
                f"数据点不足 | 周期: {timeframe} | "
                f"实际: {actual_count} | 需要: {min_data_points}"
            )
            return False, actual_count

        # 计算期望的数据点数量（基于时间窗口）
        interval_minutes = self._timeframe_to_minutes(timeframe)
        expected_count = (window_days * 24 * 60) // interval_minutes

        # 计算覆盖率（允许85%覆盖率）
        coverage_ratio = actual_count / expected_count if expected_count > 0 else 0
        is_sufficient = coverage_ratio >= 0.85 and actual_count >= min_data_points

        if not is_sufficient:
            logger.debug(
                f"数据覆盖率不足 | 周期: {timeframe} | "
                f"窗口: {window_days}天 | "
                f"覆盖率: {coverage_ratio:.2%} | "
                f"实际: {actual_count} | 期望: {expected_count}"
            )

        return is_sufficient, actual_count

    def _is_in_cooldown(self, symbol: str, timeframe: str) -> bool:
        """
        检查是否在冷却期内

        Args:
            symbol: 币种符号
            timeframe: 时间周期

        Returns:
            bool: 是否在冷却期内
        """
        key = (symbol, timeframe)
        last_fill = self.fill_cooldown.get(key, 0)
        return time.time() - last_fill < self.COOLDOWN_SECONDS

    def _update_cooldown(self, symbol: str, timeframe: str):
        """
        更新冷却时间戳

        Args:
            symbol: 币种符号
            timeframe: 时间周期
        """
        self.fill_cooldown[(symbol, timeframe)] = time.time()

        # 定期清理过期的冷却记录
        self._cleanup_counter += 1
        if self._cleanup_counter >= self._cleanup_interval:
            self._cleanup_expired_cooldowns()
            self._cleanup_counter = 0

    def _cleanup_expired_cooldowns(self):
        """清理过期的冷却记录"""
        current_time = time.time()
        cutoff_time = current_time - self.COOLDOWN_SECONDS * 2
        old_count = len(self.fill_cooldown)

        self.fill_cooldown = {
            k: v for k, v in self.fill_cooldown.items()
            if v > cutoff_time
        }

        if old_count != len(self.fill_cooldown):
            logger.debug(
                f"清理冷却记录: {old_count} → {len(self.fill_cooldown)}"
            )

    def fill_missing_data_precise(
        self,
        symbol: str,
        timeframe: str,
        missing_timestamps: List[datetime]
    ) -> int:
        """
        精准补充：只拉取缺失时间点附近的数据

        相比 fill_missing_data 拉取完整时间范围，此方法只拉取缺失点附近的最小数据量，
        大幅减少 API 请求和数据库写入（节省 95%+ 资源）。

        Args:
            symbol: 币种符号（如 'BTC/USDC:USDC'）
            timeframe: 时间周期（如 '5m', '1h'）
            missing_timestamps: 缺失的时间点列表（由 validate_continuity 返回）

        Returns:
            int: 补充的记录数（如在冷却期内或失败返回0）
        """
        if not missing_timestamps:
            return 0

        # 冷却检查
        if self._is_in_cooldown(symbol, timeframe):
            logger.debug(
                f"冷却期内，跳过精准补充 | {symbol} @ {timeframe} | "
                f"缺失点数: {len(missing_timestamps)}"
            )
            return 0

        # 立即更新冷却，防止并发重复补充
        self._update_cooldown(symbol, timeframe)

        # 符号规范化
        api_symbol = self._normalize_symbol_for_ccxt(symbol)

        # 计算最小时间范围：min(missing) - 1周期 ~ max(missing) + 1周期
        interval_minutes = self._timeframe_to_minutes(timeframe)
        interval_delta = timedelta(minutes=interval_minutes)

        min_ts = min(missing_timestamps)
        max_ts = max(missing_timestamps)
        start_time = min_ts - interval_delta
        end_time = max_ts + interval_delta

        # 计算需要拉取的数据量（缺失点数 + 2 个边界点，但至少 10 条以确保覆盖）
        limit = max(len(missing_timestamps) + 2, 10)

        logger.info(
            f"精准补充K线数据 | {symbol} @ {timeframe} | "
            f"缺失点数: {len(missing_timestamps)} | 拉取: {limit} 条 | "
            f"范围: {start_time.isoformat()} ~ {end_time.isoformat()}"
        )

        try:
            since = int(start_time.timestamp() * 1000)

            # 单次 API 调用获取数据（带重试）
            ohlcv = self._fetch_ohlcv_with_retry(
                api_symbol,
                timeframe,
                since=since,
                limit=min(limit, self.API_LIMIT)
            )

            if not ohlcv:
                logger.warning(f"精准补充：API返回空数据 | {symbol} @ {timeframe}")
                return 0

            # 转换为数据库格式
            klines = self._convert_ohlcv_to_klines(ohlcv, symbol, timeframe)

            # 使用 ON CONFLICT DO NOTHING 避免覆盖已有数据
            count = self.kline_repo.batch_upsert_copy(klines, on_conflict='ignore')

            logger.info(
                f"精准补充完成 | {symbol} @ {timeframe} | "
                f"获取: {len(ohlcv)} 条 | 写入: {count} 条"
            )

            return count

        except Exception as e:
            logger.error(f"精准补充失败 | {symbol} @ {timeframe} | {e}", exc_info=True)
            return 0

    def fill_missing_data(
        self,
        symbol: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime
    ) -> int:
        """
        从API获取缺失数据并写入数据库（完整范围补充）

        如果在冷却期内会立即返回0，否则同步阻塞执行补充操作，补充完成后返回。
        包含冷却机制和重试逻辑。适用于新币等需要完整历史数据的场景。

        注意：对于已知缺失点的场景，优先使用 fill_missing_data_precise 方法。

        Args:
            symbol: 币种符号（如 'BTC/USDC:USDC'）
            timeframe: 时间周期（如 '5m', '1h'）
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            int: 补充的记录数（如在冷却期内或失败返回0）
        """
        # 冷却检查
        if self._is_in_cooldown(symbol, timeframe):
            logger.debug(
                f"冷却期内，跳过补充 | {symbol} @ {timeframe} | "
                f"剩余: {self.COOLDOWN_SECONDS - (time.time() - self.fill_cooldown.get((symbol, timeframe), 0)):.0f}秒"
            )
            return 0

        # 【立即更新冷却】防止并发窗口内多线程重复补充（Phase 1.5 优化）
        self._update_cooldown(symbol, timeframe)

        # 符号规范化：解决 kSHIB vs KSHIB 大小写不一致问题
        api_symbol = self._normalize_symbol_for_ccxt(symbol)

        logger.info(
            f"开始补充K线数据 | {symbol} @ {timeframe} | "
            f"时间范围: {start_time.isoformat()} ~ {end_time.isoformat()}"
        )

        try:
            # 转换时间为毫秒时间戳
            since = int(start_time.timestamp() * 1000)
            until = int(end_time.timestamp() * 1000)

            all_rows = []
            retry_count = 0

            while since < until:
                try:
                    # 调用 ccxt API（使用规范化后的符号，带重试）
                    ohlcv = self._fetch_ohlcv_with_retry(
                        api_symbol,
                        timeframe,
                        since=since,
                        limit=self.API_LIMIT
                    )

                    if not ohlcv:
                        logger.debug(f"API返回空数据，停止获取 | {symbol} @ {timeframe}")
                        break

                    all_rows.extend(ohlcv)
                    since = ohlcv[-1][0] + 1  # 下一个请求从最后一条之后开始

                    logger.debug(
                        f"获取K线数据 | {symbol} @ {timeframe} | "
                        f"本次: {len(ohlcv)} 条 | 累计: {len(all_rows)} 条"
                    )

                    # 检查是否已获取足够数据
                    if len(ohlcv) < self.API_LIMIT:
                        break

                    # API限流：1.5秒间隔
                    time.sleep(self.API_REQUEST_INTERVAL)
                    retry_count = 0  # 重置重试计数

                except ccxt.RateLimitExceeded as e:
                    retry_count += 1
                    if retry_count >= self.MAX_RETRIES:
                        logger.warning(f"达到最大重试次数，停止获取 | {symbol} @ {timeframe}")
                        break
                    wait_time = self.API_REQUEST_INTERVAL * (2 ** retry_count)
                    logger.warning(f"触发限流，等待 {wait_time:.1f} 秒后重试 | 重试次数: {retry_count}")
                    time.sleep(wait_time)

                except ccxt.NetworkError as e:
                    retry_count += 1
                    if retry_count >= self.MAX_RETRIES:
                        logger.error(f"网络错误达到最大重试次数 | {symbol} @ {timeframe} | {e}")
                        break
                    wait_time = self.API_REQUEST_INTERVAL * (2 ** retry_count)
                    logger.warning(f"网络错误，等待 {wait_time:.1f} 秒后重试 | {e}")
                    time.sleep(wait_time)

            if not all_rows:
                logger.warning(f"未获取到任何K线数据 | {symbol} @ {timeframe}")
                # 冷却已在方法开头更新，无需重复
                return 0

            # 转换为数据库格式
            klines = self._convert_ohlcv_to_klines(all_rows, symbol, timeframe)

            # 批量写入数据库（使用COPY命令高性能写入）
            count = self.kline_repo.batch_upsert_copy(klines, on_conflict='update')

            # 冷却已在方法开头更新，无需重复

            logger.info(
                f"K线数据补充完成 | {symbol} @ {timeframe} | "
                f"获取: {len(all_rows)} 条 | 写入: {count} 条"
            )

            return count

        except Exception as e:
            logger.error(f"K线数据补充失败 | {symbol} @ {timeframe} | {e}", exc_info=True)
            # 冷却已在方法开头更新，避免频繁重试
            return 0

    def _convert_ohlcv_to_klines(
        self,
        ohlcv_data: List[List],
        symbol: str,
        timeframe: str
    ) -> List[Dict]:
        """
        将 OHLCV 数据转换为数据库K线格式

        Args:
            ohlcv_data: ccxt OHLCV 数据 [[timestamp, open, high, low, close, volume], ...]
            symbol: 币种符号
            timeframe: 时间周期

        Returns:
            List[Dict]: 数据库K线格式列表
        """
        klines = []

        for row in ohlcv_data:
            timestamp_ms, open_price, high_price, low_price, close_price, volume = row[:6]

            # 转换时间戳
            kline_time = datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc)

            # 计算收益率
            return_pct = (close_price - open_price) / open_price if open_price > 0 else 0.0

            # 计算成交额（USD）
            volume_usd = close_price * volume if volume else 0.0

            klines.append({
                'time': kline_time,
                'symbol': symbol,
                'timeframe': timeframe,
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': volume or 0.0,
                'volume_usd': volume_usd,
                'return_pct': return_pct
            })

        return klines

    def check_and_fill(
        self,
        symbol: str,
        timeframe: str,
        klines: List[Dict],
        window_days: int,
        min_data_points: int = 100,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Tuple[bool, List[Dict]]:
        """
        校验数据并在需要时自动补充（便捷方法）

        整合校验和补充逻辑。如果补充成功，返回原始数据并建议调用方重新查询数据库获取最新数据。

        Args:
            symbol: 币种符号
            timeframe: 时间周期
            klines: 当前K线数据
            window_days: 期望的时间窗口（天）
            min_data_points: 最小数据点数量
            start_time: 开始时间（可选，默认从当前时间倒推window_days）
            end_time: 结束时间（可选，默认当前时间）

        Returns:
            Tuple[bool, List[Dict]]:
                - data_ready: 数据是否准备就绪（补充后仍可能不满足要求）
                - klines: 补充后返回原始数据（建议重新查询数据库获取完整数据）
        """
        # 校验连续性
        is_continuous, missing = self.validate_continuity(klines, timeframe)

        # 校验窗口长度
        is_sufficient, actual_count = self.validate_window_length(
            klines, timeframe, window_days, min_data_points
        )

        # 如果数据完整，直接返回
        if is_continuous and is_sufficient:
            return True, klines

        # 需要补充数据
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        if start_time is None:
            start_time = end_time - timedelta(days=window_days)

        # 尝试补充
        filled_count = self.fill_missing_data(symbol, timeframe, start_time, end_time)

        if filled_count > 0:
            logger.info(
                f"数据补充完成，需要重新查询 | {symbol} @ {timeframe} | "
                f"补充: {filled_count} 条"
            )
            # 返回标记，让调用方重新查询
            return False, klines

        # 补充失败或在冷却期
        logger.warning(
            f"数据补充未完成 | {symbol} @ {timeframe} | "
            f"连续性: {is_continuous} | 充足性: {is_sufficient} | "
            f"数据点: {actual_count}/{min_data_points}"
        )
        return False, klines

    def get_stats(self) -> Dict:
        """
        获取补充器统计信息

        Returns:
            Dict: 统计信息
        """
        return {
            'cooldown_entries': len(self.fill_cooldown),
            'cooldown_seconds': self.COOLDOWN_SECONDS,
            'api_request_interval': self.API_REQUEST_INTERVAL,
            'exchange': self.exchange.id if self.exchange else None,
        }


# =====================================================
# 导出接口
# =====================================================

__all__ = ['KlineDataFiller']
