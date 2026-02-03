#!/bin/bash
# WebSocket 服务启动脚本（含网络检测）

echo "🌐 检测网络连通性..."

# 检测网络是否可用
check_network() {
    # 方法 1: 尝试 ping Google DNS
    if ping -c 1 -W 3 8.8.8.8 > /dev/null 2>&1; then
        return 0
    fi

    # 方法 2: 尝试解析目标域名
    if nslookup api.hyperliquid.xyz > /dev/null 2>&1; then
        return 0
    fi

    return 1
}

# 等待网络恢复
wait_for_network() {
    local max_attempts=12  # 最多等待 120 秒（12 * 10s）
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        attempt=$((attempt + 1))
        echo "⏳ 检测网络 (第 $attempt/$max_attempts 次)..."

        if check_network; then
            echo "✅ 网络连通性检测通过"
            return 0
        fi

        if [ $attempt -lt $max_attempts ]; then
            echo "⚠️  网络不可用，10 秒后重试..."
            sleep 10
        fi
    done

    echo "❌ 网络检测失败：120 秒内网络未恢复"
    return 1
}

# 执行网络检测
if ! wait_for_network; then
    echo "❌ 无法启动服务：网络不可用"
    exit 1
fi

echo ""
echo "🚀 启动 WebSocket 服务..."
echo ""

# 启动服务
nohup uv run python -m src.services.realtime_kline_service >> logs/realtime_kline.log 2>&1 &

echo "✅ 服务已在后台启动"
echo "📋 查看日志: tail -f logs/realtime_kline.log"
echo "🔍 查看进程: ps aux | grep realtime_kline_service"
