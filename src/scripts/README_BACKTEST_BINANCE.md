# BTC-ETH 4H K线回测与Z-score分析（Binance数据源）

## 📊 数据源对比

| 特性 | yfinance | CCXT Binance ✅ 推荐 |
|------|----------|---------------------|
| **最大历史范围** | 730天（2年） | **8.5年** |
| **总数据点** | 4,370个 | **18,540个** |
| **数据质量** | Yahoo Finance | **交易所原生数据** |
| **API调用次数** | 1次 | 19次 |
| **获取耗时** | ~5秒 | **~40秒** |
| **数据起始时间** | 2024-02-03 | **2017-08-17** |

## 🚀 快速开始

### 安装依赖

依赖会在首次运行时自动安装（通过 uv）：

```bash
# 确保已安装 uv
# brew install uv  # macOS
# pip install uv   # 其他系统
```

### 基本使用

#### 1. Dry-Run 模式（测试数据获取）

```bash
# 获取最近1个月数据（快速测试）
uv run python src/scripts/backtest_eth_btc_zscore_4h_binance.py \
    --dry-run \
    --start-date "2025-01-01" \
    --end-date "2025-02-01"
```

#### 2. 完整历史数据回测（8.5年）

```bash
# 获取并写入完整历史数据
uv run python src/scripts/backtest_eth_btc_zscore_4h_binance.py
```

**预计耗时**：约 3-4 分钟
- 数据获取：~40秒（19次API调用）
- Z-score计算：~90秒（18,425个数据点）
- 数据库写入：~2秒（18次批量写入）

#### 3. 自定义参数

```bash
# 指定时间范围
uv run python src/scripts/backtest_eth_btc_zscore_4h_binance.py \
    --start-date "2020-01-01" \
    --end-date "2023-12-31"

# 调整API调用间隔（避免限流）
uv run python src/scripts/backtest_eth_btc_zscore_4h_binance.py \
    --api-delay 0.5

# 自定义批量写入大小
uv run python src/scripts/backtest_eth_btc_zscore_4h_binance.py \
    --batch-size 500
```

## 📋 命令行参数

```bash
python src/scripts/backtest_eth_btc_zscore_4h_binance.py -h

参数:
  --start-date YYYY-MM-DD    开始日期（默认: 2017-08-17，Binance上线时）
  --end-date YYYY-MM-DD      结束日期（默认: 今天）
  --batch-size N             批量写入大小（默认: 1000）
  --api-delay SECONDS        API调用间隔（默认: 0.2秒）
  --dry-run                  仅计算不写入数据库
```

## 📈 实际运行结果

### 完整历史数据回测（8.5年）

```
=== BTC-ETH 4H K线回测与Z-score分析（Binance数据源）===
开始日期: 2017-08-17 (Binance上线时)
结束日期: 今天
批量写入大小: 1000
API调用间隔: 0.2秒
模式: 计算并写入数据库

获取 BTC/USDT: 100%|██████████| 18541/18541 [00:19<00:00, 945.53条/s]
BTC/USDT: 成功获取 18525 个 4h K线数据
  时间范围: 2017-08-17 04:00:00+00:00 至 2026-02-01 04:00:00+00:00

获取 ETH/USDT: 100%|██████████| 18541/18541 [00:09<00:00, 1871.32条/s]
ETH/USDT: 成功获取 18525 个 4h K线数据
  时间范围: 2017-08-17 04:00:00+00:00 至 2026-02-01 04:00:00+00:00

数据对齐完成: 18525 个时间点

计算 Z-score: 100%|██████████| 18425/18425 [01:30<00:00, 204.21it/s]
Z-score 计算完成: 18425 个结果

=== 统计信息 ===
总数据点: 18425
Z-score 数量: 18425
Z-score 范围: [-12.24, 16.88]
Z-score 平均: -0.11
异常点数量 (|z|>2.0): 3486 (18.9%)
极端异常 (|z|>3.0): 902 (4.9%)
协整检验通过: 3620 (19.6%)

批量写入: 1000 条记录 × 18 次 + 425 条记录
成功写入 18425 条分析结果到数据库

=== 回测完成 ===
```

### 数据库验证结果

```sql
SELECT
    COUNT(*) as total_count,
    AVG(zscore_4h) as avg_zscore,
    MIN(zscore_4h) as min_zscore,
    MAX(zscore_4h) as max_zscore,
    COUNT(*) FILTER (WHERE is_anomaly = TRUE) as anomaly_count,
    MIN(kline_time) as first_kline_time,
    MAX(kline_time) as last_kline_time
FROM analysis_results
WHERE symbol = 'ETH/USDC:USDC' AND base_symbol = 'BTC/USDC:USDC';
```

