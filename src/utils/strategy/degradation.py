"""
降级策略模块 - 系统过载保护
用途: 队列压力过大时自动降级，保护系统稳定性
"""
from typing import Dict, Set, List, Optional
from src.utils.core.logging_config import logger


class DegradationStrategy:
    """降级策略管理器"""

    # 核心交易对（始终处理）
    CORE_SYMBOLS: Set[str] = {
        'BTC/USDC:USDC',
        'ETH/USDC:USDC',
        'SOL/USDC:USDC',
        'HYPE/USDC:USDC',
        'PURR/USDC:USDC'
    }

    # 关键时间周期（降级时保留）
    CRITICAL_TIMEFRAMES: Set[str] = {'5m', '1h'}

    # 降级级别定义
    DEGRADATION_LEVELS = {
        0: {'name': '正常', 'threshold': 0.0, 'enabled': False},
        1: {'name': '轻度降级', 'threshold': 0.80, 'enabled': True},
        2: {'name': '中度降级', 'threshold': 0.90, 'enabled': True},
        3: {'name': '重度降级', 'threshold': 0.95, 'enabled': True},
        4: {'name': '极限降级', 'threshold': 0.98, 'enabled': True}
    }

    def __init__(self, enabled: bool = True):
        """
        初始化降级策略

        Args:
            enabled: 是否启用降级策略
        """
        self.enabled = enabled
        self.current_level = 0
        self.stats = {
            'total_checks': 0,
            'degraded_count': 0,
            'level_changes': 0,
            'skipped_tasks': 0
        }

        logger.info(f"✅ 降级策略已初始化: enabled={enabled}")

    def get_degradation_level(self, queue_utilization: float) -> int:
        """
        根据队列使用率计算降级级别

        Args:
            queue_utilization: 队列使用率 (0.0-1.0)

        Returns:
            降级级别 (0-4)
        """
        if not self.enabled:
            return 0

        for level in range(4, -1, -1):
            config = self.DEGRADATION_LEVELS[level]
            if queue_utilization >= config['threshold']:
                return level

        return 0

    def should_process_task(
        self,
        symbol: str,
        timeframe: str,
        queue_utilization: float
    ) -> bool:
        """
        判断是否应该处理该任务

        Args:
            symbol: 交易对
            timeframe: 时间周期
            queue_utilization: 队列使用率 (0.0-1.0)

        Returns:
            True表示应该处理，False表示应该跳过
        """
        self.stats['total_checks'] += 1

        if not self.enabled:
            return True

        # 计算当前降级级别
        new_level = self.get_degradation_level(queue_utilization)

        # 记录级别变化
        if new_level != self.current_level:
            self._log_level_change(self.current_level, new_level, queue_utilization)
            self.current_level = new_level
            self.stats['level_changes'] += 1

        # 级别0: 正常处理
        if new_level == 0:
            return True

        # 级别1: 轻度降级 - 只跳过次要周期
        if new_level == 1:
            if timeframe not in self.CRITICAL_TIMEFRAMES:
                self.stats['skipped_tasks'] += 1
                self.stats['degraded_count'] += 1
                logger.debug(f"[轻度降级] 跳过次要周期: {symbol} @ {timeframe}")
                return False
            return True

        # 级别2: 中度降级 - 只处理核心交易对的关键周期
        if new_level == 2:
            if symbol not in self.CORE_SYMBOLS or timeframe not in self.CRITICAL_TIMEFRAMES:
                self.stats['skipped_tasks'] += 1
                self.stats['degraded_count'] += 1
                logger.debug(f"[中度降级] 跳过非核心任务: {symbol} @ {timeframe}")
                return False
            return True

        # 级别3: 重度降级 - 只处理核心交易对的5分钟周期
        if new_level == 3:
            if symbol not in self.CORE_SYMBOLS or timeframe != '5m':
                self.stats['skipped_tasks'] += 1
                self.stats['degraded_count'] += 1
                logger.debug(f"[重度降级] 只处理核心5m: {symbol} @ {timeframe}")
                return False
            return True

        # 级别4: 极限降级 - 只处理BTC/ETH的5分钟周期
        if new_level == 4:
            extreme_core = {'BTC/USDC:USDC', 'ETH/USDC:USDC'}
            if symbol not in extreme_core or timeframe != '5m':
                self.stats['skipped_tasks'] += 1
                self.stats['degraded_count'] += 1
                logger.debug(f"[极限降级] 只处理BTC/ETH 5m: {symbol} @ {timeframe}")
                return False
            return True

        return True

    def _log_level_change(self, old_level: int, new_level: int, utilization: float) -> None:
        """记录降级级别变化"""
        old_name = self.DEGRADATION_LEVELS[old_level]['name']
        new_name = self.DEGRADATION_LEVELS[new_level]['name']

        if new_level > old_level:
            logger.warning(
                f"⚠️ 降级升级: {old_name} → {new_name} | "
                f"队列使用率: {utilization*100:.1f}%"
            )
        elif new_level < old_level:
            logger.info(
                f"✅ 降级恢复: {old_name} → {new_name} | "
                f"队列使用率: {utilization*100:.1f}%"
            )

    def get_stats(self) -> Dict:
        """获取降级统计信息"""
        total = self.stats['total_checks']
        skip_rate = (self.stats['skipped_tasks'] / total * 100) if total > 0 else 0

        return {
            'enabled': self.enabled,
            'current_level': self.current_level,
            'level_name': self.DEGRADATION_LEVELS[self.current_level]['name'],
            'total_checks': total,
            'degraded_count': self.stats['degraded_count'],
            'skipped_tasks': self.stats['skipped_tasks'],
            'skip_rate': skip_rate,
            'level_changes': self.stats['level_changes']
        }

    def log_stats(self) -> None:
        """输出降级统计日志"""
        stats = self.get_stats()
        logger.info(
            f"📊 降级统计 | "
            f"级别: {stats['level_name']} ({stats['current_level']}) | "
            f"检查: {stats['total_checks']} | "
            f"跳过: {stats['skipped_tasks']} ({stats['skip_rate']:.1f}%) | "
            f"级别变化: {stats['level_changes']}"
        )

    def reset_stats(self) -> None:
        """重置统计信息"""
        self.stats = {
            'total_checks': 0,
            'degraded_count': 0,
            'level_changes': 0,
            'skipped_tasks': 0
        }
        logger.debug("降级统计已重置")


