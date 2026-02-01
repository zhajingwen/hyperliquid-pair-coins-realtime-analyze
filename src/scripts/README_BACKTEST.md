# BTC-ETH 4H K线回测与Z-score分析

## 功能说明

该脚本使用 yfinance 获取 BTC-USD 和 ETH-USD 的 4 小时历史K线数据，计算 ETH vs BTC 的滑动窗口 Z-score，并将分析结果写入 PostgreSQL 数据库。

## 安装依赖

```bash
# 确保已安装 uv（现代 Python 包管理器）
# 如果没有，可以通过 brew install uv 或 pip install uv 安装

# 依赖会在首次运行时自动安装
uv run python src/scripts/backtest_eth_btc_zscore_4h.py --help
```

## 使用方法

### 1. Dry-Run 模式（仅计算，不写入数据库）

```bash
# 默认获取最近730天的数据（yfinance 4h数据的最大范围）
uv run python src/scripts/backtest_eth_btc_zscore_4h.py --dry-run
```

### 2. 写入数据库模式

```bash
# 获取最大历史数据并写入数据库
uv run python src/scripts/backtest_eth_btc_zscore_4h.py
```

### 3. 自定义参数

```bash
# 自定义批量写入大小
uv run python src/scripts/backtest_eth_btc_zscore_4h.py --batch-size 500

# 指定日期范围（注意：yfinance 4h数据只支持最近730天）
uv run python src/scripts/backtest_eth_btc_zscore_4h.py \
    --start-date "2024-06-01" \
    --end-date "2024-12-31"
```

### 4. 完整参数说明

```bash
python src/scripts/backtest_eth_btc_zscore_4h.py -h

参数:
  --start-date YYYY-MM-DD    开始日期（可选，默认获取最大历史范围）
  --end-date YYYY-MM-DD      结束日期（可选，默认今天）
  --batch-size N             批量写入大小（默认1000）
  --dry-run                  仅计算不写入数据库
```

## 数据库配置

脚本会自动从 `src/utils/core/config.py` 读取数据库配置，无需手动配置。

如果需要修改数据库连接参数，可以设置环境变量：

```bash
export TIMESCALEDB_HOST=127.0.0.1
export TIMESCALEDB_PORT=5432  # 本地环境通常为 5433
export TIMESCALEDB_USER=postgres
export TIMESCALEDB_PASSWORD=your_password
```

## 输出示例

### 控制台输出

```
=== BTC-ETH 4H K线回测与Z-score分析 ===
开始日期: 默认 (yfinance 最早可用)
结束日期: 今天
批量写入大小: 1000
模式: 计算并写入数据库

开始获取 BTC-USD 的 4h K线数据...
BTC-USD: 成功获取 4370 个 4h K线数据
  时间范围: 2024-02-03 00:00:00+00:00 至 2026-02-01 04:00:00+00:00

开始获取 ETH-USD 的 4h K线数据...
ETH-USD: 成功获取 4370 个 4h K线数据
  时间范围: 2024-02-03 00:00:00+00:00 至 2026-02-01 04:00:00+00:00

开始对齐 BTC 和 ETH 的K线数据...
数据对齐完成: 4370 个时间点

开始计算 Z-score (滑动窗口计算)...
  BETA_WINDOW = 100
  ZSCORE_WINDOW = 30
计算 Z-score: 100%|██████████| 4270/4270 [00:24<00:00, 175.00it/s]

Z-score 计算完成: 4270 个结果

=== 统计信息 ===
总数据点: 4270
Z-score 数量: 4270
Z-score 范围: [-6.47, 6.12]
Z-score 平均: -0.20
异常点数量 (|z|>2.0): 791 (18.5%)
极端异常 (|z|>3.0): 195 (4.6%)
协整检验通过: 923 (21.6%)

开始写入数据库 (共 4270 条记录)...
批量写入: 1000 条记录 (总计: 1000/4270)
批量写入: 1000 条记录 (总计: 2000/4270)
批量写入: 1000 条记录 (总计: 3000/4270)
批量写入: 1000 条记录 (总计: 4000/4270)
批量写入: 270 条记录 (总计: 4270/4270)
成功写入 4270 条分析结果到数据库

=== 回测完成 ===
```

