-- ============================================================
-- 数据库性能优化脚本
-- 用途: 优化分析队列性能，减少数据库查询耗时
-- 执行: psql -U postgres -d crypto_data -f scripts/db_optimize.sql
-- ============================================================

-- 1. 创建复合索引（如果不存在）
-- 用于加速按交易对、时间周期、时间范围查询
CREATE INDEX IF NOT EXISTS idx_kline_symbol_timeframe_time
ON kline_data (symbol, timeframe, time DESC);

-- 2. 创建单独时间索引（用于时间范围过滤）
CREATE INDEX IF NOT EXISTS idx_kline_time
ON kline_data (time DESC);

-- 3. 创建分析结果表索引
CREATE INDEX IF NOT EXISTS idx_analysis_symbol_timeframe_time
ON analysis_results (symbol, timeframe, analyzed_at DESC);

-- 4. 分析表统计信息更新（提升查询计划质量）
ANALYZE kline_data;
ANALYZE analysis_results;

-- 5. 检查索引使用情况
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
  AND tablename IN ('kline_data', 'analysis_results')
ORDER BY idx_scan DESC;

-- 6. 检查表大小和索引大小
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS table_size,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename)) AS index_size
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN ('kline_data', 'analysis_results');

-- 7. 优化查询示例（使用索引的最佳实践）
-- ✅ 正确：带时间范围过滤，利用分区和索引
EXPLAIN ANALYZE
SELECT * FROM kline_data
WHERE symbol = 'BTC/USDC:USDC'
  AND timeframe = '5m'
  AND time > NOW() - INTERVAL '7 days'
ORDER BY time DESC
LIMIT 2000;

-- 8. 批量查询优化示例（减少数据库往返）
EXPLAIN ANALYZE
WITH periods AS (
    SELECT '5m' as tf, 7 as days UNION ALL
    SELECT '1h', 30 UNION ALL
    SELECT '4h', 60
)
SELECT k.symbol, k.timeframe, k.time, k.open, k.high, k.low, k.close, k.volume
FROM kline_data k
JOIN periods p ON k.timeframe = p.tf
WHERE k.symbol = 'BTC/USDC:USDC'
  AND k.time > NOW() - (p.days || ' days')::INTERVAL
ORDER BY k.timeframe, k.time DESC;

-- 9. 清理过期数据（可选，释放存储空间）
-- 注意：根据实际需求调整保留时间
-- DELETE FROM kline_data
-- WHERE time < NOW() - INTERVAL '90 days'
--   AND timeframe = '5m';  -- 只清理5分钟数据

-- 10. 真空清理（回收空间并更新统计信息）
VACUUM ANALYZE kline_data;
VACUUM ANALYZE analysis_results;

-- ============================================================
-- 性能监控查询
-- ============================================================

-- 查看慢查询
SELECT
    query,
    calls,
    total_time,
    mean_time,
    max_time,
    stddev_time
FROM pg_stat_statements
WHERE query LIKE '%kline_data%'
ORDER BY mean_time DESC
LIMIT 10;

-- 查看表膨胀情况
SELECT
    schemaname,
    tablename,
    n_live_tup,
    n_dead_tup,
    ROUND(n_dead_tup * 100.0 / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_ratio
FROM pg_stat_user_tables
WHERE schemaname = 'public'
  AND tablename IN ('kline_data', 'analysis_results')
ORDER BY dead_ratio DESC;