**查询结果**:
- ✅ 总记录数：22,695条（包含yfinance的4,270条）
- ✅ 时间跨度：8.4年（2017-09-02 至 2026-02-01）
- ✅ Z-score 范围：[-12.24, 16.88]
- ✅ 异常点：4,277个（18.8%）
- ✅ 协整检验通过：4,543个（20.0%）

## 🔧 技术细节

### 数据获取策略

1. **分批获取**：
   - Binance API 每次最多返回 1000 个数据点
   - 8.5年的4h数据需要约 **19次** API调用
   - 每次调用间隔 0.2秒（可调整），避免触发限流

2. **API速率限制**：
   - Binance 限制：1200请求/分钟
   - 脚本默认间隔：0.2秒/请求（300请求/分钟）
   - 安全裕度：充足（仅使用25%的限额）

3. **数据对齐**：
   - 使用时间戳哈希表对齐 BTC 和 ETH 数据
   - 确保两个币种的时间点完全一致

### Symbol 格式

- **Binance格式**：`BTC/USDT`, `ETH/USDT`
- **数据库格式**：`BTC/USDC:USDC`, `ETH/USDC:USDC`（保持与现有系统一致）

### 性能优化

- **进度显示**：使用 tqdm 实时显示获取和计算进度
- **批量写入**：1000条/批次，减少数据库往返
- **内存优化**：流式处理，避免一次性加载所有数据

## 📊 数据质量对比

### yfinance vs Binance

| 指标 | yfinance（2年） | Binance（8.5年） |
|------|----------------|------------------|
| 数据点数 | 4,370 | 18,425 |
| Z-score范围 | [-6.47, 6.12] | [-12.24, 16.88] |
| 异常点比例 | 18.5% | 18.9% |
| 协整检验通过率 | 21.6% | 19.6% |

**结论**：
- ✅ Binance 提供了 **4.2倍** 的数据量
- ✅ 更长的历史范围，包含更多市场周期
- ✅ 数据质量一致，统计特征相似

## 🚨 常见问题

### Q: 获取数据时出现 "Rate limit exceeded" 错误？

**A**: 增加 API 调用间隔：
```bash
uv run python src/scripts/backtest_eth_btc_zscore_4h_binance.py --api-delay 0.5
```

### Q: 数据库连接失败？

**A**: 检查数据库配置：
```bash
# 查看环境变量
echo $TIMESCALEDB_PORT  # 应该是 5432 或 5433

# 测试连接
psql -h 127.0.0.1 -p 5432 -U postgres -d crypto_data
```

### Q: 如何获取更多历史数据？

**A**: Binance 的数据已经是 **8.5年**（从上线开始），这是该交易对的全部历史数据。

### Q: 如何只更新最新数据（增量更新）？

**A**:
```bash
# 查询数据库中最新的时间点
# 然后从该时间点开始获取新数据
uv run python src/scripts/backtest_eth_btc_zscore_4h_binance.py \
    --start-date "2026-01-01"
```

### Q: 能否使用其他交易所的数据？

**A**: 可以，CCXT 支持 100+ 交易所。修改脚本中的：
```python
exchange = ccxt.binance()  # 改为其他交易所
# 如：ccxt.coinbase(), ccxt.kraken(), ccxt.okx()
```

## 📁 相关文件

- **Binance脚本**: `src/scripts/backtest_eth_btc_zscore_4h_binance.py`
- **yfinance脚本**: `src/scripts/backtest_eth_btc_zscore_4h.py`
- **分析算法**: `src/utils/analysis/analysis_core.py`
- **数据库客户端**: `src/utils/database/timescaledb.py`
- **配置文件**: `src/utils/core/config.py`

## 🎯 推荐使用场景

### 使用 Binance 数据源的场景

✅ 需要长期历史数据（>2年）
✅ 进行长周期回测和分析
✅ 研究多个市场周期
✅ 需要更多异常点样本

### 使用 yfinance 数据源的场景

✅ 快速测试和验证
✅ 只需要最近数据
✅ 网络受限环境
✅ 不想处理API限流

## 📝 更新日志

**2026-02-01**:
- ✅ 初始版本发布
- ✅ 支持 8.5年历史数据获取
- ✅ 自动分批获取和进度显示
- ✅ 完整的错误处理和重试机制

## 👤 作者

Claude Code

## 📄 许可证

与主项目相同
