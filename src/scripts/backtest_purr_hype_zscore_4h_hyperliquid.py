#!/usr/bin/env python3
"""
PURR-HYPE 4H K线回测与Z-score分析（Hyperliquid数据源）

功能：
1. 使用 CCXT Hyperliquid 获取 HYPE/USDC 和 PURR/USDC 的 4H 历史K线数据（现货）
2. 计算 PURR vs HYPE 的滑动窗口 Z-score
3. 将分析结果写入 PostgreSQL analysis_results 表

数据优势：
- 数据质量：Hyperliquid 交易所原生现货数据（USDC 本位）
- 专注于 HYPE-PURR 配对分析

Author: Claude Code
Date: 2026-02-01
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from pathlib import Path

import ccxt
from tqdm import tqdm

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.utils.analysis.analysis_core import (
    calculate_cointegration_params_dual_window,
    calculate_zscore_ols
)
from src.utils.database.timescaledb import TimescaleDBClient
from src.utils.core.config import BETA_WINDOW, ZSCORE_WINDOW
from src.utils.core.logging_config import logger


# =====================================================
# 数据获取模块
# =====================================================

def fetch_klines_from_hyperliquid(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    interval: str = '4h',
    api_delay: float = 0.2
) -> List[Dict]:
    """
    使用 CCXT Hyperliquid 获取指定币种的K线数据（现货）

    Args:
        symbol: Hyperliquid 现货交易对格式（如 'HYPE/USDC', 'PURR/USDC'）
        start_date: 开始日期（可选，格式：'YYYY-MM-DD'）
        end_date: 结束日期（可选，默认今天）
        interval: 时间周期（默认 '4h'）
        api_delay: API 调用间隔（秒，默认 0.2，避免限流）

    Returns:
        List[Dict]: K线数据列表，格式：
            [
                {
                    'time': datetime,
                    'open': float,
                    'high': float,
                    'low': float,
                    'close': float,
                    'volume': float
                },
                ...
            ]
    """
    logger.info(f"开始获取 {symbol} 的 {interval} K线数据...")

    try:
        # 初始化 Hyperliquid 交易所
        exchange = ccxt.hyperliquid({
            'enableRateLimit': True,  # 启用内置的速率限制
        })

        # 确定时间范围
        if start_date:
            since = int(datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp() * 1000)
        else:
            # 默认从 2023 年开始（Hyperliquid 相关代币上线时间）
            since = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

        if end_date:
            until = int(datetime.strptime(end_date, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp() * 1000)
        else:
            until = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

        # 计算需要的总数据量
        timeframe_seconds = {
            '4h': 4 * 3600,
            '1h': 3600,
            '1d': 24 * 3600
        }
        interval_ms = timeframe_seconds.get(interval, 4 * 3600) * 1000
        total_expected = int((until - since) / interval_ms)

        logger.info(f"  时间范围: {datetime.fromtimestamp(since/1000, tz=timezone.utc)} 至 {datetime.fromtimestamp(until/1000, tz=timezone.utc)}")
        logger.info(f"  预计数据点: 约 {total_expected} 个")

        # 分批获取数据
        all_klines = []
        current_since = since
        limit = 1000  # Binance API 单次最大返回数量

        # 使用 tqdm 显示进度
        with tqdm(total=total_expected, desc=f"获取 {symbol}", unit="条") as pbar:
            while current_since < until:
                # 调用 Binance API
                ohlcv = exchange.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=interval,
                    since=current_since,
                    limit=limit
                )

                if not ohlcv:
                    logger.debug(f"未获取到更多数据，退出循环")
                    break

                # 转换数据格式
                for candle in ohlcv:
                    timestamp_ms, open_price, high, low, close, volume = candle

                    # 过滤无效数据
                    if open_price is None or close is None:
                        continue

                    kline = {
                        'time': datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc),
                        'open': float(open_price),
                        'high': float(high),
                        'low': float(low),
                        'close': float(close),
                        'volume': float(volume)
                    }

                    # 检查是否在时间范围内
                    if timestamp_ms <= until:
                        all_klines.append(kline)
                    else:
                        break

                # 更新进度条
                pbar.update(len(ohlcv))

                # 准备下一批
                if len(ohlcv) < limit:
                    # 没有更多数据了
                    break

                # 下一批的起始时间（最后一个数据点的时间 + 1个interval）
                last_timestamp = ohlcv[-1][0]
                current_since = last_timestamp + interval_ms

                # 如果已经超过结束时间，退出
                if current_since > until:
                    break

                # API 调用延迟（避免限流）
                time.sleep(api_delay)

        logger.info(f"{symbol}: 成功获取 {len(all_klines)} 个 {interval} K线数据")
        if all_klines:
            logger.info(f"  时间范围: {all_klines[0]['time']} 至 {all_klines[-1]['time']}")

        return all_klines

    except Exception as e:
        logger.error(f"获取 {symbol} 数据失败: {e}", exc_info=True)
        return []


def align_klines(
    hype_klines: List[Dict],
    purr_klines: List[Dict]
) -> Tuple[List[Dict], List[Dict]]:
    """
    对齐两个币种的K线数据（确保时间戳一致）

    Args:
        hype_klines: HYPE K线数据
        purr_klines: PURR K线数据

    Returns:
        (aligned_hype, aligned_purr): 对齐后的K线数据
    """
    logger.info("开始对齐 HYPE 和 PURR 的K线数据...")

    # 创建时间戳到K线的映射
    hype_map = {k['time']: k for k in hype_klines}
    purr_map = {k['time']: k for k in purr_klines}

    # 找到共同的时间戳
    common_times = sorted(set(hype_map.keys()) & set(purr_map.keys()))

    # 构建对齐后的数据
    aligned_hype = [hype_map[t] for t in common_times]
    aligned_purr = [purr_map[t] for t in common_times]

    logger.info(f"数据对齐完成: {len(aligned_hype)} 个时间点")
    if aligned_hype:
        logger.info(f"  时间范围: {aligned_hype[0]['time']} 至 {aligned_hype[-1]['time']}")

    return aligned_hype, aligned_purr


# =====================================================
# Z-score 计算模块
# =====================================================

def calculate_zscore_backtest(
    base_klines: List[Dict],
    alt_klines: List[Dict],
    beta_window: int = BETA_WINDOW,
    zscore_window: int = ZSCORE_WINDOW
) -> List[Dict]:
    """
    批量计算滑动窗口 Z-score

    Args:
        base_klines: BTC K线数据（对齐后）
        alt_klines: ETH K线数据（对齐后）
        beta_window: OLS 回归窗口（默认 100）
        zscore_window: Z-score 统计窗口（默认 30）

    Returns:
        List[Dict]: 分析结果列表
    """
    logger.info(f"开始计算 Z-score (滑动窗口计算)...")
    logger.info(f"  BETA_WINDOW = {beta_window}")
    logger.info(f"  ZSCORE_WINDOW = {zscore_window}")

    min_window = max(beta_window, zscore_window)
    total_points = len(base_klines)

    if total_points < min_window:
        logger.error(f"数据点不足: {total_points} < {min_window}")
        return []

    results = []

    # 滑动窗口计算（从第 min_window 个数据点开始）
    for i in tqdm(range(min_window, total_points), desc="计算 Z-score"):
        # 窗口数据（取前 i 个数据点）
        window_base = base_klines[:i]
        window_alt = alt_klines[:i]

        # 计算协整参数
        coint_result = calculate_cointegration_params_dual_window(
            window_base,
            window_alt,
            beta_window,
            zscore_window
        )

        if coint_result is None:
            logger.debug(f"时间点 {base_klines[i-1]['time']}: 协整计算失败")
            continue

        # 计算 Z-score
        zscore = calculate_zscore_ols(
            window_base,
            window_alt,
            zscore_window,
            beta_window,
            cointegration_result=coint_result
        )

        if zscore is None:
            logger.debug(f"时间点 {base_klines[i-1]['time']}: Z-score 计算失败")
            continue

        # 记录结果
        results.append({
            'kline_time': base_klines[i-1]['time'],  # 使用窗口最后一个时间点
            'zscore_4h': zscore,
            'alpha': coint_result['alpha'],
            'beta': coint_result['beta'],
            'adf_pvalue': coint_result['adf_pvalue'],
            'rsquared': coint_result['rsquared'],
            'cointegration_passed': coint_result['adf_pvalue'] < 0.05
        })

    logger.info(f"Z-score 计算完成: {len(results)} 个结果")

    return results


# =====================================================
# 数据库写入模块
# =====================================================

def determine_trading_direction(zscore: float) -> str:
    """根据 Z-score 判断交易方向"""
    if zscore > 2.0:
        return 'short'  # PURR 相对高估，做空 PURR
    elif zscore < -2.0:
        return 'long'   # PURR 相对低估，做多 PURR
    else:
        return 'none'


def determine_signal_strength(zscore: float) -> str:
    """根据 Z-score 判断信号强度"""
    abs_zscore = abs(zscore)

    if abs_zscore > 3.0:
        return 'extreme'
    elif abs_zscore > 2.5:
        return 'strong'
    elif abs_zscore > 2.0:
        return 'medium'
    else:
        return 'weak'


def write_results_to_db(
    results: List[Dict],
    batch_size: int = 1000
) -> int:
    """
    批量写入分析结果到 analysis_results 表

    Args:
        results: 分析结果列表
        batch_size: 批量写入大小（默认 1000）

    Returns:
        int: 成功写入的记录数
    """
    if not results:
        logger.warning("没有结果需要写入数据库")
        return 0

    logger.info(f"开始写入数据库 (共 {len(results)} 条记录)...")

    db_client = TimescaleDBClient()
    total_written = 0

    # 批量写入
    for batch_start in range(0, len(results), batch_size):
        batch_end = min(batch_start + batch_size, len(results))
        batch = results[batch_start:batch_end]

        try:
            with db_client.get_connection() as conn:
                with conn.cursor() as cur:
                    # 准备批量插入数据
                    insert_query = """
                        INSERT INTO analysis_results (
                            analysis_time, kline_time, symbol, base_symbol,
                            zscore_4h, corr_4h_60d,
                            cointegration_passed, adf_pvalue,
                            is_anomaly, trading_direction, signal_strength,
                            analysis_delay_seconds
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s,
                            %s, %s,
                            %s, %s, %s,
                            %s
                        )
                        ON CONFLICT (analysis_time, id) DO UPDATE SET
                            zscore_4h = EXCLUDED.zscore_4h,
                            cointegration_passed = EXCLUDED.cointegration_passed,
                            adf_pvalue = EXCLUDED.adf_pvalue,
                            is_anomaly = EXCLUDED.is_anomaly,
                            trading_direction = EXCLUDED.trading_direction,
                            signal_strength = EXCLUDED.signal_strength
                    """

                    # 准备批量数据
                    batch_data = []
                    for result in batch:
                        zscore = result['zscore_4h']
                        batch_data.append((
                            datetime.now(timezone.utc),          # analysis_time
                            result['kline_time'],                # kline_time
                            'PURR/USDC:USDC',                    # symbol (合约格式)
                            'HYPE/USDC:USDC',                    # base_symbol (合约格式)
                            zscore,                              # zscore_4h
                            None,                                # corr_4h_60d (可选)
                            result['cointegration_passed'],      # cointegration_passed
                            result['adf_pvalue'],                # adf_pvalue
                            abs(zscore) > 2.0 if zscore else False,  # is_anomaly
                            determine_trading_direction(zscore), # trading_direction
                            determine_signal_strength(zscore),   # signal_strength
                            None                                 # analysis_delay_seconds (回测无延迟)
                        ))

                    # 批量执行插入
                    cur.executemany(insert_query, batch_data)
                    conn.commit()

                    total_written += len(batch)
                    logger.info(f"批量写入: {len(batch)} 条记录 (总计: {total_written}/{len(results)})")

        except Exception as e:
            logger.error(f"批量写入失败: {e}", exc_info=True)
            continue

    logger.info(f"成功写入 {total_written} 条分析结果到数据库")
    return total_written


# =====================================================
# 统计模块
# =====================================================

def print_statistics(results: List[Dict]):
    """打印统计信息"""
    if not results:
        logger.warning("没有结果可以统计")
        return

    zscores = [r['zscore_4h'] for r in results if r['zscore_4h'] is not None]

    if not zscores:
        logger.warning("没有有效的 Z-score 数据")
        return

    logger.info("\n=== 统计信息 ===")
    logger.info(f"总数据点: {len(results)}")
    logger.info(f"Z-score 数量: {len(zscores)}")
    logger.info(f"Z-score 范围: [{min(zscores):.2f}, {max(zscores):.2f}]")
    logger.info(f"Z-score 平均: {sum(zscores) / len(zscores):.2f}")

    # 异常点统计
    anomaly_2 = sum(1 for z in zscores if abs(z) > 2.0)
    anomaly_3 = sum(1 for z in zscores if abs(z) > 3.0)
    logger.info(f"异常点数量 (|z|>2.0): {anomaly_2} ({anomaly_2/len(zscores)*100:.1f}%)")
    logger.info(f"极端异常 (|z|>3.0): {anomaly_3} ({anomaly_3/len(zscores)*100:.1f}%)")

    # 协整检验统计
    coint_passed = sum(1 for r in results if r.get('cointegration_passed', False))
    logger.info(f"协整检验通过: {coint_passed} ({coint_passed/len(results)*100:.1f}%)")


# =====================================================
# 主流程模块
# =====================================================

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='PURR-HYPE 4H K线回测与Z-score分析（Hyperliquid数据源）'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        help='开始日期 (格式: YYYY-MM-DD，默认: 2023-01-01)',
        default=None
    )
    parser.add_argument(
        '--end-date',
        type=str,
        help='结束日期 (格式: YYYY-MM-DD)',
        default=None
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        help='批量写入大小',
        default=1000
    )
    parser.add_argument(
        '--api-delay',
        type=float,
        help='API 调用间隔（秒）',
        default=0.2
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='仅计算不写入数据库'
    )

    args = parser.parse_args()

    logger.info("=== PURR-HYPE 4H K线回测与Z-score分析（Hyperliquid数据源）===")
    logger.info(f"开始日期: {args.start_date or '2023-01-01'}")
    logger.info(f"结束日期: {args.end_date or '今天'}")
    logger.info(f"批量写入大小: {args.batch_size}")
    logger.info(f"API调用间隔: {args.api_delay}秒")
    logger.info(f"模式: {'仅计算 (不写入数据库)' if args.dry_run else '计算并写入数据库'}")

    # 1. 获取 HYPE 和 PURR 的 4H K线数据（现货）
    hype_klines = fetch_klines_from_hyperliquid(
        'HYPE/USDC',
        start_date=args.start_date,
        end_date=args.end_date,
        interval='4h',
        api_delay=args.api_delay
    )

    purr_klines = fetch_klines_from_hyperliquid(
        'PURR/USDC',
        start_date=args.start_date,
        end_date=args.end_date,
        interval='4h',
        api_delay=args.api_delay
    )

    if not hype_klines or not purr_klines:
        logger.error("数据获取失败，程序退出")
        sys.exit(1)

    # 2. 数据对齐
    aligned_hype, aligned_purr = align_klines(hype_klines, purr_klines)

    if len(aligned_hype) < BETA_WINDOW:
        logger.error(
            f"对齐后数据点不足 {BETA_WINDOW} 个 (当前: {len(aligned_hype)})，"
            f"无法进行分析"
        )
        sys.exit(1)

    # 3. 批量计算 Z-score
    results = calculate_zscore_backtest(aligned_hype, aligned_purr)

    if not results:
        logger.error("Z-score 计算失败，程序退出")
        sys.exit(1)

    # 4. 打印统计信息
    print_statistics(results)

    # 5. 写入数据库（如果非 dry-run 模式）
    if not args.dry_run:
        written_count = write_results_to_db(results, args.batch_size)
        logger.info(f"\n成功写入 {written_count} 条分析结果到数据库")
    else:
        logger.info("\n[DRY RUN] 跳过数据库写入")

    logger.info("\n=== 回测完成 ===")


if __name__ == '__main__':
    main()
