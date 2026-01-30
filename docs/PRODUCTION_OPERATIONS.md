# 生产环境运维指南 (Production Operations Guide)

## 📋 文档概述

本文档基于实际生产环境运维经验编写，提供实时K线分析系统的监控、告警、故障排查和性能优化指南。

**适用场景**:
- 系统部署后的日常监控
- 故障诊断和快速恢复
- 性能瓶颈分析和优化
- 数据质量保障

**目标读者**:
- 系统运维人员
- SRE工程师
- 开发人员

---

## 🔍 监控和告警

### 实时监控命令

#### 1. 服务状态检查

```bash
# 检查服务进程
ps aux | grep realtime_kline_service

# 预期输出示例:
# user  47276  25.3  2.1  realtime_kline_service_hype.py

# 检查进程运行时长
ps -p <PID> -o etime=

# 检查服务端口（如果有）
netstat -tulpn | grep <PORT>
```

#### 2. 实时日志监控

```bash
# 基础日志监控
tail -f logs/service.log

# 过滤关键错误
tail -f logs/service.log | grep -i "error\|exception\|failed"

# 监控WebSocket状态
tail -f logs/service.log | grep -i "websocket\|reconnect\|假活"

# 监控数据库死锁
tail -f logs/service.log | grep -i "deadlock\|死锁"

# 监控分析延迟
tail -f logs/service.log | grep "分析完成\|延迟"
```

#### 3. 专用监控脚本

```bash
# 死锁监控（HYPE版本）
./monitor_deadlock_hype.sh

# 脚本功能:
# - 实时统计死锁频率
# - 计算重试成功率
# - 告警阈值检查

# 数据完整性验证
python validate_data_consistency.py --hours 1

# 持续监控（每分钟检查）
python monitor.py
```

#### 4. 数据库监控

```bash
# 连接数据库
docker exec -it crypto_timescaledb psql -U postgres -d crypto_data

# 检查最新K线数据
SELECT symbol, timeframe, MAX(time) as latest_time, COUNT(*) as count
FROM klines
WHERE time >= NOW() - INTERVAL '1 hour'
GROUP BY symbol, timeframe
ORDER BY symbol, timeframe;

# 检查分析结果延迟
SELECT 
    symbol,
    timeframe,
    AVG(analysis_delay_seconds) as avg_delay,
    MAX(analysis_delay_seconds) as max_delay,
    COUNT(*) as count
FROM analysis_results
WHERE analysis_time >= NOW() - INTERVAL '1 hour'
GROUP BY symbol, timeframe
ORDER BY avg_delay DESC;

# 检查死锁频率（从日志表，如果有）
-- 需要自定义实现日志表
```

### 告警指标和阈值

| 指标 | 告警阈值 | 级别 | 处理 |
|------|---------|------|------|
| **服务状态** | 进程不存在 | 致命 | 立即重启 |
| **死锁频率** | >5次/小时 | 警告 | 检查并发配置 |
| **WebSocket重连** | >3次/小时 | 警告 | 检查网络稳定性 |
| **分析延迟P95** | >10秒 | 警告 | 检查数据库性能 |
| **分析延迟P99** | >30秒 | 错误 | 优化查询或扩容 |
| **数据覆盖率** | <90% | 警告 | 检查数据采集 |
| **K线缺失率** | >5% | 错误 | 运行数据补全 |
| **CPU占用** | >50% | 警告 | 检查系统负载 |
| **内存占用** | >512MB | 警告 | 检查内存泄漏 |
| **队列积压** | >1000 | 警告 | 增加工作线程 |

### 飞书告警集成

**配置告警**:
```bash
# 环境变量配置
export LARKBOT_ID="your-bot-id"
export LARK_WEBHOOK_URL="your-webhook-url"

# 测试告警
python -c "
from utils.lark_bot import sender_colourful
sender_colourful(
    '测试告警',
    '这是一条测试消息',
    webhook_url='$LARK_WEBHOOK_URL'
)
"
```

**告警场景**:
1. 服务启动/停止
2. WebSocket连接/断开
3. 数据库连接失败
4. 异常信号检测（Z-score超阈值）
5. 数据质量异常
6. 性能指标超阈值

