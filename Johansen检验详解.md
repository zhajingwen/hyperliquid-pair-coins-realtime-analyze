# Johansen 协整检验详解

> 多变量协整关系检验：理论、实现与应用

> **专注加密货币市场** | 完整理论 + 代码实现 + 实战案例

---

## 目录

1. [理论基础与历史背景](#第1章理论基础与历史背景)
2. [数学原理与公式推导](#第2章数学原理与公式推导)
3. [向量误差修正模型（VECM）](#第3章向量误差修正模型vecm)
4. [检验步骤详解](#第4章检验步骤详解)
5. [迹检验与最大特征值检验](#第5章迹检验与最大特征值检验)
6. [优缺点分析](#第6章优缺点分析)
7. [与Engle-Granger检验对比](#第7章与engle-granger检验对比)
8. [代码实现详解](#第8章代码实现详解)
9. [实战应用案例](#第9章实战应用案例)
10. [常见问题与注意事项](#第10章常见问题与注意事项)
11. [改进方向与扩展](#第11章改进方向与扩展)

---

## 第1章：理论基础与历史背景

### 1.1 Johansen 检验的提出

**Johansen 检验**是由丹麦统计学家 Søren Johansen 在1988年和1991年提出的多变量协整检验方法，是对 Engle-Granger 两步法的重要扩展。

#### 1.1.1 历史背景

**1988年论文**：
- Johansen, S. (1988). "Statistical analysis of cointegration vectors"
- 提出了基于最大似然估计的协整检验方法

**1991年论文**：
- Johansen, S. (1991). "Estimation and Hypothesis Testing of Cointegration Vectors in Gaussian Vector Autoregressive Models"
- 完善了迹检验（Trace Test）和最大特征值检验（Maximum Eigenvalue Test）

**重要意义**：
- 解决了多变量协整检验的问题
- 可以同时检测多个协整关系
- 提供了更严格的统计推断框架

### 1.2 为什么需要 Johansen 检验？

#### 1.2.1 Engle-Granger 方法的局限性

**Engle-Granger 两步法的限制**：
1. **仅适用于2个变量**：无法处理3个或更多变量
2. **只能检测1个协整关系**：可能遗漏其他协整关系
3. **变量选择问题**：需要预先指定因变量
4. **统计性质**：在小样本下可能不够精确

#### 1.2.2 Johansen 检验的优势

**核心优势**：
1. **多变量支持**：可以同时处理多个变量（≥2）
2. **多个协整关系**：可以检测并估计多个协整向量
3. **对称性**：不需要预先指定因变量
4. **统计性质更优**：基于最大似然估计，渐近性质更好

### 1.3 应用场景

#### 1.3.1 适合使用 Johansen 检验的情况

**推荐场景**：
1. **多资产组合**：3个或更多加密货币（如 HYPE、PURR、TON）
2. **复杂系统**：可能存在多个协整关系
3. **学术研究**：需要严格的统计推断
4. **长期分析**：不追求实时性，更注重准确性

#### 1.3.2 在加密货币市场的应用

**实际案例**：
- **三币组合**：HYPE、PURR、TON 三者之间的协整关系
- **板块分析**：同一板块内多个代币的协整关系
- **跨链分析**：不同链上相关资产的关系
- **套利组合**：多个交易所之间的价格关系

---

## 第2章：数学原理与公式推导

### 2.1 向量自回归（VAR）模型

#### 2.1.1 VAR 模型的基本形式

**p阶VAR模型**：
```
Y_t = A_1 × Y_{t-1} + A_2 × Y_{t-2} + ... + A_p × Y_{t-p} + ε_t
```

其中：
- $Y_t$：$n \times 1$ 向量，包含 $n$ 个变量
- $A_i$：$n \times n$ 系数矩阵
- $\varepsilon_t$：$n \times 1$ 误差向量，$\varepsilon_t \sim N(0, \Sigma)$
- $p$：滞后阶数

**在加密货币中的应用**：
```
Y_t = [log(HYPE_t), log(PURR_t), log(TON_t)]'
```

#### 2.1.2 VAR 模型的差分形式

**将VAR模型改写为差分形式**：
```
ΔY_t = Π × Y_{t-1} + Γ_1 × ΔY_{t-1} + Γ_2 × ΔY_{t-2} + ... + Γ_{p-1} × ΔY_{t-p+1} + ε_t
```

其中：
- $\Delta Y_t = Y_t - Y_{t-1}$：一阶差分
- $\Pi = -(I - A_1 - A_2 - ... - A_p)$：长期影响矩阵
- $\Gamma_i$：短期动态系数矩阵

### 2.2 协整关系的矩阵表示

#### 2.2.1 矩阵 $\Pi$ 的分解

**关键分解**：
```
Π = α × β'
```

其中：
- $\alpha$：$n \times r$ 调整速度矩阵（Error Correction Coefficients）
- $\beta$：$n \times r$ 协整向量矩阵（Cointegration Vectors）
- $r$：协整关系的数量（$0 \leq r \leq n-1$）

**经济含义**：
- $\beta$：描述长期均衡关系
- $\alpha$：描述向均衡调整的速度

#### 2.2.2 协整关系的数量

**矩阵 $\Pi$ 的秩**：
- $rank(\Pi) = 0$：不存在协整关系，所有变量都是 $I(1)$
- $rank(\Pi) = r$（$1 \leq r \leq n-1$）：存在 $r$ 个协整关系
- $rank(\Pi) = n$：所有变量都是 $I(0)$（平稳）

**Johansen 检验的核心**：
检验矩阵 $\Pi$ 的秩，即协整关系的数量 $r$。

### 2.3 向量误差修正模型（VECM）

#### 2.3.1 VECM 的完整形式

**VECM 模型**：
```
ΔY_t = α × β' × Y_{t-1} + Γ_1 × ΔY_{t-1} + ... + Γ_{p-1} × ΔY_{t-p+1} + ε_t
```

**展开形式**（以3变量为例）：
```
Δlog(HYPE_t) = α_1 × [β_1×log(HYPE_{t-1}) + β_2×log(PURR_{t-1}) + β_3×log(TON_{t-1})] + ...
Δlog(PURR_t) = α_2 × [β_1×log(HYPE_{t-1}) + β_2×log(PURR_{t-1}) + β_3×log(TON_{t-1})] + ...
Δlog(TON_t)  = α_3 × [β_1×log(HYPE_{t-1}) + β_2×log(PURR_{t-1}) + β_3×log(TON_{t-1})] + ...
```

**协整关系**：
```
EC_t = β_1×log(HYPE_{t-1}) + β_2×log(PURR_{t-1}) + β_3×log(TON_{t-1})
```

这就是误差修正项（Error Correction Term），表示偏离长期均衡的程度。

#### 2.3.2 误差修正机制

**调整过程**：
- 当 $EC_t > 0$ 时，系统偏离均衡，各变量会调整以回归均衡
- $\alpha$ 系数表示调整速度
- $\alpha < 0$ 表示向均衡回归（均值回归）
- $\alpha$ 的绝对值越大，调整速度越快

---

## 第3章：向量误差修正模型（VECM）

### 3.1 VECM 的估计

#### 3.1.1 最大似然估计（MLE）

**Johansen 方法的核心**：
使用最大似然估计（MLE）来估计 VECM 模型参数。

**估计步骤**：
1. 估计无约束 VAR 模型
2. 估计约束 VECM 模型（给定协整秩 $r$）
3. 计算似然比统计量
4. 进行假设检验

#### 3.1.2 特征值分解

**关键数学工具**：
Johansen 方法通过特征值分解来检验协整关系。

**特征值 $\lambda_i$**：
- 按降序排列：$\lambda_1 > \lambda_2 > ... > \lambda_n$
- 特征值的大小反映协整关系的强度
- 非零特征值的数量等于协整关系的数量

### 3.2 确定性项的处理

#### 3.2.1 三种确定性项形式

**形式1：无常数项、无趋势项**（`det_order=0`）
```
ΔY_t = α × β' × Y_{t-1} + Γ_1 × ΔY_{t-1} + ... + ε_t
```

**形式2：有常数项、无趋势项**（`det_order=1`，最常用）
```
ΔY_t = α × β' × Y_{t-1} + μ + Γ_1 × ΔY_{t-1} + ... + ε_t
```

**形式3：有常数项、有趋势项**（`det_order=-1`）
```
ΔY_t = α × β' × Y_{t-1} + μ + δt + Γ_1 × ΔY_{t-1} + ... + ε_t
```

**选择建议**：
- 对于价格序列，通常使用 `det_order=1`（有常数项）
- 如果序列有明显趋势，考虑使用 `det_order=-1`

### 3.3 滞后阶数的选择

#### 3.3.1 信息准则

**常用准则**：
1. **AIC**（Akaike Information Criterion）
2. **BIC**（Bayesian Information Criterion）
3. **HQ**（Hannan-Quinn Criterion）

**选择原则**：
- AIC：倾向于选择更多滞后项
- BIC：倾向于选择更少滞后项（更保守）
- 通常先估计无约束 VAR，选择最优滞后阶数

**代码示例**：
```python
from statsmodels.tsa.vector_ar.var_model import VAR

# 估计VAR模型
model = VAR(data)
lag_order = model.select_order(maxlags=10)

# 使用AIC选择
optimal_lag = lag_order.aic
```

---

## 第4章：检验步骤详解

### 4.1 完整检验流程

#### 步骤1：数据准备

**要求**：
1. 所有变量必须是 $I(1)$（一阶单整）
2. 数据长度必须相同
3. 建议至少100-200个观测值

**代码示例**：
```python
import pandas as pd
import numpy as np
from statsmodels.tsa.stattools import adfuller

# 准备数据
data = pd.DataFrame({
    'hype': log_hype_prices,
    'purr': log_purr_prices,
    'ton': log_ton_prices
})

# 验证每个变量都是I(1)
for col in data.columns:
    adf_result = adfuller(data[col].diff().dropna())
    print(f"{col}: ADF p-value = {adf_result[1]:.4f}")
    # p-value < 0.05 表示差分后平稳，原序列是I(1)
```

#### 步骤2：选择滞后阶数

**方法**：
使用信息准则（AIC/BIC）选择最优滞后阶数。

**代码示例**：
```python
from statsmodels.tsa.vector_ar.var_model import VAR

# 估计VAR模型选择滞后阶数
model = VAR(data)
lag_order = model.select_order(maxlags=10)

print(f"最优滞后阶数（AIC）: {lag_order.aic}")
print(f"最优滞后阶数（BIC）: {lag_order.bic}")

# 通常使用AIC或BIC，Johansen检验中滞后阶数 = VAR滞后阶数 - 1
k_ar_diff = lag_order.aic - 1  # 或 lag_order.bic - 1
```

#### 步骤3：选择确定性项形式

**选择原则**：
- 对于价格序列，通常使用 `det_order=1`（有常数项）
- 如果序列有明显趋势，使用 `det_order=-1`

**代码示例**：
```python
det_order = 1  # 有常数项，无趋势项
```

#### 步骤4：执行 Johansen 检验

**代码示例**：
```python
from statsmodels.tsa.vector_ar.vecm import coint_johansen

# 执行Johansen检验
result = coint_johansen(
    data,
    det_order=1,      # 确定性项：1=有常数项
    k_ar_diff=k_ar_diff  # 滞后阶数
)
```

#### 步骤5：解读检验结果

**关键输出**：
- `result.lr1`：迹检验统计量
- `result.lr2`：最大特征值检验统计量
- `result.cvt`：临界值表
- `result.cvm`：最大特征值检验的临界值
- `result.evec`：协整向量
- `result.eig`：特征值

### 4.2 结果解读示例

```python
# 迹检验
print("迹检验统计量:")
for i in range(len(result.lr1)):
    print(f"r <= {i}: {result.lr1[i]:.4f} (临界值5%: {result.cvt[i, 1]:.4f})")
    if result.lr1[i] > result.cvt[i, 1]:
        print(f"  -> 拒绝 H0: r <= {i}，存在至少 {i+1} 个协整关系")
    else:
        print(f"  -> 不能拒绝 H0: r <= {i}")

# 最大特征值检验
print("\n最大特征值检验统计量:")
for i in range(len(result.lr2)):
    print(f"r = {i}: {result.lr2[i]:.4f} (临界值5%: {result.cvm[i, 1]:.4f})")
    if result.lr2[i] > result.cvm[i, 1]:
        print(f"  -> 拒绝 H0: r = {i}，存在至少 {i+1} 个协整关系")
    else:
        print(f"  -> 不能拒绝 H0: r = {i}")

# 协整向量
print("\n协整向量（标准化后）:")
print(result.evec[:, 0])  # 第一个协整向量
```

---

## 第5章：迹检验与最大特征值检验

### 5.1 迹检验（Trace Test）

#### 5.1.1 检验假设

**序列检验**：
- $H_0: r = 0$ vs $H_1: r \geq 1$
- $H_0: r \leq 1$ vs $H_1: r \geq 2$
- $H_0: r \leq 2$ vs $H_1: r \geq 3$
- ...

**检验统计量**：
```
λ_trace(r) = -T × Σ_{i=r+1}^{n} ln(1 - λ_i)
```

其中：
- $T$：样本量
- $\lambda_i$：特征值（按降序排列）
- $r$：假设的协整关系数量

#### 5.1.2 检验步骤

**从下往上检验**：
1. 先检验 $r = 0$（不存在协整关系）
2. 如果拒绝，检验 $r \leq 1$（最多1个协整关系）
3. 如果拒绝，检验 $r \leq 2$（最多2个协整关系）
4. 继续直到不能拒绝原假设

**判断标准**：
- 如果 $\lambda_{trace}(r) >$ 临界值，拒绝 $H_0$，存在至少 $r+1$ 个协整关系
- 如果 $\lambda_{trace}(r) \leq$ 临界值，不能拒绝 $H_0$，最多存在 $r$ 个协整关系

### 5.2 最大特征值检验（Maximum Eigenvalue Test）

#### 5.2.1 检验假设

**逐个检验**：
- $H_0: r = 0$ vs $H_1: r = 1$
- $H_0: r = 1$ vs $H_1: r = 2$
- $H_0: r = 2$ vs $H_1: r = 3$
- ...

**检验统计量**：
```
λ_max(r, r+1) = -T × ln(1 - λ_{r+1})
```

其中：
- $T$：样本量
- $\lambda_{r+1}$：第 $r+1$ 个特征值

#### 5.2.2 检验步骤

**从上往下检验**：
1. 先检验 $r = 0$ vs $r = 1$
2. 如果拒绝，检验 $r = 1$ vs $r = 2$
3. 如果拒绝，检验 $r = 2$ vs $r = 3$
4. 继续直到不能拒绝原假设

**判断标准**：
- 如果 $\lambda_{max}(r, r+1) >$ 临界值，拒绝 $H_0$，存在至少 $r+1$ 个协整关系
- 如果 $\lambda_{max}(r, r+1) \leq$ 临界值，不能拒绝 $H_0$，最多存在 $r$ 个协整关系

### 5.3 两种检验的对比

#### 5.3.1 检验功效

**迹检验**：
- 功效更高（更容易拒绝原假设）
- 适合检测多个协整关系
- 推荐用于确定协整关系的数量

**最大特征值检验**：
- 功效较低
- 适合检测单个协整关系
- 通常作为迹检验的补充

#### 5.3.2 实际应用建议

**推荐做法**：
1. **主要使用迹检验**：确定协整关系的数量
2. **最大特征值检验作为验证**：确认结果的一致性
3. **如果两种检验结果不一致**：通常以迹检验为准

**代码示例**：
```python
def interpret_johansen_result(result):
    """解读Johansen检验结果"""
    n_vars = len(result.eig)
    
    # 迹检验
    print("=" * 60)
    print("迹检验结果:")
    print("=" * 60)
    trace_rank = None
    for i in range(n_vars):
        trace_stat = result.lr1[i]
        critical_value = result.cvt[i, 1]  # 5%临界值
        print(f"H0: r <= {i}  |  统计量: {trace_stat:.4f}  |  临界值(5%): {critical_value:.4f}", end="")
        if trace_stat > critical_value:
            print("  ✅ 拒绝H0")
            trace_rank = i + 1
        else:
            print("  ❌ 不能拒绝H0")
            break
    
    # 最大特征值检验
    print("\n" + "=" * 60)
    print("最大特征值检验结果:")
    print("=" * 60)
    max_eigen_rank = None
    for i in range(n_vars):
        max_eigen_stat = result.lr2[i]
        critical_value = result.cvm[i, 1]  # 5%临界值
        print(f"H0: r = {i}  |  统计量: {max_eigen_stat:.4f}  |  临界值(5%): {critical_value:.4f}", end="")
        if max_eigen_stat > critical_value:
            print("  ✅ 拒绝H0")
            max_eigen_rank = i + 1
        else:
            print("  ❌ 不能拒绝H0")
            if max_eigen_rank is None:
                max_eigen_rank = i
            break
    
    # 综合判断
    print("\n" + "=" * 60)
    print("综合判断:")
    print("=" * 60)
    if trace_rank is not None:
        print(f"迹检验：存在 {trace_rank} 个协整关系")
    if max_eigen_rank is not None:
        print(f"最大特征值检验：存在 {max_eigen_rank} 个协整关系")
    
    # 推荐使用迹检验的结果
    final_rank = trace_rank if trace_rank is not None else max_eigen_rank
    print(f"\n推荐结论：存在 {final_rank} 个协整关系")
    
    return final_rank
```

---

## 第6章：优缺点分析

### 6.1 Johansen 检验的优点

#### 6.1.1 多变量支持

**核心优势**：
- 可以同时处理多个变量（≥2）
- 不需要预先指定因变量
- 所有变量在模型中地位平等

**应用场景**：
- 三币组合：HYPE、PURR、TON
- 多资产套利组合
- 板块内多个代币的关系分析

#### 6.1.2 多个协整关系

**核心优势**：
- 可以检测并估计多个协整关系
- 对于复杂系统，不会遗漏协整关系
- 可以分析多个长期均衡关系

**例子**：
- 3个变量可能同时存在2个协整关系
- 每个协整关系代表不同的长期均衡

#### 6.1.3 统计性质更优

**理论优势**：
- 基于最大似然估计（MLE）
- 渐近性质更好
- 可以同时估计所有参数
- 提供了完整的统计推断框架

#### 6.1.4 对称性

**优势**：
- 不需要预先指定因变量
- 所有变量在模型中地位平等
- 避免了变量选择问题

### 6.2 Johansen 检验的缺点

#### 6.2.1 计算复杂度高

**问题**：
- 需要估计VAR模型
- 需要特征值分解
- 计算时间较长
- 不适合实时交易

**影响**：
- 对于高频交易，计算延迟可能较大
- 需要更多的计算资源

#### 6.2.2 参数选择复杂

**问题**：
- 需要选择滞后阶数
- 需要选择确定性项形式
- 参数选择对结果影响较大
- 需要一定的经验

**建议**：
- 使用信息准则（AIC/BIC）选择滞后阶数
- 对于价格序列，通常使用 `det_order=1`
- 可以尝试不同的参数组合

#### 6.2.3 样本量要求高

**问题**：
- 需要较大的样本量（建议100-200+）
- 小样本下检验功效较低
- 临界值在小样本下可能不准确

**建议**：
- 至少需要100个观测值
- 对于高频数据，可以使用更长的历史窗口
- 考虑使用小样本修正

#### 6.2.4 结果解释复杂

**问题**：
- 协整向量的解释不如Engle-Granger直观
- 需要理解矩阵和特征值
- 多个协整关系时，解释更复杂

**建议**：
- 标准化协整向量（通常将第一个系数设为1）
- 结合经济理论解释结果
- 可视化协整关系

### 6.3 适用场景总结

**适合使用 Johansen 检验的情况**：
- ✅ 3个或更多变量
- ✅ 可能存在多个协整关系
- ✅ 需要严格的统计推断
- ✅ 不追求实时性
- ✅ 样本量充足（>100）

**不适合使用的情况**：
- ❌ 只有2个变量（使用Engle-Granger更简单）
- ❌ 需要实时交易（计算延迟）
- ❌ 样本量很小（<50）
- ❌ 需要快速筛选大量资产对

---

## 第7章：与Engle-Granger检验对比

### 7.1 方法对比表

| 特性 | Engle-Granger | Johansen |
|------|---------------|----------|
| **适用变量数** | 仅2个变量 | 多个变量（≥2） |
| **协整关系数** | 只能检测1个 | 可以检测多个 |
| **方法类型** | 两步法 | 系统方法 |
| **理论基础** | 基于残差平稳性 | 基于VAR模型 |
| **估计方法** | OLS | 最大似然估计（MLE） |
| **实现难度** | 简单 | 较复杂 |
| **计算速度** | 快 | 较慢 |
| **统计性质** | 渐近有效 | 更优 |
| **变量选择** | 需要指定因变量 | 不需要 |
| **样本量要求** | 50+ | 100+ |

### 7.2 数学原理对比

#### 7.2.1 Engle-Granger 方法

**模型**：
```
Y_t = α + βX_t + ε_t
检验：ε_t 是否平稳（ADF检验）
```

**特点**：
- 单方程模型
- 需要预先指定因变量
- 基于残差检验
- 简单直观

#### 7.2.2 Johansen 方法

**模型**：
```
ΔY_t = ΠY_{t-1} + Γ_1ΔY_{t-1} + ... + ε_t
其中：Π = αβ'
检验：rank(Π) = r（矩阵秩检验）
```

**特点**：
- 多方程系统
- 不需要预先指定因变量
- 基于矩阵秩检验
- 更严格的理论框架

### 7.3 实际应用建议

#### 7.3.1 何时使用 Engle-Granger？

**推荐场景**：
1. **配对交易**：只有2个资产，如 HYPE/PURR
2. **快速筛选**：需要快速验证大量资产对
3. **实时交易**：需要低延迟的计算
4. **易于解释**：需要向非技术人员解释结果

#### 7.3.2 何时使用 Johansen？

**推荐场景**：
1. **多资产组合**：3个或更多资产
2. **学术研究**：需要严格的统计推断
3. **复杂系统**：可能存在多个协整关系
4. **长期分析**：不追求实时性

### 7.4 代码对比示例

#### Engle-Granger 实现（简单）
```python
from sklearn.linear_model import LinearRegression
from statsmodels.tsa.stattools import adfuller

# 只需几行代码
model = LinearRegression()
model.fit(log_base, log_alt)
spread = log_alt - model.predict(log_base)
adf_result = adfuller(spread)
is_cointegrated = adf_result[1] < 0.05
```

#### Johansen 实现（复杂）
```python
from statsmodels.tsa.vector_ar.vecm import coint_johansen
from statsmodels.tsa.vector_ar.var_model import VAR

# 需要准备多变量数据
data = pd.DataFrame({
    'hype': log_hype_prices,
    'purr': log_purr_prices,
    'ton': log_ton_prices
})

# 需要选择滞后阶数
model = VAR(data)
lag_order = model.select_order(maxlags=10)
k_ar_diff = lag_order.aic - 1

# 需要选择参数
result = coint_johansen(
    data, 
    det_order=1,      # 确定性项
    k_ar_diff=k_ar_diff  # 滞后阶数
)

# 需要解释多个统计量
trace_stat = result.lr1
max_eigen_stat = result.lr2
cointegration_vectors = result.evec
```

---

## 第8章：代码实现详解

### 8.1 完整的实现示例

#### 8.1.1 基础实现

```python
import pandas as pd
import numpy as np
from statsmodels.tsa.vector_ar.vecm import coint_johansen
from statsmodels.tsa.vector_ar.var_model import VAR
from statsmodels.tsa.stattools import adfuller

def johansen_cointegration_test(
    data: pd.DataFrame,
    det_order: int = 1,
    maxlags: int = 10,
    significance_level: float = 0.05
) -> dict:
    """
    Johansen 协整检验
    
    Parameters:
    -----------
    data : pd.DataFrame
        多变量时间序列数据，每列一个变量
    det_order : int
        确定性项形式：
        - 0: 无常数项、无趋势项
        - 1: 有常数项、无趋势项（推荐）
        - -1: 有常数项、有趋势项
    maxlags : int
        最大滞后阶数（用于选择最优滞后阶数）
    significance_level : float
        显著性水平（默认0.05）
    
    Returns:
    --------
    dict: 包含检验结果的字典
    """
    # 1. 数据验证
    if data.isnull().any().any():
        raise ValueError("数据包含缺失值，请先处理")
    
    if len(data) < 50:
        raise ValueError(f"样本量不足，至少需要50个观测值，当前{len(data)}个")
    
    # 2. 验证变量是I(1)
    print("验证变量是否为I(1)...")
    for col in data.columns:
        diff_data = data[col].diff().dropna()
        adf_result = adfuller(diff_data)
        if adf_result[1] >= 0.05:
            print(f"警告：{col} 的差分序列可能非平稳（ADF p-value={adf_result[1]:.4f}）")
    
    # 3. 选择滞后阶数
    print("\n选择最优滞后阶数...")
    model = VAR(data)
    lag_order = model.select_order(maxlags=maxlags)
    k_ar_diff = lag_order.aic - 1  # Johansen检验中滞后阶数 = VAR滞后阶数 - 1
    print(f"最优滞后阶数（AIC）: {lag_order.aic}")
    print(f"Johansen检验滞后阶数: {k_ar_diff}")
    
    # 4. 执行Johansen检验
    print("\n执行Johansen检验...")
    result = coint_johansen(
        data,
        det_order=det_order,
        k_ar_diff=k_ar_diff
    )
    
    # 5. 解读结果
    n_vars = len(data.columns)
    trace_rank = None
    max_eigen_rank = None
    
    # 迹检验
    print("\n" + "=" * 70)
    print("迹检验结果:")
    print("=" * 70)
    for i in range(n_vars):
        trace_stat = result.lr1[i]
        critical_value = result.cvt[i, 1]  # 5%临界值
        print(f"H0: r <= {i:2d}  |  统计量: {trace_stat:8.4f}  |  临界值(5%): {critical_value:8.4f}", end="")
        if trace_stat > critical_value:
            print("  ✅ 拒绝H0")
            trace_rank = i + 1
        else:
            print("  ❌ 不能拒绝H0")
            break
    
    # 最大特征值检验
    print("\n" + "=" * 70)
    print("最大特征值检验结果:")
    print("=" * 70)
    for i in range(n_vars):
        max_eigen_stat = result.lr2[i]
        critical_value = result.cvm[i, 1]  # 5%临界值
        print(f"H0: r = {i:2d}   |  统计量: {max_eigen_stat:8.4f}  |  临界值(5%): {critical_value:8.4f}", end="")
        if max_eigen_stat > critical_value:
            print("  ✅ 拒绝H0")
            max_eigen_rank = i + 1
        else:
            print("  ❌ 不能拒绝H0")
            if max_eigen_rank is None:
                max_eigen_rank = i
            break
    
    # 6. 提取协整向量
    final_rank = trace_rank if trace_rank is not None else max_eigen_rank
    
    cointegration_vectors = {}
    if final_rank and final_rank > 0:
        print("\n" + "=" * 70)
        print(f"协整向量（存在 {final_rank} 个协整关系）:")
        print("=" * 70)
        for i in range(final_rank):
            vec = result.evec[:, i]
            # 标准化（使第一个系数为1）
            vec_normalized = vec / vec[0]
            cointegration_vectors[f'vector_{i+1}'] = pd.Series(
                vec_normalized,
                index=data.columns
            )
            print(f"\n协整向量 {i+1}:")
            for j, col in enumerate(data.columns):
                print(f"  {col:10s}: {vec_normalized[j]:8.4f}")
    
    # 7. 返回结果
    return {
        'trace_rank': trace_rank,
        'max_eigen_rank': max_eigen_rank,
        'final_rank': final_rank,
        'cointegration_vectors': cointegration_vectors,
        'eigenvalues': result.eig,
        'trace_stats': result.lr1,
        'max_eigen_stats': result.lr2,
        'trace_critical_values': result.cvt,
        'max_eigen_critical_values': result.cvm,
        'is_cointegrated': final_rank is not None and final_rank > 0,
        'raw_result': result
    }
```

#### 8.1.2 使用示例

```python
# 准备数据
data = pd.DataFrame({
    'hype': np.log(hype_prices),
    'purr': np.log(purr_prices),
    'ton': np.log(ton_prices)
})

# 执行检验
result = johansen_cointegration_test(
    data,
    det_order=1,
    maxlags=10
)

# 查看结果
if result['is_cointegrated']:
    print(f"\n✅ 协整检验通过：存在 {result['final_rank']} 个协整关系")
    for vec_name, vec in result['cointegration_vectors'].items():
        print(f"\n{vec_name}:")
        print(vec)
else:
    print("\n❌ 协整检验未通过：不存在协整关系")
```

### 8.2 误差修正项的计算

#### 8.2.1 计算误差修正项

```python
def calculate_error_correction_term(
    data: pd.DataFrame,
    cointegration_vector: pd.Series
) -> pd.Series:
    """
    计算误差修正项（Error Correction Term）
    
    Parameters:
    -----------
    data : pd.DataFrame
        原始数据（对数价格）
    cointegration_vector : pd.Series
        协整向量
    
    Returns:
    --------
    pd.Series: 误差修正项序列
    """
    # 计算线性组合
    ec_term = (data * cointegration_vector).sum(axis=1)
    return ec_term

# 使用示例
if result['is_cointegrated']:
    # 使用第一个协整向量
    vec1 = result['cointegration_vectors']['vector_1']
    ec_term = calculate_error_correction_term(data, vec1)
    
    # 误差修正项应该平稳（均值回归）
    print("误差修正项统计:")
    print(f"均值: {ec_term.mean():.4f}")
    print(f"标准差: {ec_term.std():.4f}")
    print(f"最小值: {ec_term.min():.4f}")
    print(f"最大值: {ec_term.max():.4f}")
```

### 8.3 调整速度的估计

#### 8.3.1 估计VECM模型

```python
from statsmodels.tsa.vector_ar.vecm import VECM

def estimate_vecm_model(
    data: pd.DataFrame,
    cointegration_rank: int,
    k_ar_diff: int = 1,
    det_order: int = 1
):
    """
    估计VECM模型，获取调整速度
    
    Parameters:
    -----------
    data : pd.DataFrame
        多变量时间序列数据
    cointegration_rank : int
        协整关系的数量
    k_ar_diff : int
        滞后阶数
    det_order : int
        确定性项形式
    
    Returns:
    --------
    VECM模型估计结果
    """
    # 估计VECM模型
    model = VECM(
        data,
        k_ar_diff=k_ar_diff,
        coint_rank=cointegration_rank,
        deterministic=det_order
    )
    vecm_result = model.fit()
    
    return vecm_result

# 使用示例
if result['final_rank'] and result['final_rank'] > 0:
    vecm_result = estimate_vecm_model(
        data,
        cointegration_rank=result['final_rank'],
        k_ar_diff=1,
        det_order=1
    )
    
    # 调整速度矩阵
    alpha = vecm_result.alpha  # 调整速度
    beta = vecm_result.beta   # 协整向量
    
    print("调整速度矩阵 (alpha):")
    print(alpha)
    print("\n协整向量矩阵 (beta):")
    print(beta)
```

---

## 第9章：实战应用案例

### 9.1 案例1：三币组合（HYPE、PURR、TON）

#### 9.1.1 数据准备

```python
import pandas as pd
import numpy as np
from statsmodels.tsa.vector_ar.vecm import coint_johansen

# 假设已有价格数据
hype_prices = ...  # HYPE价格序列
purr_prices = ...  # PURR价格序列
ton_prices = ...   # TON价格序列

# 转换为对数价格
data = pd.DataFrame({
    'hype': np.log(hype_prices),
    'purr': np.log(purr_prices),
    'ton': np.log(ton_prices)
})

print("数据概览:")
print(data.describe())
```

#### 9.1.2 执行检验

```python
# 执行Johansen检验
result = johansen_cointegration_test(
    data,
    det_order=1,
    maxlags=10
)
```

#### 9.1.3 结果解读

**假设检验结果**：
```
迹检验结果:
H0: r <= 0  |  统计量: 45.2341  |  临界值(5%): 29.7971  ✅ 拒绝H0
H0: r <= 1  |  统计量: 12.3456  |  临界值(5%): 15.4947  ❌ 不能拒绝H0

结论：存在1个协整关系
```

**协整向量**：
```
协整向量 1:
  hype      :  1.0000
  purr      : -1.4800
  ton       :  0.3200
```

**经济解释**：
- 长期均衡关系：`hype - 1.48*purr + 0.32*ton = 0`
- 当价差偏离均衡时，三个币种会调整以回归均衡

#### 9.1.4 交易策略

```python
# 计算误差修正项
vec1 = result['cointegration_vectors']['vector_1']
ec_term = calculate_error_correction_term(data, vec1)

# 计算Z-score
ec_mean = ec_term.mean()
ec_std = ec_term.std()
z_score = (ec_term - ec_mean) / ec_std

# 交易信号
# 当Z-score > 2：价差偏高，做空组合
# 当Z-score < -2：价差偏低，做多组合
```

### 9.2 案例2：板块内多个代币

#### 9.2.1 场景描述

**分析目标**：
- 同一板块内的多个代币（如DeFi板块）
- 检测是否存在板块内的协整关系
- 构建板块套利策略

#### 9.2.2 实现代码

```python
# 假设有5个DeFi代币
defi_tokens = ['token1', 'token2', 'token3', 'token4', 'token5']

# 准备数据
data = pd.DataFrame()
for token in defi_tokens:
    prices = get_token_prices(token)
    data[token] = np.log(prices)

# 执行检验
result = johansen_cointegration_test(
    data,
    det_order=1,
    maxlags=10
)

# 如果存在多个协整关系
if result['final_rank'] and result['final_rank'] > 1:
    print(f"发现 {result['final_rank']} 个协整关系，可以构建多个套利组合")
    
    # 每个协整向量代表一个套利机会
    for i, (vec_name, vec) in enumerate(result['cointegration_vectors'].items()):
        print(f"\n套利组合 {i+1}:")
        print(vec)
```

### 9.3 案例3：跨交易所套利

#### 9.3.1 场景描述

**分析目标**：
- 同一资产在不同交易所的价格
- 检测是否存在跨交易所的协整关系
- 构建跨交易所套利策略

#### 9.3.2 实现代码

```python
# 假设有3个交易所
exchanges = ['binance', 'coinbase', 'hyperliquid']
token = 'BTC'

# 准备数据
data = pd.DataFrame()
for exchange in exchanges:
    prices = get_prices(exchange, token)
    data[exchange] = np.log(prices)

# 执行检验
result = johansen_cointegration_test(
    data,
    det_order=1,
    maxlags=10
)

# 如果存在协整关系，可以进行跨交易所套利
if result['is_cointegrated']:
    print("✅ 跨交易所价格存在协整关系，可以进行套利")
    
    # 计算价差
    vec1 = result['cointegration_vectors']['vector_1']
    spread = calculate_error_correction_term(data, vec1)
    
    # 当价差偏离均衡时，进行套利
    # 例如：binance价格偏高，coinbase价格偏低
    # 策略：在binance卖出，在coinbase买入
```

---

## 第10章：常见问题与注意事项

### 10.1 数据要求

#### 10.1.1 变量必须是I(1)

**要求**：
- 所有变量必须是一阶单整 $I(1)$
- 即原序列非平稳，但一阶差分后平稳

**验证方法**：
```python
from statsmodels.tsa.stattools import adfuller

# 检验原序列（应该非平稳）
adf_original = adfuller(data['hype'])
print(f"原序列ADF p-value: {adf_original[1]:.4f}")  # 应该 > 0.05

# 检验差分序列（应该平稳）
adf_diff = adfuller(data['hype'].diff().dropna())
print(f"差分序列ADF p-value: {adf_diff[1]:.4f}")  # 应该 < 0.05
```

**如果变量不是I(1)**：
- 可能需要进一步差分（但很少见）
- 或者变量本身就是平稳的（不适合协整检验）

#### 10.1.2 样本量要求

**建议**：
- 最少需要 **50-100** 个观测值
- 推荐使用 **100-200+** 个观测值
- 对于高频数据，可以使用更长的历史窗口

**原因**：
- Johansen检验需要估计多个参数
- 小样本下检验功效较低
- 临界值在小样本下可能不准确

### 10.2 参数选择

#### 10.2.1 滞后阶数选择

**方法**：
1. 使用信息准则（AIC/BIC）自动选择
2. 尝试不同的滞后阶数，观察结果稳定性
3. 考虑数据的频率（日线、小时线等）

**代码示例**：
```python
from statsmodels.tsa.vector_ar.var_model import VAR

# 使用AIC选择
model = VAR(data)
lag_order_aic = model.select_order(maxlags=10).aic

# 使用BIC选择
lag_order_bic = model.select_order(maxlags=10).bic

# 通常使用AIC（更保守，选择更多滞后项）
k_ar_diff = lag_order_aic - 1
```

#### 10.2.2 确定性项选择

**三种形式**：
- `det_order=0`：无常数项、无趋势项
- `det_order=1`：有常数项、无趋势项（**推荐**）
- `det_order=-1`：有常数项、有趋势项

**选择建议**：
- 对于价格序列，通常使用 `det_order=1`
- 如果序列有明显趋势，考虑使用 `det_order=-1`
- 可以尝试不同的形式，观察结果

### 10.3 结果解读

#### 10.3.1 协整向量的标准化

**问题**：
- 协整向量可以任意缩放
- 需要标准化以便解释

**方法**：
```python
# 方法1：使第一个系数为1（常用）
vec_normalized = vec / vec[0]

# 方法2：使向量长度为1
vec_normalized = vec / np.linalg.norm(vec)
```

#### 10.3.2 多个协整关系的解释

**问题**：
- 当存在多个协整关系时，如何解释？

**建议**：
- 每个协整向量代表一个独立的长期均衡关系
- 可以分别分析每个协整关系
- 结合经济理论解释

### 10.4 常见误区

#### 10.4.1 混淆协整和相关性

**错误理解**：
- 认为高相关性就意味着协整
- 认为协整就是相关性

**正确理解**：
- **相关性**：衡量两个序列的线性关系强度
- **协整**：衡量两个序列的长期均衡关系
- 高相关性不一定协整，协整也不一定高相关

#### 10.4.2 忽略变量必须是I(1)

**错误做法**：
- 直接对平稳序列进行协整检验
- 对已经是I(0)的序列进行检验

**正确做法**：
- 先验证变量是I(1)
- 如果变量是I(0)，不需要协整检验

#### 10.4.3 参数选择不当

**错误做法**：
- 随意选择滞后阶数
- 不验证参数选择的合理性

**正确做法**：
- 使用信息准则选择滞后阶数
- 尝试不同的参数组合
- 验证结果的稳定性

---

## 第11章：改进方向与扩展

### 11.1 理论扩展

#### 11.1.1 时变协整

**问题**：传统Johansen检验假设协整关系是常数

**扩展方向**：
- 时变协整模型
- 滚动窗口Johansen检验
- 结构突变检测

#### 11.1.2 非线性协整

**问题**：线性协整可能无法捕捉非线性关系

**扩展方向**：
- 非线性协整检验
- 神经网络协整模型

### 11.2 方法改进

#### 11.2.1 小样本修正

**问题**：小样本下临界值可能不准确

**改进方向**：
- 使用Bootstrap方法
- 小样本修正的临界值
- 蒙特卡洛模拟

#### 11.2.2 结构突变检测

**问题**：如果存在结构突变，Johansen检验可能失效

**改进方向**：
- 结合结构突变检测
- 分段协整检验
- 时变协整模型

### 11.3 实际应用扩展

#### 11.3.1 实时监控

**扩展**：
- 滚动窗口Johansen检验
- 实时监控协整关系
- 自动调整参数

#### 11.3.2 多资产组合优化

**扩展**：
- 结合协整关系构建投资组合
- 风险优化
- 动态调整

### 11.4 代码改进建议

#### 11.4.1 完整的实现类

```python
class JohansenCointegrationAnalyzer:
    """Johansen协整检验分析器"""
    
    def __init__(self, significance_level=0.05):
        self.significance_level = significance_level
    
    def test(self, data, det_order=1, maxlags=10):
        """执行Johansen检验"""
        # 实现检验逻辑
        pass
    
    def estimate_vecm(self, data, cointegration_rank, k_ar_diff=1):
        """估计VECM模型"""
        # 实现VECM估计
        pass
    
    def calculate_ec_term(self, data, cointegration_vector):
        """计算误差修正项"""
        # 实现EC项计算
        pass
    
    def plot_results(self, result):
        """可视化结果"""
        # 实现可视化
        pass
```

#### 11.4.2 滚动窗口检验

```python
def rolling_johansen_test(
    data: pd.DataFrame,
    window: int = 200,
    step: int = 20,
    det_order: int = 1,
    maxlags: int = 10
) -> pd.DataFrame:
    """
    滚动窗口Johansen检验，监控协整关系的稳定性
    """
    results = []
    
    for i in range(window, len(data), step):
        window_data = data.iloc[i-window:i]
        
        try:
            result = johansen_cointegration_test(
                window_data,
                det_order=det_order,
                maxlags=maxlags
            )
            
            results.append({
                'window_end': window_data.index[-1],
                'rank': result['final_rank'],
                'is_cointegrated': result['is_cointegrated']
            })
        except Exception as e:
            print(f"窗口 {i-window}:{i} 检验失败: {e}")
    
    return pd.DataFrame(results)
```

---

## 总结

### 核心要点

1. **Johansen检验**是多变量协整检验的标准方法
2. **适用场景**：3个或更多变量的协整分析
3. **核心步骤**：选择滞后阶数 → 执行检验 → 解读结果
4. **两种检验**：迹检验（推荐）和最大特征值检验
5. **关键输出**：协整关系的数量和协整向量

### 在项目中的应用建议

**当前项目**：
- ✅ 主要使用Engle-Granger（2变量配对交易）
- 🔄 未来可扩展：多币种组合分析

**扩展方向**：
- 三币组合：HYPE、PURR、TON
- 板块分析：同一板块内多个代币
- 跨交易所套利：多个交易所的价格关系

### 进一步学习

- **理论**：Johansen (1988, 1991) 原始论文
- **实践**：statsmodels 的 `coint_johansen` 函数
- **扩展**：时变协整、非线性协整

---

**文档版本**：v1.0  
**最后更新**：2024年  
**基于项目**：hyperliquid-pair-hype-purr-analyze

