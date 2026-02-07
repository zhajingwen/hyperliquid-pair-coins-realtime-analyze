# Hyperliquid 配对交易信号实时分析系统

> 基于协整理论的加密货币配对交易信号实时监测与智能告警系统

## 项目概述

本项目是一个高性能的加密货币配对交易分析系统，专注于实时检测 Hyperliquid 交易所上币种对之间的统计套利机会。系统通过 WebSocket 实时订阅 K 线数据，运用协整分析、相关性检验和 Z-score 异常检测等统计方法，自动识别潜在的配对交易信号并通过飞书机器人发送富文本告警。

### 核心特性

- **实时数据接收**: 直接订阅 Hyperliquid 原生 K 线（5m/1h/4h），无聚合误差
- **多周期统计分析**: 基于 Engle-Granger 双窗口协整检验，平衡稳定性与灵敏度
- **智能告警系统**: 飞书富文本卡片告警，包含 Z-score 可视化、相关性分析、风险评估
- **建仓双重确认**: 首次信号记录状态，5 分钟内信号增强确认后才发送告警，降低误报
- **均值回归平仓**: 实时追踪 Z-score 4h 回归至建仓 baseline，自动发送平仓信号
- **高性能架构**: 40K+ 条/秒数据库吞吐，<5 秒分析延迟，<10 秒告警延迟
- **数据质量保证**: 自动检测并补充缺失 K 线，黑名单机制过滤无效币种
- **可靠性设计**: 双重健康检测、智能重连、异常恢复机制
- **易于扩展**: 模板方法模式支持快速新增服务变体

---

## 系统架构

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
│   └─ 批量写入线程 (1K/5s)│  │  └─ 30×分析工作线程              │
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
                             │  建仓双重确认？        │
                             │  ├─ 协整通过数 ≥ 2    │
                             │  ├─ Z-score超阈值     │
                             │  ├─ 协整健康状态正常   │
                             │  └─ 5分钟内信号增强   │
                             └───────────┬───────────┘
                                         │
                             ┌───────────▼───────────┐
                             │  Lark Bot API (飞书) │
                             │  ├─ 建仓富文本告警    │
                             │  └─ 平仓回归告警      │
                             └───────────────────────┘
