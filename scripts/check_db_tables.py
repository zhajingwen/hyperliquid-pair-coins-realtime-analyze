#!/usr/bin/env python3
"""检查数据库表结构"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import asyncpg
from src.utils.core.config import (
    TIMESCALEDB_HOST,
    TIMESCALEDB_PORT,
    TIMESCALEDB_NAME,
    TIMESCALEDB_USER,
    TIMESCALEDB_PASSWORD
)


async def check_tables():
    """检查数据库表"""
    print(f"📡 连接数据库: {TIMESCALEDB_HOST}:{TIMESCALEDB_PORT}/{TIMESCALEDB_NAME}\n")

    conn = await asyncpg.connect(
        host=TIMESCALEDB_HOST,
        port=TIMESCALEDB_PORT,
        database=TIMESCALEDB_NAME,
        user=TIMESCALEDB_USER,
        password=TIMESCALEDB_PASSWORD,
        timeout=10
    )

    # 查询所有表
    print("=" * 60)
    print("数据库表列表:")
    print("=" * 60)
    tables = await conn.fetch("""
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename
    """)

    if tables:
        for i, table in enumerate(tables, 1):
            print(f"{i}. {table['schemaname']}.{table['tablename']}")
    else:
        print("⚠️ 未发现任何表")

    # 查询所有索引
    print("\n" + "=" * 60)
    print("现有索引:")
    print("=" * 60)
    indexes = await conn.fetch("""
        SELECT schemaname, tablename, indexname
        FROM pg_indexes
        WHERE schemaname = 'public'
        ORDER BY tablename, indexname
    """)

    if indexes:
        current_table = None
        for idx in indexes:
            if idx['tablename'] != current_table:
                print(f"\n{idx['tablename']}:")
                current_table = idx['tablename']
            print(f"  - {idx['indexname']}")
    else:
        print("⚠️ 未发现任何索引")

    # 如果发现类似K线的表，显示表结构
    print("\n" + "=" * 60)
    print("查找K线相关表:")
    print("=" * 60)
    for table in tables:
        table_name = table['tablename']
        if 'kline' in table_name.lower() or 'candle' in table_name.lower() or 'ohlcv' in table_name.lower():
            print(f"\n✅ 发现K线表: {table_name}")

            # 显示列结构
            columns = await conn.fetch(f"""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = '{table_name}'
                ORDER BY ordinal_position
            """)

            print(f"   列结构:")
            for col in columns:
                print(f"     - {col['column_name']}: {col['data_type']}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(check_tables())
