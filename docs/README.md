# TimescaleDB实时套利信号分析系统 - 设计文档索引

## 📚 文档结构

本目录包含TimescaleDB实时套利信号分析系统的完整模块化设计文档，支持独立开发、测试和部署。

### 📋 总览文档

**[DESIGN_OVERVIEW.md](DESIGN_OVERVIEW.md)** - 总体设计概览
- 项目概述和技术栈
- 系统架构图（实时分析架构）
- 模块拆分和依赖关系
- 实施路线图和性能预期

---

## 🔧 核心模块（P0，按实施顺序）

### 1️⃣ [MODULE1_DATABASE_INFRASTRUCTURE.md](MODULE1_DATABASE_INFRASTRUCTURE.md)

**数据库基础设施模块**

- **职责**: TimescaleDB容器部署、Schema初始化、表结构创建
- **交付物**:
  - `docker-compose.yml`
  - `init_timescaledb.sql`
  - `.env.example`
- **依赖**: 无（基础模块）
- **预计时间**: 30分钟
- **优先级**: P0 (核心)

**关键内容**:
- 3张表设计（klines, symbol_metadata, analysis_results）
- Hypertable自动分区（7天chunk）
- 数据保留策略（90天）
- 压缩策略（7天后自动压缩）

---

### 2️⃣ [MODULE2_DATABASE_ACCESS_LAYER.md](MODULE2_DATABASE_ACCESS_LAYER.md)

**数据库访问层模块**

- **职责**: 连接池管理、CRUD操作、COPY命令批量写入优化
- **交付物**:
  - `utils/timescaledb.py`
  - `tests/test_timescaledb.py`
- **依赖**: 模块1
- **预计时间**: 2小时
- **优先级**: P0 (核心)

**关键内容**:
- TimescaleDBClient（连接池管理）
- KlineRepository（COPY命令批量写入，10-100x性能提升）
- SymbolMetadataRepository（动态币种管理）
- AnalysisResultRepository（分析结果持久化）

---

### 3️⃣ [MODULE3_REALTIME_DATAFLOW.md](MODULE3_REALTIME_DATAFLOW.md) ⭐

**实时分析引擎模块（主分析引擎）**

- **核心职责**:
  - WebSocket实时K线接收（仅5m/1h/4h周期）
  - **收到5m K线WebSocket推送后触发分析**（受去重保护：30s入队/60s分析，延迟<1分钟）
  - 调用utils/analysis_core.py进行相关性、协整、Z-score分析
  - Z-score异常检测与飞书实时告警
  - 批量写入TimescaleDB
  - 动态币种订阅和新币种监控
- **交付物**:
  - `realtime_kline_service.py`（主分析引擎，完全替代multi_coins.py）
  - `utils/analysis_core.py`（公共分析模块，从multi_coins.py提取）
  - `Dockerfile.realtime`
  - `tests/test_realtime_service.py`
- **依赖**: 模块1、模块2
- **预计时间**: 6小时
- **优先级**: P0 (核心，主分析引擎)

**关键内容**:
- WebSocket订阅600个频道（200币种 × 3周期：5m/1h/4h）
- 实时分析流程：on_message() → 写入DB（异步） + 分析（同步）
- utils/analysis_core.py公共函数：calculate_correlation(), check_cointegration(), calculate_zscore(), detect_anomaly()
- 分析频率：12次/分钟 = 8(5m) + 3.3(1h) + 0.83(4h)
- 飞书实时告警集成
- 缓冲队列+异步批量写入线程

**架构变更**:
- v1.0: 模块3为P1可选（仅数据收集）
- v2.0: 模块3升级为P0核心（主分析引擎）✅

---

## 🔧 可选模块（P1）

### 4️⃣ [MODULE4_ANALYSIS_ENGINE_INTEGRATION.md](MODULE4_ANALYSIS_ENGINE_INTEGRATION.md)

**multi_coins.py改造指南（可选）**

- **定位**: 批量历史回测工具（可选改造）
- **职责**: multi_coins.py改造支持数据库查询（仅在需要批量回测时实施）
- **交付物**:
  - 修改后的 `multi_coins.py`（可选）
  - `tests/test_integration.py`
- **依赖**: 模块1、模块2
- **预计时间**: 2小时
- **优先级**: P1 (可选，仅用于批量回测)