```

---

## 技术栈

### 核心依赖

| 类别 | 技术 | 版本 | 用途 |
|------|------|------|------|
| **数据库** | TimescaleDB | 2.x | 时序数据库（基于 PostgreSQL） |
| **数据处理** | Pandas | 3.0+ | 时序数据处理 |
| | NumPy | 2.4+ | 数值计算 |
| **统计分析** | Statsmodels | 0.14.6+ | ADF、协整检验 |
| | SciPy | 1.17+ | 科学计算 |
| | Scikit-learn | 1.8+ | 机器学习工具 |
| **交易所 API** | hyperliquid-python-sdk | 0.21+ | Hyperliquid 原生 SDK |
| | CCXT | 4.5+ | 统一交易所接口（数据补充） |
| **网络通信** | websocket-client | 1.6+ | WebSocket 客户端 |
| **数据库驱动** | Psycopg | 3.1+ | PostgreSQL 连接池 |

### 架构设计模式

- **模板方法模式**: `RealtimeKlineServiceBase` 抽象基类（90% 共用逻辑，1931 行）
- **单例模式**: `TimescaleDBClient` 全局连接池
- **生产者-消费者模式**: WebSocket 接收 + 30 个分析工作线程
- **状态机模式**: 连接状态管理（DISCONNECTED/CONNECTING/CONNECTED/RECONNECTING/FAILED）

---

## 快速开始

### 1. 环境要求

- Python >= 3.12
- Docker 和 Docker Compose（推荐）
- PostgreSQL 16 + TimescaleDB 2.x 扩展（或使用 Docker）

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
LARKBOT_ID=your_lark_bot_id_here
TIMESCALEDB_USER=postgres
TIMESCALEDB_PASSWORD=your_strong_password
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

## 目录结构

```
hyperliquid-pair-hype-purr-analyze/
├── src/
│   ├── services/                        # 核心服务层
│   │   ├── realtime_kline_service_base.py      # 抽象基类（1931行，90%共用逻辑）
│   │   ├── realtime_kline_service.py           # 通用版实现（动态币种，30 workers）
│   │   └── realtime_kline_service_hype.py      # HYPE/PURR专用版（固定币种，2 workers）
│   ├── utils/
│   │   ├── analysis/                    # 分析引擎
│   │   │   ├── analysis_core.py                # 统计分析核心（协整、Z-score）
│   │   │   ├── kline_data_filler.py            # K线数据校验与补充（CCXT版）
│   │   │   ├── kline_data_filler_lazy.py       # 懒加载版本（HYPE专用）
│   │   │   └── coingetation_more_check.py      # 协整健康监控（双窗口评分）
│   │   ├── database/                    # 数据库层
│   │   │   └── timescaledb.py                  # TimescaleDB连接池 + COPY批量写入
│   │   ├── websocket/                   # 网络通信层
│   │   │   └── enhanced_ws_manager.py          # 增强型WebSocket管理器
│   │   ├── monitoring/                  # 监控告警层
│   │   │   ├── alert_formatter.py              # 多周期告警格式化
│   │   │   └── lark_bot.py                     # 飞书Webhook集成
│   │   └── core/                        # 核心配置
│   │       ├── config.py                       # 全局配置管理（158行参数）
│   │       └── logging_config.py               # 统一日志配置
│   └── scripts/                         # 辅助脚本
│       ├── btc_autocorrelation.py              # BTC自相关性分析
│       ├── validate_data_consistency.py        # 数据一致性验证
│       ├── backtest_eth_btc_zscore_4h.py       # ETH/BTC回测脚本
│       ├── backtest_eth_btc_zscore_4h_binance.py  # ETH/BTC Binance回测
│       ├── backtest_purr_hype_zscore_4h_hyperliquid.py  # PURR/HYPE回测
│       └── query_analyze_result/               # 分析结果查询脚本
│           ├── query_purr_zscore.py            # PURR Z-score查询
│           ├── query_purr_zscore_beyond2_5.py  # 极端Z-score查询
│           ├── query_eth_zscore.py             # ETH Z-score查询
│           ├── check_base_symbols.py           # 基准币种检查
│           ├── check_db_symbols.py             # 数据库币种检查
│           └── search_eth_symbols.py           # ETH相关币种搜索
├── database/
│   └── init_timescaledb.sql             # 数据库初始化脚本
├── docker/
│   ├── docker-compose.yml               # Docker容器编排
│   ├── Dockerfile.akash                 # Akash部署镜像
│   └── deploy-akash.yaml               # Akash部署配置
├── docs/
│   ├── DESIGN.md                        # 技术设计文档
│   └── Johansen检验详解.md               # 统计分析文档
├── tests/                               # 测试目录
│   └── database/                        # 数据库测试
├── monitor_resources.py                 # 系统资源监控
├── pyproject.toml                       # Python项目配置
└── .env.example                         # 环境变量示例
```

---

## 核心功能详解

### 1. 实时数据接收与处理

- **WebSocket 实时订阅**: 直接订阅 Hyperliquid 原生 K 线（5m/1h/4h）
  - 通用版: N 个活跃币种 × 3 个周期 = 3N 个订阅
  - HYPE 版: 2 个币种（HYPE/PURR）× 3 个周期 = 6 个订阅
- **数据精度保证**: 精度与 REST API 一致，无本地聚合误差
- **队列缓冲**: 两级队列系统
  - `kline_buffer`: 原始 K 线数据（通用版: 10000，HYPE版: 1000）
  - `analysis_queue`: 待分析币种对（通用版: 30000，HYPE版: 1000）

### 2. 多周期统计分析

**相关性分析**:
- 基于收益率相关系数（Pearson/Kendall/Spearman，默认 Pearson）
- 数据窗口: 5m→7天, 1h→30天, 4h→60天
- 前置过滤: 4h/60d 相关系数 > 0.6（通用版），> 0.5（HYPE版）

**协整检验** (Engle-Granger 两步法):
- **Old方法**: 全量窗口 OLS 协整（验证性分析）
- **New方法**: 双窗口 OLS 协整（实时交易）
  - `beta_window=100`: 稳定回归参数估计
  - `zscore_window=30`: 敏感均值回归检测
  - 避免 look-ahead bias: 使用前 N-1 期计算 OLS
- **智能模型选择**: 根据 α 显著性选择有 α/无 α 模型

**Z-score 异常检测**:
- 基于 OLS 价差（非简单价格比率）
- 短周期阈值（5m）: 1.8
- 中周期阈值（1h）: 1.5
- 长周期阈值（4h）: 0.2

**多周期验证**: 3 个周期 × 2 种方法（Old+New） = 6 个协整检验结果

### 3. 建仓智能告警系统（双重确认）

**告警触发条件**:
1. 协整通过数 ≥ 2（6 个检验中至少 2 个通过）
2. 3 个周期 Z-score 符号一致
3. 3 个周期 Z-score 均超各自阈值
4. 协整健康状态约束（短期窗口需 HEALTHY）

**双重确认机制** (`DoubleCheckState`):
- **首次信号**: 记录 5m Z-score 和方向，等待确认
- **5 分钟内再次信号**:
  - 信号增强（|Z-score| 增大且 > 2.5）→ 确认发送告警
  - 信号未增强 → 刷新状态，重新等待
- **超过 5 分钟** → 超时重置为新的首次信号

**富文本格式** (飞书卡片):
- 信号概览（方向、币种、最新价格）
- Z-score 可视化进度条
- 相关性分析表格
- 协整检验统计
- 健康监控对比（长/短期窗口）
- 风险三级评估（红/黄/绿）
- 交易建议

### 4. 平仓告警系统（均值回归）

**平仓检测机制** (`MeanReversionState`):
- 建仓告警发送后，缓存 baseline（近 4 小时 avg_zscore_4h）和方向
- 实时追踪 zscore_4h：
  - Long 方向: zscore_4h 回升至 baseline 以上 → 回归
  - Short 方向: zscore_4h 回落至 baseline 以下 → 回归

**平仓双重确认**:
- 首次检测到回归 → 记录时间，不触发
- 5 分钟内二次确认 → 发送平仓告警
- 超时 → 重置为新的首次检测
- 回归消失 → 清除首次检测状态

### 5. 数据质量保证

- **K 线连续性校验**: 自动检测时间间隙
- **自动数据补充**: 通过 CCXT 从 REST API 补充缺失 K 线
- **黑名单机制**: 过滤 4h 数据不足 358 条的新币种
- **协整健康监控**: 避免协整关系恶化时的虚假信号

---

## 性能指标

| 指标 | 目标值 | 实现方式 |
|------|--------|---------|
| **分析延迟** | <5 秒 | 异步处理 + 队列机制 |
| **告警延迟** | <10 秒 | 直接触发 + 批量缓冲 |
| **数据库吞吐** | >40K 条/秒 | COPY 命令 + 批量写入 |
| **内存占用** | <512 MB | TTL 缓存 + 定期清理 |
| **CPU 占用** | <50% | 多线程分布式处理 |

### 性能优化技术

1. **COPY 命令**: 比 INSERT 快 100 倍
2. **批量写入**: K 线 1000 条/5 秒，分析结果 100 条/2 秒
3. **TTL 缓存**: 自动过期防止内存泄漏（TTLCache）
4. **连接池**: 复用连接减少开销（min=5, max=60）
5. **索引优化**: (symbol, timeframe, time DESC)
6. **三级缓冲**: K 线 + 分析任务 + 分析结果分开处理
7. **死锁防护**: 批量排序保证锁获取顺序一致，指数退避重试

---

## 可靠性设计

### WebSocket 双重健康检测

**1. 底层连接检测**:
- `ws.keep_running`: WebSocket 连接状态
- `ws_ready_event`: 就绪标志
- `ws_thread`: 线程存活检查

**2. 应用层心跳**（假活检测）:
- `HealthMonitor`: 追踪最后消息时间
- 超时阈值: 15 秒
- 定期报告: 每 60 秒

### 智能重连策略

- **指数退避**: 1s → 2s → 4s → 8s → 10s（最大）
- **随机抖动**: ±25%（防止雷鸣羊群效应）
- **最大重试**: 无限制（默认）
- **5 步确定性清理**:
  1. 停止循环
  2. 停止 Ping 线程
  3. 关闭连接
  4. 等待工作线程
  5. 清除引用

---

## 配置说明

### 核心配置参数

**分析参数** (`src/utils/core/config.py`):
```python
BETA_WINDOW = 100           # OLS 回归参数窗口
ZSCORE_WINDOW = 30          # Z-score 计算窗口
MIN_DATA_POINTS = 100       # 最小数据点数
MIN_4H_DATA_POINTS = 358    # 4H最小数据点（新币过滤）

