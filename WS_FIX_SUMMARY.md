# WebSocket 网络不稳定环境修复实施总结

## 修复完成时间
2026-02-01

## 问题根因
网络不稳定导致的核心问题链:
```
WebSocket 连接管理缺陷
→ 服务器端订阅残留 ("幽灵订阅")
→ 重连后重复订阅
→ 数据洪流
→ 队列满溢出
```

## 实施的修复

### 改进1: 三层清理策略 ✅

**文件**: `src/utils/websocket/enhanced_ws_manager.py:746-868`
**方法**: `_force_cleanup_connection()`

**变更内容**:
1. **第一层: 应用层取消订阅**
   - 在断开前遍历所有活跃订阅
   - 发送 `unsubscribe` 消息到服务器
   - 给服务器 200ms 处理时间

2. **第二层: TCP层强制断开** ⭐ 核心改进!
   - 设置 `SO_LINGER = {1, 0}`
   - 调用 `shutdown(SHUT_RDWR)`
   - 关闭 socket，触发 **TCP RST**
   - **确保服务器端清理所有状态**

3. **第三层: 线程清理**
   - 保留原有的 5 步清理逻辑
   - 停止运行循环、ping 线程、WebSocket 连接
   - 等待线程退出、清除引用

**预期效果**:
- ✅ 消除"幽灵订阅": TCP RST 强制服务器清理
- ✅ 防止重复订阅: 双重保险 (应用层 + TCP层)

---

### 改进2: 保底清理机制 ✅

**文件**: `src/utils/websocket/enhanced_ws_manager.py:600-627`
**方法**: `_on_open()`

**变更内容**:
1. **重连前先尝试取消所有旧订阅**
   - 遍历订阅列表，发送 `unsubscribe` 消息
   - 失败不影响流程 (幂等性保证)
   - 给服务器 200ms 处理时间

2. **清空并重建订阅状态**
   - 清空 `active_subscriptions` 集合
   - 确保"干净"的重连状态

**为什么重要**:
- ✅ 双重保险: 如果 TCP RST 失败，应用层仍会清理
- ✅ 幂等性: 取消不存在的订阅不影响流程
- ✅ 确保每次重连都是干净状态

---

### 改进3: 增强连接检查 ✅

**文件**: `src/utils/websocket/enhanced_ws_manager.py:502-539`
**方法**: `_is_connected()`

**变更内容**:
1. **新增第5项检查: socket 状态**
   ```python
   # 检查 socket 是否有效
   if hasattr(self.ws, 'sock') and self.ws.sock:
       self.ws.sock.fileno()  # socket关闭会抛异常
   ```

2. **增强日志输出**
   - 每项检查失败都有详细日志
   - 帮助快速定位连接问题

**为什么重要**:
- ✅ 早期发现 socket 关闭
- ✅ 避免在无效连接上继续发送
- ✅ 减少无效重试

---

## 代码修改统计

| 文件 | 方法 | 新增行数 | 修改行数 | 总变更 |
|------|------|----------|----------|--------|
| `enhanced_ws_manager.py` | `_force_cleanup_connection()` | ~40 | ~50 | ~90 |
| `enhanced_ws_manager.py` | `_on_open()` | ~15 | ~5 | ~20 |
| `enhanced_ws_manager.py` | `_is_connected()` | ~15 | ~5 | ~20 |
| **总计** | | **~70** | **~60** | **~130** |

---

## 关键改进点对比

### 修复前:
```python
def _force_cleanup_connection(self):
    # 只调用 ws.close()
    if self.ws:
        self.ws.close()
    # 问题: 服务器可能还保留订阅状态
```

### 修复后:
```python
def _force_cleanup_connection(self):
    # 第一层: 应用层取消订阅
    for sub_key in active_subscriptions:
        ws.send({"method": "unsubscribe", ...})

    # 第二层: TCP RST 强制断开 ⭐ 核心!
    ws.sock.setsockopt(SOL_SOCKET, SO_LINGER, struct.pack('ii', 1, 0))
    ws.sock.shutdown(SHUT_RDWR)
    ws.sock.close()

    # 第三层: 线程清理
    ws.close()
    ...
```

