"""
增强型 WebSocket 连接管理器

设计灵感来源: https://github.com/zhajingwen/strong-hyperliquid-websocket
核心改进:
- 双重健康检测（底层连接 + 应用层心跳）
- 指数退避重连策略
- 完整的状态机管理
- 线程安全设计
- 可观测性（统计信息和健康报告）

Author: Claude Code (基于 strong-hyperliquid-websocket 设计)
Date: 2026-01-19
"""

import time
import json
import threading
import socket
import websocket
from enum import Enum
from typing import Dict, List, Optional, Callable
from datetime import datetime, timezone

from utils.logging_config import logger
from utils.config import (
    WS_PING_INTERVAL_MS, WS_PING_THREAD_SHUTDOWN_TIMEOUT,
    WS_STATE_VALIDATION_DELAY, WS_READY_TIMEOUT,
    WS_RECONNECT_MIN_DELAY, WS_RECONNECT_INITIAL_DELAY,
    WS_RECONNECT_MAX_DELAY, WS_RECONNECT_MULTIPLIER, WS_RECONNECT_JITTER,
    WS_URL, WS_TIMEOUT, WS_MAX_RETRIES, WS_ALERT_THRESHOLD,
    WS_HEALTH_MONITOR_TIMEOUT, WS_HEALTH_MONITOR_WARNING_THRESHOLD,
    WS_CLEANUP_DELAY, WS_HEALTH_REPORT_INTERVAL, WS_HEALTH_CHECK_INTERVAL
)


# =====================================================
# 状态枚举
# =====================================================

class ConnectionState(Enum):
    """WebSocket连接状态"""
    DISCONNECTED = "disconnected"  # 未连接
    CONNECTING = "connecting"      # 连接中
    CONNECTED = "connected"        # 已连接
    RECONNECTING = "reconnecting"  # 重连中
    FAILED = "failed"              # 连接失败


# =====================================================
# 健康监控器
# =====================================================

class HealthMonitor:
    """
    健康监控器（应用层心跳）

    功能:
    - 追踪最后消息接收时间
    - 检测数据流中断（假活状态）
    - 双阈值告警（警告 + 超时）

    设计参考: strong-hyperliquid-websocket 的 HealthMonitor
    """

    def __init__(
        self,
        timeout: int = WS_HEALTH_MONITOR_TIMEOUT,
        warning_threshold: int = WS_HEALTH_MONITOR_WARNING_THRESHOLD
    ):
        """
        初始化健康监控器

        Args:
            timeout: 超时阈值（秒），超过此时间未收到数据判定为假活
            warning_threshold: 警告阈值（秒），超过此时间触发警告日志
        """
        self.timeout = timeout
        self.warning_threshold = warning_threshold
        self.last_message_time = time.time()
        self.message_count = 0
        self._lock = threading.Lock()
        self._warned = False  # 防止重复警告（参考 strong-hyperliquid-websocket）

    def on_message(self):
        """更新最后消息接收时间"""
        with self._lock:
            self.last_message_time = time.time()
            self.message_count += 1
            self._warned = False  # 重置警告标志

    def is_alive(self) -> tuple[bool, float]:
        """
        检查连接是否存活

        Returns:
            (is_alive, idle_seconds): 是否存活，空闲时长（秒）
        """
        with self._lock:
            idle_time = time.time() - self.last_message_time

            if idle_time > self.timeout:
                return False, idle_time
            elif idle_time > self.warning_threshold and not self._warned:
                logger.warning(f"健康检查警告: {idle_time:.1f}秒未收到数据")
                self._warned = True  # 设置警告标志，防止重复输出

            return True, idle_time

    def get_health_percentage(self) -> float:
        """获取健康度百分比（0-100%）"""
        _, idle_time = self.is_alive()
        return max(0, 100 - (idle_time / self.timeout * 100))


# =====================================================
# 重连管理器
# =====================================================

class ReconnectionManager:
    """
    重连管理器（指数退避策略）

    特性:
    - 指数退避: 1s → 2s → 4s → 8s → 16s → 32s → 60s
    - 随机抖动: ±25% (防止雷鸣羊群效应)
    - 可配置最大延迟和重试次数

    设计参考: strong-hyperliquid-websocket 的 ReconnectionManager
    """

    def __init__(
        self,
        initial_delay: float = WS_RECONNECT_INITIAL_DELAY,
        max_delay: float = WS_RECONNECT_MAX_DELAY,
        multiplier: float = WS_RECONNECT_MULTIPLIER,
        max_retries: Optional[int] = None
    ):
        """
        初始化重连管理器

        Args:
            initial_delay: 初始延迟（秒）
            max_delay: 最大延迟（秒）
            multiplier: 延迟递增因子
            max_retries: 最大重试次数（None = 无限重试）
        """
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.max_retries = max_retries
        self.retry_count = 0
        self.total_reconnections = 0

    def get_delay(self) -> float:
        """
        计算下次重连延迟（指数退避 + 随机抖动）

        Returns:
            延迟时间（秒）
        """
        import random

        # 指数退避
        delay = self.initial_delay * (self.multiplier ** self.retry_count)
        delay = min(delay, self.max_delay)

        # 随机抖动
        jitter = delay * WS_RECONNECT_JITTER
        delay += random.uniform(-jitter, jitter)

        return max(WS_RECONNECT_MIN_DELAY, delay)

    def should_retry(self) -> bool:
        """判断是否应该继续重试"""
        if self.max_retries is None:
            return True
        return self.retry_count < self.max_retries

    def record_attempt(self):
        """记录一次重连尝试"""
        self.retry_count += 1
        self.total_reconnections += 1

    def reset(self):
        """重置重试计数器（连接成功后调用）"""
        self.retry_count = 0


