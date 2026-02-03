-- ============================================================
-- 数据库性能优化脚本 (针对实际表结构)
-- 表名: klines (实际), analysis_results
-- ============================================================

-- 1. 分析表统计信息更新（提升查询计划质量）
ANALYZE klines;
ANALYZE analysis_results;
ANALYZE symbol_metadata;

-- 2. 检查现有索引使用情况
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
  AND tablename IN ('klines', 'analysis_results')
ORDER BY idx_scan DESC;

-- 3. 检查表大小和索引大小
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS table_size,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename)) AS index_size
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN ('klines', 'analysis_results', 'symbol_metadata');

-- 4. 创建额外的性能优化索引（如果不存在）

-- 4.1 为 klines 表创建覆盖索引（包含常用列）
CREATE INDEX IF NOT EXISTS idx_klines_symbol_time_close
ON klines (symbol, time DESC, close);

-- 4.2 为 klines 表创建按时间周期的局部索引（加速特定周期查询）
CREATE INDEX IF NOT EXISTS idx_klines_5m
ON klines (symbol, time DESC)
WHERE timeframe = '5m';

CREATE INDEX IF NOT EXISTS idx_klines_1h
ON klines (symbol, time DESC)
WHERE timeframe = '1h';

CREATE INDEX IF NOT EXISTS idx_klines_4h
ON klines (symbol, time DESC)
WHERE timeframe = '4h';

-- 4.3 为分析结果创建组合索引
CREATE INDEX IF NOT EXISTS idx_analysis_results_symbol_timeframe
ON analysis_results (symbol, timeframe, analyzed_at DESC);

-- 5. 优化查询示例（使用索引的最佳实践）

-- 5.1 正确的查询方式（利用索引）
EXPLAIN ANALYZE
SELECT * FROM klines
WHERE symbol = 'BTC/USDC:USDC'
  AND timeframe = '5m'
  AND time > NOW() - INTERVAL '7 days'
ORDER BY time DESC
LIMIT 2000;

-- 5.2 批量查询优化示例
EXPLAIN ANALYZE
WITH periods AS (
    SELECT '5m' as tf, 7 as days UNION ALL
    SELECT '1h', 30 UNION ALL
    SELECT '4h', 60
)
SELECT k.symbol, k.timeframe, k.time, k.open, k.high, k.low, k.close, k.volume
FROM klines k
JOIN periods p ON k.timeframe = p.tf
WHERE k.symbol = 'BTC/USDC:USDC'
  AND k.time > NOW() - (p.days || ' days')::INTERVAL
ORDER BY k.timeframe, k.time DESC;

-- 6. 清理过期数据（可选，释放存储空间）
-- 注意：根据实际需求调整保留时间
-- DELETE FROM klines
-- WHERE time < NOW() - INTERVAL '90 days'
--   AND timeframe = '5m';  -- 只清理5分钟数据

-- 7. 真空清理（回收空间并更新统计信息）
VACUUM ANALYZE klines;
VACUUM ANALYZE analysis_results;
VACUUM ANALYZE symbol_metadata;

-- ============================================================
-- 性能监控查询
-- ============================================================

-- 查看表膨胀情况
SELECT
    schemaname,
    tablename,
    n_live_tup as live_rows,
    n_dead_tup as dead_rows,
    ROUND(n_dead_tup * 100.0 / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_ratio
FROM pg_stat_user_tables
WHERE schemaname = 'public'
  AND tablename IN ('klines', 'analysis_results')
ORDER BY dead_ratio DESC;

-- 查看缓存命中率
SELECT
    schemaname,
    tablename,
    heap_blks_read as disk_reads,
    heap_blks_hit as cache_hits,
    ROUND(100.0 * heap_blks_hit / NULLIF(heap_blks_hit + heap_blks_read, 0), 2) as cache_hit_ratio
FROM pg_statio_user_tables
WHERE schemaname = 'public'
  AND tablename IN ('klines', 'analysis_results')
ORDER BY cache_hit_ratio DESC;

-- 查看最常用的查询模式（需要pg_stat_statements扩展）
-- SELECT
--     query,
--     calls,
--     total_exec_time,
--     mean_exec_time,
--     max_exec_time
-- FROM pg_stat_statements
-- WHERE query LIKE '%klines%'
-- ORDER BY mean_exec_time DESC
-- LIMIT 10;

-- ============================================================
-- 优化完成
-- ============================================================
