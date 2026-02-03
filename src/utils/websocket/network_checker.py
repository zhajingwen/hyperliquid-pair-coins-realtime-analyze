"""
网络连通性检测工具

用于在 WebSocket 重连前检测网络是否可用，避免在无网络时频繁重试。
"""

import socket
import time
from typing import Tuple
from src.utils.core.logging_config import logger


def check_network_connectivity(timeout: int = 3) -> Tuple[bool, str]:
    """
    检测网络连通性

    检测策略：
    1. 尝试 DNS 解析 (8.8.8.8 Google DNS)
    2. 尝试 TCP 连接 (1.1.1.1:80 Cloudflare)
    3. 尝试解析目标域名

    Args:
        timeout: 每次测试的超时时间（秒）

    Returns:
        (is_available, reason): 网络是否可用，原因说明
    """

    # 测试 1: DNS 解析（最快）
    try:
        socket.gethostbyname('www.google.com')
        return True, "DNS 解析正常"
    except socket.gaierror:
        logger.debug("DNS 解析失败，尝试备用检测")
    except Exception as e:
        logger.debug(f"DNS 检测异常: {e}")

    # 测试 2: TCP 连接（无需 DNS）
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(('1.1.1.1', 80))  # Cloudflare DNS
        sock.close()
        return True, "TCP 连接正常（DNS 可能暂时不可用）"
    except (socket.timeout, socket.error):
        logger.debug("TCP 连接失败")
    except Exception as e:
        logger.debug(f"TCP 检测异常: {e}")

    # 测试 3: 尝试解析目标域名
    try:
        socket.gethostbyname('api.hyperliquid.xyz')
        return True, "目标域名解析正常"
    except socket.gaierror:
        return False, "DNS 解析失败：网络不可用或 DNS 服务器故障"
    except Exception as e:
        return False, f"网络检测异常: {e}"

    return False, "网络连通性检测失败"


def wait_for_network(
    max_wait: int = 300,
    check_interval: int = 10,
    timeout: int = 3
) -> bool:
    """
    等待网络恢复

    Args:
        max_wait: 最大等待时间（秒）
        check_interval: 检测间隔（秒）
        timeout: 每次检测超时时间（秒）

    Returns:
        网络是否已恢复
    """
    start_time = time.time()
    attempt = 0

    while time.time() - start_time < max_wait:
        attempt += 1
        is_available, reason = check_network_connectivity(timeout)

        if is_available:
            logger.info(f"✅ 网络已恢复 (第{attempt}次检测): {reason}")
            return True

        elapsed = int(time.time() - start_time)
        remaining = max_wait - elapsed
        logger.warning(
            f"⏳ 网络未恢复 (第{attempt}次检测): {reason} | "
            f"已等待 {elapsed}秒，剩余 {remaining}秒"
        )

        time.sleep(check_interval)

    logger.error(f"❌ 网络恢复超时: {max_wait}秒内网络未恢复")
    return False


def is_dns_error(error: Exception) -> bool:
    """
    判断是否为 DNS 解析错误

    Args:
        error: 异常对象

    Returns:
        是否为 DNS 错误
    """
    error_str = str(error).lower()
    dns_keywords = [
        'nodename nor servname provided',
        'name or service not known',
        'gaierror',
        'name resolution',
        'failed to resolve'
    ]

    return any(keyword in error_str for keyword in dns_keywords)


if __name__ == '__main__':
    """测试网络检测功能"""
    print("=== 测试网络连通性检测 ===")

    is_available, reason = check_network_connectivity()
    print(f"网络状态: {'✅ 可用' if is_available else '❌ 不可用'}")
    print(f"原因: {reason}")

    if not is_available:
        print("\n=== 测试等待网络恢复 ===")
        recovered = wait_for_network(max_wait=30, check_interval=5)
        print(f"网络恢复: {'✅ 是' if recovered else '❌ 否'}")
