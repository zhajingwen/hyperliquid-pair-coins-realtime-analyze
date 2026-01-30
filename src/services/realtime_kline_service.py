"""
实时K线分析服务 (Realtime Kline Analysis Service)

核心功能：
- WebSocket 实时数据接收（N个订阅: N个活跃币种 × 3周期(5m/1h/4h)）
- 直接订阅交易所原生 1h/4h K线（精度优于本地聚合）
- 异步批量写入数据库（1000-2000条或5秒触发）
- 收到5m K线WebSocket推送时触发分析（受去重窗口保护）
- Z-score 异常检测 + 飞书告警
- 新币种自动监控

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

性能目标：
- 分析延迟: <5秒
- 告警延迟: <10秒
- 内存占用: <512MB
- CPU占用: <50%

Author: Claude Code
Date: 2026-01-19
"""

from typing import List

from hyperliquid.info import Info
import hyperliquid.utils.constants as constants

from src.services.realtime_kline_service_base import RealtimeKlineServiceBase, ServiceConfig
from src.utils.analysis.kline_data_filler import KlineDataFiller
from src.utils.core.config import (
    # 服务配置
    DEFAULT_BASE_SYMBOL,
    # 队列配置
    QUEUE_CONFIG_GENERAL,
    # 分析参数
    TARGET_CORR_THRESHOLD,
    # 工作线程配置
    ANALYSIS_WORKERS_GENERAL,
)


# =====================================================
# 实时K线分析服务（通用版）
# =====================================================

class RealtimeKlineService(RealtimeKlineServiceBase):
    """
    实时K线分析服务（通用版 - 主分析引擎）

    架构（直接订阅版）：
    ┌─────────────────────────────────────────────────┐
    │ Hyperliquid WebSocket API                       │
    │ (订阅 5m/1h/4h K线，订阅数=活跃币种数×3)        │
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
        获取通用版服务配置参数

        Returns:
            ServiceConfig 实例
        """
        return ServiceConfig(
            base_symbol=DEFAULT_BASE_SYMBOL,
            corr_threshold=TARGET_CORR_THRESHOLD,
            queue_config=QUEUE_CONFIG_GENERAL,
            analysis_workers=ANALYSIS_WORKERS_GENERAL,
            data_filler_class=KlineDataFiller,
            logger_module='logger'  # 使用 from utils.logging_config import logger
        )

    def _get_active_symbols(self) -> List[str]:
        """
        获取活跃币种列表（动态获取）

        Returns:
            活跃币种列表（格式: BTC/USDC:USDC）
        """
        try:
            # 从数据库获取活跃币种
            active_symbols = self.symbol_repo.get_active_symbols()

            if active_symbols:
                self.logger.info(f"从数据库加载 {len(active_symbols)} 个活跃币种")
                return active_symbols

            # 如果数据库为空，从交易所获取
            self.logger.info("数据库无币种数据，从交易所获取...")
            info = Info(constants.MAINNET_API_URL, skip_ws=True)
            meta = info.meta()

            symbols = []
            for asset_info in meta.get('universe', []):
                name = asset_info.get('name')
                if name:
                    # Hyperliquid 格式转换: BTC → BTC/USDC:USDC
                    symbol = f"{name}/USDC:USDC"
                    symbols.append(symbol)

                    # 注册币种到数据库
                    self.symbol_repo.upsert_symbol(
                        symbol=symbol,
                        base_asset=name,
                        quote_asset='USDC',
                        is_active=True
                    )

            self.logger.info(f"从交易所获取 {len(symbols)} 个币种")
            return symbols

        except Exception as e:
            self.logger.error(f"获取币种列表失败: {e}", exc_info=True)
            # 返回默认币种
            return ['BTC/USDC:USDC', 'ETH/USDC:USDC']

    def _should_enable_symbol_monitoring(self) -> bool:
        """
        是否启用新币种监控线程（通用版启用）

        Returns:
            True（启用新币种监控）
        """
        return True

    def _get_corr_threshold_for_analysis(self) -> float:
        """
        获取分析用的相关系数阈值（通用版）

        Returns:
            TARGET_CORR_THRESHOLD (0.6)
        """
        return TARGET_CORR_THRESHOLD


# =====================================================
# 主程序入口
# =====================================================

def main():
    """主程序入口"""
    # 创建服务实例（使用配置文件中的默认值）
    service = RealtimeKlineService()

    # 启动服务
    service.start()


if __name__ == '__main__':
    main()
