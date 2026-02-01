#!/usr/bin/env python3
"""
检查base_symbol字段
"""

from src.utils.database.timescaledb import TimescaleDBClient


def check_base_symbols():
    """检查base_symbol字段"""
    try:
        client = TimescaleDBClient()

        # 查询所有base_symbol
        query = """
            SELECT DISTINCT base_symbol, COUNT(*) as count
            FROM analysis_results
            GROUP BY base_symbol
            ORDER BY count DESC;
        """

        results = client.execute_query(query)

        if not results:
            print("数据库中没有任何数据")
            return

        print(f"\n数据库中所有base_symbol (共{len(results)}个):\n")
        print(f"{'Base Symbol':<20} {'记录数':<10}")
        print("=" * 35)

        for r in results:
            print(f"{r['base_symbol']:<20} {r['count']:<10}")

    except Exception as e:
        print(f"查询失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    check_base_symbols()