---

## 🔧 故障排查清单

### WebSocket连接问题

**症状**: WebSocket频繁断开或无法连接

**排查步骤**:

1. **检查网络连接**
```bash
# 测试API可达性
ping api.hyperliquid.xyz

# 测试WebSocket端口
telnet api.hyperliquid.xyz 443
```

2. **查看重连日志**
```bash
grep "reconnect\|重连" logs/service.log | tail -20

# 分析重连频率
grep "重连成功" logs/service.log | wc -l
```

3. **验证订阅配置**
```bash
# 检查币种列表
grep "订阅数量" logs/service.log

# 预期: 600个订阅 (200币种 × 3周期)
```

4. **检查假活状态**
```bash
grep "假活\|无数据" logs/service.log | tail -10

# 如果频繁出现，调整健康检查超时
export WS_TIMEOUT=45  # 增加到45秒
```

5. **重启服务**
```bash
# 停止服务
pkill -f realtime_kline_service_hype

# 启动服务（带环境变量）
LARKBOT_ID=xxx LARK_WEBHOOK_URL=xxx \
nohup python realtime_kline_service_hype.py > logs/service.log 2>&1 &

# 验证启动
tail -f logs/service.log
```

**常见原因**:
- ✅ 网络不稳定或防火墙阻止
- ✅ API服务器维护
- ✅ 订阅数过多（超过服务器限制）
- ✅ 本地资源耗尽（CPU/内存）

---

### 数据库死锁问题

**症状**: 日志中频繁出现 "DeadlockDetected" 错误

**排查步骤**:

1. **查看死锁日志**
```bash
grep -i "deadlock" logs/service.log | tail -20

# 统计死锁频率
grep -i "deadlock" logs/service.log | wc -l
```

2. **检查重试成功率**
```bash
# 成功重试数
grep "重试.*成功" logs/service.log | wc -l

# 重试耗尽数
grep "重试.*耗尽" logs/service.log | wc -l

# 计算成功率（应该 >95%）
```

3. **数据库连接池状态**
```bash
# 如果有监控接口，查询连接池状态
# 检查连接数和等待队列

# 临时方案：增加连接池大小
export TIMESCALEDB_POOL_MAX_SIZE=15  # 从10增加到15
```

4. **调整批量大小**
```bash
# 减小批量写入大小，降低冲突
export ANALYSIS_RESULT_BATCH_SIZE=500  # 从1000减到500
```

**解决方案**:
- ✅ v2.2已实现死锁重试机制（成功率>95%）
- ✅ 如仍频繁发生，考虑：
  - 增加数据库连接池大小
  - 减小批量写入大小
  - 增加重试次数
  - 优化事务隔离级别

**预防措施**:
- 定期监控死锁频率
- 在非高峰期进行批量操作
- 保持数据库统计信息更新（ANALYZE）

---

### 时区偏移问题

**症状**: 数据时间与实际时间相差8小时

**排查步骤**:

1. **验证新数据**
```bash
python verify_new_data.py

# 检查输出中的时区字段
# 应该全部显示 UTC+0
```

2. **检查时区设置**
```sql
-- 连接数据库
docker exec -it crypto_timescaledb psql -U postgres -d crypto_data

-- 检查时区偏移
SELECT 
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE EXTRACT(TIMEZONE FROM analysis_time) != 0) as wrong_tz
FROM analysis_results;

-- wrong_tz 应该为 0
```

3. **历史数据检测**
```bash
python detect_timezone_errors.py

# 输出报告会显示:
# - 总记录数
# - 8小时偏移记录数
# - 负延迟记录数
```

4. **运行迁移（如需要）**
```bash
# 参考时区修复文档
cat TIMEZONE_FIX_SUMMARY.md

# 运行迁移脚本
python run_timezone_migration.py
```

**解决方案**:
- ✅ v2.2已统一使用UTC时区感知
- ✅ 新数据不会出现时区偏移
- ✅ 历史数据需要手动迁移

---

### 数据质量问题

**症状**: 数据覆盖率低或K线缺失

