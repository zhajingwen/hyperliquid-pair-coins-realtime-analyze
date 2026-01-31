# 🚀 Akash 完全部署指南

## 📋 目录

1. [环境准备](#环境准备)
2. [构建 Docker 镜像](#构建-docker-镜像)
3. [部署到 Akash](#部署到-akash)
4. [连接和验证](#连接和验证)
5. [备份和恢复](#备份和恢复)
6. [监控和维护](#监控和维护)
7. [故障排除](#故障排除)

---

## 环境准备

### 1. 安装 Akash CLI

```bash
# macOS
curl -sSfL https://raw.githubusercontent.com/akash-network/node/main/install.sh | sh

# 验证安装
akash version
```

### 2. 创建或导入钱包

```bash
# 创建新钱包
akash keys add my-wallet

# 或导入现有钱包（助记词）
akash keys add my-wallet --recover

# 查看地址
akash keys show my-wallet -a
```

### 3. 获取 AKT 代币

**最低要求**: 5 AKT（用于押金和 gas 费用）

购买渠道：
- [Osmosis DEX](https://app.osmosis.zone/)
- [Kraken](https://www.kraken.com/)（如支持）
- [其他交易所](https://www.coingecko.com/en/coins/akash-network#markets)

转账到你的 Akash 地址：
```bash
# 查看余额
akash query bank balances <your-akash-address> --node https://rpc.akashnet.net:443
```

### 4. 安装 Docker

```bash
# macOS (使用 Homebrew)
brew install --cask docker

# 启动 Docker Desktop
open -a Docker
```

### 5. 注册 Docker Hub

如果还没有账号：
1. 访问 [Docker Hub](https://hub.docker.com/)
2. 注册免费账号
3. 本地登录

```bash
docker login
# 输入用户名和密码
```

---

## 构建 Docker 镜像

### 1. 构建镜像

```bash
# 进入项目目录
cd /Users/test/Downloads/hyperliquid-pair-hype-purr-analyze

# 构建镜像（替换 YOUR_DOCKERHUB_USERNAME）
docker build \
  -t YOUR_DOCKERHUB_USERNAME/crypto-timescaledb-akash:v1.0 \
  -f docker/Dockerfile.akash \
  .

# 查看构建的镜像
docker images | grep crypto-timescaledb
```

### 2. 本地测试镜像

```bash
# 启动容器测试
docker run -d \
  --name test-timescaledb \
  -e POSTGRES_PASSWORD=test123 \
  -p 5432:5432 \
  YOUR_DOCKERHUB_USERNAME/crypto-timescaledb-akash:v1.0

# 等待 30 秒初始化

# 测试连接
psql -h localhost -p 5432 -U postgres -d crypto_data

# 查看表结构
\dt

# 退出
\q

# 查看日志
docker logs test-timescaledb

# 测试监控脚本
docker exec test-timescaledb /usr/local/bin/monitor.sh

# 测试健康检查
docker exec test-timescaledb /usr/local/bin/healthcheck.sh

# 停止并删除测试容器
docker stop test-timescaledb
docker rm test-timescaledb
```

### 3. 推送到 Docker Hub

```bash
# 推送镜像
docker push YOUR_DOCKERHUB_USERNAME/crypto-timescaledb-akash:v1.0

# 验证推送成功
# 访问 https://hub.docker.com/r/YOUR_DOCKERHUB_USERNAME/crypto-timescaledb-akash
```

### 4. 修改 SDL 配置

```bash
# 编辑 deploy-akash.yaml
vim docker/deploy-akash.yaml

# 修改以下字段：
# 1. image: YOUR_DOCKERHUB_USERNAME/crypto-timescaledb-akash:v1.0
# 2. POSTGRES_PASSWORD: 设置强密码
```

---

## 部署到 Akash

### 1. 设置环境变量

```bash
# 设置 Akash 网络配置
export AKASH_NET="https://raw.githubusercontent.com/akash-network/net/main/mainnet"
export AKASH_VERSION="$(curl -s https://api.github.com/repos/akash-network/node/releases/latest | jq -r '.tag_name')"
export AKASH_CHAIN_ID="akashnet-2"
export AKASH_NODE="https://rpc.akashnet.net:443"

# 设置钱包信息
export AKASH_WALLET="my-wallet"
export AKASH_ACCOUNT_ADDRESS="$(akash keys show $AKASH_WALLET -a)"

# 验证配置
echo "Chain ID: $AKASH_CHAIN_ID"
echo "Node: $AKASH_NODE"
echo "Wallet: $AKASH_WALLET"
echo "Address: $AKASH_ACCOUNT_ADDRESS"

# 检查余额
akash query bank balances $AKASH_ACCOUNT_ADDRESS --node $AKASH_NODE
```

### 2. 创建部署

```bash
# 创建部署（会消耗一定 gas 费用）
akash tx deployment create docker/deploy-akash.yaml \
  --from $AKASH_WALLET \
  --chain-id $AKASH_CHAIN_ID \
  --node $AKASH_NODE \
  --fees 5000uakt \
  --gas auto \
  --gas-adjustment 1.3 \
  --yes

# 等待交易确认（约 10-30 秒）
```

### 3. 查询部署序列号 (DSEQ)

```bash
# 查询你的部署列表
akash query deployment list --owner $AKASH_ACCOUNT_ADDRESS --node $AKASH_NODE

# 记录 DSEQ（deployment sequence）
export AKASH_DSEQ=<your-dseq-number>

# 示例输出：
# deployments:
# - deployment:
#     created_at: "12345678"
#     deployment_id:
#       dseq: "12345678"  # ← 这是你的 DSEQ
#       owner: akash1...
#     state: active
```

### 4. 查看市场报价

```bash
# 查看提供商报价
akash query market bid list \
  --owner $AKASH_ACCOUNT_ADDRESS \
  --node $AKASH_NODE \
  --dseq $AKASH_DSEQ

# 选择价格合适的提供商
# 记录 provider 地址
export AKASH_PROVIDER=<provider-address>
```

### 5. 创建租约

```bash
# 接受报价并创建租约
akash tx market lease create \
  --dseq $AKASH_DSEQ \
  --from $AKASH_WALLET \
  --provider $AKASH_PROVIDER \
  --chain-id $AKASH_CHAIN_ID \
  --node $AKASH_NODE \
  --fees 5000uakt \
  --yes

# 等待租约创建（约 30 秒）
```

### 6. 验证部署状态

```bash
# 查询租约状态
akash query market lease list \
  --owner $AKASH_ACCOUNT_ADDRESS \
  --node $AKASH_NODE \
  --dseq $AKASH_DSEQ

# 应该显示 state: active
```

---

## 连接和验证

### 1. 获取服务访问信息

```bash
# 查询服务状态和 URI
akash provider lease-status \
  --dseq $AKASH_DSEQ \
  --from $AKASH_WALLET \
  --provider $AKASH_PROVIDER \
  --node $AKASH_NODE

# 输出示例：
# {
#   "services": {
#     "timescaledb": {
#       "uris": ["provider.hostname.com:12345"]
#     }
#   }
# }

# 提取主机和端口
export AKASH_DB_HOST="provider.hostname.com"
export AKASH_DB_PORT="12345"
```

### 2. 连接数据库

```bash
# 使用 psql 连接
psql -h $AKASH_DB_HOST -p $AKASH_DB_PORT -U postgres -d crypto_data

# 输入密码（你在 SDL 中设置的 POSTGRES_PASSWORD）
```

### 3. 验证初始化

```sql
-- 查看扩展
\dx

-- 应该看到 timescaledb 扩展

-- 查看表
\dt

-- 应该看到：
-- klines
-- symbol_metadata
-- analysis_results
-- daily_analysis_stats

-- 查看 Hypertable
SELECT hypertable_name, num_chunks
FROM timescaledb_information.hypertables;

-- 退出
\q
```

### 4. 查看容器日志

```bash
# 实时查看日志
akash provider lease-logs \
  --dseq $AKASH_DSEQ \
  --from $AKASH_WALLET \
  --provider $AKASH_PROVIDER \
  --node $AKASH_NODE \
  --follow

# Ctrl+C 停止查看
```

### 5. 执行监控脚本

```bash
# 通过 shell 执行监控
akash provider lease-shell \
  --dseq $AKASH_DSEQ \
  --from $AKASH_WALLET \
  --provider $AKASH_PROVIDER \
  --node $AKASH_NODE \
  --service timescaledb \
  /usr/local/bin/monitor.sh
```

---

## 备份和恢复

### 1. 手动备份

```bash
# 方法 1: 在容器内执行备份脚本
akash provider lease-shell \
  --dseq $AKASH_DSEQ \
  --from $AKASH_WALLET \
  --provider $AKASH_PROVIDER \
  --node $AKASH_NODE \
  --service timescaledb \
  /usr/local/bin/backup.sh

# 方法 2: 直接使用 pg_dump
pg_dump -h $AKASH_DB_HOST -p $AKASH_DB_PORT -U postgres crypto_data > backup_$(date +%Y%m%d).sql

# 压缩备份
gzip backup_$(date +%Y%m%d).sql
```

### 2. 自动化备份脚本

创建本地备份脚本：

```bash
# 创建备份脚本
cat > ~/akash-backup.sh <<'EOF'
#!/bin/bash
set -e

BACKUP_DIR="$HOME/akash-backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/crypto_db_${TIMESTAMP}.sql.gz"

mkdir -p ${BACKUP_DIR}

echo "🔄 开始备份 Akash 数据库..."
pg_dump -h $AKASH_DB_HOST -p $AKASH_DB_PORT -U postgres crypto_data | gzip > ${BACKUP_FILE}

echo "✅ 备份完成: ${BACKUP_FILE}"
echo "📦 大小: $(du -h ${BACKUP_FILE} | cut -f1)"

# 清理 7 天前的备份
find ${BACKUP_DIR} -name "crypto_db_*.sql.gz" -mtime +7 -delete
echo "🗑️  旧备份已清理"
EOF

chmod +x ~/akash-backup.sh
```

### 3. 设置定时备份

```bash
# 添加 crontab 任务（每 6 小时备份一次）
crontab -e

# 添加以下行：
0 */6 * * * /Users/test/akash-backup.sh >> /Users/test/akash-backups/backup.log 2>&1
```

### 4. 恢复数据

```bash
# 从备份恢复
gunzip -c backup_20250131.sql.gz | \
  psql -h $AKASH_DB_HOST -p $AKASH_DB_PORT -U postgres -d crypto_data
```

---

## 监控和维护

### 1. 定期检查

```bash
# 创建健康检查脚本
cat > ~/akash-healthcheck.sh <<'EOF'
#!/bin/bash

echo "🔍 检查 Akash 部署健康状态..."

# 检查数据库连接
if psql -h $AKASH_DB_HOST -p $AKASH_DB_PORT -U postgres -d crypto_data -c "SELECT 1" > /dev/null 2>&1; then
  echo "✅ 数据库连接正常"
else
  echo "❌ 数据库连接失败"
  exit 1
fi

# 查询租约状态
akash query market lease list \
  --owner $AKASH_ACCOUNT_ADDRESS \
  --node $AKASH_NODE \
  --dseq $AKASH_DSEQ | grep -q "state: active"

if [ $? -eq 0 ]; then
  echo "✅ 租约状态正常"
else
  echo "❌ 租约状态异常"
  exit 1
fi

echo "✅ 所有检查通过"
EOF

chmod +x ~/akash-healthcheck.sh
```

### 2. 成本监控

```bash
# 查看账户余额
akash query bank balances $AKASH_ACCOUNT_ADDRESS --node $AKASH_NODE

# 查看押金账户
akash query escrow account $AKASH_ACCOUNT_ADDRESS --node $AKASH_NODE
```

### 3. 性能监控

```bash
# 创建性能监控脚本
cat > ~/akash-monitor.sh <<'EOF'
#!/bin/bash

echo "📊 Akash 数据库性能监控"
echo "======================="

# 数据库大小
psql -h $AKASH_DB_HOST -p $AKASH_DB_PORT -U postgres -d crypto_data -c "
SELECT pg_size_pretty(pg_database_size('crypto_data')) AS db_size;
"

# 连接数
psql -h $AKASH_DB_HOST -p $AKASH_DB_PORT -U postgres -d crypto_data -c "
SELECT count(*) as connections FROM pg_stat_activity WHERE datname = 'crypto_data';
"

# 慢查询
psql -h $AKASH_DB_HOST -p $AKASH_DB_PORT -U postgres -d crypto_data -c "
SELECT query, calls, mean_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 5;
" 2>/dev/null || echo "ℹ️  需要启用 pg_stat_statements 扩展"

EOF

chmod +x ~/akash-monitor.sh
```

---

## 故障排除

### 问题 1: 部署失败

```bash
# 检查部署状态
akash query deployment list --owner $AKASH_ACCOUNT_ADDRESS --node $AKASH_NODE

# 常见原因：
# 1. 余额不足 → 充值 AKT
# 2. SDL 配置错误 → 检查 YAML 语法
# 3. 镜像拉取失败 → 确认镜像是公开的
```

### 问题 2: 无法连接数据库

```bash
# 1. 检查租约状态
akash query market lease list --owner $AKASH_ACCOUNT_ADDRESS --node $AKASH_NODE

# 2. 查看容器日志
akash provider lease-logs --dseq $AKASH_DSEQ --from $AKASH_WALLET --provider $AKASH_PROVIDER --node $AKASH_NODE

# 3. 检查防火墙/网络
ping $AKASH_DB_HOST
telnet $AKASH_DB_HOST $AKASH_DB_PORT
```

### 问题 3: 提供商变更

```bash
# 如果提供商下线，需要重新部署

# 1. 关闭当前部署
akash tx deployment close --dseq $AKASH_DSEQ --from $AKASH_WALLET --node $AKASH_NODE

# 2. 重新创建部署（重复部署步骤）
akash tx deployment create docker/deploy-akash.yaml ...

# ⚠️ 数据会丢失，需要从备份恢复
```

### 问题 4: 数据丢失

```bash
# 从最新备份恢复
ls -lt ~/akash-backups/

# 恢复数据
gunzip -c ~/akash-backups/crypto_db_XXXXXX.sql.gz | \
  psql -h $AKASH_DB_HOST -p $AKASH_DB_PORT -U postgres -d crypto_data
```

---

## 🎯 最佳实践

### 1. 安全

- ✅ 使用强密码（至少 16 字符）
- ✅ 定期更换密码
- ✅ 考虑使用 VPN 访问
- ✅ 监控异常连接

### 2. 备份

- ✅ 每 6 小时自动备份
- ✅ 保留 7 天的备份
- ✅ 定期测试恢复流程
- ✅ 异地备份（云存储）

### 3. 监控

- ✅ 每日健康检查
- ✅ 监控成本和余额
- ✅ 设置告警通知
- ✅ 跟踪性能指标

### 4. 成本优化

- ✅ 不使用时关闭部署
- ✅ 根据实际需求调整资源
- ✅ 监控提供商报价
- ✅ 定期审查账单

---

## 📚 参考资源

- [Akash 官方文档](https://docs.akash.network/)
- [Akash CLI 参考](https://docs.akash.network/cli)
- [SDL 规范](https://docs.akash.network/sdl)
- [Discord 社区](https://discord.akash.network)
- [论坛](https://forum.akash.network)

---

## 🆘 获取帮助

遇到问题？

1. 检查本文档的故障排除部分
2. 搜索 [Akash 论坛](https://forum.akash.network)
3. 加入 [Discord](https://discord.akash.network) 提问
4. 提交 [GitHub Issue](https://github.com/akash-network/support)

