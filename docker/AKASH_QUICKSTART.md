# ⚡ Akash 快速部署清单

## 🚀 5 步快速部署

### 步骤 1: 准备 Docker 镜像（10 分钟）

```bash
# 1.1 登录 Docker Hub
docker login

# 1.2 构建镜像（替换 YOUR_USERNAME）
cd /Users/test/Downloads/hyperliquid-pair-hype-purr-analyze
docker build -t YOUR_USERNAME/crypto-timescaledb-akash:v1.0 -f docker/Dockerfile.akash .

# 1.3 推送到 Docker Hub
docker push YOUR_USERNAME/crypto-timescaledb-akash:v1.0

# ✅ 验证：访问 https://hub.docker.com/r/YOUR_USERNAME/crypto-timescaledb-akash
```

### 步骤 2: 修改配置（2 分钟）

```bash
# 编辑 deploy-akash.yaml
vim docker/deploy-akash.yaml

# 修改以下 2 处：
# 1. image: YOUR_USERNAME/crypto-timescaledb-akash:v1.0
# 2. POSTGRES_PASSWORD: 设置强密码（至少 16 字符）

# ✅ 保存文件
```

### 步骤 3: 设置环境变量（2 分钟）

```bash
# 复制粘贴以下命令
export AKASH_NET="https://raw.githubusercontent.com/akash-network/net/main/mainnet"
export AKASH_CHAIN_ID="akashnet-2"
export AKASH_NODE="https://rpc.akashnet.net:443"
export AKASH_WALLET="my-wallet"  # 你的钱包名称
export AKASH_ACCOUNT_ADDRESS="$(akash keys show $AKASH_WALLET -a)"

# ✅ 验证余额（至少 5 AKT）
akash query bank balances $AKASH_ACCOUNT_ADDRESS --node $AKASH_NODE
```

### 步骤 4: 部署（5 分钟）

```bash
# 4.1 创建部署
akash tx deployment create docker/deploy-akash.yaml \
  --from $AKASH_WALLET \
  --chain-id $AKASH_CHAIN_ID \
  --node $AKASH_NODE \
  --fees 5000uakt \
  --gas auto \
  --gas-adjustment 1.3 \
  --yes

# 4.2 获取 DSEQ（等待 30 秒）
akash query deployment list --owner $AKASH_ACCOUNT_ADDRESS --node $AKASH_NODE

# 4.3 设置 DSEQ
export AKASH_DSEQ=<你的-dseq-数字>

# 4.4 查看报价并选择提供商
akash query market bid list --owner $AKASH_ACCOUNT_ADDRESS --node $AKASH_NODE --dseq $AKASH_DSEQ

# 4.5 设置提供商地址
export AKASH_PROVIDER=<provider-address>

# 4.6 创建租约
akash tx market lease create \
  --dseq $AKASH_DSEQ \
  --from $AKASH_WALLET \
  --provider $AKASH_PROVIDER \
  --chain-id $AKASH_CHAIN_ID \
  --node $AKASH_NODE \
  --fees 5000uakt \
  --yes

# ✅ 等待租约激活（约 1-2 分钟）
```

### 步骤 5: 连接验证（3 分钟）

```bash
# 5.1 获取访问信息
akash provider lease-status \
  --dseq $AKASH_DSEQ \
  --from $AKASH_WALLET \
  --provider $AKASH_PROVIDER \
  --node $AKASH_NODE

# 5.2 设置连接信息（从上面输出中提取）
export AKASH_DB_HOST="provider.hostname.com"
export AKASH_DB_PORT="12345"

# 5.3 测试连接
psql -h $AKASH_DB_HOST -p $AKASH_DB_PORT -U postgres -d crypto_data

# 5.4 验证表结构
\dt

# 应该看到：
# - klines
# - symbol_metadata
# - analysis_results
# - daily_analysis_stats

# ✅ 部署成功！
```

---

## 📋 部署前检查清单

在执行部署前，确认以下所有项目：

### 前置条件
- [ ] 已安装 Akash CLI (`akash version`)
- [ ] 已安装 Docker (`docker --version`)
- [ ] 已安装 PostgreSQL 客户端 (`psql --version`)
- [ ] 已创建 Akash 钱包
- [ ] 钱包余额 ≥ 5 AKT
- [ ] 已注册 Docker Hub 账号

### 镜像准备
- [ ] 已构建 Docker 镜像
- [ ] 已推送到 Docker Hub
- [ ] 镜像是公开的（不是 private）
- [ ] 本地测试镜像正常工作