**说明**:
- multi_coins.py可保持原样作为备用工具
- 仅在需要批量历史回测时实施此模块
- 主分析引擎已由模块3的realtime_kline_service.py实现

**关键内容**:
- `__init__()` 改造：数据库连接初始化
- `download_ccxt_data()` 改造：智能增量更新（API调用减少70%）
- `one_coin_analysis()` 改造：分析结果自动保存
- 降级策略：数据库不可用时自动降级

---

### 5️⃣ [MODULE5_CONFIGURATION_DEPLOYMENT.md](MODULE5_CONFIGURATION_DEPLOYMENT.md)

**配置和部署模块（可选）**

- **职责**: 环境变量配置、依赖管理、部署文档
- **交付物**:
  - `utils/config.py`（新增TimescaleDB配置）
  - `pyproject.toml`（新增psycopg依赖）
  - `README_REALTIME.md`（部署指南）
  - `scripts/verify_deployment.sh`（部署验证脚本）
- **依赖**: 核心模块（1、2、3）
- **预计时间**: 1小时
- **优先级**: P1 (可选)

**关键内容**:
- 环境变量配置（.env.example）
- 依赖声明（psycopg, psycopg-pool）
- Docker Compose整合配置
- 一键部署验证脚本

---

## 📖 运维和优化文档

### 🛠️ [PRODUCTION_OPERATIONS.md](PRODUCTION_OPERATIONS.md) ⭐ (v2.2 新增)

**生产环境运维指南**

- **内容**:
  - 实时监控命令和告警阈值
  - 故障排查清单（WebSocket、死锁、时区、数据质量、性能）
  - 性能优化建议（数据库层面、应用层面）
  - 常见问题FAQ
  - 备份和恢复

**适用场景**:
- 系统部署后的日常监控
- 故障诊断和快速恢复
- 性能瓶颈分析和优化
- 数据质量保障

---

### 🚀 [OPTIMIZATION_ROADMAP.md](OPTIMIZATION_ROADMAP.md)

**性能优化路线图**

- **已完成**:
  - ✅ Phase 1.5: 多线程分析、差异化去重、死锁修复、时区优化、增强型WebSocket管理器
  - 生产验证: 连续运行7天，死锁频率降低90%，CPU占用降低30%

- **规划中**:
  - Phase 2: 全异步架构（asyncio + asyncpg）
  - 触发条件: 支持>500币种或需要毫秒级延迟

---

## 📊 实施路线图

### Phase 1-3: 核心系统（P0，总计8.5小时）

```
Phase 1: 模块1（数据库基础设施）- 30分钟
Phase 2: 模块2（数据库访问层）- 2小时
Phase 3: 模块3（实时分析引擎）- 6小时 ⭐
  ├─ 3.1: 提取utils/analysis_core.py - 1小时
  ├─ 3.2: WebSocket数据接收和批量写入 - 2小时
  ├─ 3.3: 实时分析逻辑集成 - 2小时
  └─ 3.4: 飞书告警和测试 - 1小时
```

**核心验收标准**:
- [ ] Docker一键部署成功
- [ ] WebSocket订阅600个频道（200币种 × 3周期: 5m/1h/4h）
- [ ] 收到5m K线WebSocket推送后触发实时分析（受去重保护，延迟<5秒）
- [ ] utils/analysis_core.py单元测试通过
- [ ] Z-score异常检测正确，飞书告警及时
- [ ] 服务稳定运行24小时无崩溃

**关键里程碑**: Phase 3完成后，实时分析系统即可上线运行

---

### Phase 4-5: 可选功能（P1，总计3小时）

```
Phase 4: 模块5（配置和部署）- 1小时（可选）
Phase 5: 模块4（multi_coins.py改造）- 2小时（可选）
```

**可选验收标准**:
- [ ] 批量回测功能正常（如需要）
- [ ] API调用次数减少70%+（批量模式）
- [ ] 部署文档完整

---

## 🎯 性能目标

| 指标 | 基准值 (批量分析) | 目标值 (实时分析) | 改善幅度 |
|------|------------------|------------------|----------|
| **分析延迟** | 5-10分钟 | <5秒 | -99% |
| **分析频率** | 每几小时 | 12次/分钟 | 实时 |
| **告警延迟** | 无实时告警 | <10秒 | N/A |
| **数据库写入** | N/A | >1000条/秒 | N/A |
| **DB查询耗时** | N/A | <100ms | N/A |
| **WebSocket延迟** | N/A | <500ms | N/A |
| **内存占用** | ~500MB | ~512MB | 稳定 |

