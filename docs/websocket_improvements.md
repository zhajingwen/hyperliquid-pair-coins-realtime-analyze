# WebSocket 连接改进方案

## 问题分析

### 根本原因
间歇性网络故障导致 DNS 解析失败：
```
socket.gaierror: [Errno 8] nodename nor servname provided, or not known
```

### 现有问题
1. **缺少网络检测**：在网络不可用时盲目重试
2. **错误类型未区分**：DNS 错误和其他错误使用相同策略
3. **重试策略不合理**：DNS 失败时短间隔重试无意义

---

## 改进方案

### 1. 集成网络检测器

在 `enhanced_ws_manager.py` 中添加网络检测：

```python
# 在文件顶部添加导入
from src.utils.websocket.network_checker import (
    check_network_connectivity,
    wait_for_network,
    is_dns_error
)

# 修改 _reconnect 方法
def _reconnect(self):
    """重连逻辑（指数退避策略 + 网络检测 + 告警机制）"""
    self._update_state(ConnectionState.RECONNECTING)

    while self.reconnection_manager.should_retry() and not self.stop_event.is_set():
        self.reconnection_manager.record_attempt()
        delay = self.reconnection_manager.get_delay()
        retry_count = self.reconnection_manager.retry_count
        max_retries = self.reconnection_manager.max_retries

        logger.info(
            f"⏳ 准备重连 (第{retry_count}次"
            f"{f'/{max_retries}' if max_retries else ''}) | "
            f"延迟: {delay:.2f}秒"
        )

        self.stop_event.wait(delay)

        if self.stop_event.is_set():
            break

        # ✅ 新增：检测网络连通性
        is_available, reason = check_network_connectivity()
        if not is_available:
            logger.warning(f"🌐 网络不可用: {reason}，等待网络恢复...")

            # 等待网络恢复（最多 60 秒）
            if not wait_for_network(max_wait=60, check_interval=10):
                logger.error("❌ 网络长时间不可用，跳过本次重连")
                continue

        try:
            # 强制清理旧连接
            if self.ws:
                self._force_cleanup_connection()

            # 重连
            self._connect()
            logger.info("✅ WebSocket重连成功")
            return

        except Exception as e:
            logger.error(f"重连失败 (第{retry_count}次): {e}")

            # ✅ 新增：区分 DNS 错误
            if is_dns_error(e):
                logger.error("❌ DNS 解析失败，可能是网络问题，将增加重连间隔")
                # 强制等待更长时间
                self.stop_event.wait(30)

            # 发送告警（原有逻辑）
            if retry_count == self.alert_threshold and self.alert_callback:
                try:
                    self.alert_callback(
                        "⚠️ WebSocket连续重连失败告警",
                        f"WebSocket已连续重连失败 {retry_count} 次\n"
                        f"最大重试次数: {max_retries or '无限'}\n"
                        f"最近错误: {e}\n"
                        f"{'⚠️ 检测到 DNS 错误，可能是网络问题' if is_dns_error(e) else ''}\n"
                        f"服务仍在尝试重连中，请关注..."
                    )
                except Exception as alert_err:
                    logger.error(f"发送重连告警失败: {alert_err}")

    # 重试次数耗尽（原有逻辑保持不变）
    ...
```

### 2. 改进错误处理

```python
def _on_error(self, ws, error):
    """WebSocket 错误回调（改进版）"""
    # 区分错误类型
    if is_dns_error(error):
        logger.error(f"🌐 WebSocket DNS 错误: {error}")
        logger.warning("可能的原因：网络断开、DNS 服务器故障、域名配置错误")
    elif "timeout" in str(error).lower():
        logger.error(f"⏱️ WebSocket 超时错误: {error}")
    elif "connection refused" in str(error).lower():
        logger.error(f"🚫 WebSocket 连接被拒绝: {error}")
    else:
        logger.error(f"❌ WebSocket 错误: {error}")
```

### 3. 启动时检测网络

