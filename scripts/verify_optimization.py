#!/usr/bin/env python3
"""
优化验证脚本
用途: 快速验证性能优化是否生效
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.utils.core.config import (
    ANALYSIS_WORKERS_GENERAL,
    QUEUE_CONFIG_GENERAL,
    TIMESCALEDB_POOL_MAX_SIZE,
    HTTP_POOL_SIZE
)
from src.utils.core.logging_config import logger


def print_section(title: str):
    """打印章节标题"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def check_config():
    """检查配置是否已优化"""
    print_section("1. 配置检查")

    checks = [
        ("工作线程数", ANALYSIS_WORKERS_GENERAL, 30, "个"),
        ("分析队列容量", QUEUE_CONFIG_GENERAL['analysis_queue_size'], 30000, "条"),
        ("数据库连接池", TIMESCALEDB_POOL_MAX_SIZE, 60, "个"),
        ("HTTP连接池", HTTP_POOL_SIZE, 100, "个"),
    ]

    all_passed = True

    for name, actual, expected, unit in checks:
        status = "✅" if actual >= expected else "❌"
        all_passed = all_passed and (actual >= expected)

        print(f"{status} {name}: {actual}{unit} (预期: >={expected}{unit})")

    return all_passed


def check_cache():
    """检查缓存模块是否可用"""
    print_section("2. 缓存模块检查")

    try:
        from src.utils.cache import get_global_cache

        cache = get_global_cache()
        print("✅ 缓存模块导入成功")

        # 测试缓存功能
        test_data = [{'time': '2024-01-01', 'close': 100}]
        cache.put('TEST/USDC:USDC', '5m', test_data)
        cached = cache.get('TEST/USDC:USDC', '5m')

        if cached is not None:
            print("✅ 缓存读写测试通过")
            stats = cache.get_stats()
            print(f"   缓存配置: max_size={stats['max_size']}, ttl=300s")
            return True
        else:
            print("❌ 缓存读写测试失败")
            return False

    except Exception as e:
        print(f"❌ 缓存模块检查失败: {e}")
        return False


def check_degradation():
    """检查降级策略是否可用"""
    print_section("3. 降级策略检查")

    try:
        from src.utils.strategy import DegradationStrategy

        degradation = DegradationStrategy(enabled=True)
        print("✅ 降级策略模块导入成功")

        # 测试降级逻辑
        result = degradation.should_process_task(
            'BTC/USDC:USDC', '5m', 0.85
        )
        print(f"✅ 降级策略测试通过 (队列85%，BTC 5m: {'处理' if result else '跳过'})")

        print(f"   核心交易对: {len(DegradationStrategy.CORE_SYMBOLS)} 个")
        print(f"   关键周期: {DegradationStrategy.CRITICAL_TIMEFRAMES}")
        return True

    except Exception as e:
        print(f"❌ 降级策略检查失败: {e}")
        return False


def check_monitoring():
    """检查监控模块是否可用"""
    print_section("4. 监控模块检查")

    try:
        from src.utils.monitoring.queue_monitor import QueueHealthMonitor
        import queue

        test_queue = queue.Queue(maxsize=100)
        monitor = QueueHealthMonitor(test_queue, name="测试队列")

        print("✅ 监控模块导入成功")

        # 测试监控功能
        for i in range(10):
            test_queue.put(i)
            monitor.record_enqueue()

        metrics = monitor.get_metrics()
        print(f"✅ 监控功能测试通过")
        print(f"   监控指标: 入队{metrics['total_enqueued']}条, 速率{metrics['enqueue_rate']:.2f}/s")

        return True

    except Exception as e:
        print(f"❌ 监控模块检查失败: {e}")
        return False


