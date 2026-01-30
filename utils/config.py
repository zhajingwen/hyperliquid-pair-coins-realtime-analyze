import os
from typing import Dict, List, Tuple, Optional
from utils.logging_config import logger

# ============ 敏感信息（保留环境变量） ============
lark_bot_id: Optional[str] = os.getenv('LARKBOT_ID')
lark_webhook_url: Optional[str] = f'https://open.larksuite.com/open-apis/bot/v2/hook/{lark_bot_id}' if lark_bot_id else None
lark_alert_email: str = os.getenv('LARK_ALERT_EMAIL', '')
redis_password: Optional[str] = os.getenv('REDIS_PASSWORD')
TIMESCALEDB_USER: str = os.getenv('TIMESCALEDB_USER', 'postgres')
TIMESCALEDB_PASSWORD: str = os.getenv('TIMESCALEDB_PASSWORD', 'postgres')

# ============ 环境配置 ============
env = 'local'

# ============ Redis配置 ============
redis_host = '127.0.0.1'

# ============ TimescaleDB配置 ============
TIMESCALEDB_HOST = '127.0.0.1'
TIMESCALEDB_PORT = 5432
TIMESCALEDB_NAME = 'crypto_data'
TIMESCALEDB_POOL_MIN_SIZE = 2
TIMESCALEDB_POOL_MAX_SIZE = 10
TIMESCALEDB_POOL_TIMEOUT = 30.0
TIMESCALEDB_POOL_MAX_LIFETIME = 3600
TIMESCALEDB_POOL_MAX_IDLE = 600

# ============ 通用服务配置 ============
DEFAULT_BASE_SYMBOL: str = 'BTC/USDC:USDC'
DEFAULT_TIMEFRAMES: List[str] = ['5m', '1h', '4h']
DEFAULT_BATCH_SIZE: int = 1000
DEFAULT_BATCH_TIMEOUT: float = 5.0

# ============ HYPE/PURR专用配置 ============
HYPE_BASE_SYMBOL: str = 'HYPE/USDC:USDC'
HYPE_SYMBOLS: List[str] = ['HYPE/USDC:USDC', 'PURR/USDC:USDC']
HYPE_CORR_THRESHOLD: float = 0.5

# ============ 队列配置 ============
QUEUE_CONFIG_GENERAL: Dict[str, int] = {'kline_buffer_size': 10000, 'analysis_queue_size': 15000, 'analysis_result_buffer_size': 10000}
QUEUE_CONFIG_HYPE: Dict[str, int] = {'kline_buffer_size': 1000, 'analysis_queue_size': 1000, 'analysis_result_buffer_size': 1000}

# ============ 工作线程配置 ============
ANALYSIS_WORKERS_GENERAL = 15
ANALYSIS_WORKERS_HYPE = 2

# ============ 去重配置 ============
ENQUEUE_DEDUP_WINDOWS: Dict[str, int] = {'5m': 30, '1h': 180, '4h': 600}
DEDUP_WINDOWS: Dict[str, int] = {'5m': 60, '1h': 300, '4h': 900}
CLEANUP_INTERVAL = 300
MAX_RECENT_TASKS = 5000

# ============ 批量写入配置 ============
ANALYSIS_RESULT_BATCH_SIZE = 100
ANALYSIS_RESULT_BATCH_TIMEOUT = 2.0
ANALYSIS_USE_COPY_METHOD = False

# ============ 监控配置 ============
QUEUE_MONITOR_INTERVAL = 60
QUEUE_WARNING_THRESHOLD = 0.8

# ============ 分析参数配置 ============
MIN_4H_DATA_POINTS = 358
MIN_DATA_POINTS = 100
MIN_POINTS_FOR_CORRELATION = 20
MIN_POINTS_FOR_ZSCORE = 19
TARGET_CORR_THRESHOLD = 0.6
DATA_WINDOW_CONFIG: Dict[str, int] = {'5m': 7, '1h': 30, '4h': 60}
BETA_WINDOW: int = 100
ZSCORE_WINDOW: int = 30
COINTEGRATION_THRESHOLD: int = 2
ZSCORE_THRESHOLDS: Dict[str, float] = {'long': 0.2, 'middle': 1.5, 'short': 1.8, 'strong': 2.5, 'medium': 2.0}
MIN_POINTS_FOR_OLS = 30  # 最小样本数，避免 sklearn UndefinedMetricWarning
ALPHA_SIGNIFICANCE_LEVEL = 0.05
ALPHA_CROSS_ASSET_THRESHOLD = 5.0
ALPHA_SAME_ASSET_THRESHOLD = 2.0
CORRELATION_METHOD = 'pearson'  # 相关系数计算方法: pearson/kendall/spearman
ADF_LAG_SELECTION_METHOD = 'AIC'  # ADF检验滞后选择: AIC/BIC/t-stat

# ============ 健康监控参数 ============
HEALTH_MONITOR_LONG_WINDOW: int = 200
HEALTH_MONITOR_SHORT_WINDOW: int = 100
HEALTH_MONITOR_STATE_THRESHOLDS: Tuple[int, int, int] = (18, 14, 10)
HEALTH_MONITOR_PERIOD: Tuple[str, str] = ('4h', '60d')
HEALTH_MONITOR_MAX_HALFLIFE: int = 30  # 半衰期上限(用于协整检查)
HEALTH_MONITOR_MIN_HALFLIFE: int = 5  # 半衰期下限
HEALTH_MONITOR_SCORE_WEIGHTS: Tuple[float, float, float] = (0.4, 0.3, 0.3)  # 得分权重(ADF,半衰期,稳定性)

