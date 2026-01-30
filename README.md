# Hyperliquid 配对交易信号实时分析系统

> 基于协整理论的加密货币配对交易信号实时监测与智能告警系统

## 📊 项目概述

本项目是一个高性能的加密货币配对交易分析系统，专注于实时检测 Hyperliquid 交易所上币种对之间的统计套利机会。系统通过 WebSocket 实时订阅 K 线数据，运用协整分析、相关性检验和 Z-score 异常检测等统计方法，自动识别潜在的配对交易信号并通过飞书机器人发送富文本告警。

### 核心特性

- ✅ **实时数据接收**: 直接订阅 Hyperliquid 原生 K 线（5m/1h/4h），无聚合误差
- ✅ **多周期统计分析**: 基于 Engle-Granger 双窗口协整检验，平衡稳定性与灵敏度
- ✅ **智能告警系统**: 飞书富文本卡片告警，包含 Z-score 可视化、相关性分析、风险评估
- ✅ **高性能架构**: 40K+ 条/秒数据库吞吐，<5秒分析延迟，<10秒告警延迟
- ✅ **数据质量保证**: 自动检测并补充缺失 K 线，黑名单机制过滤无效币种
- ✅ **可靠性设计**: 双重健康检测、智能重连、异常恢复机制
- ✅ **易于扩展**: 模板方法模式支持快速新增服务变体

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Hyperliquid WebSocket                        │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│           EnhancedWebSocketManager (双重健康检测)               │
│  ├─ 底层连接检测: ws.keep_running + ws_ready_event             │
│  └─ 应用层心跳: HealthMonitor (15秒超时)                       │
└────────────────────────────┬────────────────────────────────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
┌───────────────▼──────────┐  ┌──────────▼───────────────────────┐
│   kline_buffer (队列)    │  │  analysis_queue (队列)           │
│   ├─ 原始K线数据         │  │  ├─ 待分析币种对                 │
│   └─ 批量写入线程 (1K/5s)│  │  └─ 15×分析工作线程              │
└───────────────┬──────────┘  └──────────┬───────────────────────┘
                │                        │
┌───────────────▼──────────┐  ┌──────────▼───────────────────────┐
│    TimescaleDB           │  │   统计分析引擎                    │
│  ├─ klines表 (7天chunk) │  │  ├─ 相关性分析                    │
│  ├─ analysis_results     │  │  ├─ Engle-Granger协整检验         │
│  └─ symbol_metadata      │  │  └─ Z-score异常检测               │
└──────────────────────────┘  └──────────┬───────────────────────┘
                                         │
                             ┌───────────▼───────────┐
                             │  触发告警条件？        │
                             │  ├─ 协整通过数 ≥ 2    │
                             │  ├─ Z-score超阈值     │
                             │  └─ 协整健康状态正常   │
                             └───────────┬───────────┘
                                         │
                             ┌───────────▼───────────┐
                             │  Lark Bot API (飞书) │
                             │  富文本卡片告警       │
                             └───────────────────────┘
```

---

## 🔧 技术栈

### 核心依赖

| 类别 | 技术 | 版本 | 用途 |
|------|------|------|------|
| **数据库** | TimescaleDB | 2.x | 时序数据库（基于 PostgreSQL） |
| | Redis | 7.1+ | 缓存层 |
| **数据处理** | Pandas | 2.3.3+ | 时序数据处理 |
| | NumPy | 2.3.4+ | 数值计算 |
| **统计分析** | Statsmodels | 0.14.6+ | ADF、协整检验 |
| | SciPy | 1.15.0+ | 科学计算 |
| | Scikit-learn | 1.8.0+ | 机器学习工具 |
| **交易所 API** | hyperliquid-python-sdk | 0.21.0+ | Hyperliquid 原生 SDK |
| | CCXT | 4.5.14+ | 统一交易所接口 |
| **网络通信** | WebSockets | 16.0+ | WebSocket 客户端 |
| **数据库驱动** | Psycopg | 3.1.0+ | PostgreSQL 连接池 |

### 架构设计模式

- **模板方法模式**: `RealtimeKlineServiceBase` 抽象基类（90% 共用逻辑）
- **单例模式**: `TimescaleDBClient` 全局连接池
- **生产者-消费者模式**: WebSocket 接收 + 15 个分析工作线程
- **状态机模式**: 连接状态管理（DISCONNECTED/CONNECTING/CONNECTED/RECONNECTING）

---

## 🚀 快速开始

### 1. 环境要求

- Python >= 3.12
- Docker 和 Docker Compose（推荐）
- PostgreSQL 16 + TimescaleDB 2.x 扩展（或使用 Docker）
- Redis 7.1+

### 2. 安装依赖

```bash
# 克隆项目
git clone <repository-url>
cd hyperliquid-pair-hype-purr-analyze

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -e .
```

### 3. 配置环境变量

```bash
# 复制环境变量示例文件
cp .env.example .env

