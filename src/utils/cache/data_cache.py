"""
数据缓存模块 - 优化分析性能
用途: 缓存历史K线数据，减少数据库查询次数
"""
import time
import threading
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import OrderedDict
from src.utils.core.logging_config import logger


class KlineDataCache:
    """K线数据缓存（LRU策略）"""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        """
        初始化缓存

        Args:
            max_size: 最大缓存条目数
            ttl_seconds: 缓存有效期（秒）
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds

        # 缓存存储: {(symbol, timeframe): (data, timestamp)}
        self.cache: OrderedDict[Tuple[str, str], Tuple[List[Dict], float]] = OrderedDict()
        self.lock = threading.RLock()

        # 统计信息
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'invalidations': 0
        }

        logger.info(f"✅ K线数据缓存已初始化: max_size={max_size}, ttl={ttl_seconds}s")

    def get(self, symbol: str, timeframe: str) -> Optional[List[Dict]]:
        """
        获取缓存数据

        Args:
            symbol: 交易对
            timeframe: 时间周期

        Returns:
            缓存的K线数据列表，如果不存在或过期则返回None
        """
        cache_key = (symbol, timeframe)

        with self.lock:
            if cache_key not in self.cache:
                self.stats['misses'] += 1
                return None

            data, timestamp = self.cache[cache_key]

            # 检查是否过期
            if time.time() - timestamp > self.ttl_seconds:
                del self.cache[cache_key]
                self.stats['invalidations'] += 1
                self.stats['misses'] += 1
                logger.debug(f"缓存过期: {symbol} @ {timeframe}")
                return None

            # 命中，移到末尾（LRU）
            self.cache.move_to_end(cache_key)
            self.stats['hits'] += 1

            logger.debug(
                f"缓存命中: {symbol} @ {timeframe} | "
                f"数据点: {len(data)} | "
                f"年龄: {time.time() - timestamp:.1f}s"
            )
            return data.copy()  # 返回副本，避免外部修改

    def put(self, symbol: str, timeframe: str, data: List[Dict]) -> None:
        """
        写入缓存

        Args:
            symbol: 交易对
            timeframe: 时间周期
            data: K线数据列表
        """
        if not data:
            return

        cache_key = (symbol, timeframe)

        with self.lock:
            # LRU淘汰
            if len(self.cache) >= self.max_size and cache_key not in self.cache:
                evicted_key = next(iter(self.cache))
                del self.cache[evicted_key]
                self.stats['evictions'] += 1
                logger.debug(f"缓存淘汰: {evicted_key[0]} @ {evicted_key[1]}")

            # 写入缓存
            self.cache[cache_key] = (data.copy(), time.time())
            self.cache.move_to_end(cache_key)

            logger.debug(
                f"缓存写入: {symbol} @ {timeframe} | "
                f"数据点: {len(data)} | "
                f"缓存大小: {len(self.cache)}/{self.max_size}"
            )

    def update(self, symbol: str, timeframe: str, new_kline: Dict) -> bool:
        """
        增量更新缓存（追加最新K线）

        Args:
            symbol: 交易对
            timeframe: 时间周期
            new_kline: 新K线数据

        Returns:
            更新成功返回True，缓存不存在返回False
        """
        cache_key = (symbol, timeframe)

        with self.lock:
            if cache_key not in self.cache:
                return False

            data, timestamp = self.cache[cache_key]

            # 检查是否过期
            if time.time() - timestamp > self.ttl_seconds:
                del self.cache[cache_key]
                self.stats['invalidations'] += 1
                return False

            # 追加新数据
            data.append(new_kline)

            # 更新时间戳
            self.cache[cache_key] = (data, time.time())
            self.cache.move_to_end(cache_key)

            logger.debug(
                f"缓存增量更新: {symbol} @ {timeframe} | "
                f"数据点: {len(data)}"
            )
            return True

    def invalidate(self, symbol: str, timeframe: str) -> None:
        """
        主动失效缓存

        Args:
            symbol: 交易对
            timeframe: 时间周期
        """
        cache_key = (symbol, timeframe)

        with self.lock:
            if cache_key in self.cache:
                del self.cache[cache_key]
                self.stats['invalidations'] += 1
                logger.debug(f"缓存失效: {symbol} @ {timeframe}")

    def clear(self) -> None:
        """清空所有缓存"""
        with self.lock:
            count = len(self.cache)
            self.cache.clear()
            logger.info(f"缓存已清空: {count} 条记录")

    def get_stats(self) -> Dict:
        """获取缓存统计信息"""
        with self.lock:
            total_requests = self.stats['hits'] + self.stats['misses']
            hit_rate = (self.stats['hits'] / total_requests * 100) if total_requests > 0 else 0

            return {
                'size': len(self.cache),
                'max_size': self.max_size,
                'utilization': len(self.cache) / self.max_size * 100,
                'hits': self.stats['hits'],
                'misses': self.stats['misses'],
                'hit_rate': hit_rate,
                'evictions': self.stats['evictions'],
                'invalidations': self.stats['invalidations'],
                'total_requests': total_requests
            }

    def log_stats(self) -> None:
        """输出缓存统计日志"""
        stats = self.get_stats()
        logger.info(
            f"📊 缓存统计 | "
            f"大小: {stats['size']}/{stats['max_size']} ({stats['utilization']:.1f}%) | "
            f"命中率: {stats['hit_rate']:.1f}% ({stats['hits']}/{stats['total_requests']}) | "
            f"淘汰: {stats['evictions']} | "
            f"失效: {stats['invalidations']}"
        )


# 全局缓存实例
_global_cache: Optional[KlineDataCache] = None


def get_global_cache() -> KlineDataCache:
    """获取全局缓存实例（单例模式）"""
    global _global_cache
    if _global_cache is None:
        _global_cache = KlineDataCache(max_size=1000, ttl_seconds=300)
    return _global_cache


def init_cache(max_size: int = 1000, ttl_seconds: int = 300) -> None:
    """初始化全局缓存"""
    global _global_cache
    _global_cache = KlineDataCache(max_size=max_size, ttl_seconds=ttl_seconds)
