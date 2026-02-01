# Z-score 写入逻辑修改总结

## 修改日期
2026-02-01

## 修改目标
只要 Z-score 计算成功，无论其他验证（协整检验、健康状态、符号一致性、阈值检查）是否通过，都应该将分析结果写入数据库。

## 核心理由
Z-score 是最关键的数据，即使某些验证不通过，这些数据仍有分析价值。

---

## 修改内容

### 修改文件
- **src/services/realtime_kline_service_base.py** (第 900-1237 行)
  - 函数：`_analyze_and_alert`

### 关键变更

#### 1. 移除基于 `passed` 字段的写入限制

**修改前**：
```python
# 第 1130-1135 行
if multi_period_result is None or not multi_period_result.get('passed', False):
    self.logger.debug(...)
    return  # ❌ 验证未通过就不写入数据库
```

**修改后**：
```python
# 第 1129-1138 行
# Z-score 计算失败，跳过
if multi_period_result is None:
    self.logger.debug("Z-score 计算失败，跳过分析")
    return

# 记录验证状态（用于日志和告警判断）
validation_passed = multi_period_result.get('passed', False)
fail_reason = multi_period_result.get('fail_reason', 'unknown') if not validation_passed else None
```

#### 2. 调整健康状态检查逻辑

**修改前**：
```python
# 第 1168-1172 行
if not health_state_passed:
    self.logger.info(...)
    return  # ❌ 健康状态不通过就不写入数据库
```

**修改后**：
```python
# 第 1171 行
# 注意：不再 return，继续执行写入逻辑
```

#### 3. 调整写入和告警逻辑

**修改前**：
```python
# 第 1202-1216 行
# 批量缓冲写入
self.analysis_result_buffer.put_nowait(analysis_record)

# 发送飞书告警（无条件发送）
self._send_alert(symbol, timeframe, multi_period_result)
```

**修改后**：
```python
# 第 1201-1229 行
# 批量缓冲写入（无论验证是否通过，只要有 Z-score 就写入）
try:
    self.analysis_result_buffer.put_nowait(analysis_record)
    self.logger.debug(
        f"分析结果已写入缓冲 | 验证通过: {validation_passed} | 健康状态: {health_state_passed}"
    )
except queue.Full:
    # ... 错误处理 ...

# 仅在所有验证通过时发送飞书告警
if validation_passed and health_state_passed:
    self._send_alert(symbol, timeframe, multi_period_result)
    self.logger.info(f"✅ 多周期验证通过")
else:
    self.logger.info(
        f"⚠️ 多周期验证未通过（但Z-score已记录） | "
        f"原因: {fail_reason if not validation_passed else health_state_reason}"
    )
```

---

## 验证场景

### 测试覆盖的 6 种场景

| 场景 | Z-score | 验证状态 | 健康状态 | 数据库写入 | 飞书告警 |
|------|---------|----------|----------|------------|----------|
| 1 | ✅ 成功 | ✅ 通过 | ✅ 通过 | ✅ 是 | ✅ 是 |
| 2 | ✅ 成功 | ❌ 协整不足 | ✅ 通过 | ✅ 是 | ❌ 否 |
| 3 | ✅ 成功 | ❌ 符号不一致 | ✅ 通过 | ✅ 是 | ❌ 否 |
| 4 | ✅ 成功 | ❌ 阈值不足 | ✅ 通过 | ✅ 是 | ❌ 否 |
| 5 | ✅ 成功 | ✅ 通过 | ❌ 不通过 | ✅ 是 | ❌ 否 |
| 6 | ❌ 失败 | - | - | ❌ 否 | ❌ 否 |

### 测试脚本
运行以下命令验证逻辑：
```bash
python test_zscore_write_logic.py
```

### SQL 验证查询
使用 `verify_zscore_data.sql` 中的查询来验证数据库中的数据：
```bash
psql -h localhost -U postgres -d hyperliquid_trading -f verify_zscore_data.sql
```

---

## 关键观察

### 数据库写入行为
- ✅ **场景 1**：所有验证通过 → 写入数据库 + 发送告警
- ✅ **场景 2-5**：Z-score 有效但验证未完全通过 → 写入数据库但不告警
- ❌ **场景 6**：Z-score 计算失败 → 既不写入也不告警

### 数据价值
即使验证未通过，Z-score 数据仍然有价值：
- 可用于历史分析和回测
- 帮助理解市场行为模式
- 支持策略优化和参数调整

