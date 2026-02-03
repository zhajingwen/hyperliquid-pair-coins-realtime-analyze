#!/usr/bin/env python3
"""执行实际表结构的数据库优化"""
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


async def optimize_database():
    """执行数据库优化"""
    print("=" * 60)
    print("  🔧 数据库性能优化 (实际表结构)")
    print("=" * 60)
    print(f"\n📡 连接: {TIMESCALEDB_HOST}:{TIMESCALEDB_PORT}/{TIMESCALEDB_NAME}\n")

    conn = await asyncpg.connect(
        host=TIMESCALEDB_HOST,
        port=TIMESCALEDB_PORT,
        database=TIMESCALEDB_NAME,
        user=TIMESCALEDB_USER,
        password=TIMESCALEDB_PASSWORD,
        timeout=30
    )
    print("✅ 连接成功\n")

    # 读取SQL文件
    sql_file = os.path.join(os.path.dirname(__file__), 'db_optimize_actual.sql')
    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_content = f.read()

    # 分割SQL语句
    statements = []
    current_statement = []

    for line in sql_content.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith('--'):
            continue

        current_statement.append(line)

        if ';' in line:
            stmt = '\n'.join(current_statement)
            if stmt.strip():
                statements.append(stmt)
            current_statement = []

    print("=" * 60)
    print("开始优化...")
    print("=" * 60 + "\n")

    success_count = 0
    error_count = 0
    skip_count = 0

    for i, stmt in enumerate(statements, 1):
        try:
            # 跳过 EXPLAIN ANALYZE
            if 'EXPLAIN ANALYZE' in stmt.upper():
                continue

            # 获取语句类型
            first_words = ' '.join(stmt.strip().split()[:3])
            print(f"[{i}/{len(statements)}] {first_words}...", end=' ')

            # 执行语句
            if stmt.strip().upper().startswith('SELECT'):
                rows = await conn.fetch(stmt)
                print(f"✅ ({len(rows)} 行)")

                # 显示重要的查询结果
                if 'idx_' in first_words or 'index' in first_words.lower():
                    for row in rows[:5]:
                        data = dict(row)
                        if 'indexname' in data:
                            print(f"     - {data.get('tablename', '')}.{data['indexname']}: {data.get('index_scans', 'N/A')} scans")
                        elif 'total_size' in data:
                            print(f"     - {data['tablename']}: {data['total_size']} (表: {data['table_size']}, 索引: {data['index_size']})")
                        elif 'dead_ratio' in data:
                            print(f"     - {data['tablename']}: 存活{data['live_rows']} 死亡{data['dead_rows']} ({data['dead_ratio']}%)")
                        elif 'cache_hit_ratio' in data:
                            print(f"     - {data['tablename']}: 缓存命中率 {data['cache_hit_ratio']}%")

                success_count += 1

            else:
                result = await conn.execute(stmt)
                print(f"✅ {result}")
                success_count += 1

        except Exception as e:
            error_str = str(e)
            if 'already exists' in error_str or '已经存在' in error_str:
                print(f"⚠️ 已存在")
                skip_count += 1
            else:
                print(f"❌ {e}")
                error_count += 1

    print("\n" + "=" * 60)
    print(f"优化完成！")
    print(f"  成功: {success_count}")
    print(f"  跳过: {skip_count}")
    print(f"  失败: {error_count}")
    print("=" * 60 + "\n")

    # 最终验证
    print("=" * 60)
    print("验证索引状态...")
    print("=" * 60 + "\n")

    indexes = await conn.fetch("""
        SELECT tablename, indexname
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename IN ('klines', 'analysis_results')
          AND indexname LIKE 'idx_%'
        ORDER BY tablename, indexname
    """)

    if indexes:
        print(f"✅ 共有 {len(indexes)} 个优化索引:\n")
        current_table = None
        for idx in indexes:
            if idx['tablename'] != current_table:
                print(f"{idx['tablename']}:")
                current_table = idx['tablename']
            print(f"  ✓ {idx['indexname']}")
    else:
        print("⚠️ 未发现优化索引")

    await conn.close()

    print("\n" + "=" * 60)
    print("🎉 数据库优化完成！")
    print("=" * 60)

    return True


if __name__ == "__main__":
    try:
        asyncio.run(optimize_database())
        print("\n下一步:")
        print("1. 重启服务: python src/main.py")
        print("2. 观察日志: tail -f logs/app.log")
        print("3. 验证效果: python scripts/verify_optimization.py\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 优化失败: {e}\n")
        sys.exit(1)
