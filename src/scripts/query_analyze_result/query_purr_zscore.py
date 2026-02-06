#!/usr/bin/env python3
"""
查询PURR的zscore_4h历史数据

用法:
    python query_purr_zscore.py [--limit N] [--days 7] [--output csv|json|table]

注意: 默认不限制返回记录数，如需限制请使用 --limit 参数
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
    查询PURR的zscore_4h历史数据

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

        params = ['PURR/USDC:USDC']

        # 添加时间过滤
        if days:
            # 使用字符串格式化，因为INTERVAL不支持参数化单位
            query += f" AND kline_time >= NOW() - INTERVAL '{days} days'"

        # 添加排序 - 按zscore绝对值升序
        # query += " ORDER BY ABS(zscore_4h) ASC"
        query += " ORDER BY kline_time ASC"

        # 添加限制
        if limit:
            query += " LIMIT %s"
            params.append(limit)

        # 执行查询
        logger.info(f"查询PURR的zscore_4h历史数据 (limit={limit}, days={days})")
        results = client.execute_query(query, tuple(params))

        if not results:
            logger.warning("未找到PURR的分析结果数据")
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
        # 表格格式输出 - 使用中文友好的格式化
        def get_display_width(s):
            """计算字符串的显示宽度（中文字符占2个宽度）"""
            width = 0
            for char in str(s):
                if '\u4e00' <= char <= '\u9fff':  # 中文字符范围
                    width += 2
                else:
                    width += 1
            return width

        def pad_string(s, width):
            """填充字符串到指定显示宽度"""
            s = str(s)
            current_width = get_display_width(s)
            if current_width >= width:
                return s
            padding = width - current_width
            return s + ' ' * padding

        # 准备表格数据
        table_data = []
        for r in results:
            analysis_time_local = to_local_time(r['analysis_time'])
            kline_time_local = to_local_time(r['kline_time'])
            table_data.append([
                analysis_time_local.strftime('%Y-%m-%d %H:%M:%S') if analysis_time_local else '',
                kline_time_local.strftime('%Y-%m-%d %H:%M:%S') if kline_time_local else '',
                r['symbol'],
                f"{r['zscore_4h']:.4f}" if r['zscore_4h'] is not None else '',
                '是' if r['is_anomaly'] else '否',
                r['trading_direction'] if r['trading_direction'] else 'none',
                r['signal_strength'] if r['signal_strength'] else 'none',
            ])

        headers = ['分析时间', 'K线时间', '币种', 'ZScore_4H', '异常', '交易方向', '信号强度']

        # 计算每列的最大宽度
        col_widths = [get_display_width(h) for h in headers]
        for row in table_data:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], get_display_width(cell))

        # 打印表头分隔线
        sep_line = '+' + '+'.join('-' * (w + 2) for w in col_widths) + '+'
        print(sep_line)

        # 打印表头
        header_row = '| ' + ' | '.join(pad_string(h, col_widths[i]) for i, h in enumerate(headers)) + ' |'
        print(header_row)
        print(sep_line)

        # 打印数据行
        for row in table_data:
            data_row = '| ' + ' | '.join(pad_string(cell, col_widths[i]) for i, cell in enumerate(row)) + ' |'
            print(data_row)

        # 打印底部分隔线
        print(sep_line)

        # 统计信息
        print(f"\n总记录数: {len(results)}")

        # zscore_4h统计
        zscore_values = [r['zscore_4h'] for r in results if r['zscore_4h'] is not None]
        if zscore_values:
            print(f"\nZ-Score 4H 统计:")
            print(f"  最小值: {min(zscore_values):.4f}")
            print(f"  最大值: {max(zscore_values):.4f}")
            print(f"  平均值: {sum(zscore_values)/len(zscore_values):.4f}")
            print(f"  异常数量 (|z|>2.5): {len([z for z in zscore_values if abs(z) > 2.5])}")
            print(f"  极端异常 (|z|>3): {len([z for z in zscore_values if abs(z) > 3])}")

            # 最近4小时平均值
            now = datetime.now().astimezone()
            four_hours_ago = now - timedelta(hours=4)
            recent_4h_values = [
                r['zscore_4h'] for r in results
                if r['zscore_4h'] is not None and r['kline_time'] is not None
                and to_local_time(r['kline_time']) >= four_hours_ago
            ]
            if recent_4h_values:
                avg_4h = sum(recent_4h_values) / len(recent_4h_values)
                print(f"  最近4小时平均值: {avg_4h:.4f} (共{len(recent_4h_values)}条)")
            else:
                print(f"  最近4小时平均值: 无数据")

        # 最近30天每天的统计
        from collections import defaultdict
        daily_stats = defaultdict(lambda: {
            'max_abs': 0, 'value': 0, 'time': None,
            'max_positive': None, 'min_negative': None
        })

        for r in results:
            if r['zscore_4h'] is None or r['kline_time'] is None:
                continue
            kline_time_local = to_local_time(r['kline_time'])
            date_key = kline_time_local.strftime('%Y-%m-%d')
            zscore = r['zscore_4h']
            abs_value = abs(zscore)

            # 更新绝对值最大值
            if abs_value > daily_stats[date_key]['max_abs']:
                daily_stats[date_key]['max_abs'] = abs_value
                daily_stats[date_key]['value'] = zscore
                daily_stats[date_key]['time'] = kline_time_local.strftime('%H:%M')

            # 更新正值最大值
            if zscore > 0:
                if daily_stats[date_key]['max_positive'] is None or zscore > daily_stats[date_key]['max_positive']:
                    daily_stats[date_key]['max_positive'] = zscore

            # 更新负值最小值
            if zscore < 0:
                if daily_stats[date_key]['min_negative'] is None or zscore < daily_stats[date_key]['min_negative']:
                    daily_stats[date_key]['min_negative'] = zscore

        if daily_stats:
            # 按日期排序，取最近30天
            sorted_dates = sorted(daily_stats.keys(), reverse=True)[:30]
            sorted_dates.reverse()  # 按时间正序显示

            print(f"\n最近30天每日 Z-Score 统计:")
            print("-" * 76)
            print(f"{'日期':<12} {'时间':<8} {'|Z|最大值':<12} {'正值最大':<12} {'负值最小':<12}")
            print("-" * 76)
            for date in sorted_dates:
                info = daily_stats[date]
                max_pos_str = f"{info['max_positive']:>+.4f}" if info['max_positive'] is not None else "    N/A "
                min_neg_str = f"{info['min_negative']:>+.4f}" if info['min_negative'] is not None else "    N/A "
                print(f"{date:<12} {info['time']:<8} {info['value']:>+.4f}     {max_pos_str}     {min_neg_str}")
            print("-" * 76)

            # 统计30天内的极值
            max_abs_all = max(daily_stats[d]['max_abs'] for d in sorted_dates)
            max_date = [d for d in sorted_dates if daily_stats[d]['max_abs'] == max_abs_all][0]
            print(f"30天内最大绝对值: {max_abs_all:.4f} (日期: {max_date})")

            # 30天内正值最大和负值最小
            all_max_pos = [daily_stats[d]['max_positive'] for d in sorted_dates if daily_stats[d]['max_positive'] is not None]
            all_min_neg = [daily_stats[d]['min_negative'] for d in sorted_dates if daily_stats[d]['min_negative'] is not None]
            if all_max_pos:
                max_pos_val = max(all_max_pos)
                max_pos_date = [d for d in sorted_dates if daily_stats[d]['max_positive'] == max_pos_val][0]
                print(f"30天内正值最大: {max_pos_val:+.4f} (日期: {max_pos_date})")
            if all_min_neg:
                min_neg_val = min(all_min_neg)
                min_neg_date = [d for d in sorted_dates if daily_stats[d]['min_negative'] == min_neg_val][0]
                print(f"30天内负值最小: {min_neg_val:+.4f} (日期: {min_neg_date})")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='查询PURR的zscore_4h历史数据')
    parser.add_argument('--limit', type=int, default=None, help='限制返回记录数 (默认: 无限制)')
    parser.add_argument('--days', type=int, help='查询最近N天的数据')
    parser.add_argument('--output', choices=['table', 'csv', 'json'], default='table',
                        help='输出格式 (默认: table)')

    args = parser.parse_args()

    try:
        # 查询数据
        results = query_eth_zscore_history(limit=args.limit, days=args.days, output_format=args.output)

        # 格式化输出
        format_output(results, args.output)

    except Exception as e:
        logger.error(f"执行失败: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
