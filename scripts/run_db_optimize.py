#!/usr/bin/env python3
"""
数据库优化执行脚本
使用 Python 连接数据库并执行优化脚本
"""
import sys
import os
import asyncio

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    import asyncpg
except ImportError:
    print("❌ 缺少 asyncpg 库，尝试使用 psycopg2...")
    try:
        import psycopg2
        USE_ASYNCPG = False
    except ImportError:
        print("❌ 未安装数据库客户端库")
        print("请安装: pip install asyncpg 或 pip install psycopg2-binary")
        sys.exit(1)
else:
    USE_ASYNCPG = True

from src.utils.core.config import (
    TIMESCALEDB_HOST,
    TIMESCALEDB_PORT,
    TIMESCALEDB_NAME,
    TIMESCALEDB_USER,
    TIMESCALEDB_PASSWORD
)


async def execute_with_asyncpg():
    """使用 asyncpg 执行优化脚本"""
    print(f"📡 连接数据库: {TIMESCALEDB_HOST}:{TIMESCALEDB_PORT}/{TIMESCALEDB_NAME}")

    try:
        conn = await asyncpg.connect(
            host=TIMESCALEDB_HOST,
            port=TIMESCALEDB_PORT,
            database=TIMESCALEDB_NAME,
            user=TIMESCALEDB_USER,
            password=TIMESCALEDB_PASSWORD,
            timeout=30
        )
        print("✅ 数据库连接成功")

        # 读取 SQL 脚本
        sql_file = os.path.join(os.path.dirname(__file__), 'db_optimize.sql')
        with open(sql_file, 'r', encoding='utf-8') as f:
            sql_content = f.read()

        print("\n" + "="*60)
        print("开始执行数据库优化...")
        print("="*60 + "\n")

        # 分割SQL语句（按分号和空行）
        statements = []
        current_statement = []

        for line in sql_content.split('\n'):
            # 跳过注释和空行
            stripped = line.strip()
            if not stripped or stripped.startswith('--'):
                continue

            current_statement.append(line)

            # 如果遇到分号，表示一个语句结束
            if ';' in line:
                stmt = '\n'.join(current_statement)
                if stmt.strip():
                    statements.append(stmt)
                current_statement = []

        # 执行每个语句
        success_count = 0
        error_count = 0

        for i, stmt in enumerate(statements, 1):
            try:
                # 跳过EXPLAIN ANALYZE语句（这些是示例查询）
                if 'EXPLAIN ANALYZE' in stmt.upper():
                    continue

                # 获取语句的第一个关键词
                first_words = ' '.join(stmt.strip().split()[:3])
                print(f"[{i}/{len(statements)}] 执行: {first_words}...")

                # 执行语句
                result = await conn.execute(stmt)

                # 特殊处理SELECT语句
                if stmt.strip().upper().startswith('SELECT'):
                    rows = await conn.fetch(stmt)
                    if rows:
                        print(f"    ✅ 查询成功 - 返回 {len(rows)} 行")
                        # 打印前3行结果
                        for row in rows[:3]:
                            print(f"       {dict(row)}")
                        if len(rows) > 3:
                            print(f"       ... 还有 {len(rows)-3} 行")
                else:
                    print(f"    ✅ 执行成功: {result}")

                success_count += 1

            except Exception as e:
                error_str = str(e)
                # 忽略"已存在"的错误
                if 'already exists' in error_str or '已经存在' in error_str:
                    print(f"    ⚠️ 跳过（已存在）")
                    success_count += 1
                else:
                    print(f"    ❌ 执行失败: {e}")
                    error_count += 1

        print("\n" + "="*60)
        print(f"优化完成！成功: {success_count}, 失败: {error_count}")
        print("="*60 + "\n")

        # 验证关键索引
        print("验证关键索引...")
        indexes = await conn.fetch("""
            SELECT indexname, tablename
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename IN ('kline_data', 'analysis_results')
              AND indexname LIKE 'idx_%'
            ORDER BY tablename, indexname
        """)

        if indexes:
            print(f"✅ 发现 {len(indexes)} 个优化索引:")
            for idx in indexes:
                print(f"   - {idx['tablename']}.{idx['indexname']}")
        else:
            print("⚠️ 未发现优化索引")

        await conn.close()
        print("\n✅ 数据库优化完成！")
        return True

    except Exception as e:
        print(f"\n❌ 数据库优化失败: {e}")
        return False


