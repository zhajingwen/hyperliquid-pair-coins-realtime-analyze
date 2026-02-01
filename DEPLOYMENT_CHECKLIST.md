# Z-score 写入逻辑修改 - 部署检查清单

## 📋 部署前检查

### ✅ 代码修改
- [x] 修改 `src/services/realtime_kline_service_base.py`
- [x] 移除基于 `passed` 字段的写入限制
- [x] 调整健康状态检查逻辑
- [x] 更新写入和告警逻辑
- [x] 语法检查通过

### ✅ 测试验证
- [x] 创建测试脚本 `test_zscore_write_logic.py`
- [x] 运行测试脚本，所有场景通过
- [x] 创建 SQL 验证脚本 `verify_zscore_data.sql`

### ✅ 文档更新
- [x] 创建修改总结文档 `ZSCORE_WRITE_LOGIC_CHANGES.md`
- [x] 创建部署检查清单 `DEPLOYMENT_CHECKLIST.md`

---

## 🚀 部署步骤

### 1. 备份当前代码
```bash
# 创建备份分支
git checkout -b backup/before-zscore-logic-update

# 提交当前状态
git add -A
git commit -m "备份：Z-score 写入逻辑修改前的代码"

# 创建新特性分支
git checkout -b feature/zscore-write-logic-update
```

### 2. 提交修改
```bash
# 添加修改的文件
git add src/services/realtime_kline_service_base.py
git add test_zscore_write_logic.py
git add verify_zscore_data.sql
git add ZSCORE_WRITE_LOGIC_CHANGES.md
git add DEPLOYMENT_CHECKLIST.md

# 提交修改
git commit -m "修改 Z-score 写入逻辑：只要计算成功就写入数据库

- 移除基于 passed 字段的写入限制
- 调整健康状态检查，不影响数据库写入
- 仅在完全验证通过时发送飞书告警
- 添加测试脚本和 SQL 验证查询
- 更新文档和检查清单"
```

### 3. 运行测试
```bash
# 运行单元测试
python test_zscore_write_logic.py

# 如果有其他测试套件，也应运行
# python -m pytest tests/
```

### 4. 部署到生产环境
```bash
# 停止实时服务（根据实际部署方式调整）
sudo systemctl stop hyperliquid-realtime-service
# 或
# supervisorctl stop hyperliquid-realtime-service

# 拉取最新代码
git pull origin feature/zscore-write-logic-update

# 启动实时服务
sudo systemctl start hyperliquid-realtime-service
# 或
# supervisorctl start hyperliquid-realtime-service
```

---

## 🔍 部署后验证

### 1. 检查服务状态
```bash
# 检查服务是否正常运行
sudo systemctl status hyperliquid-realtime-service

# 查看最新日志
tail -f /var/log/hyperliquid-realtime-service.log
# 或
# journalctl -u hyperliquid-realtime-service -f
```

### 2. 监控日志关键信息

观察以下日志消息：

#### 成功写入（验证通过）
```
✅ 多周期验证通过: PURR/USDC:USDC @ 4h | 2.35秒
```

#### 成功写入（验证未通过）
```
⚠️ 多周期验证未通过（但Z-score已记录）: PURR/USDC:USDC @ 4h |
原因: cointegration_insufficient | 验证: False | 健康: True | 2.15秒
```

#### Z-score 计算失败（不写入）
```
Z-score 计算失败，跳过分析: PURR/USDC:USDC @ 4h
```

### 3. 验证数据库写入

```bash
# 连接数据库
psql -h localhost -U postgres -d hyperliquid_trading

# 运行验证查询
\i verify_zscore_data.sql
```

**预期结果**：
- 应该看到更多的分析记录（包括验证未通过的）
- `cointegration_passed` 字段应该有 `true` 和 `false` 两种值
- 所有记录都应该有有效的 Z-score 值

### 4. 验证飞书告警

检查飞书群消息：
- 只有完全验证通过的记录才会发送告警
- 告警频率可能会降低（因为现在有更严格的告警条件）

### 5. 性能监控