### 配置修改
- [ ] 已修改 `deploy-akash.yaml` 中的 `image` 字段
- [ ] 已设置强密码（POSTGRES_PASSWORD）
- [ ] 已保存所有配置文件

### 环境变量
- [ ] 已设置 `AKASH_WALLET`
- [ ] 已设置 `AKASH_ACCOUNT_ADDRESS`
- [ ] 已设置 `AKASH_NODE`
- [ ] 已设置 `AKASH_CHAIN_ID`

### 风险理解
- [ ] 理解这是测试/开发环境
- [ ] 理解数据可能丢失
- [ ] 理解需要定期备份
- [ ] 理解数据库暴露在公网的风险

---

## 🔧 常用命令速查

```bash
# 查看部署列表
akash query deployment list --owner $AKASH_ACCOUNT_ADDRESS --node $AKASH_NODE

# 查看租约状态
akash query market lease list --owner $AKASH_ACCOUNT_ADDRESS --node $AKASH_NODE

# 查看容器日志
akash provider lease-logs \
  --dseq $AKASH_DSEQ \
  --from $AKASH_WALLET \
  --provider $AKASH_PROVIDER \
  --node $AKASH_NODE \
  --follow

# 执行监控脚本
akash provider lease-shell \
  --dseq $AKASH_DSEQ \
  --from $AKASH_WALLET \
  --provider $AKASH_PROVIDER \
  --node $AKASH_NODE \
  --service timescaledb \
  /usr/local/bin/monitor.sh

# 连接数据库
psql -h $AKASH_DB_HOST -p $AKASH_DB_PORT -U postgres -d crypto_data

# 手动备份
pg_dump -h $AKASH_DB_HOST -p $AKASH_DB_PORT -U postgres crypto_data | gzip > backup_$(date +%Y%m%d).sql.gz

# 查看余额
akash query bank balances $AKASH_ACCOUNT_ADDRESS --node $AKASH_NODE

# 关闭部署
akash tx deployment close --dseq $AKASH_DSEQ --from $AKASH_WALLET --node $AKASH_NODE
```

---

## ⏱️ 预计时间

| 任务 | 时间 |
|------|------|
| 环境准备 | 15 分钟 |
| 构建镜像 | 10 分钟 |
| 修改配置 | 2 分钟 |
| 执行部署 | 5 分钟 |
| 连接验证 | 3 分钟 |
| **总计** | **35 分钟** |

---

## 💰 成本预算

| 项目 | 成本 |
|------|------|
| 部署押金 | 5 AKT（可退还）|
| Gas 费用 | ~0.1 AKT |
| 月租费用 | $1-5 |
| **首月总计** | **~$10-20** |

---

## 🆘 遇到问题？

### 常见错误

**1. 镜像拉取失败**
```
Error: failed to pull image
```
解决：确认镜像是公开的，而非 private

**2. 余额不足**
```
Error: insufficient funds
```
解决：充值至少 5 AKT

**3. 无法连接数据库**
```
Error: connection refused
```
解决：
- 等待 2-3 分钟让容器初始化
- 检查租约状态是否 active
- 查看容器日志

**4. 密码错误**
```
Error: password authentication failed
```
解决：检查 SDL 中配置的密码是否正确

### 获取帮助

1. 查看完整文档：`docs/AKASH_DEPLOYMENT.md`
2. 加入 Discord：https://discord.akash.network
3. 搜索论坛：https://forum.akash.network

---

## 🎯 下一步

部署成功后，建议：

1. **设置自动备份**
   ```bash
   # 配置定时备份（每 6 小时）
   crontab -e
   # 添加：0 */6 * * * ~/akash-backup.sh
   ```

2. **配置监控**
   ```bash
   # 每日健康检查
   0 9 * * * ~/akash-healthcheck.sh
   ```

3. **测试应用连接**
   - 修改应用配置文件
   - 更新数据库连接字符串
   - 测试数据写入

4. **性能优化**
   - 监控查询性能
   - 优化慢查询
   - 调整资源配置

---

## 📚 文档索引

- **完整部署指南**: `docs/AKASH_DEPLOYMENT.md`
- **Dockerfile**: `docker/Dockerfile.akash`
- **SDL 配置**: `docker/deploy-akash.yaml`
- **原始配置**: `docker/docker-compose.yml`

---

**祝部署顺利！** 🚀

