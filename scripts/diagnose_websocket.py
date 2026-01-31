#!/usr/bin/env python3
"""
WebSocket 连接诊断工具

用途:
- 测试 WebSocket 连接性能
- 检测网络延迟和超时问题
- 监控订阅成功率
- 分析连接稳定性

使用:
    python scripts/diagnose_websocket.py
"""

import time
import asyncio
import websocket
from datetime import datetime

WS_URL = "wss://api.hyperliquid.xyz/ws"

def test_connection_time():
    """测试 WebSocket 连接耗时"""
    print("\n" + "="*60)
    print("🔍 测试 WebSocket 连接性能")
    print("="*60)

    for i in range(3):
        start_time = time.time()
        try:
            ws = websocket.create_connection(WS_URL, timeout=60)
            connect_time = time.time() - start_time

            print(f"\n✅ 测试 {i+1}/3:")
            print(f"   连接耗时: {connect_time:.2f} 秒")

            if connect_time < 5:
                print("   状态: 🟢 优秀")
            elif connect_time < 15:
                print("   状态: 🟡 正常")
            elif connect_time < 30:
                print("   状态: 🟠 偏慢")
            else:
                print("   状态: 🔴 超时风险高")

            # 测试发送消息
            test_msg = '{"method":"ping"}'
            send_start = time.time()
            ws.send(test_msg)
            response = ws.recv()
            rtt = time.time() - send_start

            print(f"   往返延迟: {rtt*1000:.0f} ms")

            ws.close()

        except Exception as e:
            connect_time = time.time() - start_time
            print(f"\n❌ 测试 {i+1}/3:")
            print(f"   连接失败: {e}")
            print(f"   耗时: {connect_time:.2f} 秒")

        time.sleep(2)

def test_subscription_load():
    """测试大量订阅的性能"""
    print("\n" + "="*60)
    print("📊 测试订阅负载性能")
    print("="*60)

    try:
        ws = websocket.create_connection(WS_URL, timeout=60)
        print("\n✅ WebSocket 连接成功")

        # 模拟订阅100个币种
        test_subscriptions = [
            {"type": "candle", "coin": f"TEST{i}", "interval": "5m"}
            for i in range(100)
        ]

        print(f"\n开始发送 {len(test_subscriptions)} 个订阅请求...")
        start_time = time.time()
        success_count = 0
        failed_count = 0

        batch_size = 50
        for i, sub in enumerate(test_subscriptions):
            try:
                import json
                msg = {"method": "subscribe", "subscription": sub}
                ws.send(json.dumps(msg))
                success_count += 1

                # 每批次延迟
                if (i + 1) % batch_size == 0:
                    time.sleep(0.1)
                    print(f"   已发送: {i+1}/{len(test_subscriptions)}")

            except Exception as e:
                failed_count += 1

        total_time = time.time() - start_time

        print(f"\n📈 订阅性能:")
        print(f"   总数: {len(test_subscriptions)}")
        print(f"   成功: {success_count}")
        print(f"   失败: {failed_count}")
        print(f"   耗时: {total_time:.2f} 秒")
        print(f"   速率: {success_count/total_time:.1f} 订阅/秒")

        ws.close()

    except Exception as e:
        print(f"\n❌ 订阅负载测试失败: {e}")

def test_connection_stability():
    """测试连接稳定性"""
    print("\n" + "="*60)
    print("⏱️  测试连接稳定性 (30秒)")
    print("="*60)

    try:
        ws = websocket.create_connection(WS_URL, timeout=60)
        print("\n✅ WebSocket 连接成功")

        print("\n保持连接30秒,监控稳定性...")
        start_time = time.time()
        message_count = 0
        error_count = 0

        # 设置非阻塞接收
        ws.settimeout(1.0)

        while time.time() - start_time < 30:
            try:
                # 发送 ping
                ws.send('{"method":"ping"}')

                # 尝试接收消息
                try:
                    msg = ws.recv()
                    message_count += 1
                except:
                    pass

                elapsed = int(time.time() - start_time)
                if elapsed % 5 == 0 and elapsed > 0:
                    print(f"   运行时长: {elapsed}秒 | 消息数: {message_count}")

                time.sleep(1)

            except Exception as e:
                error_count += 1
                if error_count > 3:
                    print(f"\n❌ 连接不稳定,错误过多: {e}")
                    break

        total_time = time.time() - start_time

        print(f"\n📊 稳定性测试结果:")
        print(f"   运行时长: {total_time:.1f} 秒")
        print(f"   消息数: {message_count}")
        print(f"   错误数: {error_count}")
        print(f"   稳定性: {'🟢 优秀' if error_count == 0 else '🟠 一般' if error_count < 3 else '🔴 较差'}")

        ws.close()

    except Exception as e:
        print(f"\n❌ 稳定性测试失败: {e}")

def main():
    """主函数"""
    print("\n" + "="*60)
    print("🚀 WebSocket 连接诊断工具")
    print("="*60)
    print(f"测试目标: {WS_URL}")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 测试连接性能
    test_connection_time()

    # 2. 测试订阅负载
    test_subscription_load()

    # 3. 测试连接稳定性
    test_connection_stability()

    print("\n" + "="*60)
    print("✅ 诊断完成")
    print("="*60)
    print("\n建议:")
    print("  • 如果连接耗时 >30秒: 增加 WS_TIMEOUT 到 60-90秒")
    print("  • 如果订阅失败率 >10%: 增加批次延迟 WS_SUBSCRIBE_BATCH_DELAY")
    print("  • 如果稳定性较差: 检查网络环境或服务器状态")

if __name__ == "__main__":
    main()