**排查步骤**:

1. **运行完整性检查**
```bash
python validate_data_consistency.py \
    --hours 24 \
    --output report.txt \
    --parallel

# 查看报告
cat report.txt
```

2. **检查覆盖率**
```sql
-- 计算各币种覆盖率
SELECT 
    symbol,
    timeframe,
    COUNT(*) as actual_count,
    (EXTRACT(EPOCH FROM (MAX(time) - MIN(time))) / 
     CASE timeframe 
         WHEN '5m' THEN 300 
         WHEN '1h' THEN 3600 
         WHEN '4h' THEN 14400 
     END) as expected_count,
    ROUND(100.0 * COUNT(*) / 
        (EXTRACT(EPOCH FROM (MAX(time) - MIN(time))) / 
         CASE timeframe 
             WHEN '5m' THEN 300 
             WHEN '1h' THEN 3600 
             WHEN '4h' THEN 14400 
         END), 2) as coverage_rate
FROM klines
WHERE time >= NOW() - INTERVAL '24 hours'
GROUP BY symbol, timeframe
ORDER BY coverage_rate ASC;
```

3. **识别缺失时间段**
```bash
python check_missing.py \
    --symbol "HYPE/USDC:USDC" \
    --timeframe "5m" \
    --hours 24
```

4. **运行数据补全**
```bash
# 使用懒加载数据填充器
python -c "
from utils.kline_data_filler_lazy import KlineDataFillerLazy
from datetime import datetime, timedelta, timezone

filler = KlineDataFillerLazy()
end_time = datetime.now(timezone.utc)
start_time = end_time - timedelta(hours=24)

filler.fill_missing_data(
    symbol='HYPE/USDC:USDC',
    timeframe='5m',
    start_time=start_time,
    end_time=end_time
)
"
```

**常见原因**:
- 服务中断或重启
- WebSocket连接不稳定
- API限流或超时
- 交易所数据缺失

---

### 性能问题

**症状**: CPU高、内存泄漏或分析延迟大

**排查步骤**:

1. **检查资源占用**
```bash
# CPU和内存监控
top -p <PID>

# 详细资源统计
ps -p <PID> -o %cpu,%mem,vsz,rss,etime,cmd

# 预期值:
# CPU: 20-30%
# MEM: <512MB
# VSZ: <1GB
```

2. **分析队列深度**
```bash
grep "队列深度\|queue_size" logs/service.log | tail -20

# 如果持续>1000，说明处理不过来
```

3. **检查数据库性能**
```sql
-- 查看慢查询
SELECT 
    calls,
    mean_exec_time,
    max_exec_time,
    query
FROM pg_stat_statements
WHERE mean_exec_time > 100  -- 超过100ms
ORDER BY mean_exec_time DESC
LIMIT 10;

-- 检查索引使用情况
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan DESC;
```

4. **优化配置**
```bash
# 调整工作线程数（根据CPU核心数）
export ANALYSIS_WORKERS=6  # 从5增加到6

# 调整批量大小（平衡延迟和吞吐）
export DEFAULT_BATCH_SIZE=1500  # 从1000增加到1500

# 调整去重窗口（减少不必要分析）
export DEDUP_WINDOWS='{"5m": 60, "1h": 600, "4h": 1800}'
```

**性能优化建议**: 见下一节

---

## ⚡ 性能优化建议

### 数据库层面

#### 1. 定期维护

```bash
# 每天执行VACUUM
docker exec -it crypto_timescaledb psql -U postgres -d crypto_data -c "VACUUM ANALYZE;"

# 每周执行VACUUM FULL（需要停机）
docker exec -it crypto_timescaledb psql -U postgres -d crypto_data -c "VACUUM FULL;"

# 更新统计信息
docker exec -it crypto_timescaledb psql -U postgres -d crypto_data -c "
ANALYZE klines;
ANALYZE analysis_results;
ANALYZE symbol_metadata;
"
```

#### 2. 监控慢查询