class PriorityQueue:
    """优先级队列管理器"""

    # 交易对优先级映射
    SYMBOL_PRIORITY: Dict[str, int] = {
        'BTC/USDC:USDC': 1,
        'ETH/USDC:USDC': 1,
        'SOL/USDC:USDC': 2,
        'HYPE/USDC:USDC': 2,
        'PURR/USDC:USDC': 2,
        # 其他交易对默认优先级3
    }

    # 时间周期优先级
    TIMEFRAME_PRIORITY: Dict[str, int] = {
        '5m': 1,
        '1h': 2,
        '4h': 3
    }

    @classmethod
    def calculate_priority(cls, symbol: str, timeframe: str) -> int:
        """
        计算任务优先级（数字越小优先级越高）

        Args:
            symbol: 交易对
            timeframe: 时间周期

        Returns:
            优先级分数 (1-6)
        """
        symbol_priority = cls.SYMBOL_PRIORITY.get(symbol, 3)
        timeframe_priority = cls.TIMEFRAME_PRIORITY.get(timeframe, 3)

        # 综合优先级（加权平均）
        priority = symbol_priority + timeframe_priority // 2

        return priority

    @classmethod
    def get_task_priority_info(cls, symbol: str, timeframe: str) -> Dict:
        """获取任务优先级信息（用于调试）"""
        return {
            'symbol': symbol,
            'timeframe': timeframe,
            'priority': cls.calculate_priority(symbol, timeframe),
            'symbol_priority': cls.SYMBOL_PRIORITY.get(symbol, 3),
            'timeframe_priority': cls.TIMEFRAME_PRIORITY.get(timeframe, 3)
        }