```python
def start(self):
    """启动 WebSocket 服务（改进版）"""
    if self.state not in [ConnectionState.DISCONNECTED, ConnectionState.FAILED]:
        logger.warning(f"WebSocket服务已在运行中 (状态: {self.state.value})")
        return

    # ✅ 新增：启动前检测网络
    logger.info("🌐 检测网络连通性...")
    is_available, reason = check_network_connectivity()
    if not is_available:
        logger.error(f"❌ 网络不可用: {reason}")
        logger.info("⏳ 等待网络恢复（最多 120 秒）...")

        if not wait_for_network(max_wait=120, check_interval=10):
            raise RuntimeError("网络不可用，无法启动 WebSocket 服务")

    logger.info(f"✅ 网络连通性检测通过: {reason}")

    # 原有启动逻辑
    logger.info("启动 WebSocket 服务...")
    self.stop_event.clear()
    try:
        self._connect()
        self._start_ping_loop()
        logger.info("✅ WebSocket 服务已启动")
    except Exception as e:
        logger.error(f"❌ WebSocket 启动失败: {e}", exc_info=True)
        self._update_state(ConnectionState.FAILED, e)
        raise
```

---

## 使用建议

### 场景 1：开发/测试环境
- **推荐**：只添加 DNS 错误检测和区分
- **原因**：网络通常稳定，过多检测影响开发效率

### 场景 2：生产环境
- **推荐**：完整集成所有改进
- **原因**：需要处理各种网络异常情况

### 场景 3：不稳定网络（移动设备、云服务器）
- **推荐**：完整集成 + 增加重试次数 + 延长等待时间
- **原因**：网络波动频繁，需要更强的容错能力

---

## 测试网络检测器

```bash
# 测试网络连通性检测
uv run python -m src.utils.websocket.network_checker

# 模拟 DNS 失败（断开网络后测试）
# 1. 关闭 WiFi/断开网络
# 2. 运行测试
# 3. 观察等待网络恢复的行为
```

---

## 配置参数建议

```python
# config.py 中添加网络检测配置
WS_NETWORK_CHECK_ENABLED = True  # 是否启用网络检测
WS_NETWORK_CHECK_TIMEOUT = 3     # 网络检测超时（秒）
WS_NETWORK_WAIT_MAX = 60         # 等待网络恢复最大时间（秒）
WS_NETWORK_WAIT_INTERVAL = 10    # 网络检测间隔（秒）
WS_DNS_ERROR_EXTRA_DELAY = 30    # DNS 错误额外等待时间（秒）
```

---

## 预期效果

### 改进前
```
16:28:06 - DNS 解析失败
16:28:06 - 立即重连（失败）
16:28:08 - 2秒后重连（失败）
16:28:12 - 4秒后重连（失败）
...频繁重试，浪费资源...
```

### 改进后
```
16:28:06 - DNS 解析失败
16:28:06 - 🌐 检测到网络不可用
16:28:06 - ⏳ 等待网络恢复（最多 60 秒）
16:28:16 - 🌐 检测网络（第 1 次）: 不可用
16:28:26 - 🌐 检测网络（第 2 次）: 不可用
16:28:36 - ✅ 网络已恢复
16:28:36 - 开始重连
16:28:37 - ✅ 重连成功
```

---

## 监控指标

添加以下监控指标以跟踪网络问题：

```python
self.stats = {
    'network_checks': 0,           # 网络检测次数
    'network_failures': 0,         # 网络失败次数
    'dns_errors': 0,               # DNS 错误次数
    'network_wait_time': 0,        # 等待网络恢复总时长（秒）
    'network_recovery_count': 0,   # 网络恢复次数
}
```

在统计报告中展示：
```
📊 网络统计:
   - 网络检测: 15 次
   - 网络失败: 3 次 (20%)
   - DNS 错误: 2 次
   - 等待网络恢复: 180 秒
   - 网络恢复: 3 次
```