# =====================================================
# 增强型 WebSocket 管理器
# =====================================================

class EnhancedWebSocketManager:
    """
    增强型 WebSocket 连接管理器

    核心功能:
    - 双重健康检测（底层连接 + 应用层心跳）
    - 自动重连（指数退避策略）
    - 状态机管理（DISCONNECTED → CONNECTING → CONNECTED → RECONNECTING → FAILED）
    - 线程安全（递归锁保护）
    - 可观测性（统计信息、健康报告）

    设计参考: https://github.com/zhajingwen/strong-hyperliquid-websocket
    作者: Claude Code (集成改进)
    """

    def __init__(
        self,
        subscriptions: List[Dict],
        message_callback: Optional[Callable[[Dict], None]] = None,
        on_state_change: Optional[Callable[[ConnectionState, Optional[Exception]], None]] = None,
        timeout: int = WS_TIMEOUT,
        skip_disconnects: bool = False,
        alert_callback: Optional[Callable[[str, str], None]] = None,
        max_retries: int = WS_MAX_RETRIES,
        alert_threshold: int = WS_ALERT_THRESHOLD
    ):
        """
        初始化增强型 WebSocket 管理器

        Args:
            subscriptions: 订阅列表，格式: [{"type": "candle", "coin": "BTC", "interval": "5m"}, ...]
            message_callback: (可选) 主消息回调函数，签名: (msg: Dict) -> None
            on_state_change: 状态变化回调，签名: (state: ConnectionState, error: Optional[Exception]) -> None
            timeout: 数据流超时（秒），默认30秒
            skip_disconnects: 是否跳过断连处理（用于测试）
            alert_callback: 告警回调函数，签名: (title: str, content: str) -> None
            max_retries: 最大重连次数（默认30次），耗尽后进入FAILED状态
            alert_threshold: 连续失败告警阈值（默认5次），达到后触发告警
        """
        self.subscriptions = subscriptions
        self.on_state_change_callback = on_state_change
        self.timeout = timeout
        self.skip_disconnects = skip_disconnects
        self.alert_callback = alert_callback
        self.alert_threshold = alert_threshold

        # ⭐ 改进 #1: 多回调系统 (借鉴 hyperliquid-trading-bot)
        self.message_callbacks: List[Callable[[Dict], None]] = []
        if message_callback:  # 保持向后兼容
            self.message_callbacks.append(message_callback)

        # ⭐ 改进 #2: 数据缓存 (借鉴 hyperliquid-trading-bot)
        # 格式: {"BTC:5m": {...}, "ETH:1h": {...}}
        self.latest_data: Dict[str, Dict] = {}
        self.latest_data_lock = threading.RLock()

        # 状态管理
        self.state = ConnectionState.DISCONNECTED
        self.state_lock = threading.RLock()

        # 动态订阅管理（修复：新币种监控失效）
        self.subscriptions_lock = threading.RLock()
        self.active_subscriptions = set()  # 去重已激活订阅

        # 原生 WebSocket 组件（替换 SDK）
        self.ws_url = WS_URL
        self.ws: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        self.ws_ready_event = threading.Event()

        # Ping 线程管理
        self.ping_thread: Optional[threading.Thread] = None
        self.stop_ping = threading.Event()

        # 健康监控
        self.health_monitor = HealthMonitor(timeout=timeout)

        # 重连管理（设置最大重试次数，防止无限重连）
        self.reconnection_manager = ReconnectionManager(max_retries=max_retries)

        # 停止事件
        self.stop_event = threading.Event()

        # 统计信息
        self.start_time = time.time()
        self.last_error: Optional[Exception] = None

        logger.info(
            f"增强型WebSocket管理器初始化完成 | 订阅数: {len(subscriptions)} | "
            f"超时: {timeout}秒 | 最大重试: {max_retries}次 | 告警阈值: {alert_threshold}次"
        )

    def _update_state(self, new_state: ConnectionState, error: Optional[Exception] = None):
        """更新连接状态（线程安全）"""
        with self.state_lock:
            old_state = self.state
            self.state = new_state
            self.last_error = error

            logger.info(f"状态转换: {old_state.value} → {new_state.value}")

            if self.on_state_change_callback:
                try:
                    self.on_state_change_callback(new_state, error)
                except Exception as e:
                    logger.error(f"状态回调执行失败: {e}", exc_info=True)

    # =====================================================
    # ⭐ 改进 #1: 多回调系统管理方法
    # =====================================================

    def add_callback(self, callback: Callable[[Dict], None]) -> None:
        """
        添加消息回调 (借鉴 hyperliquid-trading-bot)

        Args:
            callback: 消息回调函数，签名: (msg: Dict) -> None

        示例:
            def my_callback(msg):
                print(f"收到消息: {msg}")

            manager.add_callback(my_callback)
        """
        if callback not in self.message_callbacks:
            self.message_callbacks.append(callback)
            logger.info(f"✅ 添加回调成功 | 当前回调数: {len(self.message_callbacks)}")
        else:
            logger.warning("⚠️ 回调已存在，跳过添加")

    def remove_callback(self, callback: Callable[[Dict], None]) -> bool:
        """
        移除消息回调

        Args:
            callback: 要移除的回调函数

        Returns:
            bool: 是否成功移除
        """
        try:
            self.message_callbacks.remove(callback)
            logger.info(f"✅ 移除回调成功 | 当前回调数: {len(self.message_callbacks)}")
            return True
        except ValueError:
            logger.warning("⚠️ 回调不存在，无需移除")
            return False

    def get_callbacks_count(self) -> int:
        """获取当前回调数量"""
        return len(self.message_callbacks)

    # =====================================================
    # ⭐ 改进 #2: 数据缓存方法
    # =====================================================

    def _cache_latest_data(self, msg: Dict) -> None:
        """
        缓存最新数据 (借鉴 hyperliquid-trading-bot)

        支持的消息类型:
        - candle: K线数据
        - l2Book: 订单簿
        - trades: 交易记录
        - allMids: 全市场中间价
        """
        try:
            channel = msg.get("channel")
            data = msg.get("data", {})

            if channel == "candle":
                # K线数据: key = "BTC:5m"
                symbol = data.get("s", "")  # "BTC/USDC:USDC"
                interval = data.get("i", "")  # "5m"

                if symbol and interval:
                    # 提取币种名称
                    coin = symbol.split("/")[0] if "/" in symbol else symbol
                    cache_key = f"{coin}:{interval}"

                    with self.latest_data_lock:
                        self.latest_data[cache_key] = msg

            elif channel == "l2Book":
                # 订单簿: key = "BTC:l2Book"
                coin = data.get("coin", "")
                if coin:
                    cache_key = f"{coin}:l2Book"
                    with self.latest_data_lock:
                        self.latest_data[cache_key] = msg

            elif channel == "trades":
                # 交易记录: key = "BTC:trades"
                if isinstance(data, list) and len(data) > 0:
                    coin = data[0].get("coin", "")
                    if coin:
                        cache_key = f"{coin}:trades"
                        with self.latest_data_lock:
                            self.latest_data[cache_key] = msg

            elif channel == "allMids":
                # 全市场中间价: key = "BTC:mid", "ETH:mid", ...
                mids = data.get("mids", {})
                with self.latest_data_lock:
                    for coin, price in mids.items():
                        cache_key = f"{coin}:mid"
                        self.latest_data[cache_key] = {
                            "channel": "allMids",
                            "data": {"coin": coin, "price": price},
                            "timestamp": time.time()
                        }

        except Exception as e:
            logger.debug(f"数据缓存失败: {e}")

    def get_latest_candle(self, coin: str, interval: str) -> Optional[Dict]:
        """
        获取最新K线数据 (同步查询接口)

        Args:
            coin: 币种名称，如 "BTC"
            interval: 时间间隔，如 "5m"

        Returns:
            最新K线消息，如果不存在返回 None

        示例:
            candle = manager.get_latest_candle("BTC", "5m")
            if candle:
                data = candle.get("data", {})
                close_price = data.get("c")
                print(f"BTC 最新价格: {close_price}")
        """
        cache_key = f"{coin}:{interval}"
        with self.latest_data_lock:
            return self.latest_data.get(cache_key)

    def get_latest_orderbook(self, coin: str) -> Optional[Dict]:
        """获取最新订单簿数据"""
        cache_key = f"{coin}:l2Book"
        with self.latest_data_lock:
            return self.latest_data.get(cache_key)

    def get_latest_trades(self, coin: str) -> Optional[Dict]:
        """获取最新交易记录"""
        cache_key = f"{coin}:trades"
        with self.latest_data_lock:
            return self.latest_data.get(cache_key)

    def get_latest_mid_price(self, coin: str) -> Optional[float]:
        """
        获取最新中间价 (allMids)

        Args:
            coin: 币种名称

        Returns:
            最新中间价，如果不存在返回 None
        """
        cache_key = f"{coin}:mid"
        with self.latest_data_lock:
            cached = self.latest_data.get(cache_key)
            if cached:
                data = cached.get("data", {})
                price_str = data.get("price")
                if price_str:
                    try:
                        return float(price_str)
                    except (ValueError, TypeError):
                        return None
            return None

    def get_cache_status(self) -> Dict[str, int]:
        """
        获取缓存状态

        Returns:
            {"total": 10, "candle": 5, "l2Book": 3, "trades": 1, "mid": 1}
        """
        with self.latest_data_lock:
            stats = {"total": len(self.latest_data)}

            # 统计各类型数量
            for key in self.latest_data.keys():
                if ":" in key:
                    data_type = key.split(":")[1]
                    stats[data_type] = stats.get(data_type, 0) + 1

            return stats

    def clear_cache(self) -> int:
        """
        清空缓存数据

        Returns:
            清空的数据条数
        """
        with self.latest_data_lock:
            count = len(self.latest_data)
            self.latest_data.clear()
            logger.info(f"🗑️ 缓存已清空 | 清除条数: {count}")
            return count

    # =====================================================
    # 连接状态检查
    # =====================================================

    def _is_connected(self) -> bool:
        """检查 WebSocket 是否已连接（原生实现）"""
        try:
            if not self.ws:
                return False

            # 检查 WebSocket 运行状态
            if not self.ws.keep_running:
                return False

            # 检查就绪标志
            if not self.ws_ready_event.is_set():
                return False

            # 检查 WebSocket 线程存活
            if not self.ws_thread or not self.ws_thread.is_alive():
                return False

            return True

        except Exception as e:
            logger.error(f"连接状态检查失败: {e}")
            return False

    def _wrapped_callback(self, msg: Dict):
        """封装的消息回调（包含健康监控 + 数据缓存 + 多回调触发）"""
        try:
            # 更新健康监控
            self.health_monitor.on_message()

            # ⭐ 改进 #2: 缓存最新数据
            self._cache_latest_data(msg)

            # ⭐ 改进 #1: 触发所有回调
            for callback in self.message_callbacks:
                try:
                    callback(msg)
                except Exception as e:
                    logger.error(f"回调执行失败: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"消息处理失败: {e}", exc_info=True)

    def _connect(self):
        """建立 WebSocket 连接（原生实现）"""
        try:
            # 只在非重连场景设置 CONNECTING
            if self.state != ConnectionState.RECONNECTING:
                self._update_state(ConnectionState.CONNECTING)

            # 使用锁保护订阅列表访问（修复：动态订阅支持）
            with self.subscriptions_lock:
                subscriptions_to_use = list(self.subscriptions)
                # 重建active_subscriptions集合（去重）
                self.active_subscriptions.clear()

            # ✅ 创建原生 WebSocketApp（无 HTTP 依赖）
            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close
            )

            # ✅ 在独立线程中运行 WebSocket
            self.ws_thread = threading.Thread(
                target=lambda: self.ws.run_forever(
                    ping_interval=None,  # 禁用内置 ping，使用自定义
                    sockopt=((socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),)
                ),
                daemon=True,
                name="ws-main-thread"
            )
            self.ws_thread.start()

            # 等待连接就绪
            if not self.ws_ready_event.wait(timeout=self.timeout):
                raise TimeoutError(f"WebSocket 连接超时（{self.timeout} 秒）")

            # 验证连接
            time.sleep(WS_STATE_VALIDATION_DELAY)  # 给WebSocket一点时间完成握手
            if self._is_connected():
                self._update_state(ConnectionState.CONNECTED)
                self.reconnection_manager.reset()
                # P0-1 修复：重置健康监控计时器，防止重连成功后被旧的idle_time立即踢掉
                self.health_monitor.on_message()
                logger.info(f"✅ WebSocket连接成功 | 订阅数: {len(self.active_subscriptions)}")
            else:
                raise ConnectionError("WebSocket连接验证失败")

        except Exception as e:
            logger.error(f"WebSocket连接失败: {e}", exc_info=True)
            # 只在初始连接时设置FAILED,重连过程中保持RECONNECTING
            if self.state != ConnectionState.RECONNECTING:
                self._update_state(ConnectionState.FAILED, e)
            raise

    def _on_open(self, ws):
        """WebSocket 连接建立回调"""
        logger.info("WebSocket 连接已建立")

        # 获取待订阅列表
        with self.subscriptions_lock:
            subscriptions_to_use = list(self.subscriptions)
            self.active_subscriptions.clear()

        # 发送订阅消息
        for subscription in subscriptions_to_use:
            try:
                msg = {"method": "subscribe", "subscription": subscription}
                ws.send(json.dumps(msg))

                # 记录订阅
                sub_key = (
                    subscription.get('type'),
                    subscription.get('coin'),
                    subscription.get('interval')
                )
                self.active_subscriptions.add(sub_key)
                logger.debug(f"订阅成功: {subscription}")
            except Exception as e:
                logger.error(f"订阅失败: {subscription} | {e}")

        # 启动 Ping 线程
        self.stop_ping.clear()
        self.ping_thread = threading.Thread(
            target=self._ping_loop,
            daemon=True,
            name="ws-ping-thread"
        )
        self.ping_thread.start()

        # 设置就绪标志
        self.ws_ready_event.set()

    def _on_message(self, ws, message):
        """WebSocket 消息接收回调"""
        try:
            # 跳过系统消息
            if message == "Websocket connection established.":
                return

            # 解析消息
            msg = json.loads(message)

            # 跳过内部协议消息（参考 strong-hyperliquid-websocket）
            if isinstance(msg, dict):
                # 跳过 pong（使用 method 字段，不是 channel）
                if msg.get("method") == "pong":
                    logger.debug("收到 pong")
                    return
                # 跳过订阅响应
                if msg.get("channel") == "subscriptionResponse":
                    logger.debug(f"订阅响应: {msg}")
                    return

            # 更新健康监控
            self.health_monitor.on_message()

            # 调用用户回调
            self._wrapped_callback(msg)

        except Exception as e:
            logger.error(f"消息处理失败: {message} | {e}", exc_info=True)

    def _on_error(self, ws, error):
        """WebSocket 错误回调"""
        logger.error(f"WebSocket 错误: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        """WebSocket 连接关闭回调"""
        logger.info(f"WebSocket 连接已关闭 | 状态码: {close_status_code} | 消息: {close_msg}")
        self.ws_ready_event.clear()

        # 如果不是正常关闭(由stop()触发),则触发重连
        if not self.stop_event.is_set() and self.state == ConnectionState.CONNECTED:
            logger.warning("检测到非正常断开，触发重连")
            # 在新线程中执行重连，避免阻塞回调
            threading.Thread(target=self._reconnect, daemon=True, name="ws-reconnect-on-close").start()

    def _ping_loop(self):
        """Ping 保活循环（参考 strong-hyperliquid-websocket）"""
        logger.debug("Ping 线程已启动")
        while not self.stop_ping.wait(WS_PING_INTERVAL_MS / 1000):
            # 安全检查：WebSocket 对象、运行状态、就绪标志
            if not self.ws or not self.ws.keep_running or not self.ws_ready_event.is_set():
                break
            try:
                self.ws.send(json.dumps({"method": "ping"}))
                logger.debug("发送 ping")
            except Exception as e:
                logger.warning(f"Ping 失败: {e}")
                break
        logger.debug("Ping 线程已停止")

    def _force_cleanup_connection(self):
        """
        强制清理WebSocket连接（原生实现，5步确定性清理）

        清理步骤:
        1. 停止WebSocket运行循环
        2. 停止 Ping 线程
        3. 关闭 WebSocket 连接
        4. 等待 WebSocket 线程退出
        5. 清除引用确保GC回收

        设计原则:
        - 每步独立try-except，互不影响
        - 详细日志记录每步清理状态（可观测性）
        - 部分失败不阻塞重连（异常容忍）
        """
        logger.info("开始强制清理WebSocket连接...")
        cleanup_status = []

        # Step 1: 停止运行循环
        try:
            if self.ws:
                self.ws.keep_running = False
                cleanup_status.append("✅ Step1: 停止运行循环")
            else:
                cleanup_status.append("⏭️ Step1: 无 WebSocket 对象")
        except Exception as e:
            cleanup_status.append(f"❌ Step1: {e}")
            logger.warning(f"停止运行循环失败: {e}")

        # Step 2: 停止 Ping 线程
        try:
            self.stop_ping.set()
            if self.ping_thread and self.ping_thread.is_alive():
                self.ping_thread.join(timeout=WS_PING_THREAD_SHUTDOWN_TIMEOUT)
                if self.ping_thread.is_alive():
                    cleanup_status.append(f"⚠️ Step2: ping 线程未在 {WS_PING_THREAD_SHUTDOWN_TIMEOUT} 秒内退出")
                else:
                    cleanup_status.append("✅ Step2: ping 线程已终止")
            else:
                cleanup_status.append("⏭️ Step2: 无活跃 ping 线程")
        except Exception as e:
            cleanup_status.append(f"❌ Step2: {e}")
            logger.warning(f"终止 ping 线程失败: {e}")

        # Step 3: 关闭 WebSocket 连接
        try:
            if self.ws:
                self.ws.close()
                cleanup_status.append("✅ Step3: WebSocket 已关闭")
            else:
                cleanup_status.append("⏭️ Step3: 无 WebSocket 连接")
        except Exception as e:
            cleanup_status.append(f"❌ Step3: {e}")
            logger.warning(f"关闭 WebSocket 失败: {e}")

        # Step 4: 等待 WebSocket 线程退出
        try:
            if self.ws_thread and self.ws_thread.is_alive():
                self.ws_thread.join(timeout=2.0)
                if self.ws_thread.is_alive():
                    cleanup_status.append("⚠️ Step4: WebSocket 线程未在 2 秒内退出")
                else:
                    cleanup_status.append("✅ Step4: WebSocket 线程已退出")
            else:
                cleanup_status.append("⏭️ Step4: 无活跃 WebSocket 线程")
        except Exception as e:
            cleanup_status.append(f"❌ Step4: {e}")
            logger.warning(f"等待 WebSocket 线程退出失败: {e}")

        # Step 5: 清除引用
        try:
            self.ws = None
            self.ws_thread = None
            self.ping_thread = None
            cleanup_status.append("✅ Step5: 引用已清除")
        except Exception as e:
            cleanup_status.append(f"❌ Step5: {e}")
            logger.warning(f"清除引用失败: {e}")

        # 等待资源释放
        time.sleep(WS_CLEANUP_DELAY)

        # 汇总日志
        logger.info(f"强制清理完成: {' | '.join(cleanup_status)}")

    def add_subscriptions(self, new_subscriptions: List[Dict]) -> bool:
        """
        动态添加订阅（运行时热更新）

        Args:
            new_subscriptions: 新增订阅列表，格式: [{"type": "candle", "coin": "NEWCOIN", "interval": "5m"}, ...]

        Returns:
            bool: 订阅是否成功

        功能:
        - 去重：避免重复订阅相同频道
        - 线程安全：使用锁保护订阅列表
        - 即时订阅：连接已建立时立即调用Info.subscribe()
        - 延迟订阅：连接未建立时添加到列表，重连时自动订阅
        
        注意：如果订阅失败，会从订阅列表中移除该订阅
        """
        if not new_subscriptions:
            return True

        try:
            added_count = 0
            skipped_count = 0

            with self.subscriptions_lock:
                for subscription in new_subscriptions:
                    # 生成订阅唯一键（去重）
                    sub_key = (
                        subscription.get('type'),
                        subscription.get('coin'),
                        subscription.get('interval')
                    )

                    # 检查是否已订阅
                    if sub_key in self.active_subscriptions:
                        skipped_count += 1
                        logger.debug(f"跳过重复订阅: {sub_key}")
                        continue

                    # 添加到订阅列表
                    self.subscriptions.append(subscription)

                    # 如果连接已建立，立即订阅
                    if self._is_connected():
                        try:
                            # ✅ 直接发送订阅消息
                            msg = {"method": "subscribe", "subscription": subscription}
                            self.ws.send(json.dumps(msg))

                            self.active_subscriptions.add(sub_key)
                            added_count += 1
                            logger.info(f"✅ 动态订阅成功: {subscription.get('coin')} @ {subscription.get('interval')}")
                        except Exception as e:
                            logger.error(f"动态订阅失败: {sub_key} | {e}")
                            # 订阅失败，从列表移除
                            self.subscriptions.remove(subscription)
                    else:
                        # 连接未建立，只添加到列表（重连时自动订阅）
                        added_count += 1
                        logger.info(f"📋 延迟订阅已添加: {subscription.get('coin')} @ {subscription.get('interval')} (重连时生效)")

            logger.info(
                f"动态订阅完成: 新增 {added_count} 个订阅，跳过 {skipped_count} 个重复订阅 | "
                f"总订阅数: {len(self.subscriptions)}"
            )
            return True

        except Exception as e:
            logger.error(f"动态添加订阅失败: {e}", exc_info=True)
            return False

    # =====================================================
    # ⭐ 改进 #3: 取消订阅功能 (借鉴 hyperliquid-trading-bot)
    # =====================================================

    def remove_subscriptions(self, subscriptions_to_remove: List[Dict]) -> bool:
        """
        动态移除订阅（运行时热更新）

        Args:
            subscriptions_to_remove: 要移除的订阅列表

        Returns:
            bool: 移除是否成功

        示例:
            # 移除 BTC 5m K线订阅
            manager.remove_subscriptions([
                {"type": "candle", "coin": "BTC", "interval": "5m"}
            ])
        """
        if not subscriptions_to_remove:
            return True

        try:
            removed_count = 0
            not_found_count = 0

            with self.subscriptions_lock:
                for subscription in subscriptions_to_remove:
                    # 生成订阅唯一键
                    sub_key = (
                        subscription.get('type'),
                        subscription.get('coin'),
                        subscription.get('interval')
                    )

                    # 检查订阅是否存在
                    if sub_key not in self.active_subscriptions:
                        not_found_count += 1
                        logger.debug(f"订阅不存在，跳过: {sub_key}")
                        continue

                    # 如果连接已建立，发送取消订阅消息
                    if self._is_connected():
                        try:
                            msg = {"method": "unsubscribe", "subscription": subscription}
                            self.ws.send(json.dumps(msg))
                            logger.debug(f"发送取消订阅消息: {subscription}")
                        except Exception as e:
                            logger.error(f"发送取消订阅消息失败: {e}")

                    # 从活跃订阅中移除
                    self.active_subscriptions.remove(sub_key)

                    # 从订阅列表中移除
                    if subscription in self.subscriptions:
                        self.subscriptions.remove(subscription)
                    else:
                        # 如果列表中找不到完全匹配的，按 key 查找并移除
                        for sub in list(self.subscriptions):
                            existing_key = (
                                sub.get('type'),
                                sub.get('coin'),
                                sub.get('interval')
                            )
                            if existing_key == sub_key:
                                self.subscriptions.remove(sub)
                                break

                    removed_count += 1
                    logger.info(f"✅ 取消订阅成功: {subscription.get('coin')} @ {subscription.get('interval')}")

            # 根据实际情况调整日志级别
            if not_found_count > 0:
                # 降级为 debug，因为这在并发环境下是正常现象
                logger.debug(
                    f"取消订阅完成: 移除 {removed_count} 个订阅，"
                    f"未找到 {not_found_count} 个 (可能已被其他线程移除) | "
                    f"剩余订阅数: {len(self.subscriptions)}"
                )
            else:
                logger.info(
                    f"取消订阅完成: 移除 {removed_count} 个订阅 | "
                    f"剩余订阅数: {len(self.subscriptions)}"
                )
            return True

        except Exception as e:
            logger.error(f"取消订阅失败: {e}", exc_info=True)
            return False

    def clear_all_subscriptions(self) -> int:
        """
        清空所有订阅

        Returns:
            int: 清除的订阅数量
        """
        try:
            with self.subscriptions_lock:
                count = len(self.subscriptions)

                # 如果连接已建立，发送取消订阅消息
                if self._is_connected():
                    for subscription in list(self.subscriptions):
                        try:
                            msg = {"method": "unsubscribe", "subscription": subscription}
                            self.ws.send(json.dumps(msg))
                        except Exception as e:
                            logger.debug(f"发送取消订阅消息失败: {e}")

                # 清空订阅列表
                self.subscriptions.clear()
                self.active_subscriptions.clear()

                logger.info(f"🗑️ 所有订阅已清空 | 清除数量: {count}")
                return count

        except Exception as e:
            logger.error(f"清空订阅失败: {e}", exc_info=True)
            return 0

    def get_subscriptions_status(self) -> Dict[str, Any]:
        """
        获取订阅状态

        Returns:
            {
                "total": 5,
                "active": 5,
                "by_type": {"candle": 3, "l2Book": 2},
                "by_coin": {"BTC": 2, "ETH": 2, "SOL": 1}
            }
        """
        with self.subscriptions_lock:
            stats = {
                "total": len(self.subscriptions),
                "active": len(self.active_subscriptions),
                "by_type": {},
                "by_coin": {}
            }

            for subscription in self.subscriptions:
                # 统计类型
                sub_type = subscription.get('type', 'unknown')
                stats["by_type"][sub_type] = stats["by_type"].get(sub_type, 0) + 1

                # 统计币种
                coin = subscription.get('coin')
                if coin:
                    stats["by_coin"][coin] = stats["by_coin"].get(coin, 0) + 1

            return stats

    def _reconnect(self):
        """重连逻辑（指数退避策略 + 告警机制）"""
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

            try:
                # 强制清理旧连接（清理 WebSocket 对象）
                if self.ws:
                    self._force_cleanup_connection()

                # ✅ 直接重连，无 HTTP 依赖
                self._connect()
                logger.info("✅ WebSocket重连成功")
                return

            except Exception as e:
                logger.error(f"重连失败 (第{retry_count}次): {e}")

                # P0-2：第N次重试时发送告警（N = alert_threshold）
                if retry_count == self.alert_threshold and self.alert_callback:
                    try:
                        self.alert_callback(
                            "⚠️ WebSocket连续重连失败告警",
                            f"WebSocket已连续重连失败 {retry_count} 次\n"
                            f"最大重试次数: {max_retries or '无限'}\n"
                            f"最近错误: {e}\n"
                            f"服务仍在尝试重连中，请关注..."
                        )
                    except Exception as alert_err:
                        logger.error(f"发送重连告警失败: {alert_err}")

        # 重试次数耗尽
        logger.error(
            f"🚨 重连失败: 达到最大重试次数 ({self.reconnection_manager.max_retries}次)，服务进入FAILED状态"
        )

        # P0-2：发送紧急告警
        if self.alert_callback:
            try:
                self.alert_callback(
                    "🚨 WebSocket重连耗尽 - 服务即将退出",
                    f"WebSocket重连已耗尽所有重试次数 ({self.reconnection_manager.max_retries}次)\n"
                    f"最近错误: {self.last_error}\n"
                    f"服务即将退出，请立即检查网络和服务状态！"
                )
            except Exception as alert_err:
                logger.error(f"发送紧急告警失败: {alert_err}")

        self._update_state(ConnectionState.FAILED)
        # 修复STAB-01: 通知所有监听线程停止
        self.stop_event.set()
        logger.critical("🚨 WebSocket重连耗尽，已设置stop_event，服务即将终止")

    def _monitor_health(self):
        """健康监控主循环"""
        logger.info("健康监控线程已启动")

        while not self.stop_event.is_set():
            try:
                # 等待连接就绪
                if not self.ws_ready_event.wait(timeout=WS_READY_TIMEOUT):
                    continue

                # 检查底层连接
                if not self._is_connected():
                    logger.warning("底层连接已断开，触发重连")
                    self._reconnect()
                    # P0-2：重连返回后检查是否已进入FAILED状态
                    if self.state == ConnectionState.FAILED:
                        logger.error("🚨 重连耗尽，健康监控退出，服务即将终止")
                        self.stop_event.set()
                        break
                    continue

                # 检查应用层心跳（假活检测）
                is_alive, idle_time = self.health_monitor.is_alive()
                if not is_alive:
                    logger.warning(f"假活状态检测: {idle_time:.1f}秒未收到数据，触发重连")
                    self._reconnect()
                    # P0-2：重连返回后检查是否已进入FAILED状态
                    if self.state == ConnectionState.FAILED:
                        logger.error("🚨 重连耗尽，健康监控退出，服务即将终止")
                        self.stop_event.set()
                        break
                    continue

                # 定期健康报告
                if int(time.time() - self.start_time) % WS_HEALTH_REPORT_INTERVAL == 0:
                    self._log_health_report()

            except Exception as e:
                logger.error(f"健康监控异常: {e}", exc_info=True)

            time.sleep(WS_HEALTH_CHECK_INTERVAL)  # 健康检查间隔

        logger.info("健康监控线程已停止")

    def _log_health_report(self):
        """记录健康报告"""
        stats = self.get_stats()
        logger.info(
            f"📊 健康报告 | "
            f"健康度: {stats['health_percentage']:.1f}% | "
            f"消息数: {stats['message_count']} | "
            f"重连次数: {stats['total_reconnections']} | "
            f"运行时长: {stats['uptime_seconds']:.0f}秒"
        )

    def get_stats(self) -> Dict:
        """
        获取统计信息 (增强版)

        Returns:
            包含连接状态、健康度、订阅、回调、缓存等信息的字典
        """
        return {
            # 基础信息
            'state': self.state.value,
            'uptime_seconds': time.time() - self.start_time,
            'last_error': str(self.last_error) if self.last_error else None,

            # 健康监控
            'health_percentage': self.health_monitor.get_health_percentage(),
            'message_count': self.health_monitor.message_count,

            # 重连信息
            'total_reconnections': self.reconnection_manager.total_reconnections,
            'current_retry_count': self.reconnection_manager.retry_count,

            # ⭐ 订阅信息 (新增)
            'subscriptions_total': len(self.subscriptions),
            'subscriptions_active': len(self.active_subscriptions),
            'subscriptions_detail': self.get_subscriptions_status(),

            # ⭐ 回调信息 (新增)
            'callbacks_count': len(self.message_callbacks),

            # ⭐ 缓存信息 (新增)
            'cache_status': self.get_cache_status(),
        }

    def start(self):
        """启动 WebSocket 服务（阻塞运行）"""
        logger.info("🚀 启动增强型WebSocket管理器...")

        try:
            # 建立初始连接
            self._connect()

            # 启动健康监控线程
            monitor_thread = threading.Thread(
                target=self._monitor_health,
                daemon=True,
                name="ws-health-monitor"
            )
            monitor_thread.start()

            # 主线程阻塞等待
            self.stop_event.wait()

        except KeyboardInterrupt:
            logger.info("接收到中断信号，停止服务...")
        except Exception as e:
            logger.error(f"服务异常: {e}", exc_info=True)
        finally:
            self.stop()

    def stop(self):
        """停止 WebSocket 服务"""
        logger.info("停止WebSocket服务...")
        self.stop_event.set()

        # 强制清理连接
        if self.ws:
            self._force_cleanup_connection()

        self._update_state(ConnectionState.DISCONNECTED)
        logger.info("WebSocket服务已停止")


# =====================================================
# 导出接口
# =====================================================

__all__ = [
    'EnhancedWebSocketManager',
    'ConnectionState',
    'HealthMonitor',
    'ReconnectionManager'
]
