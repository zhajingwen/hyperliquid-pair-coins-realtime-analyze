#!/usr/bin/env python3
"""
查询ETH的zscore_4h历史数据

用法:
    python query_eth_zscore.py [--limit N] [--days 7] [--output csv|json|table]
    python query_eth_zscore.py --year 2020 [--output csv|json|table]
    python query_eth_zscore.py --start-date 2020-01-01 --end-date 2020-12-31

注意: 默认不限制返回记录数，如需限制请使用 --limit 参数
"""

import sys
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json

from src.utils.database.timescaledb import TimescaleDBClient, AnalysisResultRepository
from src.utils.core.logging_config import logger


def query_eth_zscore_history(
    limit: int = None,
    days: int = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    year: Optional[int] = None,
    output_format: str = 'table'
) -> List[Dict]:
    """
    查询ETH的zscore_4h历史数据

    Args:
        limit: 限制返回记录数
        days: 查询最近N天的数据
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        year: 查询指定年份的数据
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
        if year:
            # 查询指定年份的数据
            query += " AND kline_time >= %s AND kline_time < %s"
            params.extend([f"{year}-01-01 00:00:00", f"{year+1}-01-01 00:00:00"])
        elif start_date and end_date:
            # 查询指定日期范围的数据
            query += " AND kline_time >= %s AND kline_time < %s"
            # 结束日期加1天，确保包含结束日期当天的所有数据
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            params.extend([f"{start_date} 00:00:00", end_dt.strftime('%Y-%m-%d %H:%M:%S')])
        elif start_date:
            # 只有开始日期
            query += " AND kline_time >= %s"
            params.append(f"{start_date} 00:00:00")
        elif end_date:
            # 只有结束日期
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query += " AND kline_time < %s"
            params.append(end_dt.strftime('%Y-%m-%d %H:%M:%S'))
        elif days:
            # 使用字符串格式化，因为INTERVAL不支持参数化单位
            query += f" AND kline_time >= NOW() - INTERVAL '{days} days'"

        # 添加排序 - 按zscore绝对值升序
        query += " ORDER BY ABS(zscore_4h) ASC"

        # 添加限制
        if limit:
            query += " LIMIT %s"
            params.append(limit)

        # 执行查询
        time_filter = f"year={year}" if year else f"days={days}" if days else f"start={start_date}, end={end_date}" if start_date or end_date else "all"
        logger.info(f"查询ETH的zscore_4h历史数据 (limit={limit}, {time_filter})")
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

    # 转换时间到本地时区的辅助函数
    def to_local_time(dt):
        """将 UTC 时间转换为本地时间"""
        if dt is None:
            return None
        return dt.astimezone()

    if output_format == 'json':
        # JSON格式输出
        output = []
        for r in results:
            output.append({
                'analysis_time': to_local_time(r['analysis_time']).isoformat() if r['analysis_time'] else None,
                'kline_time': to_local_time(r['kline_time']).isoformat() if r['kline_time'] else None,
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
            analysis_time_local = to_local_time(r['analysis_time'])
            kline_time_local = to_local_time(r['kline_time'])
            print(f"{analysis_time_local},{kline_time_local},{r['symbol']},{r['base_symbol']},"
                  f"{r['zscore_4h']},{r['corr_4h_60d']},{r['is_anomaly']},"
                  f"{r['signal_strength']},{r['trading_direction']},{r['analysis_delay_seconds']}")

    else:  # table格式
        # 表格格式输出
        from tabulate import tabulate

        # 准备表格数据
        table_data = []
        for r in results:
            kline_time_local = to_local_time(r['kline_time'])
            table_data.append([
                kline_time_local.strftime('%Y-%m-%d %H:%M:%S') if kline_time_local else '',
                r['symbol'],
                f"{r['zscore_4h']:.4f}" if r['zscore_4h'] is not None else '',
            ])

        headers = ['K线时间', '币种', 'Z-Score 4H']
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
    parser.add_argument('--limit', type=int, default=None, help='限制返回记录数 (默认: 无限制)')
    parser.add_argument('--days', type=int, help='查询最近N天的数据')
    parser.add_argument('--year', type=int, help='查询指定年份的数据 (例如: 2020)')
    parser.add_argument('--start-date', type=str, help='开始日期 (格式: YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='结束日期 (格式: YYYY-MM-DD)')
    parser.add_argument('--output', choices=['table', 'csv', 'json'], default='table',
                        help='输出格式 (默认: table)')

    args = parser.parse_args()

    # 验证日期格式
    if args.start_date:
        try:
            datetime.strptime(args.start_date, '%Y-%m-%d')
        except ValueError:
            logger.error("开始日期格式错误，应为 YYYY-MM-DD")
            sys.exit(1)

    if args.end_date:
        try:
            datetime.strptime(args.end_date, '%Y-%m-%d')
        except ValueError:
            logger.error("结束日期格式错误，应为 YYYY-MM-DD")
            sys.exit(1)

    # 检查参数冲突
    time_params = sum([bool(args.days), bool(args.year), bool(args.start_date or args.end_date)])
    if time_params > 1:
        logger.error("--days, --year, --start-date/--end-date 参数不能同时使用")
        sys.exit(1)

    try:
        # 查询数据
        results = query_eth_zscore_history(
            limit=args.limit,
            days=args.days,
            start_date=args.start_date,
            end_date=args.end_date,
            year=args.year,
            output_format=args.output
        )

        # 格式化输出
        format_output(results, args.output)

    except Exception as e:
        logger.error(f"执行失败: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
