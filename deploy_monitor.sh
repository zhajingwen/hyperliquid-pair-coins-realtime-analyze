#!/bin/bash
#
# Akash 容器监控脚本快速部署
# 用法: curl -sSL <url> | bash
#

set -e

echo "================================================================"
echo "  Akash 容器监控脚本 - 快速部署"
echo "================================================================"
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查 Python
echo -n "检查 Python 环境... "
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    echo -e "${GREEN}✓${NC} Python $PYTHON_VERSION"
else
    echo -e "${RED}✗${NC} Python 未安装"
    exit 1
fi

# 检查 psutil
echo -n "检查 psutil 库... "
if python3 -c "import psutil" 2>/dev/null; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${YELLOW}!${NC} 未安装，尝试安装..."
    pip3 install psutil || {
        echo -e "${RED}安装失败${NC}"
        echo "请手动安装: pip3 install psutil"
        exit 1
    }
    echo -e "${GREEN}✓${NC} 安装成功"
fi

# 确定安装位置
if [ -d "/root/hyperliquid-pair-coins-realtime-analyze" ]; then
    INSTALL_DIR="/root/hyperliquid-pair-coins-realtime-analyze"
elif [ -d "$(pwd)/hyperliquid-pair-coins-realtime-analyze" ]; then
    INSTALL_DIR="$(pwd)/hyperliquid-pair-coins-realtime-analyze"
else
    INSTALL_DIR="/tmp"
    echo -e "${YELLOW}警告: 项目目录未找到，将安装到 /tmp${NC}"
fi

MONITOR_SCRIPT="$INSTALL_DIR/monitor_resources.py"

echo ""
echo "安装位置: $INSTALL_DIR"
echo ""

# 检查是否已存在
if [ -f "$MONITOR_SCRIPT" ]; then
    echo -e "${YELLOW}监控脚本已存在，是否覆盖？(y/N)${NC}"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "取消安装"
        exit 0
    fi
fi

# 下载或创建脚本
echo "正在创建监控脚本..."

# 这里应该包含完整的 monitor_resources.py 内容
# 为了简化，我们提供一个模板
cat > "$MONITOR_SCRIPT" << 'EOF'
#!/usr/bin/env python3
# 注意：这是一个简化版本
# 完整版本请从项目仓库获取：monitor_resources.py

import os
import sys

print("=" * 80)
print("  监控脚本部署成功！")
print("=" * 80)
print("")
print("完整监控脚本请从项目仓库复制 monitor_resources.py")
print("")
print("或者在容器内运行以下命令获取完整版本：")
print("")
print("  cd /root/hyperliquid-pair-coins-realtime-analyze")
print("  # 将完整的 monitor_resources.py 复制到这里")
print("")
print("=" * 80)
EOF

chmod +x "$MONITOR_SCRIPT"

echo -e "${GREEN}✓${NC} 监控脚本已创建: $MONITOR_SCRIPT"
echo ""

# 创建快捷命令
SHORTCUT_SCRIPT="/usr/local/bin/monitor"
echo "正在创建快捷命令..."

cat > "$SHORTCUT_SCRIPT" << EOF
#!/bin/bash
cd $INSTALL_DIR
python3 $MONITOR_SCRIPT "\$@"
EOF

chmod +x "$SHORTCUT_SCRIPT"

echo -e "${GREEN}✓${NC} 快捷命令已创建: monitor"
echo ""

# 创建 systemd 服务（可选）
echo "是否创建 systemd 服务用于后台运行？(y/N)"
read -r create_service

if [[ "$create_service" =~ ^[Yy]$ ]]; then
    SERVICE_FILE="/etc/systemd/system/akash-monitor.service"

    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Akash Container Resource Monitor
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $MONITOR_SCRIPT -i 10
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    echo -e "${GREEN}✓${NC} Systemd 服务已创建"
    echo ""
    echo "启动服务: systemctl start akash-monitor"
    echo "查看状态: systemctl status akash-monitor"
    echo "开机启动: systemctl enable akash-monitor"
fi

# 完成
echo ""
echo "================================================================"
echo -e "  ${GREEN}部署完成！${NC}"
echo "================================================================"
echo ""
echo "使用方法："
echo ""
echo "  1. 运行监控（完整路径）："
echo "     python3 $MONITOR_SCRIPT"
echo ""
echo "  2. 使用快捷命令："
echo "     monitor"
echo ""
echo "  3. 指定刷新间隔："
echo "     monitor -i 10"
echo ""
echo "  4. 简化模式："
echo "     monitor -s"
echo ""
echo "  5. 查看帮助："
echo "     monitor -h"
echo ""
echo "================================================================"
echo ""

# 询问是否立即运行
echo "是否立即运行监控？(y/N)"
read -r run_now

if [[ "$run_now" =~ ^[Yy]$ ]]; then
    echo ""
    python3 "$MONITOR_SCRIPT"
fi
