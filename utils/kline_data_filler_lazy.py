"""
K线数据补充器 - 延迟加载版本

专为 realtime_kline_service_hype.py 优化的版本，特点：
- 启动时不加载交易所（延迟初始化）
- 不调用 load_markets()，避免耗时的 API 请求
- 按需初始化，只在真正需要时才创建交易所实例
- API 调用失败时优雅降级，不影响主服务

Author: Claude Code
Date: 2026-01-27
"""

import time
import threading
from typing import List, Optional
from datetime import datetime

import ccxt

from utils.kline_data_filler import KlineDataFiller
from utils.logging_config import logger
from utils.config import KLINE_FILLER_LAZY_RATE_LIMIT, KLINE_FILLER_LAZY_TIMEOUT_MS


class KlineDataFillerLazy(KlineDataFiller):
    """
    K线数据补充器 - 延迟加载版本
    
    继承自 KlineDataFiller，但使用延迟初始化策略：
    - 启动时不创建交易所实例（极速启动）
    - 首次调用数据补充方法时才初始化
    - 移除 load_markets() 调用（不需要预加载市场信息）
    - 支持优雅降级（初始化失败不影响主服务）
    
    适用场景：
    - 实时数据服务（WebSocket 为主，数据补充为辅）
    - 网络不稳定环境
    - 需要快速启动的场景
    """
    
    def __init__(
        self,
        kline_repo=None,
        exchange_id: str = 'hyperliquid'
    ):
        """
        初始化 K线数据补充器（延迟加载版本）
        
        注意：不会立即创建交易所实例，只在首次需要时才初始化
        
        实现机制：
        - 通过 _skip_parent_init 标志跳过父类 __init__ 中的交易所初始化
        - 父类调用 _init_exchange() 时，检查该标志并返回 None
        - 交易所实例延迟到首次实际使用时才创建（通过 _ensure_exchange_initialized）
        
        Args:
            kline_repo: K线数据仓库（可选）
            exchange_id: 交易所ID（默认 hyperliquid）
        """
        # 调用父类的 __init__，但通过 _skip_parent_init 标志跳过交易所初始化
        self._skip_parent_init = True
        super().__init__(kline_repo, exchange_id)
        
        # 延迟初始化：不在 __init__ 时创建交易所实例
        self.exchange: Optional[ccxt.Exchange] = None
        self.exchange_id = exchange_id
        self._exchange_lock = threading.RLock()
        self._init_attempted = False
        
        logger.info(f"KlineDataFiller 初始化完成 | 交易所: {exchange_id} (延迟加载)")
    
    def _init_exchange(self, exchange_id: str) -> ccxt.Exchange:
        """
        轻量级交易所初始化（延迟加载模式）
        
        说明：
        - 父类 __init__ 调用时：通过 _skip_parent_init 标志跳过，返回 None
        - 延迟加载调用时：创建交易所实例，不调用 load_markets() 以提升速度
        - 设置更长的超时时间（30秒）以适应网络环境
        
        Args:
            exchange_id: 交易所ID
            
        Returns:
            ccxt.Exchange: 交易所实例（父类调用时返回 None）
        """
        # 如果是父类 __init__ 调用的，跳过初始化
        if hasattr(self, '_skip_parent_init') and self._skip_parent_init:
            return None
            
        try:
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class({
                'enableRateLimit': True,
                'rateLimit': KLINE_FILLER_LAZY_RATE_LIMIT,
                'timeout': KLINE_FILLER_LAZY_TIMEOUT_MS,
            })
            # ✅ 不调用 load_markets()，瞬间完成
            logger.info(f"交易所 {exchange_id} 轻量级初始化完成")
            return exchange
        except Exception as e:
            logger.error(f"交易所初始化失败: {e}")
            raise
    
    def _ensure_exchange_initialized(self) -> bool:
        """
        确保交易所已初始化（线程安全、按需加载）
        
        使用双检锁（Double-Checked Locking）模式：
        1. 第一次检查（无锁）：快速路径
        2. 加锁
        3. 第二次检查（有锁）：防止竞态条件
        4. 初始化
        
        Returns:
            bool: 交易所是否可用
        """
        # 第一次检查（无锁）- 快速路径
        if self.exchange is not None:
            return True
        
        # 加锁进行初始化
        with self._exchange_lock:
            # 第二次检查（有锁）
            if self.exchange is not None:
                return True
            
            # 只尝试一次初始化
            if self._init_attempted:
                return False
            
            self._init_attempted = True
            
            try:
                logger.info(f"首次需要交易所连接，正在初始化 {self.exchange_id}...")
                self._skip_parent_init = False
                self.exchange = self._init_exchange(self.exchange_id)
                logger.info(f"✓ 交易所初始化成功")
                return True
            except Exception as e:
                logger.error(f"✗ 交易所初始化失败: {e}")
                logger.warning("数据补充功能将不可用，但不影响主服务运行")
                return False
    
    def _normalize_symbol_for_ccxt(self, symbol: str) -> str:
        """
        符号规范化（简化版 - 适用于已知符号）
        
        不依赖 exchange.markets，直接进行大写转换。
        适用于 HYPE/PURR 等已知符号。
        
        Args:
            symbol: 原始符号（如 'HYPE/USDC:USDC', 'kSHIB/USDC:USDC'）
            
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
    
    def _fetch_ohlcv_with_retry(
        self,
        symbol: str,
        timeframe: str,
        since: int,
        limit: int,
        max_retries: int = 3
    ) -> List:
        """
        带重试机制的 OHLCV 获取
        
        在网络超时或临时错误时自动重试，使用指数退避策略。
        
        Args:
            symbol: 交易对符号
            timeframe: 时间周期
            since: 起始时间戳（毫秒）
            limit: 数据条数限制
            max_retries: 最大重试次数
            
        Returns:
            List: OHLCV 数据
        """
        for attempt in range(1, max_retries + 1):
            try:
                ohlcv = self.exchange.fetch_ohlcv(
                    symbol,
                    timeframe=timeframe,
                    since=since,
                    limit=limit
                )
                
                if attempt > 1:
                    logger.info(f"✓ API 请求成功（重试 {attempt - 1} 次后）")
                
                return ohlcv
            
            except ccxt.RequestTimeout as e:
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"API 请求超时，{wait_time}秒后重试 ({attempt}/{max_retries}) | {e}"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"API 请求超时，已达最大重试次数 ({max_retries}) | {e}")
                    raise
            
            except ccxt.NetworkError as e:
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"网络错误，{wait_time}秒后重试 ({attempt}/{max_retries}) | {e}"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"网络错误，已达最大重试次数 ({max_retries}) | {e}")
                    raise
            
            except ccxt.RateLimitExceeded as e:
                if attempt < max_retries:
                    wait_time = self.API_REQUEST_INTERVAL * (2 ** attempt)
                    logger.warning(
                        f"触发限流，{wait_time:.1f}秒后重试 ({attempt}/{max_retries}) | {e}"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"触发限流，已达最大重试次数 ({max_retries}) | {e}")
                    raise
            
            except Exception as e:
                logger.error(f"API 调用失败: {e}")
                raise
        
        return []
    
    def fill_missing_data_precise(
        self,
        symbol: str,
        timeframe: str,
        missing_timestamps: List[datetime]
    ) -> int:
        """
        精准补充（覆盖父类方法，添加按需初始化）
        """
        if not missing_timestamps:
            return 0
        
        if self._is_in_cooldown(symbol, timeframe):
            logger.debug(
                f"冷却期内，跳过精准补充 | {symbol} @ {timeframe} | "
                f"缺失点数: {len(missing_timestamps)}"
            )
            return 0
        
        self._update_cooldown(symbol, timeframe)
        
        # ✅ 按需初始化交易所
        if not self._ensure_exchange_initialized():
            logger.warning(f"交易所不可用，跳过精准补充 | {symbol} @ {timeframe}")
            return 0
        
        # 使用简化的符号规范化
        api_symbol = self._normalize_symbol_for_ccxt(symbol)
        
        # 调用父类的实现逻辑
        from datetime import timedelta
        
        interval_minutes = self._timeframe_to_minutes(timeframe)
        interval_delta = timedelta(minutes=interval_minutes)
        
        min_ts = min(missing_timestamps)
        max_ts = max(missing_timestamps)
        start_time = min_ts - interval_delta
        end_time = max_ts + interval_delta
        
        limit = max(len(missing_timestamps) + 2, 10)
        
        logger.info(
            f"精准补充K线数据 | {symbol} @ {timeframe} | "
            f"缺失点数: {len(missing_timestamps)} | 拉取: {limit} 条 | "
            f"范围: {start_time.isoformat()} ~ {end_time.isoformat()}"
        )
        
        try:
            since = int(start_time.timestamp() * 1000)
            
            # 使用带重试机制的 API 调用
            ohlcv = self._fetch_ohlcv_with_retry(
                api_symbol,
                timeframe=timeframe,
                since=since,
                limit=min(limit, self.API_LIMIT)
            )
            
            if not ohlcv:
                logger.warning(f"精准补充：API返回空数据 | {symbol} @ {timeframe}")
                return 0
            
            klines = self._convert_ohlcv_to_klines(ohlcv, symbol, timeframe)
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
        完整范围补充（覆盖父类方法，添加按需初始化）
        """
        if self._is_in_cooldown(symbol, timeframe):
            logger.debug(
                f"冷却期内，跳过补充 | {symbol} @ {timeframe} | "
                f"剩余: {self.COOLDOWN_SECONDS - (time.time() - self.fill_cooldown.get((symbol, timeframe), 0)):.0f}秒"
            )
            return 0
        
        self._update_cooldown(symbol, timeframe)
        
        # ✅ 按需初始化交易所
        if not self._ensure_exchange_initialized():
            logger.warning(f"交易所不可用，跳过数据补充 | {symbol} @ {timeframe}")
            return 0
        
        # 使用简化的符号规范化
        api_symbol = self._normalize_symbol_for_ccxt(symbol)
        
        logger.info(
            f"开始补充K线数据 | {symbol} @ {timeframe} | "
            f"时间范围: {start_time.isoformat()} ~ {end_time.isoformat()}"
        )
        
        try:
            since = int(start_time.timestamp() * 1000)
            until = int(end_time.timestamp() * 1000)
            
            all_rows = []
            
            while since < until:
                try:
                    # 使用带重试机制的 API 调用
                    ohlcv = self._fetch_ohlcv_with_retry(
                        api_symbol,
                        timeframe=timeframe,
                        since=since,
                        limit=self.API_LIMIT
                    )
                    
                    if not ohlcv:
                        logger.debug(f"API返回空数据，停止获取 | {symbol} @ {timeframe}")
                        break
                    
                    all_rows.extend(ohlcv)
                    since = ohlcv[-1][0] + 1
                    
                    logger.debug(
                        f"获取K线数据 | {symbol} @ {timeframe} | "
                        f"本次: {len(ohlcv)} 条 | 累计: {len(all_rows)} 条"
                    )
                    
                    if len(ohlcv) < self.API_LIMIT:
                        break
                    
                    time.sleep(self.API_REQUEST_INTERVAL)
                
                except Exception as e:
                    logger.error(f"获取K线数据失败 | {symbol} @ {timeframe} | {e}")
                    break
            
            if not all_rows:
                logger.warning(f"未获取到任何K线数据 | {symbol} @ {timeframe}")
                return 0
            
            klines = self._convert_ohlcv_to_klines(all_rows, symbol, timeframe)
            count = self.kline_repo.batch_upsert_copy(klines, on_conflict='update')
            
            logger.info(
                f"K线数据补充完成 | {symbol} @ {timeframe} | "
                f"获取: {len(all_rows)} 条 | 写入: {count} 条"
            )
            
            return count
        
        except Exception as e:
            logger.error(f"K线数据补充失败 | {symbol} @ {timeframe} | {e}", exc_info=True)
            return 0


# 导出
__all__ = ['KlineDataFillerLazy']