```sql
-- 启用pg_stat_statements扩展（如果未启用）
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- 查看最慢的10个查询
SELECT 
    round(total_exec_time::numeric, 2) as total_time_ms,
    calls,
    round(mean_exec_time::numeric, 2) as avg_time_ms,
    round(max_exec_time::numeric, 2) as max_time_ms,
    substring(query, 1, 100) as query_preview
FROM pg_stat_statements
WHERE query NOT LIKE '%pg_stat_statements%'
ORDER BY mean_exec_time DESC
LIMIT 10;
```

#### 3. 连接池调优

```bash
# 根据实际负载调整
export TIMESCALEDB_POOL_MIN_SIZE=3      # 最小连接数（保持热连接）
export TIMESCALEDB_POOL_MAX_SIZE=12     # 最大连接数（避免资源耗尽）
export TIMESCALEDB_POOL_TIMEOUT=30      # 获取连接超时
export TIMESCALEDB_POOL_MAX_LIFETIME=3600   # 连接最大存活时间
export TIMESCALEDB_POOL_MAX_IDLE=600    # 连接最大空闲时间

# 公式建议:
# MAX_SIZE = (分析工作线程数 + 批量写入线程数 + 预留) × 1.5
# 例如: (5 + 1 + 2) × 1.5 = 12
```

#### 4. TimescaleDB优化

```sql
-- 调整chunk大小（当前7天）
SELECT set_chunk_time_interval('klines', INTERVAL '7 days');

-- 启用自动压缩
ALTER TABLE klines SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,timeframe',
    timescaledb.compress_orderby = 'time DESC'
);

-- 设置压缩策略（7天后压缩）
SELECT add_compression_policy('klines', INTERVAL '7 days');

-- 设置数据保留策略（90天后删除）
SELECT add_retention_policy('klines', INTERVAL '90 days');
```

### 应用层面

#### 1. 分析工作线程数

```bash
# 根据CPU核心数调整
# 推荐公式: CPU核心数 × 1.5 - 2

# 4核CPU
export ANALYSIS_WORKERS=4

# 8核CPU
export ANALYSIS_WORKERS=10

# 12核CPU
export ANALYSIS_WORKERS=16

# 验证线程数
grep "启动.*个分析工作线程" logs/service.log
```

#### 2. 批量写入优化

```bash
# 调整批量大小（平衡延迟和吞吐）
export DEFAULT_BATCH_SIZE=1500           # K线批量写入
export ANALYSIS_RESULT_BATCH_SIZE=800    # 分析结果批量写入

# 调整批量超时
export DEFAULT_BATCH_TIMEOUT=3           # 3秒超时（从5秒降低）
export ANALYSIS_RESULT_BATCH_TIMEOUT=2   # 2秒超时

# 使用COPY方法（性能提升40倍）
export ANALYSIS_USE_COPY_METHOD=true
```

#### 3. 去重窗口调整

```bash
# 差异化去重策略（减少不必要分析）
export DEDUP_WINDOWS='{
    "5m": 60,     # 5分钟周期: 60秒冷却
    "1h": 600,    # 1小时周期: 10分钟冷却（从5分钟增加）
    "4h": 1800    # 4小时周期: 30分钟冷却（从15分钟增加）
}'

# 效果: 减少70-80%重复分析
```

#### 4. 队列深度管理

```bash
# 监控队列深度
export QUEUE_WARNING_THRESHOLD=0.8  # 80%告警
export QUEUE_MONITOR_INTERVAL=60    # 每60秒监控

# 调整队列大小（根据实际需求）
export QUEUE_CONFIG_HYPE='{
    "kline_buffer_size": 15000,      # K线缓冲（从10000增加）
    "analysis_queue_size": 6000      # 分析队列（从5000增加）
}'
```

### 监控指标

**关键性能指标** (KPI):
- 分析延迟 P50: <5秒
- 分析延迟 P95: <10秒
- 分析延迟 P99: <30秒
- CPU占用: 20-30%
- 内存占用: <512MB
- 队列深度: <500
- 数据覆盖率: >95%
- WebSocket稳定性: >99.9%

---

## 📊 常见问题FAQ

### Q1: 如何查看服务运行状态？

