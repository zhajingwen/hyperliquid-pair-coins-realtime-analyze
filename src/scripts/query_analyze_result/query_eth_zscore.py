#!/usr/bin/env python3
"""
查询ETH的zscore_4h历史数据

用法:
    python query_eth_zscore.py [--limit 100] [--days 7] [--output csv|json|table]
"""

import sys
import argparse
from datetime import datetime, timedelta
from typing import List, Dict
import json

from src.utils.database.timescaledb import TimescaleDBClient, AnalysisResultRepository
from src.utils.core.logging_config import logger


def query_eth_zscore_history(
    limit: int = None,
    days: int = None,
    output_format: str = 'table'
) -> List[Dict]:
    """
    查询ETH的zscore_4h历史数据

    Args:
        limit: 限制返回记录数
        days: 查询最近N天的数据
        output_format: 输出格式 (table, csv, json)

    Returns:
        查询结果列表
    """
    try:
        # 初始化数据库客户端
        client = TimescaleDBClient()

        # 构建查询语句
        query = """
            SELECT
                analysis_time,
                kline_time,
                symbol,
                base_symbol,
                zscore_4h,
                corr_4h_60d,
                is_anomaly,
                signal_strength,
                trading_direction,
                analysis_delay_seconds
            FROM analysis_results
            WHERE symbol = %s
        """

        params = ['ETH/USDC:USDC']

        # 添加时间过滤
        if days:
            query += " AND analysis_time >= NOW() - INTERVAL '%s days'"
            params.append(days)

        # 添加排序
        query += " ORDER BY analysis_time DESC"

        # 添加限制
        if limit:
            query += " LIMIT %s"
            params.append(limit)

        # 执行查询
        logger.info(f"查询ETH的zscore_4h历史数据 (limit={limit}, days={days})")
        results = client.execute_query(query, tuple(params))

        if not results:
            logger.warning("未找到ETH的分析结果数据")
            return []

        logger.info(f"成功查询到 {len(results)} 条记录")
        return results

    except Exception as e:
        logger.error(f"查询失败: {e}")
        raise


def format_output(results: List[Dict], output_format: str = 'table'):
    """
    格式化输出结果

    Args:
        results: 查询结果
        output_format: 输出格式 (table, csv, json)
    """
    if not results:
        print("没有查询到数据")
        return

    if output_format == 'json':
        # JSON格式输出
        output = []
        for r in results:
            output.append({
                'analysis_time': r['analysis_time'].isoformat() if r['analysis_time'] else None,
                'kline_time': r['kline_time'].isoformat() if r['kline_time'] else None,
                'symbol': r['symbol'],
                'base_symbol': r['base_symbol'],
                'zscore_4h': r['zscore_4h'],
                'corr_4h_60d': r['corr_4h_60d'],
                'is_anomaly': r['is_anomaly'],
                'signal_strength': r['signal_strength'],
                'trading_direction': r['trading_direction'],
                'analysis_delay_seconds': r['analysis_delay_seconds']
            })
        print(json.dumps(output, indent=2, ensure_ascii=False))

    elif output_format == 'csv':
        # CSV格式输出
        print("analysis_time,kline_time,symbol,base_symbol,zscore_4h,corr_4h_60d,is_anomaly,signal_strength,trading_direction,analysis_delay_seconds")
        for r in results:
            print(f"{r['analysis_time']},{r['kline_time']},{r['symbol']},{r['base_symbol']},"
                  f"{r['zscore_4h']},{r['corr_4h_60d']},{r['is_anomaly']},"
                  f"{r['signal_strength']},{r['trading_direction']},{r['analysis_delay_seconds']}")

    else:  # table格式
        # 表格格式输出
        from tabulate import tabulate

        # 准备表格数据
        table_data = []
        for r in results:
            table_data.append([
                # r['analysis_time'].strftime('%Y-%m-%d %H:%M:%S') if r['analysis_time'] else '',
                r['kline_time'].strftime('%Y-%m-%d %H:%M:%S') if r['kline_time'] else '',
                r['symbol'],
                # r['base_symbol'],
                f"{r['zscore_4h']:.4f}" if r['zscore_4h'] is not None else '',
                # f"{r['corr_4h_60d']:.4f}" if r['corr_4h_60d'] is not None else '',
                # '✓' if r['is_anomaly'] else '',
                # r['signal_strength'] or '',
                # r['trading_direction'] or '',
                # f"{r['analysis_delay_seconds']:.2f}" if r['analysis_delay_seconds'] is not None else ''
            ])

        headers = ['分析时间', 'K线时间', '币种', '基准', 'Z-Score 4H', '相关系数 4H', '异常', '信号强度', '交易方向', '延迟(秒)']
        print(tabulate(table_data, headers=headers, tablefmt='grid'))

        # 统计信息
        print(f"\n总记录数: {len(results)}")

        # zscore_4h统计
        zscore_values = [r['zscore_4h'] for r in results if r['zscore_4h'] is not None]
        if zscore_values:
            print(f"\nZ-Score 4H 统计:")
            print(f"  最小值: {min(zscore_values):.4f}")
            print(f"  最大值: {max(zscore_values):.4f}")
            print(f"  平均值: {sum(zscore_values)/len(zscore_values):.4f}")
            print(f"  异常数量 (|z|>2): {len([z for z in zscore_values if abs(z) > 2])}")
            print(f"  极端异常 (|z|>3): {len([z for z in zscore_values if abs(z) > 3])}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='查询ETH的zscore_4h历史数据')
    parser.add_argument('--limit', type=int, default=100, help='限制返回记录数 (默认: 100)')
    parser.add_argument('--days', type=int, help='查询最近N天的数据')
    parser.add_argument('--output', choices=['table', 'csv', 'json'], default='table',
                        help='输出格式 (默认: table)')
    parser.add_argument('--all', action='store_true', help='查询所有数据（忽略limit限制）')

    args = parser.parse_args()

    try:
        # 查询数据
        limit = None if args.all else args.limit
        results = query_eth_zscore_history(limit=limit, days=args.days, output_format=args.output)

        # 格式化输出
        format_output(results, args.output)

    except Exception as e:
        logger.error(f"执行失败: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
