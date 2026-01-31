# Akash 容器资源监控指南

## 📊 监控脚本功能

### 监控指标

#### 1. CPU 监控
- CPU 使用率
- 系统负载（1分钟、5分钟、15分钟）
- 容器 CPU 配额限制

#### 2. 内存监控
- 总内存使用量和百分比
- 应用内存（anon）
- 文件缓存（file）
- 内核内存（kernel）
- 容器内存限制（从 cgroup v2 读取）

#### 3. 磁盘监控 ⭐️ **新增**
- **挂载点使用率**：
  - `/`（根目录）
  - `/mnt/data`（持久化存储，如果存在）
  - `/var/lib/postgresql`（数据库目录，如果存在）
  - `/tmp`（临时文件）

- **磁盘 I/O 统计**：
  - 累计读取量（MB）和次数
  - 累计写入量（MB）和次数

- **应用目录占用**：
  - `logs/` 目录大小
  - `database/` 目录大小
  - 应用根目录大小

- **告警阈值**：
  - 🟡 黄色警告：使用率 > 70%
  - 🔴 红色告警：使用率 > 85%

#### 4. 网络监控
- 接收/发送流量（MB）
- 接收/发送数据包数量
- 网络错误统计

#### 5. 进程监控
- Python 进程列表
- 每个进程的内存使用
- 线程数量
- 命令行参数

## 🚀 使用方法

### 基本用法

```bash
# 在容器内运行
cd /root/hyperliquid-pair-coins-realtime-analyze
python3 monitor_resources.py
```

### 高级选项

```bash
# 指定刷新间隔（秒）
python3 monitor_resources.py -i 10

# 简化模式（隐藏详细信息）
python3 monitor_resources.py -s

# 组合使用
python3 monitor_resources.py -i 3 -s
```

### 参数说明

| 参数 | 简写 | 说明 | 默认值 |
|------|------|------|--------|
| `--interval` | `-i` | 监控刷新间隔（秒） | 5 |
| `--simple` | `-s` | 简化模式，隐藏详细信息 | False |
| `--help` | `-h` | 显示帮助信息 | - |

## 📈 监控输出示例

```
================================================================================
  Hyperliquid 数据分析应用 - Akash 容器资源监控
================================================================================

容器资源限制: CPU=1.0核, 内存=1.00GB
监控间隔: 5秒
详细模式: 开启

================================================================================
  监控时间: 2026-01-31 22:45:30 (第 1 次刷新)
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
```

## 🎨 颜色说明

- 🟢 **绿色**：使用率正常（< 60%）
- 🟡 **黄色**：使用率较高（60-85%）
- 🔴 **红色**：使用率告警（> 85%）

## ⚠️ 告警阈值

### CPU
- 黄色警告：> 60%
- 红色告警：> 80%

### 内存
- 黄色警告：> 70%
- 红色告警：> 85%

### 磁盘
- 黄色警告：> 70%
- 红色告警：> 85%

## 🔧 部署到容器

### 方法1：通过 SSH 上传

```bash
# 在本地执行
scp monitor_resources.py root@<akash-container>:/root/hyperliquid-pair-coins-realtime-analyze/

# SSH 进入容器
ssh root@<akash-container>

# 运行监控
cd /root/hyperliquid-pair-coins-realtime-analyze
python3 monitor_resources.py
```

### 方法2：集成到镜像

在 `Dockerfile` 中添加：

```dockerfile
# 复制监控脚本
COPY monitor_resources.py /usr/local/bin/monitor_resources.py
RUN chmod +x /usr/local/bin/monitor_resources.py

# 可选：添加到 PATH
RUN ln -s /usr/local/bin/monitor_resources.py /usr/local/bin/monitor
```

然后在容器内直接运行：

```bash
monitor
# 或
monitor_resources.py
```

### 方法3：在容器内创建

```bash
# SSH 进入容器后
cd /root/hyperliquid-pair-coins-realtime-analyze

# 下载脚本（如果有网络）
curl -O https://raw.githubusercontent.com/your-repo/monitor_resources.py

# 或者直接复制粘贴创建（见下方命令）
```

## 📝 快速部署命令

在容器内执行以下命令创建监控脚本：

```bash
# 创建监控脚本
cat > /tmp/monitor_resources.py << 'HEREDOC'
# 这里粘贴完整的 monitor_resources.py 内容
HEREDOC

# 设置执行权限
chmod +x /tmp/monitor_resources.py

# 运行
python3 /tmp/monitor_resources.py
```

## 🔄 后台运行

### 使用 screen

```bash
# 创建 screen 会话
screen -S monitor

# 运行监控
python3 monitor_resources.py

# 分离会话：Ctrl+A, D
# 重新连接：screen -r monitor
```

### 使用 tmux

```bash
# 创建 tmux 会话
tmux new -s monitor

# 运行监控
python3 monitor_resources.py

# 分离会话：Ctrl+B, D
# 重新连接：tmux attach -t monitor
```

### 使用 nohup

```bash
# 后台运行并输出到文件
nohup python3 monitor_resources.py > monitor.log 2>&1 &

# 查看日志
tail -f monitor.log
```

## 📊 集成到应用

### 添加到项目依赖

在 `pyproject.toml` 中添加：

```toml
[project.scripts]
monitor = "monitor_resources:main"
```

### 在代码中调用

```python
from monitor_resources import get_resource_limits, get_memory_usage, get_disk_usage

# 获取资源信息
cpu_limit, mem_limit = get_resource_limits()
memory = get_memory_usage()
disks = get_disk_usage()

# 使用资源信息
if memory['percent'] > 85:
    logger.warning(f"内存使用率过高: {memory['percent']:.1f}%")

for disk in disks:
    if disk['percent'] > 85:
        logger.warning(f"磁盘 {disk['mount']} 使用率过高: {disk['percent']:.1f}%")
```

## 🚨 监控最佳实践

1. **定期检查**：至少每天查看一次资源使用趋势
2. **设置告警**：当资源使用超过阈值时发送飞书通知
3. **日志轮转**：定期清理应用日志，防止磁盘占满
4. **资源优化**：根据监控数据调整资源配额
5. **数据备份**：定期备份重要数据，特别是数据库

## 🔗 相关资源

- [Akash Network 文档](https://docs.akash.network/)
- [cgroup v2 文档](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)
- [psutil 文档](https://psutil.readthedocs.io/)

## 📞 支持

如有问题，请查看：
- 项目 README.md
- Akash Network Discord
- GitHub Issues