```bash
# 方法1: 检查进程
ps aux | grep realtime_kline_service

# 方法2: 查看最新日志
tail -20 logs/service.log

# 方法3: 检查健康报告
grep "健康报告" logs/service.log | tail -1
```

### Q2: 如何重启服务？

```bash
# 停止服务
pkill -f realtime_kline_service_hype

# 等待进程完全退出（5-10秒）
sleep 10

# 启动服务
LARKBOT_ID=xxx LARK_WEBHOOK_URL=xxx \
nohup python realtime_kline_service_hype.py > logs/service_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# 验证启动
tail -f logs/service_*.log
```

### Q3: 数据延迟过大怎么办？

**可能原因**:
1. 数据库查询慢 → 优化索引、增加连接池
2. 分析计算慢 → 增加工作线程数
3. 队列积压 → 调整批量大小、增加工作线程
4. 网络延迟 → 检查网络质量

**排查命令**:
```bash
# 查看延迟分布
grep "延迟.*秒" logs/service.log | tail -50

# 数据库查询性能
# 见上文"性能问题"章节
```

### Q4: 如何补全历史数据？

```bash
# 使用KlineDataFillerLazy
python -c "
from utils.kline_data_filler_lazy import KlineDataFillerLazy
from datetime import datetime, timedelta, timezone

filler = KlineDataFillerLazy()

# 补全最近7天的HYPE数据
filler.fill_missing_data(
    symbol='HYPE/USDC:USDC',
    timeframe='5m',
    start_time=datetime.now(timezone.utc) - timedelta(days=7),
    end_time=datetime.now(timezone.utc)
)
"
```

### Q5: 如何备份和恢复数据？

**备份**:
```bash
# 备份数据库
docker exec crypto_timescaledb pg_dump -U postgres crypto_data > backup_$(date +%Y%m%d).sql

# 备份特定表
docker exec crypto_timescaledb pg_dump -U postgres -t analysis_results crypto_data > analysis_backup.sql

# 压缩备份
gzip backup_$(date +%Y%m%d).sql
```

**恢复**:
```bash
# 解压
gunzip backup_20260129.sql.gz

# 恢复数据库
docker exec -i crypto_timescaledb psql -U postgres crypto_data < backup_20260129.sql

# 恢复特定表
docker exec -i crypto_timescaledb psql -U postgres crypto_data < analysis_backup.sql
```

### Q6: 如何查看系统版本？

```bash
# 查看代码版本
grep "^| 2026" docs/DESIGN_OVERVIEW.md | tail -1

# 查看最后部署时间
ls -lt realtime_kline_service_hype.py

# 查看Git提交
git log --oneline -5
```

---

## 📚 相关文档

### 设计文档
- [DESIGN_OVERVIEW.md](DESIGN_OVERVIEW.md) - 总体设计
- [MODULE2_DATABASE_ACCESS_LAYER.md](MODULE2_DATABASE_ACCESS_LAYER.md) - 数据库访问层
- [MODULE3_REALTIME_DATAFLOW.md](MODULE3_REALTIME_DATAFLOW.md) - 实时分析引擎

### 修复文档
- [DEADLOCK_FIX_HYPE_SUMMARY.md](../DEADLOCK_FIX_HYPE_SUMMARY.md) - 数据库死锁修复
- [TIMEZONE_FIX_SUMMARY.md](../TIMEZONE_FIX_SUMMARY.md) - 时区处理修复
- [BUG_FIX_SUMMARY.md](../BUG_FIX_SUMMARY.md) - 资源管理修复
- [DEPLOYMENT_SUCCESS.md](../DEPLOYMENT_SUCCESS.md) - 部署成功记录

### 运维脚本
- `monitor_deadlock_hype.sh` - 死锁监控
- `validate_data_consistency.py` - 数据完整性验证
- `verify_new_data.py` - 新数据验证
- `check_missing.py` - 缺失数据检测

---

## 📞 技术支持

**问题反馈**: GitHub Issues
**紧急联系**: 飞书告警群
**文档版本**: v2.2
**更新日期**: 2026-01-29

---

**Author**: Claude Code  
**Maintainer**: SRE Team
