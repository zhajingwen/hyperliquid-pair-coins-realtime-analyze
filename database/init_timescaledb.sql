-- =====================================================
-- TimescaleDB 初始化脚本
-- 用途: 加密货币实时套利信号分析系统数据库
-- 版本: 1.0
-- 创建时间: 2025-01-18
-- =====================================================

-- 1. 启用 TimescaleDB 扩展
CREATE EXTENSION IF NOT EXISTS timescaledb;

\echo '✅ TimescaleDB 扩展已启用'

-- =====================================================
-- 2. 创建表结构
-- =====================================================

-- 表1: klines (K线数据表)
-- 用途: 存储多币种、多周期的K线数据
CREATE TABLE IF NOT EXISTS klines (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    volume_usd DOUBLE PRECISION,
    return_pct DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- 复合主键
    PRIMARY KEY (time, symbol, timeframe)
);

\echo '✅ 表 klines 已创建'

-- 表2: symbol_metadata (币种元数据表)
-- 用途: 追踪币种上线时间、数据质量、活跃状态
CREATE TABLE IF NOT EXISTS symbol_metadata (
    symbol VARCHAR(50) PRIMARY KEY,
    base_asset VARCHAR(20) NOT NULL,
    quote_asset VARCHAR(20) NOT NULL,
    listing_time TIMESTAMPTZ,
    first_kline_time TIMESTAMPTZ,
    last_kline_time TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    data_quality_score DOUBLE PRECISION DEFAULT 0.0,
    total_klines BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

\echo '✅ 表 symbol_metadata 已创建'

-- 表3: analysis_results (分析结果表)
-- 用途: 存储相关性分析、Z-score、协整检验等结果
CREATE TABLE IF NOT EXISTS analysis_results (
    id SERIAL,
    analysis_time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    base_symbol VARCHAR(50) NOT NULL,

    -- 时间链路字段
    kline_time TIMESTAMPTZ,                    -- K线原始时间（新增）
    analysis_delay_seconds FLOAT,              -- 分析延迟（秒，新增）

    -- 相关系数（不同周期）
    corr_5m_7d DOUBLE PRECISION,
    corr_1h_30d DOUBLE PRECISION,
    corr_4h_60d DOUBLE PRECISION,

    -- Z-score（标准分数）
    zscore_5m DOUBLE PRECISION,
    zscore_1h DOUBLE PRECISION,
    zscore_4h DOUBLE PRECISION,

    -- 协整检验
    cointegration_passed BOOLEAN DEFAULT FALSE,
    adf_pvalue DOUBLE PRECISION,

    -- 信号标识
    is_anomaly BOOLEAN DEFAULT FALSE,
    trading_direction VARCHAR(50),
    signal_strength VARCHAR(20),

    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- 复合主键（时间分区）
    PRIMARY KEY (analysis_time, id)
);

\echo '✅ 表 analysis_results 已创建'

-- =====================================================
-- 3. 转换为 Hypertable（时序表）
-- =====================================================

-- 将 klines 转换为 Hypertable（7天chunk）
SELECT create_hypertable(
    'klines',
    'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

\echo '✅ klines 已转换为 Hypertable (7天chunk)'

-- 将 analysis_results 转换为 Hypertable（30天chunk）
SELECT create_hypertable(
    'analysis_results',
    'analysis_time',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);

\echo '✅ analysis_results 已转换为 Hypertable (30天chunk)'

-- =====================================================
-- 4. 创建索引（优化查询性能）
-- =====================================================

-- 索引1: klines 按币种+周期+时间倒序（最常用查询）
CREATE INDEX IF NOT EXISTS idx_klines_symbol_timeframe_time
ON klines (symbol, timeframe, time DESC);

\echo '✅ 索引 idx_klines_symbol_timeframe_time 已创建'

-- 索引2: symbol_metadata 活跃币种快速查询（部分索引）
CREATE INDEX IF NOT EXISTS idx_symbol_active
ON symbol_metadata (symbol)
WHERE is_active = TRUE;

\echo '✅ 索引 idx_symbol_active 已创建'

-- 索引3: symbol_metadata 上线时间排序
CREATE INDEX IF NOT EXISTS idx_symbol_listing_time
ON symbol_metadata (listing_time DESC);

\echo '✅ 索引 idx_symbol_listing_time 已创建'

-- 索引4: analysis_results 按币种+时间倒序
CREATE INDEX IF NOT EXISTS idx_analysis_symbol_time
ON analysis_results (symbol, analysis_time DESC);

\echo '✅ 索引 idx_analysis_symbol_time 已创建'

-- 索引5: analysis_results 异常信号快速过滤（部分索引）
CREATE INDEX IF NOT EXISTS idx_analysis_anomaly_time
ON analysis_results (analysis_time DESC)
WHERE is_anomaly = TRUE;

\echo '✅ 索引 idx_analysis_anomaly_time 已创建'

-- 索引6: analysis_results 按 kline_time 查询（可选）
CREATE INDEX IF NOT EXISTS idx_analysis_kline_time
ON analysis_results (symbol, kline_time DESC);

\echo '✅ 索引 idx_analysis_kline_time 已创建'

-- 索引7: 延迟监控查询索引（可选）
CREATE INDEX IF NOT EXISTS idx_analysis_delay
ON analysis_results (analysis_delay_seconds DESC)
WHERE analysis_delay_seconds > 5;  -- 只索引延迟较高的记录

\echo '✅ 索引 idx_analysis_delay 已创建'

-- =====================================================
-- 5. 配置保留策略（自动清理历史数据）
-- =====================================================

-- klines: 保留90天
SELECT add_retention_policy(
    'klines',
    INTERVAL '90 days',
    if_not_exists => TRUE
);

\echo '✅ klines 保留策略已配置 (90天)'

-- analysis_results: 保留180天
SELECT add_retention_policy(
    'analysis_results',
    INTERVAL '180 days',
    if_not_exists => TRUE
);

\echo '✅ analysis_results 保留策略已配置 (180天)'

-- =====================================================
-- 6. 配置压缩策略（节省存储空间）
-- =====================================================

-- klines: 7天后自动压缩（按symbol和timeframe分段压缩）
ALTER TABLE klines SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,timeframe'
);

SELECT add_compression_policy(
    'klines',
    INTERVAL '7 days',
    if_not_exists => TRUE
);

\echo '✅ klines 压缩策略已配置 (7天后压缩)'

-- analysis_results: 30天后自动压缩（按symbol分段压缩）
ALTER TABLE analysis_results SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol'
);