# ============ 多周期分析配置 ============
REQUIRED_PERIODS = [('5m', '7d'), ('1h', '30d'), ('4h', '60d')]

# ============ 告警格式化配置 ============
ALERT_SIGNAL_STRENGTH: Dict[str, float] = {'extreme': 1.5, 'strong': 1.0, 'medium': 0.5}
ALERT_QUALITY: Dict[str, int] = {'excellent': 5, 'good': 4, 'fair': 3}
ALERT_CORR: Dict[str, float] = {'excellent': 0.8, 'good': 0.6}
ALERT_HURST: Dict[str, float] = {'trend': 0.6, 'mean_reversion': 0.4}
ALERT_SCORE_DIFF: Dict[str, int] = {'high': 15, 'medium': 10, 'deteriorate': 5}
ALERT_RISK_HIGH_HURST: float = 0.7
ALERT_RISK_MID: Dict[str, float] = {'coint_min': 3, 'zscore_ratio': 3, 'beta_cv': 0.2}
ALERT_RATING_COUNT_THRESHOLD: int = 2
ALERT_PROGRESS_BAR_WIDTH = 10  # 进度条宽度
ALERT_ZSCORE_MAX_VALUE = 3.0  # Z-score最大显示值

# ============ WebSocket配置 ============
WS_TIMEOUT = 30
WS_MAX_RETRIES = None
WS_ALERT_THRESHOLD = None
WS_URL = "wss://api.hyperliquid.xyz/ws"  # WebSocket连接地址
WS_PING_INTERVAL_MS = 5000  # Ping间隔(毫秒) - 每60秒心跳,防止会话过期
WS_PING_THREAD_SHUTDOWN_TIMEOUT = 2.0  # Ping线程关闭超时(秒)
WS_STATE_VALIDATION_DELAY = 1.0  # 状态验证延迟(秒)
WS_READY_TIMEOUT = 5.0  # WebSocket就绪超时(秒)
WS_RECONNECT_MIN_DELAY = 0.1  # 重连最小延迟(秒)
WS_RECONNECT_INITIAL_DELAY = 1.0  # 重连初始延迟(秒)
WS_RECONNECT_MAX_DELAY = 10.0  # 重连最大延迟(秒)
WS_RECONNECT_MULTIPLIER = 2.0  # 重连延迟倍数
WS_RECONNECT_JITTER = 0.25  # 重连抖动系数
WS_HEALTH_MONITOR_TIMEOUT = 15  # 健康监控超时阈值(秒) - 超过此时间未收到数据判定为假活
WS_HEALTH_MONITOR_WARNING_THRESHOLD = 15  # 健康监控警告阈值(秒) - 超过此时间触发警告日志
WS_HEALTH_REPORT_INTERVAL = 60  # 健康报告输出间隔(秒) - 定期输出健康统计信息
WS_HEALTH_CHECK_INTERVAL = 2  # 健康检查循环间隔(秒) - 健康监控线程检查频率
WS_CLEANUP_DELAY = 0.5  # 强制清理连接延迟(秒) - 清理旧连接前的等待时间

# ============ K线数据补充器配置 ============
KLINE_FILLER_COOLDOWN_SECONDS = 600  # 补充冷却时间(秒)
KLINE_FILLER_API_INTERVAL = 1.5  # API请求间隔(秒)
KLINE_FILLER_MAX_RETRIES = 3  # 最大重试次数
KLINE_FILLER_API_LIMIT = 1500  # API单次查询限制
KLINE_FILLER_CLEANUP_INTERVAL = 100  # 清理间隔(次)
KLINE_FILLER_LAZY_RATE_LIMIT = 1500  # Lazy模式速率限制(ms)
KLINE_FILLER_LAZY_TIMEOUT_MS = 30000  # Lazy模式超时(ms)

# ============ 飞书告警高级配置 ============
LARK_MAX_RETRIES = 3  # 最大重试次数
LARK_REQUEST_TIMEOUT = 10.0  # 请求超时(秒)
LARK_BACKOFF_BASE = 2  # 指数退避基数

# ============ 调度器配置 ============
SCHEDULER_WEEKDAY_CHECK_INTERVAL = 60  # 工作日检查间隔(秒)
SCHEDULER_TIME_CHECK_INTERVAL = 10  # 时间检查间隔(秒)
SCHEDULER_EXECUTION_WINDOW_MINUTES = 10  # 执行窗口(分钟)
SCHEDULER_POST_EXECUTION_WAIT_SECONDS = 3600  # 执行后等待(秒)

# ============ 服务线程超时配置 ============
QUEUE_GET_TIMEOUT = 1.0  # 队列读取超时(秒)
WORKER_THREAD_SHUTDOWN_TIMEOUT = 5.0  # 工作线程关闭超时(秒)
MAIN_THREAD_SHUTDOWN_TIMEOUT = 10.0  # 主线程关闭超时(秒)
CPU_CHECK_INTERVAL = 0.1  # CPU检查间隔(秒)
DB_QUERY_LIMIT = 10000  # 数据库查询限制