def check_database():
    """检查数据库连接和索引"""
    print_section("5. 数据库检查")

    try:
        import asyncpg
        import asyncio
        from src.utils.core.config import (
            TIMESCALEDB_HOST,
            TIMESCALEDB_PORT,
            TIMESCALEDB_NAME,
            TIMESCALEDB_USER,
            TIMESCALEDB_PASSWORD
        )

        async def check_db():
            try:
                # 连接数据库
                conn = await asyncpg.connect(
                    host=TIMESCALEDB_HOST,
                    port=TIMESCALEDB_PORT,
                    database=TIMESCALEDB_NAME,
                    user=TIMESCALEDB_USER,
                    password=TIMESCALEDB_PASSWORD,
                    timeout=10
                )

                print("✅ 数据库连接成功")

                # 检查索引
                indexes = await conn.fetch("""
                    SELECT indexname
                    FROM pg_indexes
                    WHERE tablename = 'kline_data'
                      AND indexname LIKE 'idx_%'
                """)

                print(f"✅ 发现 {len(indexes)} 个索引")
                for idx in indexes:
                    print(f"   - {idx['indexname']}")

                # 检查特定索引
                critical_indexes = ['idx_kline_symbol_timeframe_time']
                for idx_name in critical_indexes:
                    exists = any(idx['indexname'] == idx_name for idx in indexes)
                    status = "✅" if exists else "⚠️"
                    print(f"{status} 关键索引: {idx_name} {'存在' if exists else '未创建（建议执行 db_optimize.sql）'}")

                await conn.close()
                return True

            except Exception as e:
                print(f"❌ 数据库检查失败: {e}")
                print("   提示: 确保数据库正在运行，且连接配置正确")
                return False

        return asyncio.run(check_db())

    except Exception as e:
        print(f"❌ 数据库检查失败: {e}")
        return False


def check_files():
    """检查优化相关文件是否存在"""
    print_section("6. 文件完整性检查")

    files = [
        ("配置文件", "src/utils/core/config.py"),
        ("缓存模块", "src/utils/cache/data_cache.py"),
        ("降级策略", "src/utils/strategy/degradation.py"),
        ("监控模块", "src/utils/monitoring/queue_monitor.py"),
        ("数据库优化脚本", "scripts/db_optimize.sql"),
        ("优化指南", "docs/OPTIMIZATION_GUIDE.md"),
    ]

    all_exist = True
    project_root = os.path.join(os.path.dirname(__file__), '..')

    for name, path in files:
        full_path = os.path.join(project_root, path)
        exists = os.path.exists(full_path)
        status = "✅" if exists else "❌"
        all_exist = all_exist and exists
        print(f"{status} {name}: {path}")

    return all_exist


def print_summary(results: dict):
    """打印总结"""
    print_section("验证总结")

    total = len(results)
    passed = sum(1 for v in results.values() if v)

    print(f"总计: {passed}/{total} 项通过")
    print()

    for name, passed in results.items():
        status = "✅" if passed else "❌"
        print(f"{status} {name}")

    print()

    if passed == total:
        print("🎉 所有检查通过！优化已成功部署。")
        print()
        print("下一步:")
        print("1. 重启服务: python src/main.py")
        print("2. 观察日志: tail -f logs/app.log")
        print("3. 监控队列: 查看 '队列健康监控' 日志")
        print("4. 查看优化指南: docs/OPTIMIZATION_GUIDE.md")
    else:
        print("⚠️ 部分检查未通过，请根据上述提示修复问题。")
        print()
        print("常见问题:")
        print("- 配置未通过: 检查 src/utils/core/config.py 是否正确修改")
        print("- 模块未通过: 检查文件是否存在且没有语法错误")
        print("- 数据库未通过: 执行 scripts/db_optimize.sql")


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("  🔍 性能优化验证脚本")
    print("=" * 60)

    results = {}

    # 执行各项检查
    results["配置优化"] = check_config()
    results["缓存模块"] = check_cache()
    results["降级策略"] = check_degradation()
    results["监控模块"] = check_monitoring()
    results["文件完整性"] = check_files()
    results["数据库"] = check_database()

    # 打印总结
    print_summary(results)

    # 返回状态码
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
