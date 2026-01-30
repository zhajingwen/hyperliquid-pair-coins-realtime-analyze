#!/usr/bin/env python3
"""
BTC连续上涨后未来涨跌幅分布分析

分析BTC在剔除噪音（涨跌幅<0.5%）后，连续上涨3天后未来一周的收益率分布特征
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats
import yfinance as yf
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# 设置中文字体和样式
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
sns.set_style("whitegrid")

def get_btc_data(start_date='2015-01-01'):
    """获取BTC历史数据"""
    print(f"正在获取BTC-USD数据（从{start_date}至今）...")
    btc = yf.download('BTC-USD', start=start_date, progress=False)
    print(f"成功获取 {len(btc)} 条数据记录")
    return btc

def calculate_returns(df):
    """计算日收益率（百分比）"""
    df = df.copy()
    df['returns'] = df['Close'].pct_change() * 100  # 转换为百分比
    return df

def apply_noise_filter(df, threshold=0.5):
    """
    应用噪音过滤：将涨跌幅绝对值<threshold%的K线标记为噪音

    Parameters:
    - df: 数据框
    - threshold: 噪音阈值（百分比）

    Returns:
    - df: 添加了filtered_returns列的数据框
    """
    df = df.copy()
    # 创建过滤后的收益率列：噪音视为0
    df['filtered_returns'] = df['returns'].apply(
        lambda x: x if abs(x) >= threshold else 0
    )

    # 统计噪音数量
    noise_count = (abs(df['returns']) < threshold).sum()
    total_count = len(df) - 1  # 减去第一个NaN
    noise_pct = (noise_count / total_count) * 100

    print(f"\n噪音过滤统计：")
    print(f"  阈值: ±{threshold}%")
    print(f"  噪音K线数量: {noise_count} / {total_count} ({noise_pct:.2f}%)")

    return df

def identify_consecutive_up_days(df, n_days=3):
    """
    识别连续上涨n天的信号（基于过滤后的收益率）

    Parameters:
    - df: 数据框
    - n_days: 连续上涨天数

    Returns:
    - df: 添加了signal列的数据框
    """
    df = df.copy()
    df['signal'] = False

    # 统计连续上涨天数
    consecutive_up = 0

    for i in range(1, len(df)):
        if df['filtered_returns'].iloc[i] > 0:
            consecutive_up += 1
        else:
            consecutive_up = 0

        # 如果连续上涨达到n_days，标记信号
        if consecutive_up >= n_days:
            df.loc[df.index[i], 'signal'] = True

    signal_count = df['signal'].sum()
    print(f"\n信号识别统计：")
    print(f"  连续上涨天数要求: {n_days}天")
    print(f"  触发信号次数: {signal_count}")

    return df

def calculate_forward_returns(df, forward_days=7):
    """
    计算信号触发后未来N天的累计收益率

    Parameters:
    - df: 数据框
    - forward_days: 前向天数

    Returns:
    - df: 添加了forward_returns列的数据框
    """
    df = df.copy()

    # 计算未来N天的累计收益率
    # 使用原始returns（不是filtered_returns）来计算实际收益
    forward_sum = df['returns'].shift(-1).rolling(forward_days).sum()

    # 只保留有信号的行的前向收益率，其他设为NaN
    df['forward_returns'] = forward_sum.where(df['signal'], np.nan)

    return df

def analyze_forward_returns(df):
    """
    分析未来收益率的统计特征

    Parameters:
    - df: 数据框

    Returns:
    - results: 统计分析结果字典
    """
    # 提取有效的前向收益率数据
    forward_rets = df['forward_returns'].dropna()

    if len(forward_rets) == 0:
        print("警告：没有有效的前向收益率数据！")
        return None

    print(f"\n=" * 60)
    print(f"未来一周收益率分布分析")
    print(f"=" * 60)
    print(f"\n样本数量: {len(forward_rets)}")

    # 1. 描述性统计
    print(f"\n【1. 描述性统计】")
    print(f"  均值: {forward_rets.mean():.4f}%")
    print(f"  中位数: {forward_rets.median():.4f}%")
    print(f"  标准差: {forward_rets.std():.4f}%")
    print(f"  最小值: {forward_rets.min():.4f}%")
    print(f"  最大值: {forward_rets.max():.4f}%")

    # 2. 分位数分析
    print(f"\n【2. 分位数分析】")
    quantiles = [0.1, 0.25, 0.5, 0.75, 0.9]
    for q in quantiles:
        val = forward_rets.quantile(q)
        print(f"  {int(q*100)}%分位数: {val:.4f}%")

    # 3. 涨跌分布
    print(f"\n【3. 涨跌分布】")
    up_count = (forward_rets > 0).sum()
    down_count = (forward_rets < 0).sum()
    flat_count = (forward_rets == 0).sum()
    total = len(forward_rets)

    print(f"  上涨: {up_count} 次 ({up_count/total*100:.2f}%)")
    print(f"  下跌: {down_count} 次 ({down_count/total*100:.2f}%)")
    print(f"  持平: {flat_count} 次 ({flat_count/total*100:.2f}%)")

    # 4. 区间分布
    print(f"\n【4. 区间分布】")
    bins = [-np.inf, -10, -5, 0, 5, 10, np.inf]
    labels = ['<-10%', '-10%~-5%', '-5%~0%', '0%~5%', '5%~10%', '>10%']

    bin_counts = pd.cut(forward_rets, bins=bins, labels=labels).value_counts().sort_index()
    for label, count in bin_counts.items():
        pct = count / total * 100
        print(f"  {label}: {count} 次 ({pct:.2f}%)")

    # 5. 统计检验
    print(f"\n【5. 统计检验】")

    # t检验：检验均值是否显著不为0
    t_stat, p_value = stats.ttest_1samp(forward_rets, 0)
    print(f"  单样本t检验（H0: μ=0）:")
    print(f"    t统计量: {t_stat:.4f}")
    print(f"    p值: {p_value:.4f}")
    print(f"    结论: {'拒绝' if p_value < 0.05 else '接受'}H0（α=0.05）")

    # 正态性检验
    _, p_norm = stats.normaltest(forward_rets)
    print(f"\n  正态性检验:")
    print(f"    p值: {p_norm:.4f}")
    print(f"    结论: 数据{'不'}符合正态分布（α=0.05）" if p_norm < 0.05 else "    结论: 数据符合正态分布（α=0.05）")

    # 偏度和峰度
    skewness = stats.skew(forward_rets)
    kurtosis = stats.kurtosis(forward_rets)
    print(f"\n  分布形态:")
    print(f"    偏度: {skewness:.4f} ({'右偏' if skewness > 0 else '左偏'})")
    print(f"    峰度: {kurtosis:.4f} ({'厚尾' if kurtosis > 0 else '薄尾'})")

    # 保存结果
    results = {
        'data': forward_rets,
        'mean': forward_rets.mean(),
        'median': forward_rets.median(),
        'std': forward_rets.std(),
        'min': forward_rets.min(),
        'max': forward_rets.max(),
        'up_pct': up_count/total*100,
        'down_pct': down_count/total*100,
        't_stat': t_stat,
        'p_value': p_value,
        'skewness': skewness,
        'kurtosis': kurtosis
    }

    return results

def plot_analysis(results, save_path='btc_forward_returns_analysis.png'):
    """
    生成分析图表

    Parameters:
    - results: 统计分析结果
    - save_path: 保存路径
    """
    if results is None:
        print("无法生成图表：缺少分析结果")
        return

    forward_rets = results['data']

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('BTC: Forward 7-Day Returns After 3 Consecutive Up Days',
                 fontsize=16, fontweight='bold', y=0.995)

    # 1. 直方图
    ax1 = axes[0, 0]
    n, bins, patches = ax1.hist(forward_rets, bins=30, alpha=0.7,
                                 color='steelblue', edgecolor='black')
    ax1.axvline(results['mean'], color='red', linestyle='--',
                linewidth=2, label=f"Mean: {results['mean']:.2f}%")
    ax1.axvline(results['median'], color='green', linestyle='--',
                linewidth=2, label=f"Median: {results['median']:.2f}%")
    ax1.set_xlabel('Forward 7-Day Return (%)', fontsize=11)
    ax1.set_ylabel('Frequency', fontsize=11)
    ax1.set_title('Distribution Histogram', fontsize=12, fontweight='bold')
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3)

    # 2. 箱线图
    ax2 = axes[0, 1]
    bp = ax2.boxplot(forward_rets, vert=True, patch_artist=True,
                     boxprops=dict(facecolor='lightblue', alpha=0.7),
                     medianprops=dict(color='red', linewidth=2),
                     whiskerprops=dict(linewidth=1.5),
                     capprops=dict(linewidth=1.5))
    ax2.set_ylabel('Forward 7-Day Return (%)', fontsize=11)
    ax2.set_title('Box Plot', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='y')

    # 添加统计信息
    stats_text = f"Q1: {forward_rets.quantile(0.25):.2f}%\n"
    stats_text += f"Q2: {results['median']:.2f}%\n"
    stats_text += f"Q3: {forward_rets.quantile(0.75):.2f}%"
    ax2.text(0.5, 0.02, stats_text, transform=ax2.transAxes,
             fontsize=9, verticalalignment='bottom',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    # 3. 累积分布函数
    ax3 = axes[1, 0]
    sorted_data = np.sort(forward_rets)
    cumulative = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
    ax3.plot(sorted_data, cumulative, linewidth=2, color='darkblue')
    ax3.axvline(0, color='red', linestyle='--', alpha=0.5, label='Zero Return')
    ax3.set_xlabel('Forward 7-Day Return (%)', fontsize=11)
    ax3.set_ylabel('Cumulative Probability', fontsize=11)
    ax3.set_title('Cumulative Distribution Function', fontsize=12, fontweight='bold')
    ax3.grid(True, alpha=0.3)
    ax3.legend(fontsize=10)

    # 添加概率信息
    prob_positive = (forward_rets > 0).sum() / len(forward_rets)
    ax3.text(0.05, 0.95, f"P(Return > 0) = {prob_positive:.2%}",
             transform=ax3.transAxes, fontsize=10,
             verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.7))

    # 4. Q-Q图（正态性检验）
    ax4 = axes[1, 1]
    stats.probplot(forward_rets, dist="norm", plot=ax4)
    ax4.set_title('Q-Q Plot (Normality Test)', fontsize=12, fontweight='bold')
    ax4.grid(True, alpha=0.3)

    # 添加正态性检验结果
    _, p_norm = stats.normaltest(forward_rets)
    norm_text = f"Normal test p-value: {p_norm:.4f}\n"
    norm_text += f"Skewness: {results['skewness']:.3f}\n"
    norm_text += f"Kurtosis: {results['kurtosis']:.3f}"
    ax4.text(0.05, 0.95, norm_text, transform=ax4.transAxes,
             fontsize=9, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.7))

    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"\n图表已保存至: {save_path}")
    plt.close()

def save_signal_data(df, save_path='btc_signal_data.csv'):
    """
    保存信号数据到CSV文件

    Parameters:
    - df: 数据框
    - save_path: 保存路径
    """
    # 只保存有信号的行
    signal_data = df[df['signal']].copy()
    signal_data = signal_data[['Close', 'returns', 'filtered_returns',
                                'forward_returns', 'signal']]
    signal_data.to_csv(save_path)
    print(f"信号数据已保存至: {save_path} ({len(signal_data)} 条记录)")

def main():
    """主函数"""
    print("=" * 60)
    print("BTC连续上涨后未来涨跌幅分布分析")
    print("=" * 60)

    # 1. 获取数据
    df = get_btc_data(start_date='2015-01-01')

    # 2. 计算收益率
    df = calculate_returns(df)

    # 3. 应用噪音过滤
    df = apply_noise_filter(df, threshold=0.5)

    # 4. 识别连续上涨3天的信号
    df = identify_consecutive_up_days(df, n_days=3)

    # 5. 计算前向收益率
    df = calculate_forward_returns(df, forward_days=7)

    # 6. 统计分析
    results = analyze_forward_returns(df)

    # 7. 生成图表
    if results is not None:
        plot_analysis(results, save_path='btc_forward_returns_analysis.png')

    # 8. 保存数据
    save_signal_data(df, save_path='btc_signal_data.csv')

    print(f"\n" + "=" * 60)
    print("分析完成！")
    print("=" * 60)

if __name__ == "__main__":
    main()
