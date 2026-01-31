# urllib3 连接池满问题解决方案

## 问题诊断

**错误信息**:
```
Connection pool is full, discarding connection: api.hyperliquid.xyz. Connection pool size: 10
```

**根本原因**:
- urllib3 默认连接池大小仅为 10
- CCXT 库底层使用 urllib3 进行 HTTP 请求
- 多线程并发访问 API 时，连接池快速耗尽
- 连接未被正确复用或及时释放

**影响范围**:
- `src/utils/analysis/kline_data_filler.py`
- `src/utils/analysis/kline_data_filler_lazy.py`

---

## 解决方案

### 方案 1: 增大 CCXT 连接池（推荐）⭐

在交易所初始化时配置连接池大小：

```python
# src/utils/analysis/kline_data_filler.py: 101-126 行
def _init_exchange(self, exchange_id: str) -> ccxt.Exchange:
    """初始化 ccxt 交易所实例"""
    try:
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class({
            'enableRateLimit': True,
            'rateLimit': 1500,
            'timeout': 30000,
            'options': {
                'defaultType': 'swap',
                'recvWindow': 60000,
            },
            # ⭐ 新增：连接池配置
            'session': {
                'pool_maxsize': 50,        # 连接池最大连接数（默认10 → 50）
                'pool_connections': 50,    # 连接池数量
                'max_retries': 3,          # 最大重试次数
                'pool_block': False        # 连接池满时不阻塞，而是创建新连接
            }
        })
        logger.info(f"交易所 {exchange_id} 初始化成功（连接池: 50）")
        return exchange
    except Exception as e:
        logger.error(f"交易所初始化失败: {e}")
        raise
```

**优点**:
- ✅ 简单高效，一处修改解决问题
- ✅ 连接复用，性能优秀
- ✅ 适应高并发场景

**适用场景**:
- 多工作线程同时调用API
- 批量数据补充场景

---

### 方案 2: 全局配置 urllib3

在项目入口或配置模块中全局增加连接池：

```python
# src/utils/core/config.py 或 服务入口文件

import urllib3
from urllib3.util.retry import Retry
from urllib3 import PoolManager

# 全局配置 urllib3 连接池
urllib3.disable_warnings()  # 可选：关闭不安全连接警告

# 创建自定义连接池管理器
http = PoolManager(
    maxsize=100,              # 最大连接数
    block=False,              # 池满时不阻塞
    retries=Retry(
        total=3,              # 总重试次数
        backoff_factor=0.5,   # 退避系数
        status_forcelist=[429, 500, 502, 503, 504]
    )
)

# 替换 requests/ccxt 的默认连接池
import requests
requests.adapters.DEFAULT_POOLSIZE = 100
requests.adapters.DEFAULT_POOLBLOCK = False
```

**优点**:
- ✅ 全局生效，影响所有HTTP请求
- ✅ 统一配置，便于管理

**缺点**:
- ⚠️ 可能影响其他依赖urllib3的库

---

### 方案 3: 请求限流（治标方案）

如果不能增大连接池，可以限制并发请求数量：

```python
# src/utils/analysis/kline_data_filler.py

import threading
from collections import deque

class KlineDataFiller:
    # 添加信号量控制并发
    _api_semaphore = threading.Semaphore(8)  # 最大并发数 8（小于连接池10）

    def _fetch_ohlcv_with_retry(self, symbol, timeframe, since=None, limit=None):
        """带限流的API请求"""
        with self._api_semaphore:  # 控制并发数
            return self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)
```

**配置建议**:
```python
# src/utils/core/config.py
KLINE_FILLER_MAX_CONCURRENT_REQUESTS = 8  # API并发请求限制
KLINE_FILLER_CONNECTION_POOL_SIZE = 50    # 连接池大小
```

**优点**:
- ✅ 主动控制并发，避免资源耗尽
- ✅ 适应服务器限流

**缺点**:
- ⚠️ 降低并发性能
- ⚠️ 无法根本解决连接池不足

