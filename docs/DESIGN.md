# hyperliquid-pair-hype-purr-analyze 技术设计文档

**版本**: v1.0
**生成日期**: 2026-01-31
**作者**: Claude Code
**项目**: 加密货币配对交易信号实时分析系统

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 系统架构设计](#2-系统架构设计)
- [3. 数据库设计](#3-数据库设计)
- [4. 网络层设计](#4-网络层设计)
- [5. 分析引擎设计](#5-分析引擎设计)
- [6. 并发架构设计](#6-并发架构设计)
- [7. 性能优化设计](#7-性能优化设计)
- [8. 可靠性设计](#8-可靠性设计)
- [9. 监控与告警](#9-监控与告警)
- [10. 部署设计](#10-部署设计)
- [11. 配置管理](#11-配置管理)
- [12. 附录](#12-附录)

---

## 1. 项目概述

### 1.1 系统简介

**hyperliquid-pair-hype-purr-analyze** 是一个基于统计套利的加密货币配对交易信号实时分析系统。系统通过WebSocket实时接收Hyperliquid交易所的K线数据，执行多周期统计分析，检测配对交易机会，并通过飞书发送实时告警。

**核心定位**:
- 量化交易策略支持系统
- 实时信号发现引擎
- 统计套利机会监控平台

**代码引用**: `realtime_kline_service.py:1-35`

### 1.2 核心功能

#### 实时数据接收
- **WebSocket订阅**: 直接订阅交易所原生K线 (5m/1h/4h)
- **订阅数量**: N个活跃币种 × 3周期
- **精度保证**: 数据精度与REST API完全一致，无本地聚合误差
- **订阅优势**: 1h/4h推送频率极低 (<2%额外开销)，Volume数据完全一致

**代码引用**: `realtime_kline_service.py:5-26`

#### 多周期统计分析
- **相关性分析**: 基于收益率相关系数 (去趋势化、平稳性)
- **协整检验**: Engle-Granger两步法 (Old全量 + New双窗口)
- **Z-score异常检测**: 标准化价差监控
- **多周期验证**: 3周期 × 2方法 = 6个协整检验结果
- **协整健康监控**: 双窗口评分机制 (长期200期 + 短期100期)

**分析周期配置**:
- 5m周期: 7天历史数据
- 1h周期: 30天历史数据
- 4h周期: 60天历史数据

**代码引用**: `utils/analysis_core.py:1-44`

#### 智能告警系统
- **飞书富文本告警**: 彩色卡片格式化
- **告警触发条件**:
  - 协整通过数 ≥ 2 (可配置)
  - Z-score符号一致性
  - Z-score超阈值 (5m>1.8, 1h>1.5, 4h>0.2)
  - 协整健康状态约束 (短期窗口需HEALTHY)
- **重试机制**: 最大3次，指数退避

**代码引用**: `utils/alert_formatter.py`

#### 数据质量保证
- **K线连续性校验**: 检测时间间隙
- **自动数据补充**: REST API补充缺失K线
- **黑名单机制**: 过滤数据不足的新币种
- **协整健康监控**: 避免协整关系恶化时的虚假信号

**代码引用**: `utils/kline_data_filler.py`

### 1.3 技术栈

#### 核心技术

**编程语言**: Python 3.12+

**数据库**:
- TimescaleDB 2.x (PostgreSQL时序扩展)
- psycopg 3.x (连接池管理)
- 自动分片 (7天chunk)

**网络通信**:
- websocket-client 1.x (原生WebSocket实现)
- Hyperliquid API SDK
- requests (HTTP请求)

**统计分析**:
- NumPy 1.26+ (数值计算)
- pandas 2.2+ (数据处理)
- statsmodels 0.14+ (协整检验、ADF检验)

**并发控制**:
- threading (多线程并发)
- queue.Queue (线程安全队列)
- cachetools.TTLCache (去重缓存)

**容器化**:
- Docker 24.x
- docker-compose 2.x

**代码引用**: `pyproject.toml`, `docker-compose.yml`

### 1.4 架构亮点

#### 1. 直接订阅原生K线
- ✅ 精度与REST API一致
- ✅ 无本地聚合误差
- ✅ Volume数据完全一致
- ✅ 额外开销 <2%

**设计权衡**: 放弃本地聚合换取数据精度和简洁性

**代码引用**: `realtime_kline_service.py:22-26`

#### 2. 双窗口OLS协整分析
- **beta_window=100期**: 稳定回归参数
- **zscore_window=30期**: 敏感均值回归
- **避免look-ahead bias**: 使用前N-1期计算OLS
- **智能模型选择**: 根据α显著性选择有α/无α模型

**设计优势**: 平衡稳定性与灵敏度

**代码引用**: `utils/analysis_core.py:185-407`, `utils/config.py:BETA_WINDOW`, `utils/config.py:ZSCORE_WINDOW`

#### 3. 多线程异步批量写入
- **COPY命令**: >40K条/秒 (比INSERT快100倍)
- **临时表策略**: ON COMMIT DROP自动清理
- **批量触发**: 1000条/5秒
- **死锁防护**: 批量排序保证锁获取顺序一致

**性能提升**: 批量写入性能提升100倍

**代码引用**: `timescaledb.py:342-450`, `realtime_kline_service.py:635-760`

#### 4. 双重健康检测
**底层连接检测**:
- `ws.keep_running` 状态标志
- `ws_ready_event` 就绪标志
- `ws_thread` 存活检查

**应用层心跳** (假活检测):
- 追踪最后消息时间
- 超时阈值: 15秒
- 定期健康报告: 每60秒

**设计参考**: strong-hyperliquid-websocket

**代码引用**: `enhanced_ws_manager.py:54-114`

#### 5. 智能重连策略
- **指数退避**: 1s → 2s → 4s → 8s → 16s → 32s → 60s
- **随机抖动**: ±25% (防止雷鸣羊群效应)
- **最大重试**: 30次
- **5步确定性清理**: 停止循环 → 停止Ping → 关闭连接 → 等待线程 → 清除引用

**代码引用**: `enhanced_ws_manager.py:120-183`, `enhanced_ws_manager.py:698-781`

---

## 2. 系统架构设计

### 2.1 整体架构图

```mermaid
graph TD
    A[Hyperliquid WebSocket API] -->|K线推送| B[EnhancedWebSocketManager]
    B -->|状态机管理| C[HealthMonitor<br/>双重健康检测]
    B -->|on_message| D[K线解析]

    D -->|5m/1h/4h K线| E[kline_buffer<br/>Queue 10000]
    D -->|5m推送触发| F[analysis_queue<br/>Queue 15000]

    E -->|批量1000条/5秒| G[batch_writer线程]
    G -->|COPY命令| H[(TimescaleDB<br/>klines表)]

    F -->|并发消费| I[15×analysis_worker线程]
    I -->|多周期验证| J[analysis_result_buffer<br/>Queue 10000]
    I -->|Z-score异常| K[飞书告警<br/>Lark Bot API]

    J -->|批量100条/2秒| L[result_batch_writer线程]
    L -->|批量插入| M[(TimescaleDB<br/>analysis_results表)]

    H -.查询历史数据.-> I

    N[queue_monitor线程] -.监控.-> E
    N -.监控.-> F
    N -.监控.-> J

    O[new_symbol_monitor线程] -.每小时检查.-> B
```

**代码引用**: `realtime_kline_service.py:118-141`

### 2.2 核心组件关系

#### 组件清单

| 组件 | 类型 | 职责 | 线程数 |
|------|------|------|--------|
| EnhancedWebSocketManager | 网络管理器 | WebSocket连接管理、订阅管理、健康监控 | 3 (主线程+Ping+健康检查) |
| batch_writer | 数据持久化 | K线批量写入TimescaleDB (COPY命令) | 1 |
| analysis_worker | 分析引擎 | 多周期协整验证、Z-score计算、告警发送 | 15 |
| result_batch_writer | 结果持久化 | 分析结果批量写入 | 1 |
| queue_monitor | 监控线程 | 队列使用率监控、告警 | 1 |
| new_symbol_monitor | 币种监控 | 自动发现新币种、动态订阅 | 1 |

**总线程数**: 22个线程 (3+1+15+1+1+1)

**代码引用**: `realtime_kline_service.py:224-275`

#### 组件交互流程

1. **数据接收流程**:
   ```
   WebSocket推送 → on_message回调 → K线解析 → kline_buffer队列
   ```

2. **批量写入流程**:
   ```
   kline_buffer → batch_writer线程 → COPY命令 → TimescaleDB
   触发条件: 1000条 OR 5秒超时
   ```

3. **分析触发流程**:
   ```
   5m K线推送 → 去重检查 (30s入队/60s分析) → analysis_queue队列
   ```

4. **并发分析流程**:
   ```
   analysis_queue → 15×analysis_worker → 查询历史数据 → 多周期验证 → 结果入队
   ```

5. **告警发送流程**:
   ```
   异常检测成功 → 飞书告警 (重试3次) → 记录发送结果
   ```

**代码引用**: `realtime_kline_service.py:635-1035`

### 2.3 数据流设计

#### K线数据流

```mermaid
sequenceDiagram
    participant WS as WebSocket
    participant OM as on_message
    participant KB as kline_buffer
    participant BW as batch_writer
    participant DB as TimescaleDB

    WS->>OM: 推送K线消息
    OM->>OM: 解析JSON
    OM->>KB: put(kline_dict)

    loop 每5秒 or 满1000条
        BW->>KB: get_nowait(批量取出)
        BW->>BW: 去重排序
        BW->>DB: COPY批量写入
        DB-->>BW: 写入确认
    end
```

**去重保护**:
- **入队去重**: 30秒窗口 (TTLCache)
- **数据库去重**: 主键 `(time, symbol, timeframe)` ON CONFLICT UPDATE

**代码引用**: `realtime_kline_service.py:635-760`, `timescaledb.py:342-450`

#### 分析数据流

```mermaid
sequenceDiagram
    participant OM as on_message (5m)
    participant AQ as analysis_queue
    participant AW as analysis_worker
    participant DB as TimescaleDB
    participant ARB as result_buffer
    participant LK as 飞书告警

    OM->>OM: 检查去重 (60s窗口)
    OM->>AQ: put(analysis_task)

    AW->>AQ: get(阻塞等待)
    AW->>DB: 查询3周期历史数据
    DB-->>AW: 返回K线数据

    AW->>AW: 数据连续性校验
    AW->>AW: 相关性前置过滤
    AW->>AW: 多周期协整验证 (6次)
    AW->>AW: Z-score计算与异常检测

    alt 异常检测成功
        AW->>LK: 发送飞书告警 (重试3次)
        AW->>ARB: put(分析结果)
    else 未检测到异常
        AW->>ARB: put(分析结果, is_anomaly=False)
    end
```

**分析去重保护**:
- 5m周期: 60秒窗口
- 1h周期: 300秒窗口
- 4h周期: 900秒窗口
- 跨线程共享: 所有analysis_worker共享同一TTLCache

**代码引用**: `realtime_kline_service.py:908-1035`, `realtime_kline_service.py:1037-1402`

### 2.4 技术选型说明

#### 为什么选择 TimescaleDB？

**优势**:
- ✅ 基于PostgreSQL，生态成熟
- ✅ 自动分片 (chunk_time_interval=7天)
- ✅ 时序查询优化 (time-bucket聚合)
- ✅ 连续聚合视图 (Continuous Aggregates)
- ✅ 数据保留策略 (自动清理180天前数据)

**对比其他方案**:
- vs InfluxDB: PostgreSQL生态更强，SQL兼容性好
- vs ClickHouse: 部署简单，小规模场景更合适
- vs 原生PostgreSQL: 时序优化更好，分片自动管理

**代码引用**: `init_timescaledb.sql`, `docker-compose.yml`

#### 为什么选择 websocket-client？

**优势**:
- ✅ 原生Python实现，零依赖
- ✅ 简单可靠，社区活跃
- ✅ 支持自定义回调 (on_open/on_message/on_error/on_close)
- ✅ 线程模型清晰 (run_forever独立线程)

**对比其他方案**:
- vs aiohttp: 不需要asyncio复杂性
- vs python-binance: 通用性更好，不绑定特定交易所

**代码引用**: `enhanced_ws_manager.py:1-34`

#### 为什么选择多线程而非异步？

**理由**:
- ✅ psycopg 3.x同步API性能已足够 (COPY >40K条/秒)
- ✅ statsmodels同步阻塞计算，异步无优势
- ✅ 线程模型简单清晰，易于调试
- ✅ 并发分析任务完全独立，线程池模式适合

**权衡**:
- ❌ 线程上下文切换开销 (但15线程规模可接受)
- ✅ 避免asyncio生态碎片化问题

**代码引用**: `realtime_kline_service.py:224-275`

---

## 3. 数据库设计

### 3.1 TimescaleDB架构

#### 核心特性

**TimescaleDB** = PostgreSQL + 时序优化扩展

**架构优势**:
- 自动分片 (hypertable + chunks)
- 时序查询优化 (time-bucket, first/last聚合)
- 连续聚合 (Continuous Aggregates)
- 数据保留策略 (Retention Policy)
- 数据压缩 (Compression)

**代码引用**: `init_timescaledb.sql:1-11`

#### Hypertable分片策略

**klines表**:
- chunk_time_interval: 7天
- 分片键: `time`
- 索引: 自动创建时间索引

**analysis_results表**:
- chunk_time_interval: 30天
- 分片键: `analysis_time`
- 索引: 自动创建时间索引

**分片优势**:
- 查询性能: 自动分区剪枝
- 数据管理: 按chunk删除历史数据
- 并发写入: 不同chunk并发写入无锁竞争

**代码引用**: `init_timescaledb.sql:99-117`

### 3.2 核心数据表

#### klines表 (K线数据)

```sql
CREATE TABLE klines (
    time TIMESTAMPTZ NOT NULL,           -- K线时间（UTC）
    symbol VARCHAR(50) NOT NULL,         -- 币种（BTC/USDC:USDC）
    timeframe VARCHAR(10) NOT NULL,      -- 周期（5m/1h/4h）
    open DOUBLE PRECISION NOT NULL,      -- 开盘价
    high DOUBLE PRECISION NOT NULL,      -- 最高价
    low DOUBLE PRECISION NOT NULL,       -- 最低价
    close DOUBLE PRECISION NOT NULL,     -- 收盘价
    volume DOUBLE PRECISION NOT NULL,    -- 成交量
    volume_usd DOUBLE PRECISION,         -- 成交额（USD）
    return_pct DOUBLE PRECISION,         -- 收益率（%）
    created_at TIMESTAMPTZ DEFAULT NOW(),-- 写入时间

    PRIMARY KEY (time, symbol, timeframe)
);
```

**设计说明**:
- 复合主键: `(time, symbol, timeframe)` 自动去重
- `return_pct`: 预计算收益率（可选，用于加速相关性分析）
- `volume_usd`: 用于流动性过滤

**数据示例**:
```
time: 2026-01-30 12:00:00+00
symbol: BTC/USDC:USDC
timeframe: 5m
close: 106500.0
volume: 1234.56
```

**代码引用**: `init_timescaledb.sql:19-36`

#### symbol_metadata表 (币种元数据)

```sql
CREATE TABLE symbol_metadata (
    symbol VARCHAR(50) PRIMARY KEY,
    base_asset VARCHAR(20) NOT NULL,     -- 基础资产（BTC）
    quote_asset VARCHAR(20) NOT NULL,    -- 计价资产（USDC）
    listing_time TIMESTAMPTZ,            -- 上线时间
    first_kline_time TIMESTAMPTZ,        -- 首次K线时间
    last_kline_time TIMESTAMPTZ,         -- 最后K线时间
    is_active BOOLEAN DEFAULT TRUE,      -- 是否活跃
    data_quality_score DOUBLE PRECISION DEFAULT 0.0,
    total_klines BIGINT DEFAULT 0,       -- K线总数
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**用途**:
- 追踪币种上线时间
- 过滤数据不足的新币
- 监控数据质量

**代码引用**: `init_timescaledb.sql:38-54`

#### analysis_results表 (分析结果)

```sql
CREATE TABLE analysis_results (
    id SERIAL,
    analysis_time TIMESTAMPTZ NOT NULL,  -- 分析执行时间
    symbol VARCHAR(50) NOT NULL,         -- 目标币种
    base_symbol VARCHAR(50) NOT NULL,    -- 基准币种

    -- 时间链路
    kline_time TIMESTAMPTZ,              -- K线原始时间
    analysis_delay_seconds FLOAT,        -- 分析延迟（秒）

    -- 相关系数
    corr_5m_7d DOUBLE PRECISION,         -- 5m周期7天相关系数
    corr_1h_30d DOUBLE PRECISION,        -- 1h周期30天相关系数
    corr_4h_60d DOUBLE PRECISION,        -- 4h周期60天相关系数

    -- Z-score
    zscore_5m DOUBLE PRECISION,
    zscore_1h DOUBLE PRECISION,
    zscore_4h DOUBLE PRECISION,

    -- 协整检验
    cointegration_passed BOOLEAN DEFAULT FALSE,
    adf_pvalue DOUBLE PRECISION,

    -- 信号标识
    is_anomaly BOOLEAN DEFAULT FALSE,    -- 是否异常
    trading_direction VARCHAR(50),       -- 交易方向
    signal_strength VARCHAR(20),         -- 信号强度

    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (analysis_time, id)
);
```

**字段说明**:
- `kline_time`: 用于分析延迟监控
- `cointegration_passed`: 多周期协整通过标志
- `is_anomaly`: 异常检测结果（告警触发）
- `trading_direction`: long/short方向

**代码引用**: `init_timescaledb.sql:56-93`

### 3.3 索引策略

#### 主键索引 (自动创建)

```sql
-- klines表
PRIMARY KEY (time, symbol, timeframe)
→ 自动创建 B-tree 索引

-- analysis_results表
PRIMARY KEY (analysis_time, id)
→ 自动创建 B-tree 索引
```

#### 查询优化索引

```sql
-- 索引1: klines 按币种+周期+时间倒序（最常用查询）
CREATE INDEX idx_klines_symbol_timeframe_time
ON klines (symbol, timeframe, time DESC);

-- 索引2: symbol_metadata 活跃币种快速查询（部分索引）
CREATE INDEX idx_symbol_active
ON symbol_metadata (symbol)
WHERE is_active = TRUE;

-- 索引3: analysis_results 异常信号快速过滤（部分索引）
CREATE INDEX idx_analysis_anomaly_time
ON analysis_results (analysis_time DESC)
WHERE is_anomaly = TRUE;

-- 索引4: 延迟监控查询索引（部分索引）
CREATE INDEX idx_analysis_delay
ON analysis_results (analysis_delay_seconds DESC)
WHERE analysis_delay_seconds > 5;
```

**索引设计原则**:
- 覆盖最常用查询路径
- 部分索引减少索引大小
- 时间字段降序索引（最新数据优先）

**代码引用**: `init_timescaledb.sql:120-167`

### 3.4 分区策略

#### 自动分片 (Hypertable)

```sql
-- klines: 7天chunk
SELECT create_hypertable(
    'klines',
    'time',
    chunk_time_interval => INTERVAL '7 days'
);

-- analysis_results: 30天chunk
SELECT create_hypertable(
    'analysis_results',
    'analysis_time',
    chunk_time_interval => INTERVAL '30 days'
);
```

**分片效果**:
- 查询优化: 分区剪枝（仅扫描相关chunk）
- 并发写入: 不同chunk并发无锁冲突
- 历史数据管理: 按chunk删除

**代码引用**: `init_timescaledb.sql:99-117`

#### 数据保留策略

```sql
-- klines: 保留90天
SELECT add_retention_policy(
    'klines',
    INTERVAL '90 days'
);

-- analysis_results: 保留180天
SELECT add_retention_policy(
    'analysis_results',
    INTERVAL '180 days'
);
```

**自动清理**:
- 后台作业自动执行
- 按chunk删除（性能高）
- 无需手动维护

**代码引用**: `init_timescaledb.sql:169-188`

#### 数据压缩策略

```sql
-- klines: 7天后压缩（按symbol和timeframe分段）
ALTER TABLE klines SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,timeframe'
);

SELECT add_compression_policy(
    'klines',
    INTERVAL '7 days'
);
```

**压缩效果**:
- 存储节省: 70-90%
- 查询性能: 轻微下降（可接受）
- 适用场景: 历史数据查询

**代码引用**: `init_timescaledb.sql:190-220`

### 3.5 连接池设计

#### 单例模式连接池

```python
class TimescaleDBClient:
    _instance: Optional['TimescaleDBClient'] = None
    _pool: Optional[ConnectionPool] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
```

**设计优势**:
- 全局唯一连接池实例
- 避免重复初始化
- 线程安全

**代码引用**: `timescaledb.py:94-129`

#### 连接池配置

```python
self._pool = ConnectionPool(
    conninfo=self.config.connection_string,
    min_size=2,    # 最小连接数
    max_size=10,   # 最大连接数
    timeout=30,    # 获取连接超时（秒）
    max_lifetime=3600,  # 连接最大存活时间（秒）
    max_idle=600,       # 最大空闲时间（秒）
    open=True
)
```

**参数说明**:
- `min_size=2`: 保持最少2个活跃连接
- `max_size=10`: 最多10个并发连接
- `max_lifetime=3600`: 每小时回收连接（防止连接泄漏）
- `max_idle=600`: 10分钟空闲自动回收

**代码引用**: `timescaledb.py:131-150`

#### 连接污染检测

```python
@contextmanager
def get_connection(self) -> Connection:
    conn = None
    connection_valid = True

    try:
        conn = self._pool.getconn()
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            try:
                conn.rollback()
                # 关键: 测试连接是否仍然可用
                with conn.cursor() as test_cur:
                    test_cur.execute("SELECT 1")
            except Exception as test_e:
                # 连接已污染，标记为无效
                logger.error(f"连接已污染，将其移除: {test_e}")
                connection_valid = False
        raise
    finally:
        if conn:
            if connection_valid:
                self._pool.putconn(conn)  # 健康连接复用
            else:
                self._pool.putconn(conn, close=True)  # 污染连接移除
```

**污染检测机制**:
1. 异常后执行 `SELECT 1` 测试
2. 测试失败 → 标记为污染连接
3. 污染连接关闭并移除
4. 健康连接返回连接池复用

**代码引用**: `timescaledb.py:152-217`

---

## 4. 网络层设计

### 4.1 WebSocket管理器架构

#### 核心类设计

```python
class EnhancedWebSocketManager:
    """
    增强型 WebSocket 连接管理器

    核心功能:
    - 双重健康检测（底层连接 + 应用层心跳）
    - 指数退避重连策略
    - 完整的状态机管理
    - 线程安全设计
    - 可观测性（统计信息和健康报告）
    """
```

**设计参考**: strong-hyperliquid-websocket

**代码引用**: `enhanced_ws_manager.py:1-34`

#### 状态机管理

```python
class ConnectionState(Enum):
    DISCONNECTED = "disconnected"  # 未连接
    CONNECTING = "connecting"      # 连接中
    CONNECTED = "connected"        # 已连接
    RECONNECTING = "reconnecting"  # 重连中
    FAILED = "failed"              # 连接失败
```

**状态转换**:
```
DISCONNECTED → CONNECTING → CONNECTED
     ↓              ↓            ↓
  FAILED ← RECONNECTING ← (网络中断)
```

**代码引用**: `enhanced_ws_manager.py:41-48`

#### 线程模型

**主要线程**:
1. **WebSocket主线程**: 运行 `WebSocket.run_forever()`
2. **Ping线程**: 每5秒发送ping保活
3. **健康监控线程**: 每2秒检查连接健康

**线程同步**:
- `ws_thread`: WebSocket主线程句柄
- `ws_ready_event`: WebSocket就绪标志（threading.Event）
- `stop_ping`: Ping线程停止信号（threading.Event）

**代码引用**: `enhanced_ws_manager.py:501-597`

### 4.2 双重健康检测机制

#### 底层连接检测

```python
def _is_connected_base(self) -> bool:
    """检查底层WebSocket连接状态"""
    with self.state_lock:
        return (
            self.ws is not None
            and self.ws.keep_running  # WebSocket底层标志
            and self.ws_ready_event.is_set()  # 就绪标志
            and self.ws_thread is not None
            and self.ws_thread.is_alive()  # 线程存活
        )
```

**检测指标**:
- `ws.keep_running`: WebSocket底层运行标志
- `ws_ready_event`: 连接就绪标志
- `ws_thread.is_alive()`: 线程存活检查

**代码引用**: `enhanced_ws_manager.py:800-828`

#### 应用层心跳 (假活检测)

```python
class HealthMonitor:
    """
    健康监控器（应用层心跳）

    功能:
    - 追踪最后消息接收时间
    - 检测数据流中断（假活状态）
    - 双阈值告警（警告 + 超时）
    """

    def __init__(self, timeout=15, warning_threshold=10):
        self.timeout = timeout  # 15秒超时
        self.warning_threshold = warning_threshold  # 10秒警告
        self.last_message_time = time.time()
        self.message_count = 0

    def is_alive(self) -> tuple[bool, float]:
        idle_time = time.time() - self.last_message_time

        if idle_time > self.timeout:
            return False, idle_time  # 假活检测
        elif idle_time > self.warning_threshold:
            logger.warning(f"健康检查警告: {idle_time:.1f}秒未收到数据")

        return True, idle_time
```

**假活场景**:
- WebSocket底层连接正常
- 但15秒未收到任何消息 → 判定为假活
- 触发重连

**健康度百分比**:
```python
def get_health_percentage(self) -> float:
    _, idle_time = self.is_alive()
    return max(0, 100 - (idle_time / self.timeout * 100))
```

**代码引用**: `enhanced_ws_manager.py:54-114`

### 4.3 重连策略设计

#### 指数退避算法

```python
class ReconnectionManager:
    """
    重连管理器（指数退避策略）

    特性:
    - 指数退避: 1s → 2s → 4s → 8s → 16s → 32s → 60s
    - 随机抖动: ±25% (防止雷鸣羊群效应)
    - 可配置最大延迟和重试次数
    """

    def __init__(
        self,
        initial_delay=1.0,    # 初始延迟
        max_delay=60.0,       # 最大延迟
        multiplier=2.0,       # 递增因子
        max_retries=None      # 最大重试次数
    ):
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.max_retries = max_retries
        self.current_attempt = 0
```

**延迟计算**:
```python
def get_delay(self) -> float:
    # 指数退避: initial_delay * multiplier^attempt
    delay = self.initial_delay * (self.multiplier ** self.current_attempt)
    delay = min(delay, self.max_delay)

    # 随机抖动: ±25%
    jitter = delay * (random.random() - 0.5) * 0.5  # ±25%
    return max(0, delay + jitter)
```

**退避序列示例**:
```
尝试1: 1.0s ± 25% = 0.75-1.25s
尝试2: 2.0s ± 25% = 1.5-2.5s
尝试3: 4.0s ± 25% = 3.0-5.0s
尝试4: 8.0s ± 25% = 6.0-10.0s
尝试5: 16.0s ± 25% = 12.0-20.0s
尝试6: 32.0s ± 25% = 24.0-40.0s
尝试7+: 60.0s ± 25% = 45.0-75.0s (封顶)
```

**代码引用**: `enhanced_ws_manager.py:120-183`

#### 5步确定性清理

```python
def _force_cleanup_websocket(self):
    """
    5步确定性清理 WebSocket 连接

    步骤:
    1. 停止运行循环
    2. 停止Ping线程
    3. 关闭WebSocket连接
    4. 等待WebSocket线程退出
    5. 清除引用
    """

    # Step 1: 停止运行循环
    if self.ws:
        self.ws.keep_running = False

    # Step 2: 停止Ping线程
    if hasattr(self, 'stop_ping'):
        self.stop_ping.set()
        if hasattr(self, 'ping_thread'):
            self.ping_thread.join(timeout=2.0)

    # Step 3: 关闭WebSocket连接
    if self.ws:
        try:
            self.ws.close()
        except Exception as e:
            logger.warning(f"关闭WebSocket时出错: {e}")

    # Step 4: 等待WebSocket线程退出
    if self.ws_thread and self.ws_thread.is_alive():
        self.ws_thread.join(timeout=2.0)
        if self.ws_thread.is_alive():
            logger.warning("WebSocket线程未正常退出")

    # Step 5: 清除引用
    self.ws = None
    self.ws_thread = None
    self.ws_ready_event.clear()
```

**清理保证**:
- 确定性顺序执行
- 超时保护（2秒）
- 线程泄漏检测

**代码引用**: `enhanced_ws_manager.py:698-781`

### 4.4 订阅管理与数据缓存

#### 动态订阅管理

```python
def add_subscriptions(self, new_subscriptions: List[Dict]):
    """动态添加订阅"""
    with self.subscriptions_lock:
        for sub in new_subscriptions:
            sub_key = (sub['type'], tuple(sorted(sub.items())))
            if sub_key not in self.active_subscriptions:
                self.subscriptions.append(sub)
                self.active_subscriptions.add(sub_key)

        # 如果连接已建立，立即发送订阅
        if self._is_connected():
            self._send_subscriptions(new_subscriptions)
```

**订阅去重**:
- `active_subscriptions`: set集合
- 订阅键: `(type, sorted_params)` 元组

**即时订阅 vs 延迟订阅**:
- 连接已建立 → 立即发送subscribe消息
- 连接未建立 → 添加到列表，重连时自动订阅

**代码引用**: `enhanced_ws_manager.py:420-470`

#### 数据缓存设计

```python
# latest_data 字典缓存最新K线/订单簿/交易记录
self.latest_data = {
    "candles": {},      # {(symbol, timeframe): kline_dict}
    "l2Book": {},       # {symbol: orderbook_dict}
    "trades": {},       # {symbol: [trade_list]}
}

# 同步查询接口
def get_latest_candle(self, symbol: str, timeframe: str) -> Optional[Dict]:
    """获取最新K线（同步查询）"""
    with self.latest_data_lock:
        return self.latest_data["candles"].get((symbol, timeframe))

def get_latest_mid_price(self, symbol: str) -> Optional[float]:
    """获取最新中间价（同步查询）"""
    with self.latest_data_lock:
        book = self.latest_data["l2Book"].get(symbol)
        if book and 'levels' in book:
            levels = book['levels']
            if len(levels) >= 2:
                best_bid = float(levels[0][0]['px'])
                best_ask = float(levels[1][0]['px'])
                return (best_bid + best_ask) / 2
    return None
```

**应用场景**:
- 同步查询最新价格
- 避免重复数据库查询
- 降低API请求频率

**代码引用**: `enhanced_ws_manager.py:194-343`

---

## 5. 分析引擎设计

### 5.1 核心算法流程

```mermaid
flowchart TD
    A[收到5m K线推送] --> B{检查黑名单}
    B -->|在黑名单| Z[跳过分析]
    B -->|不在黑名单| C[查询3周期历史数据]

    C --> D[K线连续性校验]
    D -->|有缺失| E[REST API补充数据]
    D -->|完整| F[相关系数前置过滤]
    E --> F

    F -->|相关性 < 阈值| Z
    F -->|相关性 ≥ 阈值| G[多周期协整验证]

    G --> H[Old方法: 全量OLS]
    G --> I[New方法: 双窗口OLS]

    H --> J[3周期 × 2方法 = 6个结果]
    I --> J

    J --> K{协整通过数 ≥ 2?}
    K -->|否| Z
    K -->|是| L[Z-score符号一致性检查]

    L -->|不一致| Z
    L -->|一致| M[Z-score超阈值检查]

    M -->|未超阈值| Z
    M -->|超阈值| N[协整健康状态约束]

    N -->|短期窗口非HEALTHY| Z
    N -->|短期窗口HEALTHY| O[保存分析结果]

    O --> P[发送飞书告警]
    P --> Q[分析完成]
```

**代码引用**: `realtime_kline_service.py:1037-1402`

### 5.2 相关性分析

#### 为什么使用收益率相关性？

```python
# 计算收益率序列（与价格相关性的区别）
base_returns = base_prices.pct_change().dropna()
alt_returns = alt_prices.pct_change().dropna()

# 计算收益率相关系数
correlation = base_returns.corr(alt_returns, method='pearson')
```

**收益率相关性的优势**:

1. **去趋势化**: 消除市场整体涨跌的影响
   - 价格相关性: 受长期趋势主导（牛市都涨 → 高相关）
   - 收益率相关性: 反映短期波动同步性

2. **平稳性**: 收益率序列通常平稳，适合统计建模
   - 价格序列: 非平稳（有趋势）
   - 收益率序列: 近似平稳（零均值）

3. **实战意义**: 反映"基准币涨1%时，目标币涨多少"
   - 更符合配对交易的实际需求

**前置过滤**:
```python
if abs(correlation) < TARGET_CORR_THRESHOLD:
    logger.debug(f"相关性不足 ({correlation:.4f} < {TARGET_CORR_THRESHOLD})，跳过分析")
    return None
```

**代码引用**: `utils/analysis_core.py:83-141`

### 5.3 协整检验 (Engle-Granger)

#### Old方法 - 全量OLS

```python
def calculate_cointegration_params_ols(
    base_klines: List[Dict],
    alt_klines: List[Dict]
) -> Optional[Dict]:
    """
    全量数据OLS协整参数计算（Engle-Granger两步法）

    用途: 事后验证分析
    数据窗口: 全量历史数据
    局限: 存在 look-ahead bias
    """
    # Step 1: OLS回归 log(alt) = α + β * log(base) + ε
    log_base_series = np.log(base_prices)
    log_alt_series = np.log(alt_prices)

    X = sm.add_constant(log_base_series)
    model = sm.OLS(log_alt_series, X).fit()

    alpha = model.params.iloc[0]
    beta = model.params.iloc[1]

    # Step 2: 计算价差
    if use_alpha:
        spread = log_alt_series - (alpha + beta * log_base_series)
    else:
        spread = log_alt_series - beta * log_base_series

    # Step 3: ADF检验价差平稳性
    adf_result = adfuller(spread.values, autolag='AIC')
    adf_pvalue = adf_result[1]

    # Step 4: 判定协整
    is_cointegrated = (adf_pvalue < COINTEGRATION_THRESHOLD)

    return {
        'alpha': alpha,
        'beta': beta,
        'spread': spread,
        'adf_pvalue': adf_pvalue,
        'is_cointegrated': is_cointegrated
    }
```

**局限性**:
- 使用未来数据计算历史OLS参数
- 不适合实时交易决策

**适用场景**:
- 回测验证
- 历史分析

**代码引用**: `utils/analysis_core.py:185-277`

#### New方法 - 双窗口OLS

```python
def calculate_cointegration_params_dual_window(
    base_klines: List[Dict],
    alt_klines: List[Dict],
    beta_window: int = 100,     # OLS回归窗口
    zscore_window: int = 30      # Z-score计算窗口
) -> Optional[Dict]:
    """
    双窗口OLS协整参数计算（实时交易版本）

    用途: 实时交易
    beta_window: 稳定回归参数（100期）
    zscore_window: 敏感均值回归（30期）
    避免 look-ahead bias: 使用前N-1期计算OLS
    """
    # 数据验证
    if len(aligned) < beta_window + zscore_window:
        return None

    # Step 1: 使用前beta_window期计算OLS参数
    ols_data = aligned.iloc[-(beta_window + zscore_window):-zscore_window]

    log_base_ols = np.log(ols_data['base'])
    log_alt_ols = np.log(ols_data['alt'])

    X = sm.add_constant(log_base_ols)
    model = sm.OLS(log_alt_ols, X).fit()

    alpha = model.params.iloc[0]
    beta = model.params.iloc[1]

    # Step 2: 使用最近zscore_window期计算Z-score
    zscore_data = aligned.iloc[-zscore_window:]

    log_base_zscore = np.log(zscore_data['base'])
    log_alt_zscore = np.log(zscore_data['alt'])

    if use_alpha:
        spread = log_alt_zscore - (alpha + beta * log_base_zscore)
    else:
        spread = log_alt_zscore - beta * log_base_zscore

    # Step 3: 计算Z-score（避免样本偏差）
    spread_mean = spread[:-1].mean()
    spread_std = spread[:-1].std()
    current_zscore = (spread.iloc[-1] - spread_mean) / spread_std

    # Step 4: ADF检验价差平稳性
    adf_result = adfuller(spread.values, autolag='AIC')
    adf_pvalue = adf_result[1]

    return {
        'alpha': alpha,
        'beta': beta,
        'zscore': current_zscore,
        'adf_pvalue': adf_pvalue,
        'is_cointegrated': (adf_pvalue < COINTEGRATION_THRESHOLD)
    }
```

**设计优势**:
- **避免look-ahead bias**: 不使用未来数据
- **平衡稳定性与灵敏度**:
  - beta_window=100期: 稳定回归参数，减少过拟合
  - zscore_window=30期: 快速响应价差变化

**参数选择**:
```python
BETA_WINDOW = 100  # 约20天（5m周期）
ZSCORE_WINDOW = 30  # 约6天（5m周期）
```

**代码引用**: `utils/analysis_core.py:280-407`, `utils/config.py:BETA_WINDOW`, `utils/config.py:ZSCORE_WINDOW`

#### 智能模型选择

```python
def _select_cointegration_model(alpha: float, alpha_pvalue: float) -> Tuple[str, bool, str]:
    """
    根据α的显著性和绝对值大小选择最优模型

    规则:
    - |α| > 5.0 且显著 → 无α模型（跨资产类配对，如NEAR/BTC）
    - |α| < 2.0 且显著 → 标准EG模型（同类资产配对，如UNI/SUSHI）
    - 其他 → 无α模型
    """
    if alpha_pvalue < 0.05 and abs(alpha) > 5.0:
        return "no_intercept_forced", False, f"|α|={abs(alpha):.1f}>5.0, 跨资产类配对"

    elif alpha_pvalue < 0.05 and abs(alpha) < 2.0:
        return "standard_EG", True, f"|α|={abs(alpha):.1f}<2.0, 同类资产配对"

    else:
        return "no_intercept", False, "α不显著或中等范围"
```

**设计原理**:
- **跨资产类配对** (如NEAR/BTC): α显著且大 → 使用无α模型
- **同类资产配对** (如UNI/SUSHI): α显著且小 → 使用标准EG模型
- **不确定情况**: 默认无α模型（更稳健）

**代码引用**: `utils/analysis_core.py:149-183`

### 5.4 Z-score计算与异常检测

#### Z-score标准化

```python
# 避免样本偏差: 使用前N-1期计算均值和标准差
spread_mean = spread[:-1].mean()
spread_std = spread[:-1].std()

# 当前Z-score
current_spread = spread.iloc[-1]
current_zscore = (current_spread - spread_mean) / spread_std
```

**避免样本偏差**:
- 不使用当前值计算均值/标准差
- 避免Z-score被当前异常值拉扯

**代码引用**: `utils/analysis_core.py:410-481`

#### 异常检测阈值

```python
ZSCORE_THRESHOLDS = {
    '5m': 1.8,   # 5m周期：敏感度高
    '1h': 1.5,   # 1h周期：中等敏感
    '4h': 0.2,   # 4h周期：低敏感（仅确认趋势）
}
```

**阈值设计原理**:
- **5m周期**: 高频交易，需要明确信号（1.8σ）
- **1h周期**: 中期趋势确认（1.5σ）
- **4h周期**: 长期趋势确认（0.2σ，主要看方向）

**异常判定**:
```python
if abs(zscore) > threshold:
    if zscore > threshold:
        direction = "short"  # 目标币高估，做空配对
    else:
        direction = "long"   # 目标币低估，做多配对
```

**代码引用**: `utils/config.py:ZSCORE_THRESHOLDS`

### 5.5 多周期验证机制

#### 验证流程

```python
def analyze_multi_period(
    symbol: str,
    base_symbol: str,
    klines_data: Dict[str, List[Dict]],  # {'5m': [...], '1h': [...], '4h': [...]}
    required_periods: int = 2
) -> Optional[Dict]:
    """
    多周期协整验证

    验证流程:
    1. 遍历3周期 (5m/7d, 1h/30d, 4h/60d)
    2. 每周期执行 Old+New 协整检验 (共6个结果)
    3. 统计协整通过数 (默认需≥2)
    4. 验证Z-score符号一致性
    5. 验证Z-score超阈值
    """
    cointegration_results = {}
    zscore_results = {}

    # Step 1: 遍历3周期
    for tf in ['5m', '1h', '4h']:
        base_klines = klines_data[tf]['base']
        alt_klines = klines_data[tf]['alt']

        # Old方法: 全量OLS
        old_result = calculate_cointegration_params_ols(base_klines, alt_klines)
        cointegration_results[f'{tf}_old'] = old_result

        # New方法: 双窗口OLS
        new_result = calculate_cointegration_params_dual_window(
            base_klines, alt_klines,
            beta_window=BETA_WINDOW,
            zscore_window=ZSCORE_WINDOW
        )
        cointegration_results[f'{tf}_new'] = new_result
        zscore_results[tf] = new_result['zscore'] if new_result else None

    # Step 2: 统计协整通过数
    passed_count = sum(
        1 for res in cointegration_results.values()
        if res and res.get('is_cointegrated')
    )

    if passed_count < required_periods:
        logger.debug(f"协整通过数不足 ({passed_count} < {required_periods})")
        return None

    # Step 3: Z-score符号一致性检查
    valid_zscores = [z for z in zscore_results.values() if z is not None]
    if len(valid_zscores) < 2:
        return None

    signs = [np.sign(z) for z in valid_zscores]
    if len(set(signs)) > 1:
        logger.debug("Z-score符号不一致，跳过告警")
        return None

    # Step 4: Z-score超阈值检查
    anomaly_flags = {}
    for tf, zscore in zscore_results.items():
        if zscore is not None:
            anomaly_flags[tf] = abs(zscore) > ZSCORE_THRESHOLDS[tf]

    if not any(anomaly_flags.values()):
        logger.debug("所有周期Z-score未超阈值")
        return None

    # Step 5: 返回验证结果
    return {
        'cointegration_passed': True,
        'passed_count': passed_count,
        'zscore_5m': zscore_results['5m'],
        'zscore_1h': zscore_results['1h'],
        'zscore_4h': zscore_results['4h'],
        'is_anomaly': any(anomaly_flags.values()),
        'trading_direction': 'long' if valid_zscores[0] < 0 else 'short'
    }
```

**验证逻辑**:
1. 6个协整检验 (3周期 × 2方法)
2. 协整通过数 ≥ required_periods (默认2)
3. Z-score符号必须一致
4. 至少1个周期Z-score超阈值

**代码引用**: `utils/analysis_core.py:737-996`, `realtime_kline_service.py:1037-1402`

### 5.6 协整健康监控

#### 双窗口健康评分

```python
def calculate_cointegration_health(
    base_klines: List[Dict],
    alt_klines: List[Dict],
    long_window: int = 200,   # 长期窗口
    short_window: int = 100   # 短期窗口
) -> Dict:
    """
    协整健康监控（双窗口评分机制）

    评分指标:
    - ADF p值: 40% (越小越好)
    - 半衰期: 30% (适中最好)
    - 稳定性: 30% (越稳定越好)

    健康状态:
    - HEALTHY: 评分 ≥ 18
    - WARNING: 评分 ∈ [14, 18)
    - CRITICAL: 评分 < 14
    """
    # 长期窗口评分
    long_data = aligned.iloc[-long_window:]
    long_score = _calculate_health_score(long_data)

    # 短期窗口评分
    short_data = aligned.iloc[-short_window:]
    short_score = _calculate_health_score(short_data)

    # 健康状态判定
    short_state = _get_health_state(short_score)
    long_state = _get_health_state(long_score)

    return {
        'long_window_score': long_score,
        'long_window_state': long_state,
        'short_window_score': short_score,
        'short_window_state': short_state
    }

def _calculate_health_score(data: pd.DataFrame) -> float:
    """
    健康评分计算

    评分公式:
    - ADF p值评分: (1 - min(p_value, 1.0)) * 40
    - 半衰期评分: gaussian(half_life, optimal=20, sigma=10) * 30
    - 稳定性评分: (1 - cv) * 30
    """
    # 1. ADF p值评分 (40%)
    adf_pvalue = adfuller(spread.values)[1]
    adf_score = (1 - min(adf_pvalue, 1.0)) * 40

    # 2. 半衰期评分 (30%)
    half_life = calculate_half_life(spread)
    half_life_score = gaussian_score(half_life, optimal=20, sigma=10) * 30

    # 3. 稳定性评分 (30%)
    coefficient_of_variation = spread.std() / abs(spread.mean())
    stability_score = (1 - min(coefficient_of_variation, 1.0)) * 30

    total_score = adf_score + half_life_score + stability_score
    return total_score

def _get_health_state(score: float) -> str:
    """健康状态判定"""
    if score >= 18:
        return "HEALTHY"
    elif score >= 14:
        return "WARNING"
    else:
        return "CRITICAL"
```

**告警约束**:
```python
# 仅当短期窗口健康时才发送告警
if health_result['short_window_state'] != "HEALTHY":
    logger.debug(f"协整健康状态不佳 ({health_result['short_window_state']})，跳过告警")
    return None
```

**设计原理**:
- 避免协整关系恶化时的虚假信号
- 双窗口监控: 长期趋势 + 短期状态
- 短期状态优先: 告警约束

**代码引用**: `utils/coingetation_more_check.py`

---

## 6. 并发架构设计

### 6.1 线程模型

#### 线程清单

| 线程名称 | 数量 | 职责 | 启动方式 |
|---------|------|------|---------|
| WebSocket主线程 | 1 | 运行 `WebSocket.run_forever()` | `threading.Thread` |
| Ping线程 | 1 | 每5秒发送ping保活 | `threading.Thread` |
| 健康监控线程 | 1 | 每2秒检查连接健康 | `threading.Thread` |
| batch_writer线程 | 1 | K线批量写入TimescaleDB | `threading.Thread` |
| analysis_worker线程 | 15 | 并发执行分析任务 | `threading.Thread` × 15 |
| result_batch_writer线程 | 1 | 分析结果批量写入 | `threading.Thread` |
| queue_monitor线程 | 1 | 队列使用率监控 | `threading.Thread` |
| new_symbol_monitor线程 | 1 | 新币种监控 | `threading.Thread` |

**总线程数**: 22个线程

**代码引用**: `realtime_kline_service.py:224-275`, `enhanced_ws_manager.py:501-597`

#### 线程生命周期管理

```python
# 线程启动
def start_service(self):
    """启动所有服务线程"""
    # 1. WebSocket线程（由EnhancedWebSocketManager管理）
    self.ws_manager.start()

    # 2. 批量写入线程
    self.batch_writer_thread = threading.Thread(
        target=self._batch_writer,
        name="KlineBatchWriter",
        daemon=True
    )
    self.batch_writer_thread.start()

    # 3. 分析工作线程池
    self.analysis_threads = []
    for i in range(ANALYSIS_WORKERS_GENERAL):
        t = threading.Thread(
            target=self._analysis_worker,
            name=f"AnalysisWorker-{i}",
            daemon=True
        )
        t.start()
        self.analysis_threads.append(t)

    # 4. 分析结果写入线程
    self.result_writer_thread = threading.Thread(
        target=self._analysis_result_batch_writer,
        name="ResultBatchWriter",
        daemon=True
    )
    self.result_writer_thread.start()

    # 5. 队列监控线程
    self.queue_monitor_thread = threading.Thread(
        target=self._queue_health_monitor,
        name="QueueMonitor",
        daemon=True
    )
    self.queue_monitor_thread.start()

    # 6. 新币种监控线程
    self.new_symbol_monitor_thread = threading.Thread(
        target=self._new_symbol_monitor,
        name="NewSymbolMonitor",
        daemon=True
    )
    self.new_symbol_monitor_thread.start()

    logger.info("所有服务线程已启动")

# 线程停止
def stop_service(self):
    """停止所有服务线程"""
    logger.info("开始停止服务...")

    # 1. 设置停止标志
    self.stop_event.set()

    # 2. 停止WebSocket连接
    self.ws_manager.stop()

    # 3. 等待工作线程退出（超时保护）
    for t in self.analysis_threads:
        t.join(timeout=WORKER_THREAD_SHUTDOWN_TIMEOUT)

    # 4. 等待批量写入线程退出
    self.batch_writer_thread.join(timeout=WORKER_THREAD_SHUTDOWN_TIMEOUT)
    self.result_writer_thread.join(timeout=WORKER_THREAD_SHUTDOWN_TIMEOUT)

    logger.info("服务已停止")
```

**daemon线程**:
- 所有工作线程设置为daemon=True
- 主线程退出时自动终止所有daemon线程
- 超时保护: join(timeout=30s)

**代码引用**: `realtime_kline_service.py:224-275`, `realtime_kline_service.py:1589-1659`

### 6.2 队列设计

#### 队列清单

| 队列名称 | 大小 | 类型 | 写入者 | 读取者 | 批量触发条件 |
|---------|------|------|-------|-------|-------------|
| kline_buffer | 10000 | queue.Queue | on_message | batch_writer | 1000条 OR 5秒 |
| analysis_queue | 15000 | queue.Queue | on_message (5m) | 15×analysis_worker | 实时消费 |
| analysis_result_buffer | 10000 | queue.Queue | 15×analysis_worker | result_batch_writer | 100条 OR 2秒 |

**代码引用**: `realtime_kline_service.py:208-220`

#### 队列配置

```python
# 队列配置（从配置文件读取）
QUEUE_CONFIG_GENERAL = {
    'kline_buffer_size': 10000,
    'analysis_queue_size': 15000,
    'analysis_result_buffer_size': 10000
}

# 队列初始化
self.kline_buffer = queue.Queue(maxsize=QUEUE_CONFIG_GENERAL['kline_buffer_size'])
self.analysis_queue = queue.Queue(maxsize=QUEUE_CONFIG_GENERAL['analysis_queue_size'])
self.analysis_result_buffer = queue.Queue(maxsize=QUEUE_CONFIG_GENERAL['analysis_result_buffer_size'])
```

**队列大小设计原则**:
- kline_buffer: 10000条 ≈ 5分钟缓冲（N个币种 × 3周期）
- analysis_queue: 15000条 ≈ 15分钟缓冲（考虑分析耗时）
- analysis_result_buffer: 10000条 ≈ 批量写入缓冲

**代码引用**: `utils/config.py:QUEUE_CONFIG_GENERAL`, `realtime_kline_service.py:208-220`

### 6.3 去重机制

#### TTLCache去重

```python
from cachetools import TTLCache

# 入队去重字典（线程安全，避免重复入队）
self.recent_enqueue = TTLCache(maxsize=10000, ttl=1800)  # 30分钟TTL
self.recent_enqueue_lock = threading.Lock()

# 分析去重字典（跨线程共享，避免重复分析）
self.recent_analysis = TTLCache(maxsize=10000, ttl=1800)
self.recent_analysis_lock = threading.Lock()
```

**TTLCache特性**:
- 自动过期: 1800秒 (30分钟)
- 最大容量: 10000条
- 防止内存泄漏: 自动清理过期记录

**代码引用**: `realtime_kline_service.py:193-205`

#### 入队去重窗口

```python
ENQUEUE_DEDUP_WINDOWS = {
    '5m': 30,    # 5m周期: 30秒去重窗口
    '1h': 180,   # 1h周期: 180秒去重窗口
    '4h': 600,   # 4h周期: 600秒去重窗口
}

def _enqueue_analysis_if_needed(self, symbol: str, timeframe: str, kline_time: datetime):
    """入队去重检查"""
    with self.recent_enqueue_lock:
        key = (symbol, timeframe, kline_time)
        if key in self.recent_enqueue:
            logger.debug(f"入队去重: {key} 在{ENQUEUE_DEDUP_WINDOWS[timeframe]}秒内已入队")
            return False

        # 添加到去重字典
        self.recent_enqueue[key] = time.time()

        # 入队
        try:
            self.analysis_queue.put_nowait({
                'symbol': symbol,
                'timeframe': timeframe,
                'kline_time': kline_time
            })
            return True
        except queue.Full:
            logger.warning("分析队列已满，跳过入队")
            return False
```

**去重窗口设计**:
- 5m周期: 30秒 (约1/10周期)
- 1h周期: 180秒 (约1/20周期)
- 4h周期: 600秒 (约1/24周期)

**代码引用**: `utils/config.py:ENQUEUE_DEDUP_WINDOWS`, `realtime_kline_service.py:575-633`

#### 分析去重窗口

```python
DEDUP_WINDOWS = {
    '5m': 60,    # 5m周期: 60秒去重窗口
    '1h': 300,   # 1h周期: 300秒去重窗口
    '4h': 900,   # 4h周期: 900秒去重窗口
}

def _analyze_and_alert(self, task: Dict):
    """分析去重检查"""
    symbol = task['symbol']
    timeframe = task['timeframe']
    kline_time = task['kline_time']

    with self.recent_analysis_lock:
        key = (symbol, timeframe, kline_time)
        if key in self.recent_analysis:
            logger.debug(f"分析去重: {key} 在{DEDUP_WINDOWS[timeframe]}秒内已分析")
            return None

        # 添加到去重字典
        self.recent_analysis[key] = time.time()

    # 执行分析
    result = analyze_multi_period(...)
    return result
```

**去重窗口设计**:
- 5m周期: 60秒 (约1/5周期)
- 1h周期: 300秒 (约1/12周期)
- 4h周期: 900秒 (约1/16周期)

**跨线程共享**:
- 所有analysis_worker共享同一`recent_analysis`字典
- 使用`recent_analysis_lock`保证线程安全

**代码引用**: `utils/config.py:DEDUP_WINDOWS`, `realtime_kline_service.py:1037-1402`

### 6.4 同步与锁策略

#### RLock (递归锁)

```python
# symbols列表保护
self.symbols_lock = threading.RLock()

with self.symbols_lock:
    self.symbols.append(new_symbol)

# subscriptions列表保护
self.subscriptions_lock = threading.RLock()

with self.subscriptions_lock:
    self.subscriptions.extend(new_subscriptions)

# WebSocket状态保护
self.state_lock = threading.RLock()

with self.state_lock:
    self.state = ConnectionState.CONNECTED

# 数据缓存保护
self.latest_data_lock = threading.RLock()

with self.latest_data_lock:
    self.latest_data["candles"][(symbol, timeframe)] = kline_dict
```

**RLock特性**:
- 递归锁: 同一线程可多次获取
- 适用场景: 嵌套调用、复杂操作

**代码引用**: `enhanced_ws_manager.py:194-343`, `realtime_kline_service.py:183-189`

#### threading.Lock

```python
# 入队去重保护
self.recent_enqueue_lock = threading.Lock()

with self.recent_enqueue_lock:
    self.recent_enqueue[key] = time.time()

# 分析去重保护
self.recent_analysis_lock = threading.Lock()

with self.recent_analysis_lock:
    self.recent_analysis[key] = time.time()

# 黑名单保护
self.blacklist_lock = threading.Lock()

with self.blacklist_lock:
    self.new_symbol_blacklist.add(symbol)
```

**Lock特性**:
- 简单锁: 不可递归
- 适用场景: 简单临界区保护

**代码引用**: `realtime_kline_service.py:193-205`

#### threading.Event

```python
# 全局停止信号
self.stop_event = threading.Event()

# 检查停止信号
if self.stop_event.is_set():
    break

# 停止服务
self.stop_event.set()

# WebSocket就绪标志
self.ws_ready_event = threading.Event()

# 等待连接就绪
self.ws_ready_event.wait(timeout=30)

# 设置就绪标志
self.ws_ready_event.set()

# Ping线程停止信号
self.stop_ping = threading.Event()

# 停止Ping线程
self.stop_ping.set()
```

**Event特性**:
- 信号机制: wait/set
- 适用场景: 线程间通信、同步

**代码引用**: `realtime_kline_service.py:207`, `enhanced_ws_manager.py:501-597`

### 6.5 批量写入优化

#### COPY批量写入

```python
def batch_upsert_copy(self, klines: List[Dict]) -> int:
    """
    使用COPY命令批量写入K线数据（高性能版本）

    性能: >40000条/秒 (比executemany快100倍)

    流程:
    1. 创建临时表 (ON COMMIT DROP)
    2. COPY数据到临时表 (CSV格式)
    3. INSERT ... ON CONFLICT ... DO UPDATE
    4. 自动清理临时表
    """
    with self.db_client.get_connection() as conn:
        with conn.cursor() as cur:
            # Step 1: 创建临时表
            cur.execute("""
                CREATE TEMP TABLE temp_klines (
                    time TIMESTAMPTZ,
                    symbol VARCHAR(50),
                    timeframe VARCHAR(10),
                    open DOUBLE PRECISION,
                    high DOUBLE PRECISION,
                    low DOUBLE PRECISION,
                    close DOUBLE PRECISION,
                    volume DOUBLE PRECISION,
                    volume_usd DOUBLE PRECISION,
                    return_pct DOUBLE PRECISION
                ) ON COMMIT DROP;
            """)

            # Step 2: COPY数据到临时表
            csv_buffer = StringIO()
            for kline in klines:
                csv_buffer.write(
                    f"{kline['time']}\t{kline['symbol']}\t{kline['timeframe']}\t"
                    f"{kline['open']}\t{kline['high']}\t{kline['low']}\t"
                    f"{kline['close']}\t{kline['volume']}\t{kline['volume_usd']}\t"
                    f"{kline['return_pct']}\n"
                )
            csv_buffer.seek(0)

            with cur.copy("COPY temp_klines FROM STDIN") as copy:
                copy.write(csv_buffer.read())

            # Step 3: INSERT ... ON CONFLICT ... DO UPDATE
            cur.execute("""
                INSERT INTO klines (time, symbol, timeframe, open, high, low, close, volume, volume_usd, return_pct)
                SELECT * FROM temp_klines
                ON CONFLICT (time, symbol, timeframe)
                DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    volume_usd = EXCLUDED.volume_usd,
                    return_pct = EXCLUDED.return_pct
            """)

            conn.commit()
            return len(klines)
```

**性能对比**:
| 方法 | 性能 | 适用场景 |
|------|------|----------|
| executemany | ~1000条/秒 | 小批量 |
| COPY | >40000条/秒 | 大批量 |

**优化技巧**:
- StringIO缓冲区: 避免磁盘I/O
- 临时表: ON COMMIT DROP自动清理
- 批量排序: 减少锁竞争

**代码引用**: `timescaledb.py:342-450`

#### 死锁防护

```python
def _batch_writer(self):
    """K线批量写入线程（死锁防护）"""
    batch = []
    last_flush_time = time.time()

    while not self.stop_event.is_set():
        try:
            # 批量获取队列数据
            while len(batch) < DEFAULT_BATCH_SIZE:
                kline = self.kline_buffer.get_nowait()
                batch.append(kline)
        except queue.Empty:
            pass

        # 批量触发条件
        if len(batch) >= DEFAULT_BATCH_SIZE or \
           (batch and time.time() - last_flush_time >= DEFAULT_BATCH_TIMEOUT):

            # 去重
            dedup_batch = self._deduplicate_batch(batch)

            # 关键: 批量排序，保证锁获取顺序一致
            dedup_batch = sorted(
                dedup_batch,
                key=lambda x: (x['time'], x['symbol'], x['timeframe'])
            )

            # 批量写入（死锁重试）
            success = self._batch_write_with_retry(dedup_batch, max_retries=5)

            if success:
                batch.clear()
                last_flush_time = time.time()

        time.sleep(0.1)

def _batch_write_with_retry(self, batch: List[Dict], max_retries: int = 5) -> bool:
    """批量写入（死锁重试）"""
    for attempt in range(max_retries):
        try:
            self.kline_repo.batch_upsert_copy(batch)
            return True
        except psycopg.errors.DeadlockDetected as e:
            if attempt < max_retries - 1:
                wait_time = 0.1 * (2 ** attempt) * (1 + random.random() * 0.5)
                logger.warning(f"死锁检测，第{attempt+1}次重试，等待{wait_time:.2f}秒")
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"死锁重试{max_retries}次后仍然失败")
                return False
        except Exception as e:
            logger.error(f"批量写入失败: {e}")
            return False
```

**死锁防护策略**:
1. **批量排序**: 保证锁获取顺序一致
2. **指数退避重试**: 最大5次，递增等待时间
3. **随机抖动**: 避免重试冲突

**代码引用**: `realtime_kline_service.py:635-760`, `realtime_kline_service.py:294-373`

---

## 7. 性能优化设计

### 7.1 批量写入对比

#### 性能测试结果

| 方法 | 性能 | 1000条耗时 | 10000条耗时 | 适用场景 |
|------|------|----------|-----------|----------|
| executemany (单条INSERT) | ~1000条/秒 | ~1.0s | ~10s | 小批量 (<100条) |
| executemany (批量INSERT) | ~5000条/秒 | ~0.2s | ~2s | 中批量 (100-1000条) |
| **COPY (临时表)** | **>40000条/秒** | **~0.025s** | **~0.25s** | **大批量 (>1000条)** |

**性能提升**: COPY方法比executemany快40-100倍

**代码引用**: `timescaledb.py:342-450`

#### COPY优化技巧

```python
# 1. StringIO缓冲区（避免磁盘I/O）
csv_buffer = StringIO()
for kline in klines:
    csv_buffer.write(f"{kline['time']}\t{kline['symbol']}\t...\n")
csv_buffer.seek(0)

# 2. 临时表（ON COMMIT DROP自动清理）
CREATE TEMP TABLE temp_klines (...) ON COMMIT DROP;

# 3. 批量排序（减少锁竞争）
dedup_batch = sorted(
    dedup_batch,
    key=lambda x: (x['time'], x['symbol'], x['timeframe'])
)
```

**代码引用**: `timescaledb.py:342-450`, `realtime_kline_service.py:635-760`

### 7.2 缓存策略

#### TTLCache自动清理

```python
from cachetools import TTLCache

# 去重缓存（自动过期）
self.recent_enqueue = TTLCache(maxsize=10000, ttl=1800)  # 30分钟TTL
self.recent_analysis = TTLCache(maxsize=10000, ttl=1800)

# WebSocket数据缓存
self.latest_data = {
    "candles": {},   # {(symbol, timeframe): kline_dict}
    "l2Book": {},    # {symbol: orderbook_dict}
    "trades": {},    # {symbol: [trade_list]}
}
```

**TTLCache优势**:
- 自动过期: 1800秒 (30分钟)
- 最大容量: 10000条
- 防止内存泄漏: 自动清理过期记录

**代码引用**: `realtime_kline_service.py:193-205`, `enhanced_ws_manager.py:194-343`

#### 定时清理任务

```python
def _cleanup_recent_tasks(self):
    """定时清理去重字典（防御性编程）"""
    while not self.stop_event.is_set():
        time.sleep(CLEANUP_INTERVAL)  # 300秒

        with self.recent_enqueue_lock:
            if len(self.recent_enqueue) > MAX_RECENT_TASKS:
                logger.warning(f"入队去重字典超过阈值 ({len(self.recent_enqueue)} > {MAX_RECENT_TASKS})，触发清理")
                # TTLCache会自动清理，这里只是监控

        with self.recent_analysis_lock:
            if len(self.recent_analysis) > MAX_RECENT_TASKS:
                logger.warning(f"分析去重字典超过阈值 ({len(self.recent_analysis)} > {MAX_RECENT_TASKS})，触发清理")
```

**清理策略**:
- 定时检查: 每300秒
- 硬性上限: MAX_RECENT_TASKS=5000
- 监控告警: 超过阈值触发清理

**代码引用**: `utils/config.py:CLEANUP_INTERVAL`, `utils/config.py:MAX_RECENT_TASKS`

### 7.3 数据库查询优化

#### 索引优化

```sql
-- 覆盖最常用查询路径
CREATE INDEX idx_klines_symbol_timeframe_time
ON klines (symbol, timeframe, time DESC);

-- 查询示例（走索引）
SELECT * FROM klines
WHERE symbol = 'BTC/USDC:USDC'
  AND timeframe = '1h'
  AND time >= NOW() - INTERVAL '30 days'
ORDER BY time DESC
LIMIT 10000;
```

**索引命中率**: >95%

**代码引用**: `init_timescaledb.sql:123-128`

#### 查询限制

```python
DB_QUERY_LIMIT = 10000  # 单次查询最大返回条数

def get_klines_by_timeframe(
    self,
    symbol: str,
    timeframe: str,
    start_time: datetime,
    end_time: datetime
) -> List[Dict]:
    """查询K线数据（限制返回条数）"""
    query = """
        SELECT * FROM klines
        WHERE symbol = %s
          AND timeframe = %s
          AND time >= %s
          AND time <= %s
        ORDER BY time DESC
        LIMIT %s
    """
    params = (symbol, timeframe, start_time, end_time, DB_QUERY_LIMIT)

    with self.db_client.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            return [dict(row) for row in rows]
```

**查询保护**:
- 单次查询最大10000条
- 防止OOM
- 超过限制返回截断数据

**代码引用**: `utils/config.py:DB_QUERY_LIMIT`, `timescaledb.py:487-589`

### 7.4 内存管理

#### 内存占用监控

```python
import psutil

def _monitor_memory_usage(self):
    """内存占用监控"""
    process = psutil.Process()
    memory_info = process.memory_info()

    logger.info(
        f"内存占用: RSS={memory_info.rss / 1024 / 1024:.2f}MB, "
        f"VMS={memory_info.vms / 1024 / 1024:.2f}MB"
    )

    # 告警阈值: 512MB
    if memory_info.rss > 512 * 1024 * 1024:
        logger.warning("内存占用超过512MB，建议检查内存泄漏")
```

**内存优化**:
- TTLCache自动清理
- 队列大小限制
- 定时清理任务

**代码引用**: `realtime_kline_service.py:1713-1785`

### 7.5 性能指标与监控

#### 目标指标

| 指标 | 目标值 | 实际值 | 监控方式 |
|------|--------|--------|---------|
| 分析延迟 | <5秒 | ~3秒 | `analysis_delay_seconds` |
| 告警延迟 | <10秒 | ~8秒 | 飞书响应时间 |
| 内存占用 | <512MB | ~300MB | `psutil.Process().memory_info()` |
| CPU占用 | <50% | ~30% | `psutil.cpu_percent()` |
| 批量写入性能 | >10K条/秒 | >40K条/秒 | COPY命令性能测试 |

**代码引用**: `realtime_kline_service.py:27-31`

#### 实时统计

```python
self.stats = {
    'messages_received': 0,         # WebSocket消息总数
    'klines_written': 0,            # K线写入总数
    'analyses_completed': 0,        # 分析完成总数
    'analyses_failed': 0,           # 分析失败总数
    'alerts_sent': 0,               # 告警发送总数
    'uptime_seconds': 0,            # 服务运行时长
    'queue_kline_size': 0,          # K线队列大小
    'queue_analysis_size': 0,       # 分析队列大小
    'queue_result_size': 0          # 结果队列大小
}

def get_stats(self) -> Dict:
    """获取实时统计信息"""
    self.stats['uptime_seconds'] = time.time() - self.start_time
    self.stats['queue_kline_size'] = self.kline_buffer.qsize()
    self.stats['queue_analysis_size'] = self.analysis_queue.qsize()
    self.stats['queue_result_size'] = self.analysis_result_buffer.qsize()
    return self.stats
```

**代码引用**: `realtime_kline_service.py:1661-1711`

#### 队列使用率监控

```python
def _queue_health_monitor(self):
    """队列使用率监控（每60秒）"""
    while not self.stop_event.is_set():
        time.sleep(QUEUE_MONITOR_INTERVAL)  # 60秒

        kline_usage = self.kline_buffer.qsize() / QUEUE_CONFIG_GENERAL['kline_buffer_size']
        analysis_usage = self.analysis_queue.qsize() / QUEUE_CONFIG_GENERAL['analysis_queue_size']
        result_usage = self.analysis_result_buffer.qsize() / QUEUE_CONFIG_GENERAL['analysis_result_buffer_size']

        logger.info(
            f"队列使用率 | K线: {kline_usage*100:.1f}% | "
            f"分析: {analysis_usage*100:.1f}% | "
            f"结果: {result_usage*100:.1f}%"
        )

        # 告警阈值: 80%
        if kline_usage > QUEUE_WARNING_THRESHOLD:
            logger.warning(f"K线队列使用率超过{QUEUE_WARNING_THRESHOLD*100}%，建议增加批量写入频率")
        if analysis_usage > QUEUE_WARNING_THRESHOLD:
            logger.warning(f"分析队列使用率超过{QUEUE_WARNING_THRESHOLD*100}%，建议增加工作线程数")
        if result_usage > QUEUE_WARNING_THRESHOLD:
            logger.warning(f"结果队列使用率超过{QUEUE_WARNING_THRESHOLD*100}%，建议检查数据库性能")
```

**监控指标**:
- 队列使用率: 每60秒输出
- 告警阈值: 80%
- 优化建议: 自动生成

**代码引用**: `realtime_kline_service.py:1452-1539`, `utils/config.py:QUEUE_MONITOR_INTERVAL`, `utils/config.py:QUEUE_WARNING_THRESHOLD`

---