# 编辑 .env 文件，填写以下必要配置
POSTGRES_PASSWORD=your_strong_password
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
LARK_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/your_webhook_key
```

### 4. 启动数据库（Docker）

```bash
cd docker
docker-compose up -d
```

数据库将自动执行 `database/init_timescaledb.sql` 初始化脚本，创建必要的表和索引。

### 5. 运行服务

**通用版（监控所有活跃币种）**:
```bash
python src/services/realtime_kline_service.py
```

**HYPE/PURR 专用版**:
```bash
python src/services/realtime_kline_service_hype.py
```

---

## 📂 目录结构

```
hyperliquid-pair-hype-purr-analyze/
├── src/
│   ├── services/                        # 核心服务层
│   │   ├── realtime_kline_service_base.py      # 抽象基类（90%共用逻辑）
│   │   ├── realtime_kline_service.py           # 通用版实现
│   │   └── realtime_kline_service_hype.py      # HYPE/PURR专用版
│   ├── utils/
│   │   ├── analysis/                    # 分析引擎
│   │   │   ├── analysis_core.py                # 统计分析核心（协整、Z-score）
│   │   │   ├── kline_data_filler.py            # K线数据校验与补充
│   │   │   ├── kline_data_filler_lazy.py       # 懒加载版本（HYPE专用）
│   │   │   ├── kline_aggregator.py             # K线聚合（可选）
│   │   │   ├── coingetation_more_check.py      # 协整检验扩展
│   │   │   └── scheduler.py                    # 定时调度装饰器
│   │   ├── database/                    # 数据库层
│   │   │   ├── timescaledb.py                  # TimescaleDB连接池 + COPY批量写入
│   │   │   └── redisdb.py                      # Redis缓存
│   │   ├── websocket/                   # 网络通信层
│   │   │   └── enhanced_ws_manager.py          # 增强型WebSocket管理器
│   │   ├── monitoring/                  # 监控告警层
│   │   │   ├── alert_formatter.py              # 多周期告警格式化
│   │   │   ├── lark_bot.py                     # 飞书Webhook集成
│   │   │   └── spider_failed_alert.py          # 爬虫失败告警
│   │   └── core/                        # 核心配置
│   │       ├── config.py                       # 全局配置管理（150+行参数）
│   │       └── logging_config.py               # 统一日志配置
│   └── scripts/                         # 辅助脚本
│       ├── btc_autocorrelation.py              # BTC自相关性分析
│       └── validate_data_consistency.py        # 数据一致性验证
├── database/
│   └── init_timescaledb.sql             # 数据库初始化脚本
├── docker/
│   └── docker-compose.yml               # Docker容器编排
├── docs/
│   ├── DESIGN.md                        # 技术设计文档（40K+字符）
│   └── Johansen检验详解.md               # 统计分析文档
├── pyproject.toml                       # Python项目配置
└── .env.example                         # 环境变量示例
```

---

## ⚙️ 核心功能详解

### 1. 实时数据接收与处理

- **WebSocket 实时订阅**: 直接订阅 Hyperliquid 原生 K 线（5m/1h/4h）
  - 通用版: N 个活跃币种 × 3 个周期 = 3N 个订阅
  - HYPE 版: 2 个币种（HYPE/PURR）× 3 个周期 = 6 个订阅
- **数据精度保证**: 精度与 REST API 一致，无本地聚合误差
- **队列缓冲**: 两级队列系统
  - `kline_buffer`: 原始 K 线数据（队列大小: 10000）
  - `analysis_queue`: 待分析币种对（队列大小: 15000）

### 2. 多周期统计分析

**相关性分析**:
- 基于收益率相关系数（Pearson/Kendall/Spearman）
- 数据窗口: 5m→7天, 1h→30天, 4h→60天

**协整检验** (Engle-Granger 两步法):
- **全量窗口**: 200 期（长期稳定性）
- **短期窗口**: 100 期（敏感变化检测）
- **双窗口评分**: 平衡稳定性与灵敏度
- **智能模型选择**: 根据 α 显著性选择有/无 α 模型

**Z-score 异常检测**:
- 标准化价差监控
- 短周期阈值（5m）: 1.8
- 中周期阈值（1h）: 1.5
- 长周期阈值（4h）: 0.2

**多周期验证**: 3 个周期 × 2 种方法 = 6 个协整检验结果

### 3. 智能告警系统

**告警触发条件**:
- 协整通过数 ≥ 2（可配置）
- Z-score 符号一致性
- Z-score 超阈值检测
- 协整健康状态约束

**富文本格式** (飞书卡片):
- 信号概览
- Z-score 可视化进度条
- 相关性分析表格
- 协整检验统计
- 健康监控对比（长/短期窗口）
- 风险三级评估（红/黄/绿）
- 交易建议

**重试机制**: 最大 3 次，指数退避

### 4. 数据质量保证

- **K 线连续性校验**: 自动检测时间间隙
- **自动数据补充**: 通过 CCXT 从 REST API 补充缺失 K 线
- **黑名单机制**: 过滤数据不足的新币种
- **协整健康监控**: 避免协整关系恶化时的虚假信号

---

## 📊 性能指标

| 指标 | 目标值 | 实现方式 |
|------|--------|---------|
| **分析延迟** | <5 秒 | 异步处理 + 队列机制 |
| **告警延迟** | <10 秒 | 直接触发 + 批量缓冲 |
| **数据库吞吐** | >40K 条/秒 | COPY 命令 + 批量写入 |
| **内存占用** | <512 MB | TTL 缓存 + 定期清理 |
| **CPU 占用** | <50% | 多线程分布式处理 |

### 性能优化技术

1. **COPY 命令**: 比 INSERT 快 100 倍
2. **批量写入**: 1000 条/5 秒触发
3. **TTL 缓存**: 自动过期防止内存泄漏
4. **连接池**: 复用连接减少开销（min=2, max=10）
5. **索引优化**: (symbol, timeframe, time DESC)
6. **双重缓冲**: K 线 + 分析结果分开处理
7. **异步设计**: WebSocket 推送 + 异步分析

---

## 🔐 可靠性设计

### WebSocket 双重健康检测

**1. 底层连接检测**:
- `ws.keep_running`: WebSocket 连接状态
- `ws_ready_event`: 就绪标志
- `ws_thread`: 线程存活检查

**2. 应用层心跳**（假活检测）:
- `HealthMonitor`: 追踪最后消息时间
- 超时阈值: 15 秒
- 警告阈值: 15 秒
- 定期报告: 每 60 秒

### 智能重连策略

- **指数退避**: 1s → 2s → 4s → 8s → 16s → 32s → 60s
- **随机抖动**: ±25%（防止雷鸣羊群效应）
- **最大重试**: 30 次
- **5 步确定性清理**:
  1. 停止循环
  2. 停止 Ping 线程
  3. 关闭连接
  4. 等待工作线程
  5. 清除引用

---

## 📈 使用示例

### 监控特定币种对

```python
from src.services.realtime_kline_service_hype import RealtimeKlineServiceHypePurr