---

## 验证方法

### 快速验证:
```bash
python test_ws_fix.py
```

### 手动验证步骤:
1. 启动服务
2. 模拟网络波动 (断网 → 恢复循环)
3. 观察日志:
   - ✅ 有 "第2层: TCP RST 已发送"
   - ✅ 有 "保底清理: 尝试取消 X 个可能存在的旧订阅"
   - ✅ "缓冲队列已满" 警告显著减少
   - ✅ 订阅数量稳定 (无异常增长)

### 日志关键字:
```
✅ 成功标志:
- "第1层: 已发送 X 个取消订阅消息"
- "第2层: TCP RST 已发送"
- "保底清理: 尝试取消 X 个可能存在的旧订阅"
- "连接检查失败: socket 已关闭"

❌ 问题标志:
- "缓冲队列已满" (频率应显著降低)
- 订阅数量异常增长
- 消息到达速率异常峰值
```

---

## 预期效果

修复完成后，在网络不稳定环境下:

| 指标 | 修复前 | 修复后 | 改善幅度 |
|------|--------|--------|----------|
| "缓冲队列已满" 警告 | ~数千次/小时 | <10次/小时 | **99%↓** |
| 重复订阅事件 | 频繁 | 0 | **100%↓** |
| 消息到达速率 | 暴涨 | 平稳 | **稳定** |
| 队列使用率 | 频繁满载 | <70% | **30%↓** |

---

## 技术细节

### TCP RST 原理
```python
# SO_LINGER = {1, 0} 的作用:
# - l_onoff = 1: 启用 linger 选项
# - l_linger = 0: 超时时间为 0
#
# 效果: close() 时不走四次挥手，直接发送 TCP RST
# 结果: 服务器端 TCP 连接立即重置，所有状态清空
```

### 为什么需要保底清理?
```
场景1: TCP RST 成功
  → 服务器清理完成
  → 保底清理的 unsubscribe 失败（订阅已不存在）
  → 无影响，幂等操作

场景2: TCP RST 失败（网络问题）
  → 服务器可能还有旧订阅
  → 保底清理的 unsubscribe 成功
  → 确保清理完成

结论: 双重保险，确保至少有一个生效
```

### socket 检查的必要性
```python
# 问题: WebSocket 对象存在 ≠ socket 有效
ws.keep_running = True  # ✅ 看起来正常
ws_ready_event.is_set()  # ✅ 看起来正常
ws.sock.fileno()  # ❌ 抛异常! socket 已关闭

# 新增检查捕获这种"假活"状态
```

---

## 风险评估

| 风险 | 级别 | 降级方案 |
|------|------|----------|
| TCP RST 过于激进 | 低 | 保留原有 `ws.close()` 作为后备 |
| 保底清理延迟 | 低 | 200ms 延迟可调整为 100ms |
| socket.fileno() 兼容性 | 极低 | websocket-client 标准实现 |

---

## 后续监控建议

1. **日志监控**:
   - 监控 "第2层: TCP RST 已发送" 频率
   - 监控 "保底清理" 执行情况
   - 监控 "缓冲队列已满" 警告频率

2. **性能监控**:
   - 队列使用率 (<70%)
   - 订阅数量稳定性
   - 消息到达速率平稳性

3. **告警阈值**:
   - "缓冲队列已满" >10次/小时 → 告警
   - 订阅数量异常增长 >20% → 告警
   - 重连失败 >5次连续 → 告警

---

## 相关文件

- **修改文件**: `src/utils/websocket/enhanced_ws_manager.py`
- **测试脚本**: `test_ws_fix.py`
- **修复计划**: (原计划文档)
- **本总结**: `WS_FIX_SUMMARY.md`

---

## 修复人员
Claude Code (Sonnet 4.5)

## 审核状态
待测试验证