SELECT add_compression_policy(
    'analysis_results',
    INTERVAL '30 days',
    if_not_exists => TRUE
);

\echo '✅ analysis_results 压缩策略已配置 (30天后压缩)'

-- =====================================================
-- 7. 创建连续聚合视图（每日分析统计）
-- =====================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS daily_analysis_stats
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', analysis_time) AS day,
    symbol,
    base_symbol,
    COUNT(*) AS analysis_count,
    COUNT(*) FILTER (WHERE is_anomaly = TRUE) AS anomaly_count,
    AVG(corr_5m_7d) AS avg_corr_5m,
    AVG(corr_1h_30d) AS avg_corr_1h,
    AVG(corr_4h_60d) AS avg_corr_4h,
    AVG(zscore_5m) AS avg_zscore_5m,
    AVG(zscore_1h) AS avg_zscore_1h,
    AVG(zscore_4h) AS avg_zscore_4h
FROM analysis_results
GROUP BY day, symbol, base_symbol;

\echo '✅ 连续聚合视图 daily_analysis_stats 已创建'

-- =====================================================
-- 8. 配置连续聚合自动刷新策略（每小时更新）
-- =====================================================

SELECT add_continuous_aggregate_policy(
    'daily_analysis_stats',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

\echo '✅ daily_analysis_stats 自动刷新策略已配置 (每小时)'

-- =====================================================
-- 9. 验证配置
-- =====================================================

\echo ''
\echo '========================================='
\echo '📊 数据库初始化验证'
\echo '========================================='

-- 查看所有表
\echo '📋 表列表:'
\dt

-- 查看 Hypertable 配置
\echo ''
\echo '⚙️  Hypertable 配置:'
SELECT hypertable_name, num_dimensions, num_chunks
FROM timescaledb_information.hypertables;

-- 查看索引
\echo ''
\echo '🔍 索引列表:'
\di

\echo ''
\echo '========================================='
\echo '✅ TimescaleDB 初始化完成！'
\echo '========================================='
\echo ''
\echo '下一步操作:'
\echo '1. 连接数据库: docker exec -it crypto_timescaledb psql -U postgres -d crypto_data'
\echo '2. 查看表结构: \d klines'
\echo '3. 测试性能: 见实施计划文档'
\echo ''