# 数据窗口配置（天数）
DATA_WINDOW_CONFIG = {
    '5m': 7,     # 5分钟K线保留7天
    '1h': 30,    # 1小时K线保留30天
    '4h': 60     # 4小时K线保留60天
}

# Z-score 阈值配置
ZSCORE_THRESHOLDS = {
    'short': 1.8,   # 5m 周期
    'middle': 1.5,  # 1h 周期
    'long': 0.2,    # 4h 周期
    'strong': 2.5,  # 信号强度-强
    'medium': 2.0   # 信号强度-中
}

# 协整通过数阈值
COINTEGRATION_THRESHOLD = 2  # 至少2个周期协整通过
```

**双重确认配置**:
```python
DOUBLE_CHECK_WINDOW_SECONDS = 300       # 建仓确认窗口（5分钟）
DOUBLE_CHECK_ZSCORE_5M_THRESHOLD = 2.5  # 5m Z-score增强阈值
DOUBLE_CHECK_CLEANUP_SECONDS = 600      # 过期清理阈值

REVERSION_DOUBLE_CHECK_WINDOW_SECONDS = 300  # 平仓确认窗口（5分钟）
```

**队列配置**:
```python
# 通用版
QUEUE_CONFIG_GENERAL = {
    'kline_buffer_size': 10000,
    'analysis_queue_size': 30000,
    'analysis_result_buffer_size': 10000
}