def execute_with_psycopg2():
    """使用 psycopg2 执行优化脚本"""
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    print(f"📡 连接数据库: {TIMESCALEDB_HOST}:{TIMESCALEDB_PORT}/{TIMESCALEDB_NAME}")

    try:
        conn = psycopg2.connect(
            host=TIMESCALEDB_HOST,
            port=TIMESCALEDB_PORT,
            database=TIMESCALEDB_NAME,
            user=TIMESCALEDB_USER,
            password=TIMESCALEDB_PASSWORD
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()

        print("✅ 数据库连接成功")

        # 读取 SQL 脚本
        sql_file = os.path.join(os.path.dirname(__file__), 'db_optimize.sql')
        with open(sql_file, 'r', encoding='utf-8') as f:
            sql_content = f.read()

        print("\n" + "="*60)
        print("开始执行数据库优化...")
        print("="*60 + "\n")

        # 分割并执行SQL语句
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

        success_count = 0
        error_count = 0

        for i, stmt in enumerate(statements, 1):
            try:
                if 'EXPLAIN ANALYZE' in stmt.upper():
                    continue

                first_words = ' '.join(stmt.strip().split()[:3])
                print(f"[{i}/{len(statements)}] 执行: {first_words}...")

                cursor.execute(stmt)

                if stmt.strip().upper().startswith('SELECT'):
                    rows = cursor.fetchall()
                    if rows:
                        print(f"    ✅ 查询成功 - 返回 {len(rows)} 行")
                        for row in rows[:3]:
                            print(f"       {row}")
                        if len(rows) > 3:
                            print(f"       ... 还有 {len(rows)-3} 行")
                else:
                    print(f"    ✅ 执行成功")

                success_count += 1

            except Exception as e:
                error_str = str(e)
                if 'already exists' in error_str or '已经存在' in error_str:
                    print(f"    ⚠️ 跳过（已存在）")
                    success_count += 1
                else:
                    print(f"    ❌ 执行失败: {e}")
                    error_count += 1

        print("\n" + "="*60)
        print(f"优化完成！成功: {success_count}, 失败: {error_count}")
        print("="*60 + "\n")

        # 验证索引
        print("验证关键索引...")
        cursor.execute("""
            SELECT indexname, tablename
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename IN ('kline_data', 'analysis_results')
              AND indexname LIKE 'idx_%'
            ORDER BY tablename, indexname
        """)

        indexes = cursor.fetchall()
        if indexes:
            print(f"✅ 发现 {len(indexes)} 个优化索引:")
            for idx in indexes:
                print(f"   - {idx[1]}.{idx[0]}")
        else:
            print("⚠️ 未发现优化索引")

        cursor.close()
        conn.close()
        print("\n✅ 数据库优化完成！")
        return True

    except Exception as e:
        print(f"\n❌ 数据库优化失败: {e}")
        return False


def main():
    """主函数"""
    print("\n" + "="*60)
    print("  🔧 数据库性能优化脚本")
    print("="*60 + "\n")

    if USE_ASYNCPG:
        print("使用 asyncpg 连接...")
        success = asyncio.run(execute_with_asyncpg())
    else:
        print("使用 psycopg2 连接...")
        success = execute_with_psycopg2()

    if success:
        print("\n🎉 优化成功！")
        print("\n下一步:")
        print("1. 重启服务: python src/main.py")
        print("2. 观察日志: tail -f logs/app.log")
        print("3. 验证效果: python scripts/verify_optimization.py")
        return 0
    else:
        print("\n⚠️ 优化失败，请检查错误信息")
        print("\n故障排查:")
        print("1. 检查数据库是否运行")
        print("2. 检查连接配置: src/utils/core/config.py")
        print("3. 检查数据库权限")
        return 1


if __name__ == "__main__":
    sys.exit(main())