---

### 方案 4: 连接复用优化

确保连接正确关闭和复用：

```python
# src/utils/analysis/kline_data_filler.py

class KlineDataFiller:
    def __init__(self, kline_repo=None, exchange_id='hyperliquid'):
        self.kline_repo = kline_repo or KlineRepository(TimescaleDBClient())
        self.exchange = self._init_exchange(exchange_id)

        # ⭐ 新增：确保Session复用
        self._session_lock = threading.RLock()

    def __del__(self):
        """析构时关闭连接"""
        if hasattr(self, 'exchange') and self.exchange:
            try:
                self.exchange.close()
            except:
                pass

    def _fetch_ohlcv_with_retry(self, symbol, timeframe, since=None, limit=None):
        """线程安全的API调用"""
        with self._session_lock:
            return self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)
```

---

## 推荐实施步骤

### 立即执行（方案1）⭐

1. **修改 `kline_data_filler.py` 和 `kline_data_filler_lazy.py`**
   - 在 `_init_exchange()` 方法中添加 `session` 配置
   - 设置 `pool_maxsize=50`

2. **添加配置参数**到 `config.py`:
   ```python
   # ============ HTTP连接池配置 ============
   HTTP_POOL_SIZE = 50              # 连接池大小
   HTTP_POOL_CONNECTIONS = 50       # 连接池数量
   HTTP_POOL_MAX_RETRIES = 3        # 最大重试
   HTTP_POOL_BLOCK = False          # 池满时不阻塞
   ```

3. **验证效果**:
   - 观察日志中是否还有连接池警告
   - 监控并发性能是否改善

### 后续优化（可选）

- 实施方案3的并发限流机制
- 添加连接池监控指标
- 定期清理空闲连接

---

## 配置参数说明

| 参数 | 默认值 | 推荐值 | 说明 |
|------|--------|--------|------|
| `pool_maxsize` | 10 | 50-100 | 单个host的最大连接数 |
| `pool_connections` | 10 | 50-100 | 连接池数量 |
| `pool_block` | True | False | 池满时是否阻塞（False=创建新连接） |
| `max_retries` | 0 | 3 | 连接失败重试次数 |

**计算公式**:
```
pool_maxsize ≥ ANALYSIS_WORKERS × 平均并发请求数
```

示例：
- 工作线程数: 15 (ANALYSIS_WORKERS_GENERAL)
- 平均并发: 2-3 个请求/线程
- 推荐池大小: 15 × 3 = 45 → **50**

---

## 监控与验证

### 日志监控
```python
# 添加连接池状态日志
logger.debug(
    f"连接池状态 | "
    f"活跃: {exchange.session.pool_manager.pools['api.hyperliquid.xyz'].num_connections} | "
    f"最大: {exchange.session.pool_manager.pools['api.hyperliquid.xyz'].maxsize}"
)
```

### 性能指标
- ✅ 警告消息消失
- ✅ API响应时间稳定
- ✅ 无连接超时错误
- ✅ 工作线程吞吐量提升

---

## 常见问题

**Q: 为什么不直接设置无限大的连接池？**
A: 过大的连接池会占用系统资源（内存、文件描述符），并可能触发服务器端限流。50-100 是经验值。

**Q: 连接池满时会丢失数据吗？**
A: 不会。警告仅表示连接被丢弃，CCXT会创建新连接继续请求。但会影响性能。

**Q: 需要重启服务吗？**
A: 是的。修改交易所初始化配置后需要重启服务生效。

**Q: 如何验证配置生效？**
A: 观察日志中是否还有 "Connection pool is full" 警告，以及API调用性能是否改善。

---

## 参考资料

- [urllib3 连接池文档](https://urllib3.readthedocs.io/en/stable/advanced-usage.html#customizing-pool-behavior)
- [CCXT 配置选项](https://docs.ccxt.com/en/latest/manual.html#instantiation)
- [Python requests 连接池](https://requests.readthedocs.io/en/latest/api/#api-changes)
