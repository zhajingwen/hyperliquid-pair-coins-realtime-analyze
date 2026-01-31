# Akash 容器资源监控

## 🚀 快速开始

### 在容器中运行监控

```bash
# 进入项目目录并运行
cd /root/hyperliquid-pair-coins-realtime-analyze
python3 monitor_resources.py
```

就这么简单！无需任何配置。

## 📊 监控内容

- 🔥 **CPU**：使用率、负载、核心限制
- 💾 **内存**：使用量、详细分类、告警
- 💿 **磁盘**：多挂载点、I/O 统计、目录占用
- 🌐 **网络**：流量、数据包、错误统计
- 🐍 **进程**：Python 进程、内存、线程

## ⚙️ 使用选项

```bash
# 默认（5秒刷新）
python3 monitor_resources.py

# 自定义刷新间隔（10秒）
python3 monitor_resources.py -i 10

# 快速刷新（3秒）
python3 monitor_resources.py -i 3

# 简化模式（隐藏详细信息）
python3 monitor_resources.py -s

# 组合使用
python3 monitor_resources.py -i 10 -s

# 查看帮助
python3 monitor_resources.py -h
```

## 🔧 一键部署

在 Akash 容器中复制粘贴：

```bash
cd /root/hyperliquid-pair-coins-realtime-analyze && \
git pull && \
python3 monitor_resources.py
```

## 🔄 后台运行

### 使用 screen

```bash
screen -S monitor
cd /root/hyperliquid-pair-coins-realtime-analyze
python3 monitor_resources.py
# 按 Ctrl+A, D 分离
# 重新连接: screen -r monitor
```

### 使用 tmux

```bash
tmux new -s monitor
cd /root/hyperliquid-pair-coins-realtime-analyze
python3 monitor_resources.py
# 按 Ctrl+B, D 分离
# 重新连接: tmux attach -t monitor
```

### 使用 nohup

```bash
cd /root/hyperliquid-pair-coins-realtime-analyze
nohup python3 monitor_resources.py > monitor.log 2>&1 &

# 查看日志
tail -f monitor.log
```

## 📈 输出示例

```
================================================================================
  监控时间: 2026-01-31 23:00:00 (第 1 次刷新)
================================================================================

🔥 CPU:
  限制: 1.0 核心
  使用率: 15.3%
  负载: 1分钟=2.30, 5分钟=2.70, 15分钟=2.94

💾 内存:
  使用: 0.48GB / 1.00GB (48.5%)
  详情:
    - 应用内存: 0.40GB
    - 文件缓存: 0.06GB
    - 内核内存: 0.02GB

💿 磁盘使用:
  /:
    使用: 162.00GB / 1500.00GB (10.8%)
    可用: 1338.00GB

📊 磁盘 I/O:
  累计读取: 1234.5MB (12,345 次)
  累计写入: 567.8MB (5,678 次)

📁 应用目录占用:
  logs: 45.23MB
  database: 12.34MB
  app_root: 123.45MB

🌐 网络:
  接收: 234.5MB (123,456 包)
  发送: 89.1MB (45,678 包)

🐍 Python 进程 (2):
  PID    20:   258.0MB,  15 线程
           uv run python3 src/main.py
  PID   199:   265.0MB,  12 线程
           uv run python3 src/worker.py

  总计: 523.0MB, 27 线程

================================================================================
按 Ctrl+C 退出监控 | 下次刷新: 5秒后

────────────────────────────────────────────────────────────────────────────────

================================================================================
  监控时间: 2026-01-31 23:00:05 (第 2 次刷新)
================================================================================
...
```

## 🎨 颜色说明

- 🟢 **绿色**：使用率正常（< 60%）
- 🟡 **黄色**：使用率较高（60-85%）
- 🔴 **红色**：使用率告警（> 85%）

## 📦 集成到代码

```python
from monitor_resources import get_disk_usage, get_memory_usage

# 获取资源信息
memory = get_memory_usage()
disks = get_disk_usage()

# 使用监控数据
if memory['percent'] > 85:
    logger.warning(f"内存使用率过高: {memory['percent']:.1f}%")

for disk in disks:
    if disk['percent'] > 85:
        logger.warning(f"磁盘 {disk['mount']} 使用率过高: {disk['percent']:.1f}%")
```

## 🎯 最佳实践

1. **定期监控**：使用 cron 或 systemd timer 定期记录资源使用
2. **日志轮转**：配置日志轮转防止磁盘占满
3. **告警集成**：将监控数据发送到飞书或其他告警系统
4. **资源优化**：根据监控数据调整 Akash 部署配置