### 告警控制
飞书告警只在以下条件同时满足时发送：
1. `validation_passed = True`（协整、符号、阈值检查通过）
2. `health_state_passed = True`（健康状态检查通过）

---

## 数据库表结构

当前 `analysis_results` 表已经包含了所有必要字段，无需修改：

```sql
CREATE TABLE analysis_results (
    id SERIAL PRIMARY KEY,
    kline_time TIMESTAMP,
    analysis_time TIMESTAMP,
    symbol VARCHAR(50),
    base_symbol VARCHAR(50),

    -- Z-score 值（核心数据）
    zscore_5m NUMERIC,
    zscore_1h NUMERIC,
    zscore_4h NUMERIC,

    -- 验证状态
    cointegration_passed BOOLEAN,
    is_anomaly BOOLEAN,

    -- 交易信息
    trading_direction VARCHAR(10),
    signal_strength VARCHAR(20),

    -- 相关系数
    corr_5m_7d NUMERIC,
    corr_1h_30d NUMERIC,
    corr_4h_60d NUMERIC,

    -- 其他字段...
);
```

### 查询示例

#### 查询所有分析结果（包括验证未通过的）
```sql
SELECT
    analysis_time,
    symbol,
    zscore_4h,
    cointegration_passed,
    is_anomaly,
    trading_direction
FROM analysis_results
WHERE symbol = 'PURR/USDC:USDC'
ORDER BY analysis_time DESC
LIMIT 100;
```

#### 统计验证通过和未通过的比例
```sql
SELECT
    cointegration_passed,
    COUNT(*) as count,
    AVG(ABS(zscore_4h)) as avg_abs_zscore
FROM analysis_results
WHERE symbol = 'PURR/USDC:USDC'
  AND analysis_time >= NOW() - INTERVAL '7 days'
GROUP BY cointegration_passed;
```

---

## 风险评估

### 低风险 ✅
- 数据库写入量增加，但在可控范围内
- 现有数据库表结构无需修改
- 回测脚本逻辑无需修改（已经符合新逻辑）

### 需要注意 ⚠️
- 数据库中会包含更多"未完全验证通过"的记录
- 查询时需要根据 `cointegration_passed` 或其他字段过滤
- 飞书告警逻辑需要确保只在完全验证通过时触发

### 缓解措施
- 通过 `cointegration_passed` 字段区分验证通过和未通过的记录
- 日志中清晰标记验证状态
- 定期监控数据库写入量和告警频率

---

## 部署步骤

### 1. 备份当前代码
```bash
git checkout -b feature/zscore-write-logic-update
git add -A
git commit -m "备份当前代码"
```

### 2. 应用修改
修改已完成，文件已更新。

### 3. 测试
```bash
# 运行单元测试
python test_zscore_write_logic.py

# 如果有其他测试，也应运行
# python -m pytest tests/
```

### 4. 部署
```bash
# 重启实时服务
sudo systemctl restart hyperliquid-realtime-service
# 或根据实际部署方式重启
```

### 5. 验证
```bash
# 监控日志
tail -f /var/log/hyperliquid-realtime-service.log

# 查询数据库
psql -h localhost -U postgres -d hyperliquid_trading -f verify_zscore_data.sql
```

---

## 回滚方案

如果需要回滚到原逻辑：

```bash
git checkout main
git branch -D feature/zscore-write-logic-update
# 重启服务
sudo systemctl restart hyperliquid-realtime-service
```

---

## 监控指标

### 数据库写入
- 每小时写入记录数
- 验证通过率（`cointegration_passed` 字段）
- 平均 Z-score 值

### 告警频率
- 飞书告警发送次数
- 告警触发条件分布

### 系统性能
- 分析延迟（`analysis_delay_seconds` 字段）
- 队列缓冲利用率

---

## 相关文件

- **src/services/realtime_kline_service_base.py** - 实时服务基类（主要修改文件）
- **src/utils/analysis/analysis_core.py** - 多周期分析函数（无需修改）
- **src/scripts/backtest_purr_hype_zscore_4h_hyperliquid.py** - 回测脚本（已符合新逻辑）
- **test_zscore_write_logic.py** - 验证测试脚本
- **verify_zscore_data.sql** - SQL 验证查询

---

## 总结

此次修改实现了以下目标：

✅ **只要 Z-score 计算成功就写入数据库**
✅ **保留验证逻辑用于告警控制**
✅ **向后兼容现有数据库结构**
✅ **清晰的日志记录和监控**
✅ **完整的测试覆盖**

这一修改提升了数据收集的完整性，为后续分析和策略优化提供了更丰富的数据基础。
