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

from typing import List

from realtime_kline_service_base import RealtimeKlineServiceBase, ServiceConfig
from utils.kline_data_filler_lazy import KlineDataFillerLazy
from utils.config import (
    # HYPE 专用配置
    HYPE_BASE_SYMBOL,
    HYPE_SYMBOLS,
    HYPE_CORR_THRESHOLD,
    # 队列配置（HYPE 专用）
    QUEUE_CONFIG_HYPE,
    # 工作线程配置（HYPE 专用）
    ANALYSIS_WORKERS_HYPE,
)


# =====================================================
# 实时K线分析服务 - HYPE/PURR 配对专用版
# =====================================================

class RealtimeKlineServiceHypePurr(RealtimeKlineServiceBase):
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

    def _get_config_params(self) -> ServiceConfig:
        """
        获取 HYPE/PURR 专用版服务配置参数

        Returns:
            ServiceConfig 实例
        """
        return ServiceConfig(
            base_symbol=HYPE_BASE_SYMBOL,
            corr_threshold=HYPE_CORR_THRESHOLD,
            queue_config=QUEUE_CONFIG_HYPE,
            analysis_workers=ANALYSIS_WORKERS_HYPE,
            data_filler_class=KlineDataFillerLazy,
            logger_module='get_logger'  # 使用 from utils.logging_config import get_logger
        )

    def _get_active_symbols(self) -> List[str]:
        """
        获取活跃币种列表（固定返回 HYPE 和 PURR）

        Returns:
            固定币种列表（从配置读取）
        """
        return HYPE_SYMBOLS

    def _should_enable_symbol_monitoring(self) -> bool:
        """
        是否启用新币种监控线程（HYPE 版禁用）

        Returns:
            False（禁用新币种监控）
        """
        return False

    def _get_corr_threshold_for_analysis(self) -> float:
        """
        获取分析用的相关系数阈值（HYPE 专用）

        Returns:
            HYPE_CORR_THRESHOLD (0.5) - 更宽松的阈值
        """
        return HYPE_CORR_THRESHOLD


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