### 数据库查询验证

```sql
-- 查询统计信息
SELECT
    COUNT(*) as total_count,
    AVG(zscore_4h) as avg_zscore,
    MIN(zscore_4h) as min_zscore,
    MAX(zscore_4h) as max_zscore,
    COUNT(*) FILTER (WHERE is_anomaly = TRUE) as anomaly_count,
    COUNT(*) FILTER (WHERE cointegration_passed = TRUE) as coint_passed_count,
    MIN(kline_time) as first_kline_time,
    MAX(kline_time) as last_kline_time
FROM analysis_results
WHERE symbol = 'ETH/USDC:USDC' AND base_symbol = 'BTC/USDC:USDC';

-- 查询异常点
SELECT
    kline_time,
    zscore_4h,
    trading_direction,
    signal_strength,
    cointegration_passed,
    adf_pvalue
FROM analysis_results
WHERE symbol = 'ETH/USDC:USDC'
    AND base_symbol = 'BTC/USDC:USDC'
    AND is_anomaly = TRUE
ORDER BY ABS(zscore_4h) DESC
LIMIT 10;
```

## 技术细节

### 数据来源

- **数据源**: yfinance (Yahoo Finance API)
- **Symbol 格式**: BTC-USD, ETH-USD
- **时间周期**: 4 小时
- **最大历史范围**: 730天（约2年）

### 分析算法

- **OLS 回归窗口**: 100期（BETA_WINDOW）
- **Z-score 统计窗口**: 30期（ZSCORE_WINDOW）
- **滑动窗口计算**: 从第100个数据点开始，逐步计算每个时间点的Z-score
- **协整检验**: ADF检验，p值 < 0.05 为通过

### 数据存储

- **目标表**: `analysis_results`
- **Symbol 格式**: ETH/USDC:USDC（目标币种）
- **Base Symbol**: BTC/USDC:USDC（基准币种）
- **写入策略**: 批量写入，使用 ON CONFLICT 处理重复
- **主要字段**:
  - `kline_time`: K线时间戳
  - `zscore_4h`: Z-score 值
  - `cointegration_passed`: 协整检验是否通过
  - `adf_pvalue`: ADF检验 p值
  - `is_anomaly`: 是否异常（|z| > 2.0）
  - `trading_direction`: 交易方向（long/short/none）
  - `signal_strength`: 信号强度（extreme/strong/medium/weak）

### 性能指标

- **计算速度**: ~175 it/s（每秒处理175个数据点）
- **总耗时**: 约30秒（4270个数据点）
- **内存占用**: 约100MB
- **数据库写入**: 批量写入，约1秒/1000条记录

## 常见问题

### Q: 为什么只能获取730天的数据？

A: yfinance 对 4h 时间周期的历史数据有限制，最多只能获取最近730天的数据。如果需要更长的历史数据，可以考虑使用其他数据源。

### Q: 数据库连接失败怎么办？

A: 检查以下几点：
1. PostgreSQL 是否正在运行
2. 端口号是否正确（本地环境通常为 5433，而非默认的 5432）
3. 用户名和密码是否正确
4. 数据库 `crypto_data` 是否已创建
5. 表 `analysis_results` 是否已创建

### Q: 如何重新运行回测？

A: 脚本使用 `ON CONFLICT DO UPDATE` 策略，可以直接重新运行，会自动更新已存在的记录。

### Q: 如何获取更多历史数据？

A: 由于 yfinance 的限制，无法获取超过730天的 4h 数据。如果需要更长的历史数据，可以：
1. 使用其他数据源（如 CCXT）
2. 使用日线数据（yfinance 支持更长的历史范围）
3. 定期运行脚本并累积数据

## 相关文件

- 脚本源码: `src/scripts/backtest_eth_btc_zscore_4h.py`
- 分析算法: `src/utils/analysis/analysis_core.py`
- 数据库客户端: `src/utils/database/timescaledb.py`
- 配置文件: `src/utils/core/config.py`
- 数据库表结构: `database/init_timescaledb.sql`

## 作者

Claude Code

## 最后更新

2026-02-01
