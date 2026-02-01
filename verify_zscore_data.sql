-- 验证 Z-score 写入逻辑的 SQL 查询脚本
-- 用于检查数据库中记录的分析结果

-- ============================================================
-- 1. 查询所有分析结果（包括验证未通过的）
-- ============================================================
SELECT
    analysis_time,
    symbol,
    zscore_5m,
    zscore_1h,
    zscore_4h,
    cointegration_passed,
    is_anomaly,
    trading_direction,
    signal_strength
FROM analysis_results
WHERE symbol = 'PURR/USDC:USDC'
ORDER BY analysis_time DESC
LIMIT 100;

-- ============================================================
-- 2. 统计验证通过和未通过的比例
-- ============================================================
SELECT
    cointegration_passed,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as percentage,
    ROUND(AVG(ABS(zscore_4h)), 2) as avg_abs_zscore_4h,
    ROUND(AVG(ABS(zscore_1h)), 2) as avg_abs_zscore_1h,
    ROUND(AVG(ABS(zscore_5m)), 2) as avg_abs_zscore_5m
FROM analysis_results
WHERE symbol = 'PURR/USDC:USDC'
  AND analysis_time >= NOW() - INTERVAL '7 days'
GROUP BY cointegration_passed
ORDER BY cointegration_passed DESC;

-- ============================================================
-- 3. 查询最近 24 小时的分析记录详情
-- ============================================================
SELECT
    analysis_time,
    zscore_4h,
    zscore_1h,
    zscore_5m,
    cointegration_passed,
    trading_direction,
    CASE
        WHEN cointegration_passed THEN '✅ 协整通过'
        ELSE '❌ 协整不足'
    END as validation_status
FROM analysis_results
WHERE symbol = 'PURR/USDC:USDC'
  AND analysis_time >= NOW() - INTERVAL '24 hours'
ORDER BY analysis_time DESC;

-- ============================================================
-- 4. 按小时统计分析结果
-- ============================================================
SELECT
    DATE_TRUNC('hour', analysis_time) as hour,
    COUNT(*) as total_count,
    SUM(CASE WHEN cointegration_passed THEN 1 ELSE 0 END) as passed_count,
    SUM(CASE WHEN NOT cointegration_passed THEN 1 ELSE 0 END) as failed_count,
    ROUND(
        SUM(CASE WHEN cointegration_passed THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
        2
    ) as pass_rate_percent
FROM analysis_results
WHERE symbol = 'PURR/USDC:USDC'
  AND analysis_time >= NOW() - INTERVAL '7 days'
GROUP BY DATE_TRUNC('hour', analysis_time)
ORDER BY hour DESC
LIMIT 168;  -- 7 天 * 24 小时

-- ============================================================
-- 5. 检查是否所有记录都有有效的 Z-score
-- ============================================================
SELECT
    COUNT(*) as total_records,
    SUM(CASE WHEN zscore_4h IS NOT NULL THEN 1 ELSE 0 END) as has_zscore_4h,
    SUM(CASE WHEN zscore_1h IS NOT NULL THEN 1 ELSE 0 END) as has_zscore_1h,
    SUM(CASE WHEN zscore_5m IS NOT NULL THEN 1 ELSE 0 END) as has_zscore_5m,
    SUM(CASE
        WHEN zscore_4h IS NOT NULL
         AND zscore_1h IS NOT NULL
         AND zscore_5m IS NOT NULL
        THEN 1 ELSE 0
    END) as has_all_zscores
FROM analysis_results
WHERE symbol = 'PURR/USDC:USDC'
  AND analysis_time >= NOW() - INTERVAL '7 days';

-- ============================================================
-- 6. 查询 Z-score 的分布范围
-- ============================================================
SELECT
    'zscore_4h' as metric,
    ROUND(MIN(zscore_4h), 2) as min_value,
    ROUND(MAX(zscore_4h), 2) as max_value,
    ROUND(AVG(zscore_4h), 2) as avg_value,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY zscore_4h), 2) as median_value
FROM analysis_results
WHERE symbol = 'PURR/USDC:USDC'
  AND analysis_time >= NOW() - INTERVAL '7 days'
  AND zscore_4h IS NOT NULL

UNION ALL

SELECT
    'zscore_1h' as metric,
    ROUND(MIN(zscore_1h), 2),
    ROUND(MAX(zscore_1h), 2),
    ROUND(AVG(zscore_1h), 2),
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY zscore_1h), 2)
FROM analysis_results
WHERE symbol = 'PURR/USDC:USDC'
  AND analysis_time >= NOW() - INTERVAL '7 days'
  AND zscore_1h IS NOT NULL

UNION ALL

SELECT
    'zscore_5m' as metric,
    ROUND(MIN(zscore_5m), 2),
    ROUND(MAX(zscore_5m), 2),
    ROUND(AVG(zscore_5m), 2),
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY zscore_5m), 2)
FROM analysis_results
WHERE symbol = 'PURR/USDC:USDC'
  AND analysis_time >= NOW() - INTERVAL '7 days'
  AND zscore_5m IS NOT NULL;

-- ============================================================
-- 7. 查询协整未通过但 Z-score 有效的记录（验证新逻辑）
-- ============================================================
SELECT
    analysis_time,
    zscore_4h,
    zscore_1h,
    zscore_5m,
    cointegration_passed,
    trading_direction,
    '✅ 新逻辑：Z-score 有效但协整未通过，仍然写入数据库' as validation
FROM analysis_results
WHERE symbol = 'PURR/USDC:USDC'
  AND cointegration_passed = FALSE
  AND zscore_4h IS NOT NULL
  AND zscore_1h IS NOT NULL
  AND zscore_5m IS NOT NULL
  AND analysis_time >= NOW() - INTERVAL '7 days'
ORDER BY analysis_time DESC
LIMIT 50;