# 启动 HYPE/PURR 专用监控服务
service = RealtimeKlineServiceHypePurr()
service.run()
```

### 查询分析结果

```python
from src.utils.database.timescaledb import TimescaleDBClient

client = TimescaleDBClient.get_instance()

# 查询最近的异常信号
query = """
SELECT
    analysis_time,
    symbol,
    base_symbol,
    zscore_5m,
    zscore_1h,
    zscore_4h,
    cointegration_passed
FROM analysis_results
WHERE cointegration_passed = true
    AND ABS(zscore_5m) > 1.8
ORDER BY analysis_time DESC
LIMIT 10
"""

results = client.execute_query(query)
```

### 自定义告警阈值

编辑 `src/utils/core/config.py`:

```python
# Z-score 阈值配置
ZSCORE_THRESHOLDS = {
    'short': 1.8,   # 5m 周期
    'middle': 1.5,  # 1h 周期
    'long': 0.2     # 4h 周期
}

# 协整通过数阈值
COINTEGRATION_THRESHOLD = 2  # 至少2个周期协整通过
```

---

## 🧪 辅助工具

### BTC 自相关性分析

```bash
python src/scripts/btc_autocorrelation.py
```

分析 BTC 价格序列的自相关性，用于验证数据质量和市场效率假设。

### 数据一致性验证

```bash
python src/scripts/validate_data_consistency.py
```

检查数据库中 K 线数据的完整性和一致性，识别潜在的数据质量问题。

---

## 🔧 配置说明

### 核心配置参数

**分析参数** (`src/utils/core/config.py`):
```python
BETA_WINDOW = 100           # OLS 回归参数窗口
ZSCORE_WINDOW = 30          # Z-score 计算窗口
MIN_DATA_POINTS = 100       # 最小数据点数