# HYPE版
QUEUE_CONFIG_HYPE = {
    'kline_buffer_size': 1000,
    'analysis_queue_size': 1000,
    'analysis_result_buffer_size': 1000
}
```

**工作线程配置**:
```python
ANALYSIS_WORKERS_GENERAL = 30  # 通用版分析工作线程
ANALYSIS_WORKERS_HYPE = 2      # HYPE版分析工作线程
```

**连接池配置**:
```python
TIMESCALEDB_POOL_MIN_SIZE = 5   # 最小连接数
TIMESCALEDB_POOL_MAX_SIZE = 60  # 最大连接数（匹配30个工作线程）
```

**WebSocket 配置**:
```python
WS_TIMEOUT = 60                    # 连接超时（秒）
WS_PING_INTERVAL_MS = 5000        # Ping 心跳间隔（毫秒）
WS_RECONNECT_MAX_DELAY = 10.0     # 最大重连延迟（秒）
WS_HEALTH_MONITOR_TIMEOUT = 15    # 健康检查超时（秒）
WS_SUBSCRIBE_BATCH_SIZE = 50      # 批量订阅大小
```

---

## 两个服务版本对比

| 维度 | 通用版 | HYPE版 |
|------|--------|--------|
| **文件** | `realtime_kline_service.py` | `realtime_kline_service_hype.py` |
| **币种来源** | 动态获取（TimescaleDB + 交易所 API） | 固定列表 `[HYPE, PURR]` |
| **基准币种** | BTC/USDC:USDC | HYPE/USDC:USDC |
| **相关系数阈值** | 0.6 | 0.5 |
| **分析线程数** | 30 | 2 |
| **K线队列** | 10000 | 1000 |
| **分析队列** | 30000 | 1000 |
| **结果队列** | 10000 | 1000 |
| **币种监控** | 启用（每小时检测新币种） | 禁用 |
| **数据填充器** | KlineDataFiller（CCXT） | KlineDataFillerLazy |
| **总线程数** | ~37 | ~8 |

---

## 辅助工具

### BTC 自相关性分析

```bash
python src/scripts/btc_autocorrelation.py
```

### 数据一致性验证

```bash
python src/scripts/validate_data_consistency.py
```

### 回测脚本

```bash
# ETH/BTC Z-score 4h 回测
python src/scripts/backtest_eth_btc_zscore_4h.py

# ETH/BTC Binance 数据回测
python src/scripts/backtest_eth_btc_zscore_4h_binance.py

# PURR/HYPE Hyperliquid 数据回测
python src/scripts/backtest_purr_hype_zscore_4h_hyperliquid.py
```

### 分析结果查询

```bash
# 查询 PURR Z-score
python src/scripts/query_analyze_result/query_purr_zscore.py

# 查询极端 Z-score（>2.5）
python src/scripts/query_analyze_result/query_purr_zscore_beyond2_5.py

# 查询 ETH Z-score
python src/scripts/query_analyze_result/query_eth_zscore.py
```

---

## 使用示例

### 监控特定币种对

```python
from src.services.realtime_kline_service_hype import RealtimeKlineServiceHypePurr

# 启动 HYPE/PURR 专用监控服务
service = RealtimeKlineServiceHypePurr()
service.start()
```

### 查询分析结果

```python
from src.utils.database.timescaledb import TimescaleDBClient

client = TimescaleDBClient()

# 查询最近的异常信号
query = """
SELECT
    analysis_time,
    symbol,
    base_symbol,
    zscore_5m,
    zscore_1h,
    zscore_4h,
    cointegration_passed,
    is_anomaly,
    trading_direction
FROM analysis_results
WHERE is_anomaly = true
ORDER BY analysis_time DESC
LIMIT 10
"""
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

# 双重确认参数
DOUBLE_CHECK_WINDOW_SECONDS = 300       # 确认窗口（秒）
DOUBLE_CHECK_ZSCORE_5M_THRESHOLD = 2.5  # 增强阈值
```

---

## 相关文档

- [DESIGN.md](DESIGN.md) - 详细的技术设计文档
  - 系统架构设计
  - 数据库设计与优化
  - 网络层设计
  - 分析引擎算法详解
  - 并发架构设计
  - 性能优化技术
  - 可靠性设计
  - 部署架构

- [Johansen检验详解.md](Johansen检验详解.md) - 多变量协整检验理论

---

## 开发计划

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

## 免责声明

本项目仅供学习和研究使用，不构成任何投资建议。加密货币交易存在高风险，请在充分了解风险的前提下谨慎参与。使用本系统进行实际交易导致的任何损失，开发者不承担任何责任。

---

## 许可证

本项目采用 MIT 许可证。详见 LICENSE 文件。
