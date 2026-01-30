"""
K线聚合器（5m → 1h/4h）

将5分钟K线实时聚合生成1小时和4小时K线。
"""

import threading
from typing import Dict, List, Optional
from datetime import datetime


class KlineAggregator:
    """
    5分钟K线聚合器，实时生成1h和4h K线

    聚合原理：
    - 1h = 12个5m K线聚合（整点对齐：00:00, 01:00, ...）
    - 4h = 48个5m K线聚合（固定时间：00:00, 04:00, 08:00, 12:00, 16:00, 20:00）

    OHLCV聚合规则：
    - open  = 第一个5m的open（固定）
    - high  = max(已收到的5m的high)（实时更新）
    - low   = min(已收到的5m的low)（实时更新）
    - close = 最新5m的close（实时更新）
    - volume = sum(已收到的5m的volume)（实时更新）
    """

    def __init__(self):
        # 缓存结构: {(symbol, timeframe): {
        #     'open': x, 'high': x, 'low': x, 'close': x,
        #     'volume': x, 'volume_usd': x,
        #     'start_time': datetime, 'count': int
        # }}
        self.pending_klines = {}
        self.lock = threading.Lock()

    def process_5m_kline(self, kline: Dict) -> List[Dict]:
        """
        处理5分钟K线并返回需要更新的聚合K线列表

        注意：每次都会返回更新后的1h和4h K线（实时更新策略），
        通过返回数据中的 `is_complete` 字段判断是否完成聚合

        Args:
            kline: 5分钟K线数据

        Returns:
            聚合后的1h和4h K线列表
        """
        symbol = kline['symbol']
        aggregated = []

        with self.lock:
            # 更新1h聚合
            h1_kline = self._update_aggregation(symbol, kline, '1h', 60)
            if h1_kline:
                aggregated.append(h1_kline)

            # 更新4h聚合
            h4_kline = self._update_aggregation(symbol, kline, '4h', 240)
            if h4_kline:
                aggregated.append(h4_kline)

        return aggregated

    def _update_aggregation(self, symbol: str, kline: Dict,
                            target_tf: str, period_minutes: int) -> Optional[Dict]:
        """
        更新聚合数据

        Args:
            symbol: 币种符号
            kline: 5分钟K线数据
            target_tf: 目标周期（'1h' 或 '4h'）
            period_minutes: 周期分钟数（60 或 240）

        Returns:
            返回当前聚合状态的K线数据（可能未完成），
            通过返回数据中的 `is_complete` 字段判断是否完成
        """
        kline_time = kline['time']

        # 计算当前周期的起始时间
        period_start = self._get_period_start(kline_time, period_minutes)
        cache_key = (symbol, target_tf)

        # 计算该周期应有的5m K线数量
        expected_count = period_minutes // 5

        # 获取或初始化缓存
        cached = self.pending_klines.get(cache_key)

        # 如果是新周期，重置缓存
        if cached is None or cached['start_time'] != period_start:
            self.pending_klines[cache_key] = {
                'open': kline['open'],
                'open_time': kline_time,  # 记录open对应的K线时间
                'high': kline['high'],
                'low': kline['low'],
                'close': kline['close'],
                'close_time': kline_time,  # 记录close对应的K线时间
                'volume': kline['volume'],
                'volume_usd': kline['volume_usd'],
                'start_time': period_start,
                'count': 1,
                'expected_count': expected_count
            }
        else:
            # 更新现有聚合（支持乱序K线）
            # 如果收到更早的K线，更新open
            if kline_time < cached['open_time']:
                cached['open'] = kline['open']
                cached['open_time'] = kline_time

            # 如果收到更晚的K线，更新close
            if kline_time > cached['close_time']:
                cached['close'] = kline['close']
                cached['close_time'] = kline_time

            cached['high'] = max(cached['high'], kline['high'])
            cached['low'] = min(cached['low'], kline['low'])
            cached['volume'] += kline['volume']
            cached['volume_usd'] += kline['volume_usd']
            cached['count'] += 1

        # 构建返回的K线
        cached = self.pending_klines[cache_key]
        is_complete = cached['count'] >= cached['expected_count']

        return {
            'time': period_start,
            'symbol': symbol,
            'timeframe': target_tf,
            'open': cached['open'],
            'high': cached['high'],
            'low': cached['low'],
            'close': cached['close'],
            'volume': cached['volume'],
            'volume_usd': cached['volume_usd'],
            'return_pct': (cached['close'] - cached['open']) / cached['open']
                          if cached['open'] > 0 else 0.0,
            'kline_count': cached['count'],
            'is_complete': is_complete
        }

    def _get_period_start(self, dt: datetime, period_minutes: int) -> datetime:
        """
        计算周期起始时间

        Args:
            dt: 当前时间
            period_minutes: 周期分钟数

        Returns:
            周期起始时间（对齐到周期边界）
        """
        total_minutes = dt.hour * 60 + dt.minute
        period_start_minutes = (total_minutes // period_minutes) * period_minutes
        return dt.replace(
            hour=period_start_minutes // 60,
            minute=period_start_minutes % 60,
            second=0,
            microsecond=0
        )

    def get_stats(self) -> Dict:
        """获取聚合器统计信息"""
        with self.lock:
            incomplete_1h = []
            incomplete_4h = []

            for key, cached in self.pending_klines.items():
                symbol, tf = key
                if cached['count'] < cached['expected_count']:
                    missing = cached['expected_count'] - cached['count']
                    info = {'symbol': symbol, 'count': cached['count'],
                            'expected': cached['expected_count'], 'missing': missing}
                    if tf == '1h':
                        incomplete_1h.append(info)
                    else:
                        incomplete_4h.append(info)

            return {
                'pending_klines_count': len(self.pending_klines),
                'symbols_1h': sum(1 for k in self.pending_klines if k[1] == '1h'),
                'symbols_4h': sum(1 for k in self.pending_klines if k[1] == '4h'),
                'incomplete_1h': incomplete_1h,
                'incomplete_4h': incomplete_4h,
            }