```sql
-- 查询最近 1 小时的分析记录数
SELECT COUNT(*) as record_count
FROM analysis_results
WHERE symbol = 'PURR/USDC:USDC'
  AND analysis_time >= NOW() - INTERVAL '1 hour';

-- 查询验证通过率
SELECT
    SUM(CASE WHEN cointegration_passed THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as pass_rate
FROM analysis_results
WHERE symbol = 'PURR/USDC:USDC'
  AND analysis_time >= NOW() - INTERVAL '1 hour';
```

---

## ⚠️ 潜在问题和解决方案

### 问题 1: 数据库写入量大幅增加

**现象**：
- 分析记录数量比之前多很多
- 数据库存储空间增长较快

**解决方案**：
- 监控数据库存储使用情况
- 如果必要，增加数据清理策略
- 考虑只保留最近 30 天的数据

```sql
-- 清理 30 天前的数据
DELETE FROM analysis_results
WHERE analysis_time < NOW() - INTERVAL '30 days';
```

### 问题 2: 飞书告警频率降低

**现象**：
- 飞书告警消息比之前少
- 可能错过一些重要信号

**解决方案**：
- 这是预期行为（告警条件更严格）
- 可以通过数据库查询监控所有分析记录
- 考虑添加定期报告功能

### 问题 3: 服务启动失败

**现象**：
- 服务无法启动
- 日志中出现语法错误或导入错误

**解决方案**：
```bash
# 回滚到上一个版本
git checkout backup/before-zscore-logic-update

# 重启服务
sudo systemctl restart hyperliquid-realtime-service

# 检查错误日志
tail -n 100 /var/log/hyperliquid-realtime-service.log
```

---

## 📊 监控指标

### 关键指标

1. **数据库写入率**
   - 目标：每小时 > 0 条记录
   - 警告：连续 2 小时无记录

2. **验证通过率**
   - 目标：20-40%（取决于市场条件）
   - 警告：< 5% 或 > 80%

3. **飞书告警频率**
   - 目标：每天 1-10 次（取决于市场波动）
   - 警告：连续 24 小时无告警

4. **服务性能**
   - 目标：分析延迟 < 5 秒
   - 警告：延迟 > 15 秒

### 监控 SQL 查询

```sql
-- 每小时分析记录数（最近 24 小时）
SELECT
    DATE_TRUNC('hour', analysis_time) as hour,
    COUNT(*) as count,
    SUM(CASE WHEN cointegration_passed THEN 1 ELSE 0 END) as passed,
    ROUND(AVG(analysis_delay_seconds), 2) as avg_delay_sec
FROM analysis_results
WHERE symbol = 'PURR/USDC:USDC'
  AND analysis_time >= NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', analysis_time)
ORDER BY hour DESC;
```

---

## 🔄 回滚计划

如果发现严重问题需要回滚：

### 回滚步骤

```bash
# 1. 停止服务
sudo systemctl stop hyperliquid-realtime-service

# 2. 切换到备份分支
git checkout backup/before-zscore-logic-update

# 3. 启动服务
sudo systemctl start hyperliquid-realtime-service

# 4. 验证服务状态
sudo systemctl status hyperliquid-realtime-service

# 5. 检查日志
tail -f /var/log/hyperliquid-realtime-service.log
```

### 回滚后验证

- 确认服务正常运行
- 确认告警恢复正常
- 记录回滚原因和时间

---

## ✅ 完成标记

部署完成后，请在以下项目打勾：

- [ ] 代码已部署到生产环境
- [ ] 服务正常运行
- [ ] 日志输出符合预期
- [ ] 数据库写入验证通过
- [ ] 飞书告警功能正常
- [ ] 性能指标正常
- [ ] 团队已通知修改内容

---

## 📝 备注

**修改日期**: 2026-02-01
**修改人员**: Claude Code
**影响范围**: 实时分析服务的数据写入逻辑
**风险评估**: 低风险（向后兼容，数据库结构不变）

**下一步计划**:
- 监控 7 天的数据写入情况
- 评估验证通过率和告警频率
- 根据实际运行情况优化阈值和验证条件