# 数据窗口配置（天数）
DATA_WINDOW_CONFIG = {
    '5m': 7,     # 5分钟K线保留7天
    '1h': 30,    # 1小时K线保留30天
    '4h': 60     # 4小时K线保留60天
}

# 协整检验阈值
COINTEGRATION_THRESHOLD = 2  # 至少2个周期协整通过
```

**队列配置**:
```python
QUEUE_CONFIG = {
    'kline_buffer_size': 10000,      # K线缓冲队列
    'analysis_queue_size': 15000,    # 分析任务队列
    'result_buffer_size': 5000       # 结果缓冲队列
}
```

**工作线程配置**:
```python
ANALYSIS_WORKERS_GENERAL = 15  # 通用版分析工作线程
ANALYSIS_WORKERS_HYPE = 2      # HYPE版分析工作线程
```

**WebSocket 配置**:
```python
WS_PING_INTERVAL_MS = 5000     # Ping 心跳间隔（毫秒）
WS_RECONNECT_MAX_DELAY = 10    # 最大重连延迟（秒）
HEALTH_CHECK_TIMEOUT = 15      # 健康检查超时（秒）
```

---

## 📚 相关文档

- [DESIGN.md](docs/DESIGN.md) - 详细的技术设计文档（40K+ 字符）
  - 系统架构设计
  - 数据库设计与优化
  - 网络层设计
  - 分析引擎算法详解
  - 并发架构设计
  - 性能优化技术
  - 可靠性设计
  - 部署架构

- [Johansen检验详解.md](docs/Johansen检验详解.md) - 多变量协整检验理论

---

## 🛠️ 开发计划

**潜在改进方向**:

- [ ] 添加单元测试覆盖（pytest）
- [ ] 实现性能基准测试脚本
- [ ] 集成 Prometheus/Grafana 监控
- [ ] 优化分析工作线程为自适应调整
- [ ] 添加数据分析和导出工具
- [ ] 实现配置热加载机制
- [ ] 支持更多交易所（通过 CCXT）
- [ ] 实现更多统计分析方法（Johansen 协整检验等）

---

## ⚠️ 免责声明

本项目仅供学习和研究使用，不构成任何投资建议。加密货币交易存在高风险，请在充分了解风险的前提下谨慎参与。使用本系统进行实际交易导致的任何损失，开发者不承担任何责任。

---

## 📄 许可证

本项目采用 MIT 许可证。详见 LICENSE 文件。

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 提交 Pull Request

---

## 📧 联系方式

如有问题或建议，请通过以下方式联系：

- 提交 GitHub Issue
- 发送邮件至: [your-email@example.com]

---

**🌟 如果这个项目对你有帮助，请给个 Star！**
