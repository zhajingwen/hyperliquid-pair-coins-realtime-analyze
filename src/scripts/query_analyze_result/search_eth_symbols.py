#!/usr/bin/env python3
"""
搜索包含ETH的币种
"""

from src.utils.database.timescaledb import TimescaleDBClient
from src.utils.core.logging_config import logger


def search_eth_symbols():
    """搜索包含ETH的币种"""
    try:
        client = TimescaleDBClient()

        # 搜索所有symbol
        query = """
            SELECT DISTINCT symbol
            FROM analysis_results
            ORDER BY symbol;
        """

        results = client.execute_query(query)

        if not results:
            print("数据库中没有任何数据")
            return

        print(f"\n数据库中所有币种 (共{len(results)}个):\n")

        eth_related = []
        other_symbols = []

        for r in results:
            symbol = r['symbol']
            if 'ETH' in symbol.upper():
                eth_related.append(symbol)
            else:
                other_symbols.append(symbol)

        if eth_related:
            print("包含ETH的币种:")
            for s in eth_related:
                print(f"  - {s}")
        else:
            print("❌ 没有找到包含ETH的币种")

        print(f"\n所有币种列表:")
        for s in results:
            print(f"  - {s['symbol']}")

    except Exception as e:
        logger.error(f"查询失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    search_eth_symbols()
