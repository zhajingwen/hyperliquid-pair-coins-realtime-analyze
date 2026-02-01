#!/usr/bin/env python3
"""
检查数据库中的币种和数据统计
"""

from src.utils.database.timescaledb import TimescaleDBClient
from src.utils.core.logging_config import logger


def check_database_symbols():
    """检查数据库中的币种和数据统计"""
    try:
        client = TimescaleDBClient()

        # 查询所有symbol统计
        query = """
            SELECT
                symbol,
                COUNT(*) as record_count,
                MIN(analysis_time) as first_analysis,
                MAX(analysis_time) as last_analysis,
                COUNT(CASE WHEN zscore_4h IS NOT NULL THEN 1 END) as zscore_4h_count,
                AVG(zscore_4h) as avg_zscore_4h,
                MIN(zscore_4h) as min_zscore_4h,
                MAX(zscore_4h) as max_zscore_4h
            FROM analysis_results
            GROUP BY symbol
            ORDER BY record_count DESC
            LIMIT 50;
        """

        results = client.execute_query(query)

        if not results:
            print("数据库中没有分析结果数据")
            return

        print(f"\n数据库中共有 {len(results)} 个币种的分析数据:\n")
        print(f"{'币种':<15} {'总记录数':<10} {'zscore_4h数':<12} {'平均Z-Score':<12} {'最小值':<10} {'最大值':<10} {'首次分析':<20} {'最后分析':<20}")
        print("=" * 130)

        for r in results:
            print(r)
            symbol = r['symbol']
            count = r['record_count']
            zscore_count = r['zscore_4h_count']
            avg_z = f"{r['avg_zscore_4h']:.4f}" if r['avg_zscore_4h'] is not None else 'N/A'
            min_z = f"{r['min_zscore_4h']:.4f}" if r['min_zscore_4h'] is not None else 'N/A'
            max_z = f"{r['max_zscore_4h']:.4f}" if r['max_zscore_4h'] is not None else 'N/A'
            first = r['first_analysis'].strftime('%Y-%m-%d %H:%M:%S') if r['first_analysis'] else 'N/A'
            last = r['last_analysis'].strftime('%Y-%m-%d %H:%M:%S') if r['last_analysis'] else 'N/A'

            print(f"{symbol:<15} {count:<10} {zscore_count:<12} {avg_z:<12} {min_z:<10} {max_z:<10} {first:<20} {last:<20}")

        print(f"\n总币种数: {len(results)}")

    except Exception as e:
        logger.error(f"查询失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    check_database_symbols()
