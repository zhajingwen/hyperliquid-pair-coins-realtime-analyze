"""
队列健康监控增强模块
用途: 实时监控队列健康状态，提供详细的性能指标
"""
import time
import threading
from typing import Dict, Optional, Callable
from collections import deque
from src.utils.core.logging_config import logger


class QueueHealthMonitor:
    """队列健康监控器"""

    def __init__(
        self,
        queue,
        name: str = "Queue",
        window_size: int = 60,
        alert_callback: Optional[Callable] = None
    ):
        """
        初始化监控器

        Args:
            queue: 要监控的队列对象
            name: 队列名称
            window_size: 统计窗口大小（秒）
            alert_callback: 告警回调函数
        """
        self.queue = queue
        self.name = name
        self.window_size = window_size
        self.alert_callback = alert_callback

        # 速率统计（使用滑动窗口）
        self.enqueue_times = deque(maxlen=1000)
        self.dequeue_times = deque(maxlen=1000)

        # 分析耗时统计
        self.analysis_durations = deque(maxlen=100)

        # 统计信息
        self.stats = {
            'total_enqueued': 0,
            'total_dequeued': 0,
            'total_drops': 0,
            'max_size_seen': 0,
            'total_analysis_time': 0.0,
            'analysis_count': 0
        }

        # 启动时间
        self.start_time = time.time()

        logger.info(f"✅ 队列监控器已初始化: {name}")

    def record_enqueue(self) -> None:
        """记录入队事件"""
        self.enqueue_times.append(time.time())
        self.stats['total_enqueued'] += 1

    def record_dequeue(self) -> None:
        """记录出队事件"""
        self.dequeue_times.append(time.time())
        self.stats['total_dequeued'] += 1

    def record_drop(self) -> None:
        """记录丢弃事件"""
        self.stats['total_drops'] += 1

    def record_analysis_duration(self, duration: float) -> None:
        """
        记录分析耗时

        Args:
            duration: 分析耗时（秒）
        """
        self.analysis_durations.append(duration)
        self.stats['total_analysis_time'] += duration
        self.stats['analysis_count'] += 1

    def calculate_rate(self, times: deque) -> float:
        """
        计算速率（每秒事件数）

        Args:
            times: 时间戳队列

        Returns:
            速率值
        """
        if len(times) < 2:
            return 0.0

        current_time = time.time()
        # 过滤窗口内的数据
        recent_times = [t for t in times if current_time - t <= self.window_size]

        if len(recent_times) < 2:
            return 0.0

        duration = current_time - recent_times[0]
        if duration == 0:
            return 0.0

        return len(recent_times) / duration

    def get_metrics(self) -> Dict:
        """获取监控指标"""
        current_size = self.queue.qsize()
        max_size = self.queue.maxsize
        utilization = current_size / max_size if max_size > 0 else 0.0

        # 更新最大大小记录
        if current_size > self.stats['max_size_seen']:
            self.stats['max_size_seen'] = current_size

        # 计算速率
        enqueue_rate = self.calculate_rate(self.enqueue_times)
        dequeue_rate = self.calculate_rate(self.dequeue_times)

        # 计算平均分析耗时
        avg_analysis_time = 0.0
        if self.analysis_durations:
            avg_analysis_time = sum(self.analysis_durations) / len(self.analysis_durations)

        # 计算工作线程利用率（估算）
        worker_utilization = 0.0
        if dequeue_rate > 0 and avg_analysis_time > 0:
            # 利用率 = 实际处理时间 / 总时间
            worker_utilization = min(dequeue_rate * avg_analysis_time, 1.0)

        # 运行时间
        uptime = time.time() - self.start_time

        return {
            'name': self.name,
            'current_size': current_size,
            'max_size': max_size,
            'utilization': utilization,
            'max_size_seen': self.stats['max_size_seen'],
            'enqueue_rate': enqueue_rate,
            'dequeue_rate': dequeue_rate,
            'rate_balance': enqueue_rate - dequeue_rate,
            'total_enqueued': self.stats['total_enqueued'],
            'total_dequeued': self.stats['total_dequeued'],
            'total_drops': self.stats['total_drops'],
            'drop_rate': self.stats['total_drops'] / self.stats['total_enqueued'] * 100 if self.stats['total_enqueued'] > 0 else 0,
            'avg_analysis_time': avg_analysis_time,
            'analysis_count': self.stats['analysis_count'],
            'worker_utilization': worker_utilization,
            'uptime': uptime
        }

    def check_health(self) -> Dict:
        """
        检查队列健康状态

        Returns:
            健康状态字典
        """
        metrics = self.get_metrics()

        # 健康评分（0-100）
        health_score = 100.0

        # 扣分因素
        issues = []

        # 1. 队列使用率过高
        if metrics['utilization'] > 0.95:
            health_score -= 50
            issues.append(f"队列使用率极高 ({metrics['utilization']*100:.1f}%)")
        elif metrics['utilization'] > 0.80:
            health_score -= 30
            issues.append(f"队列使用率偏高 ({metrics['utilization']*100:.1f}%)")

        # 2. 速率不平衡
        if metrics['rate_balance'] > metrics['dequeue_rate'] * 0.5:
            health_score -= 20
            issues.append(f"入队速率远超出队速率 ({metrics['enqueue_rate']:.2f} vs {metrics['dequeue_rate']:.2f})")

        # 3. 丢弃率过高
        if metrics['drop_rate'] > 10:
            health_score -= 20
            issues.append(f"丢弃率过高 ({metrics['drop_rate']:.1f}%)")

        # 4. 分析耗时过长
        if metrics['avg_analysis_time'] > 30:
            health_score -= 10
            issues.append(f"平均分析耗时过长 ({metrics['avg_analysis_time']:.1f}s)")

        # 5. 工作线程利用率过高
        if metrics['worker_utilization'] > 0.90:
            health_score -= 10
            issues.append(f"工作线程利用率过高 ({metrics['worker_utilization']*100:.1f}%)")

        # 确保分数在0-100范围内
        health_score = max(0, min(100, health_score))

        # 健康等级
        if health_score >= 80:
            status = '健康'
            level = 'HEALTHY'
        elif health_score >= 60:
            status = '警告'
            level = 'WARNING'
        elif health_score >= 40:
            status = '异常'
            level = 'UNHEALTHY'
        else:
            status = '严重'
            level = 'CRITICAL'

        health_status = {
            'score': health_score,
            'status': status,
            'level': level,
            'issues': issues,
            'metrics': metrics
        }

        # 触发告警
        if self.alert_callback and level in ['UNHEALTHY', 'CRITICAL']:
            self.alert_callback(health_status)

        return health_status

    def log_health(self) -> None:
        """输出健康状态日志"""
        health = self.check_health()
        metrics = health['metrics']

        log_msg = (
            f"📊 {self.name}健康监控 | "
            f"状态: {health['status']} ({health['score']:.0f}分) | "
            f"队列: {metrics['current_size']}/{metrics['max_size']} ({metrics['utilization']*100:.1f}%) | "
            f"速率: ↑{metrics['enqueue_rate']:.2f}/s ↓{metrics['dequeue_rate']:.2f}/s | "
            f"丢弃: {metrics['total_drops']} ({metrics['drop_rate']:.1f}%) | "
            f"耗时: {metrics['avg_analysis_time']:.1f}s"
        )

        if health['issues']:
            log_msg += f" | 问题: {'; '.join(health['issues'])}"

        if health['level'] == 'CRITICAL':
            logger.error(log_msg)
        elif health['level'] == 'UNHEALTHY':
            logger.warning(log_msg)
        elif health['level'] == 'WARNING':
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

    def get_recommendations(self) -> list:
        """
        获取优化建议

        Returns:
            建议列表
        """
        metrics = self.get_metrics()
        recommendations = []

        # 队列容量建议
        if metrics['utilization'] > 0.90:
            recommendations.append(
                f"建议增加队列容量: 当前 {metrics['max_size']} → 建议 {int(metrics['max_size'] * 1.5)}"
            )

        # 工作线程建议
        if metrics['rate_balance'] > 0 and metrics['utilization'] > 0.80:
            estimated_workers = int(metrics['enqueue_rate'] / metrics['dequeue_rate'] * 1.5)
            recommendations.append(
                f"建议增加工作线程: 估算需要 {estimated_workers} 个线程"
            )

        # 性能优化建议
        if metrics['avg_analysis_time'] > 20:
            recommendations.append(
                "建议优化分析逻辑: 平均耗时过长，考虑添加缓存或优化数据库查询"
            )

        # 降级策略建议
        if metrics['drop_rate'] > 5:
            recommendations.append(
                "建议启用降级策略: 丢弃率过高，可通过降级保护系统稳定性"
            )

        return recommendations


# 示例使用
if __name__ == "__main__":
    import queue

    # 创建测试队列
    test_queue = queue.Queue(maxsize=100)

    # 创建监控器
    monitor = QueueHealthMonitor(test_queue, name="测试队列")

    # 模拟入队和出队
    for i in range(50):
        test_queue.put(i)
        monitor.record_enqueue()

    for i in range(20):
        test_queue.get()
        monitor.record_dequeue()
        monitor.record_analysis_duration(0.5)

    # 输出健康状态
    monitor.log_health()

    # 获取建议
    recommendations = monitor.get_recommendations()
    for rec in recommendations:
        print(f"💡 {rec}")
