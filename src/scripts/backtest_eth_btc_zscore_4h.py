#!/usr/bin/env python3
"""
BTC-ETH 4H K线回测与Z-score分析

功能：
1. 使用 yfinance 获取 BTC-USD 和 ETH-USD 的 4H 历史K线数据
2. 计算 ETH vs BTC 的滑动窗口 Z-score
3. 将分析结果写入 PostgreSQL analysis_results 表

数据要求：
- 最小数据点数：100（BETA_WINDOW）
- 时间对齐：确保两个币种的时间戳一致
- 数据格式：符合 analysis_core.py 的 List[Dict] 要求

Author: Claude Code
Date: 2026-02-01
"""

import argparse
import sys
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from pathlib import Path

import pandas as pd
import yfinance as yf
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

def fetch_klines_from_yfinance(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    interval: str = '4h',
    period: str = '730d'  # 默认获取最近730天（yfinance 4h数据的最大范围）
) -> List[Dict]:
    """
    使用 yfinance 获取指定币种的K线数据

    Args:
        ticker: yfinance ticker 代码（如 'BTC-USD', 'ETH-USD'）
        start_date: 开始日期（可选，格式：'YYYY-MM-DD'）
        end_date: 结束日期（可选，默认今天）
        interval: 时间周期（默认 '4h'）
        period: 时间周期（如 '730d', '1mo', '1y'），当未指定 start_date 时使用

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
    logger.info(f"开始获取 {ticker} 的 {interval} K线数据...")

    try:
        # 使用 yfinance 下载数据
        ticker_obj = yf.Ticker(ticker)

        # 如果指定了 start_date，使用 start/end；否则使用 period
        if start_date:
            df = ticker_obj.history(
                interval=interval,
                start=start_date,
                end=end_date,
                auto_adjust=False,
                actions=False
            )
        else:
            df = ticker_obj.history(
                interval=interval,
                period=period,
                auto_adjust=False,
                actions=False
            )

        if df.empty:
            logger.warning(f"{ticker} 未获取到数据")
            return []

        # 数据转换：DataFrame → List[Dict]
        klines = []
        for index, row in df.iterrows():
            # 过滤无效数据
            if pd.isna(row['Close']) or pd.isna(row['Volume']):
                logger.debug(f"跳过无效数据点: {index}")
                continue

            klines.append({
                'time': index.to_pydatetime().replace(tzinfo=timezone.utc),
                'open': float(row['Open']),
                'high': float(row['High']),
                'low': float(row['Low']),
                'close': float(row['Close']),
                'volume': float(row['Volume'])
            })

        logger.info(f"{ticker}: 成功获取 {len(klines)} 个 {interval} K线数据")
        if klines:
            logger.info(f"  时间范围: {klines[0]['time']} 至 {klines[-1]['time']}")

        return klines

    except Exception as e:
        logger.error(f"获取 {ticker} 数据失败: {e}", exc_info=True)
        return []


def align_klines(
    btc_klines: List[Dict],
    eth_klines: List[Dict]
) -> Tuple[List[Dict], List[Dict]]:
    """
    对齐两个币种的K线数据（确保时间戳一致）

    Args:
        btc_klines: BTC K线数据
        eth_klines: ETH K线数据

    Returns:
        (aligned_btc, aligned_eth): 对齐后的K线数据
    """
    logger.info("开始对齐 BTC 和 ETH 的K线数据...")

    # 转换为 DataFrame 进行时间对齐
    btc_df = pd.DataFrame(btc_klines).set_index('time')
    eth_df = pd.DataFrame(eth_klines).set_index('time')

    # 内连接：只保留两个数据集都有的时间点
    aligned = btc_df.join(eth_df, how='inner', lsuffix='_btc', rsuffix='_eth')

    # 转换回 List[Dict]
    aligned_btc = []
    aligned_eth = []

    for timestamp, row in aligned.iterrows():
        aligned_btc.append({
            'time': timestamp,
            'open': row['open_btc'],
            'high': row['high_btc'],
            'low': row['low_btc'],
            'close': row['close_btc'],
            'volume': row['volume_btc']
        })
        aligned_eth.append({
            'time': timestamp,
            'open': row['open_eth'],
            'high': row['high_eth'],
            'low': row['low_eth'],
            'close': row['close_eth'],
            'volume': row['volume_eth']
        })

    logger.info(f"数据对齐完成: {len(aligned_btc)} 个时间点")
    if aligned_btc:
        logger.info(f"  时间范围: {aligned_btc[0]['time']} 至 {aligned_btc[-1]['time']}")

    return aligned_btc, aligned_eth


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
        List[Dict]: 分析结果列表，格式：
            [
                {
                    'kline_time': datetime,
                    'zscore_4h': float,
                    'alpha': float,
                    'beta': float,
                    'adf_pvalue': float,
                    'rsquared': float,
                    'cointegration_passed': bool
                },
                ...
            ]
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
    """
    根据 Z-score 判断交易方向

    Args:
        zscore: Z-score 值

    Returns:
        str: 交易方向 ('long', 'short', 'none')
    """
    if zscore > 2.0:
        return 'short'  # ETH 相对高估，做空 ETH
    elif zscore < -2.0:
        return 'long'   # ETH 相对低估，做多 ETH
    else:
        return 'none'


def determine_signal_strength(zscore: float) -> str:
    """
    根据 Z-score 判断信号强度

    Args:
        zscore: Z-score 值

    Returns:
        str: 信号强度 ('extreme', 'strong', 'medium', 'weak')
    """
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
                            'ETH/USDC:USDC',                     # symbol
                            'BTC/USDC:USDC',                     # base_symbol
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
# 主流程模块
# =====================================================

def print_statistics(results: List[Dict]):
    """
    打印统计信息

    Args:
        results: 分析结果列表
    """
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


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='BTC-ETH 4H K线回测与Z-score分析'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        help='开始日期 (格式: YYYY-MM-DD)',
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
        '--dry-run',
        action='store_true',
        help='仅计算不写入数据库'
    )

    args = parser.parse_args()

    logger.info("=== BTC-ETH 4H K线回测与Z-score分析 ===")
    logger.info(f"开始日期: {args.start_date or '默认 (yfinance 最早可用)'}")
    logger.info(f"结束日期: {args.end_date or '今天'}")
    logger.info(f"批量写入大小: {args.batch_size}")
    logger.info(f"模式: {'仅计算 (不写入数据库)' if args.dry_run else '计算并写入数据库'}")

    # 1. 获取 BTC 和 ETH 的 4H K线数据
    btc_klines = fetch_klines_from_yfinance(
        'BTC-USD',
        start_date=args.start_date,
        end_date=args.end_date,
        interval='4h'
    )

    eth_klines = fetch_klines_from_yfinance(
        'ETH-USD',
        start_date=args.start_date,
        end_date=args.end_date,
        interval='4h'
    )

    if not btc_klines or not eth_klines:
        logger.error("数据获取失败，程序退出")
        sys.exit(1)

    # 2. 数据对齐
    aligned_btc, aligned_eth = align_klines(btc_klines, eth_klines)

    if len(aligned_btc) < BETA_WINDOW:
        logger.error(
            f"对齐后数据点不足 {BETA_WINDOW} 个 (当前: {len(aligned_btc)})，"
            f"无法进行分析"
        )
        sys.exit(1)

    # 3. 批量计算 Z-score
    results = calculate_zscore_backtest(aligned_btc, aligned_eth)

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