---

## 🔗 快速导航

### 按开发阶段

1. **规划阶段** → [DESIGN_OVERVIEW.md](DESIGN_OVERVIEW.md)
2. **核心开发** → Phase 1→2→3（模块1→2→3）⭐
3. **可选功能** → Phase 4→5（模块5→4）
4. **部署阶段** → [MODULE5](MODULE5_CONFIGURATION_DEPLOYMENT.md) → README_REALTIME.md

### 按技术领域

- **数据库设计** → [MODULE1](MODULE1_DATABASE_INFRASTRUCTURE.md)
- **性能优化** → [MODULE2](MODULE2_DATABASE_ACCESS_LAYER.md)（COPY命令、死锁重试、时区处理）
- **实时分析引擎** → [MODULE3](MODULE3_REALTIME_DATAFLOW.md) ⭐（主引擎、增强型WebSocket）
- **批量回测** → [MODULE4](MODULE4_ANALYSIS_ENGINE_INTEGRATION.md)（可选）
- **运维部署** → [MODULE5](MODULE5_CONFIGURATION_DEPLOYMENT.md)（可选）
- **生产运维** → [PRODUCTION_OPERATIONS.md](PRODUCTION_OPERATIONS.md) ⭐（监控告警、故障排查）
- **优化路线** → [OPTIMIZATION_ROADMAP.md](OPTIMIZATION_ROADMAP.md)（Phase 1.5完成、Phase 2规划）

### 按模块优先级

- **P0核心模块**: MODULE1 → MODULE2 → MODULE3
- **P1可选模块**: MODULE4, MODULE5
- **运维文档**: PRODUCTION_OPERATIONS, OPTIMIZATION_ROADMAP

---

## 📞 技术支持

- **问题反馈**: GitHub Issues
- **文档更新**: 2026-01-29
- **版本**: v2.2（生产环境优化）
- **作者**: Claude Sonnet 4.5

---

## 🚀 快速开始

**推荐实施路径**：

1. **阅读总览**: [DESIGN_OVERVIEW.md](DESIGN_OVERVIEW.md) - 理解整体架构
2. **核心实施**:
   - Phase 1: [MODULE1](MODULE1_DATABASE_INFRASTRUCTURE.md) - 数据库基础设施（30分钟）
   - Phase 2: [MODULE2](MODULE2_DATABASE_ACCESS_LAYER.md) - 数据库访问层（2小时）
   - Phase 3: [MODULE3](MODULE3_REALTIME_DATAFLOW.md) - 实时分析引擎（6小时）⭐
3. **系统上线**: Phase 3完成后即可运行实时分析系统
4. **可选增强**: 根据需要实施MODULE4（批量回测）和MODULE5（配置部署）

**关键变更**:

**v2.0 核心架构**:
- ✅ 实时分析替代批量分析
- ✅ 收到5m K线WebSocket推送后触发分析（受去重保护，延迟<1分钟）
- ✅ 订阅5m/1h/4h周期（节省90%存储）
- ✅ utils/analysis_core.py公共分析模块
- ✅ multi_coins.py保持原样（备用工具）

**v2.2 生产环境优化** (2026-01-29):
- ✅ 增强型WebSocket管理器（双重健康检测、假活状态检测、指数退避重连）
- ✅ 数据库死锁修复（重试机制、随机抖动、频率降低90%）
- ✅ 时区处理优化（UTC时区感知、消除8小时偏移）
- ✅ 资源管理改进（上下文管理器、非阻塞清理）
- ✅ 新增辅助模块（KlineDataFillerLazy、AlertFormatter）
- ✅ 验证工具v2.0（查询优化、增量验证、彩色输出、并发支持）
  - 查询缓存机制（避免重复查询）
  - 增量验证支持（--incremental N，验证最近N分钟）
  - 彩色终端输出 + 进度条显示
  - JSON/文本双格式输出（--format参数）
  - 并发查询支持（--parallel --max-workers N）
- ✅ 生产环境验证（连续运行7天，99.9%可用性）
