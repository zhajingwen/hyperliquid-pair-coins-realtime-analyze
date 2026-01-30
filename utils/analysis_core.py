"""
分析核心模块 (Analysis Core)

提供共享的时序分析算法，包括：
- 相关性分析
- 协整检验
- Z-score计算
- 异常检测

被以下模块调用：
- realtime_kline_service.py (实时分析引擎)
- multi_coins.py (批量分析，如需改造)

Author: Claude Code
Date: 2026-01-19
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional
from statsmodels.tsa.stattools import coint, adfuller
import statsmodels.api as sm

from utils.logging_config import logger
from utils.config import CORRELATION_METHOD, ADF_LAG_SELECTION_METHOD
from utils.config import (
    MIN_POINTS_FOR_CORRELATION,
    MIN_POINTS_FOR_ZSCORE,
    MIN_POINTS_FOR_OLS,
    BETA_WINDOW,
    ZSCORE_WINDOW,
    COINTEGRATION_THRESHOLD,
    TARGET_CORR_THRESHOLD,
    ALPHA_SIGNIFICANCE_LEVEL,
    ALPHA_CROSS_ASSET_THRESHOLD,
    ALPHA_SAME_ASSET_THRESHOLD,
    ZSCORE_THRESHOLDS,
    HEALTH_MONITOR_LONG_WINDOW,
    HEALTH_MONITOR_SHORT_WINDOW,
    HEALTH_MONITOR_STATE_THRESHOLDS,
    HEALTH_MONITOR_PERIOD,
    REQUIRED_PERIODS,
    MIN_DATA_POINTS
)


# =====================================================
# 数据预处理
# =====================================================

def prepare_price_series(
    klines: List[Dict],
    price_col: str = 'close'
) -> pd.Series:
    """
    将K线数据转换为价格序列

    Args:
        klines: K线数据列表 [{"time": datetime, "close": float, ...}, ...]
        price_col: 价格字段名（默认 'close'）

    Returns:
        pd.Series: 价格序列，索引为时间
    """
    if not klines:
        return pd.Series()

    df = pd.DataFrame(klines)

    # 确保时间排序
    df = df.sort_values('time')

    # 设置时间索引
    df = df.set_index('time')

    return df[price_col]


# =====================================================
# 相关性分析
# =====================================================

def calculate_correlation(
    base_klines: List[Dict],
    alt_klines: List[Dict],
    method: str = CORRELATION_METHOD
) -> float:
    """
    计算两个币种的收益率相关系数

    使用收益率（return）而非价格（price）计算相关系数，
    与 multi_coins5.py 的计算逻辑保持一致。

    收益率相关性的优势：
    - 去趋势化：消除市场整体涨跌的影响
    - 平稳性：收益率序列通常平稳，适合统计建模
    - 实战意义：反映"基准币涨1%时，目标币涨多少"的关系

    Args:
        base_klines: 基础币种K线数据
        alt_klines: 目标币种K线数据
        method: 相关系数类型 ('pearson' | 'spearman' | 'kendall')

    Returns:
        float: 相关系数 (-1.0 ~ 1.0)
    """
    try:
        base_prices = prepare_price_series(base_klines)
        alt_prices = prepare_price_series(alt_klines)

        if len(base_prices) < MIN_POINTS_FOR_CORRELATION or len(alt_prices) < MIN_POINTS_FOR_CORRELATION:
            logger.warning(f"数据点不足{MIN_POINTS_FOR_CORRELATION}个，无法计算可靠的相关性")
            return 0.0

        # 对齐时间索引
        aligned = pd.DataFrame({
            'base': base_prices,
            'alt': alt_prices
        }).dropna()

        if len(aligned) < MIN_POINTS_FOR_CORRELATION:
            logger.warning(f"对齐后数据点不足{MIN_POINTS_FOR_CORRELATION}个")
            return 0.0

        # 计算收益率序列（与 multi_coins5.py 对齐）
        base_returns = aligned['base'].pct_change().dropna()
        alt_returns = aligned['alt'].pct_change().dropna()

        if len(base_returns) < MIN_POINTS_FOR_ZSCORE:
            logger.warning(f"收益率序列数据点不足{MIN_POINTS_FOR_ZSCORE}个")
            return 0.0

        # 计算收益率相关系数
        correlation = base_returns.corr(alt_returns, method=method)

        return float(correlation)

    except Exception as e:
        logger.error(f"相关性计算失败: {e}")
        return 0.0




# =====================================================
# OLS 协整分析（高级方法）
# =====================================================

def _select_cointegration_model(
    alpha: float,
    alpha_pvalue: float
) -> Tuple[str, bool, str]:
    """
    智能协整模型选择

    根据α的显著性和绝对值大小选择最优模型：
    - |α| > ALPHA_CROSS_ASSET_THRESHOLD 且显著 → 无α模型（跨资产类配对）
    - |α| < ALPHA_SAME_ASSET_THRESHOLD 且显著 → 标准EG模型（同类资产配对）
    - 其他 → 无α模型

    Args:
        alpha: OLS回归截距项
        alpha_pvalue: α的p值

    Returns:
        (model_type, use_alpha, model_reason): 模型类型、是否使用α、选择原因
    """
    if alpha_pvalue < ALPHA_SIGNIFICANCE_LEVEL and abs(alpha) > ALPHA_CROSS_ASSET_THRESHOLD:
        # α显著且绝对值很大 → 跨资产类配对（如NEAR/BTC）
        return "no_intercept_forced", False, f"|α|={abs(alpha):.1f}>{ALPHA_CROSS_ASSET_THRESHOLD}, 跨资产类配对"

    elif alpha_pvalue < ALPHA_SIGNIFICANCE_LEVEL and abs(alpha) < ALPHA_SAME_ASSET_THRESHOLD:
        # α显著且绝对值较小 → 同类资产配对（如UNI/SUSHI）
        return "standard_EG", True, f"|α|={abs(alpha):.1f}<{ALPHA_SAME_ASSET_THRESHOLD}, 同类资产配对"

    else:
        # α不显著或中等范围（ALPHA_SAME_ASSET_THRESHOLD<=|α|<=ALPHA_CROSS_ASSET_THRESHOLD）
        if alpha_pvalue >= ALPHA_SIGNIFICANCE_LEVEL:
            reason = "α不显著"
        else:
            reason = f"|α|={abs(alpha):.1f}∈[{ALPHA_SAME_ASSET_THRESHOLD},{ALPHA_CROSS_ASSET_THRESHOLD}], 中等范围"
        return "no_intercept", False, reason


def calculate_cointegration_params_ols(
    base_klines: List[Dict],
    alt_klines: List[Dict]
) -> Optional[Dict]:
    """
    全量数据OLS协整参数计算（Engle-Granger两步法）

    使用全量数据计算OLS回归参数和ADF检验，适用于事后验证分析。

    注意：此方法存在 look-ahead bias，仅用于验证性分析，不适用于实时交易。
    实时交易请使用 calculate_cointegration_params_dual_window。

    Args:
        base_klines: 基础币种K线数据
        alt_klines: 目标币种K线数据

    Returns:
        Dict: {
            'alpha': 截距项,
            'beta': 斜率,
            'spread': 价差序列,
            'adf_pvalue': ADF检验p值,
            'alpha_pvalue': α的p值,
            'beta_pvalue': β的p值,
            'rsquared': R²,
            'model_type': 模型类型,
            'use_alpha': 是否使用α,
            'model_reason': 模型选择原因
        } 或 None
    """
    try:
        base_prices = prepare_price_series(base_klines)
        alt_prices = prepare_price_series(alt_klines)

        # 对齐时间索引（自动处理数据长度不一致问题）
        aligned = pd.DataFrame({
            'base': base_prices,
            'alt': alt_prices
        }).dropna()

        # 数据验证
        if len(aligned) < MIN_POINTS_FOR_OLS:
            logger.debug(f"协整参数计算失败：对齐后数据点不足{MIN_POINTS_FOR_OLS}个")
            return None

        # 计算对数价格
        log_base_series = np.log(aligned['base'])
        log_alt_series = np.log(aligned['alt'])

        # statsmodels OLS回归：log_alt = α + β * log_base + ε
        X = sm.add_constant(log_base_series)
        model = sm.OLS(log_alt_series, X).fit()

        alpha = model.params.iloc[0]
        beta = model.params.iloc[1]
        alpha_pvalue = model.pvalues.iloc[0]
        beta_pvalue = model.pvalues.iloc[1]
        rsquared = model.rsquared

        # 智能模型选择
        model_type, use_alpha, model_reason = _select_cointegration_model(alpha, alpha_pvalue)

        # 计算价差
        if use_alpha:
            spread_ols = log_alt_series - (alpha + beta * log_base_series)
        else:
            spread_ols = log_alt_series - beta * log_base_series

        # ADF检验价差平稳性
        adf_result = adfuller(spread_ols.values, autolag=ADF_LAG_SELECTION_METHOD)
        adf_pvalue = adf_result[1]

        logger.debug(
            f"OLS协整参数 | α={alpha:.4f} (p={alpha_pvalue:.4f}) | "
            f"β={beta:.4f} (p={beta_pvalue:.4f}) | R²={rsquared:.4f} | "
            f"模型: {model_type} | 原因: {model_reason} | ADF p={adf_pvalue:.4f}"
        )

        return {
            'alpha': alpha,
            'beta': beta,
            'spread': spread_ols,
            'adf_pvalue': adf_pvalue,
            'alpha_pvalue': alpha_pvalue,
            'beta_pvalue': beta_pvalue,
            'rsquared': rsquared,
            'model_type': model_type,
            'use_alpha': use_alpha,
            'model_reason': model_reason
        }

    except Exception as e:
        logger.debug(f"OLS协整参数计算失败：{type(e).__name__}: {str(e)}", exc_info=True)
        return None


def calculate_cointegration_params_dual_window(
    base_klines: List[Dict],
    alt_klines: List[Dict],
    beta_window: int = None,
    zscore_window: int = None
) -> Optional[Dict]:
    """
    双窗口策略OLS协整参数计算

    关键特性：
    - beta_window (100期): 用于稳定的OLS回归参数估计
    - zscore_window (30期): 用于敏感的均值回归检测
    - 避免 look-ahead bias：使用前 beta_window-1 个点计算OLS

    Args:
        base_klines: 基础币种K线数据
        alt_klines: 目标币种K线数据
        beta_window: OLS回归窗口大小（默认从配置读取）
        zscore_window: Z-score计算窗口大小（默认从配置读取）

    Returns:
        Dict: {
            'alpha': 截距项,
            'beta': 斜率,
            'spread': 价差序列（用于Z-score计算）,
            'adf_pvalue': ADF检验p值,
            'alpha_pvalue': α的p值,
            'beta_pvalue': β的p值,
            'rsquared': R²,
            'model_type': 模型类型,
            'use_alpha': 是否使用α,
            'model_reason': 模型选择原因
        } 或 None
    """
    # 应用默认值
    if beta_window is None:
        beta_window = BETA_WINDOW
    if zscore_window is None:
        zscore_window = ZSCORE_WINDOW
    
    try:
        base_prices = prepare_price_series(base_klines)
        alt_prices = prepare_price_series(alt_klines)

        # 对齐时间索引（自动处理数据长度不一致问题）
        aligned = pd.DataFrame({
            'base': base_prices,
            'alt': alt_prices
        }).dropna()

        # 数据验证
        data_window = max(beta_window, zscore_window)
        if len(aligned) < data_window:
            logger.debug(f"双窗口OLS失败：对齐后数据点不足{data_window}个")
            return None

        # 数据切片：取足够计算OLS和统计量的数据
        recent_base_full = aligned['base'].iloc[-data_window:]
        recent_alt_full = aligned['alt'].iloc[-data_window:]

        # OLS回归：使用前 beta_window-1 个点（避免 look-ahead bias）
        ols_base = recent_base_full.iloc[:-1]
        ols_alt = recent_alt_full.iloc[:-1]

        # 计算对数价格
        log_base_ols = np.log(ols_base)
        log_alt_ols = np.log(ols_alt)

        # statsmodels OLS回归
        X = sm.add_constant(log_base_ols)
        model = sm.OLS(log_alt_ols, X).fit()

        alpha = model.params.iloc[0]
        beta_ols = model.params.iloc[1]
        alpha_pvalue = model.pvalues.iloc[0]
        beta_pvalue = model.pvalues.iloc[1]
        rsquared = model.rsquared

        # 智能模型选择
        model_type, use_alpha, model_reason = _select_cointegration_model(alpha, alpha_pvalue)

        # 计算价差（用于ADF检验，使用全部beta_window期）
        log_base_full = np.log(recent_base_full)
        log_alt_full = np.log(recent_alt_full)

        if use_alpha:
            spread_full = log_alt_full - (alpha + beta_ols * log_base_full)
        else:
            spread_full = log_alt_full - beta_ols * log_base_full

        # ADF检验价差平稳性
        adf_result = adfuller(spread_full.values, autolag=ADF_LAG_SELECTION_METHOD)
        adf_pvalue = adf_result[1]

        # 价差构建（用于Z-score计算：使用短窗口保持敏感度）
        recent_base = recent_base_full.iloc[-zscore_window:]
        recent_alt = recent_alt_full.iloc[-zscore_window:]
        log_base = np.log(recent_base)
        log_alt = np.log(recent_alt)

        if use_alpha:
            spread = log_alt - (alpha + beta_ols * log_base)
        else:
            spread = log_alt - beta_ols * log_base

        logger.debug(
            f"双窗口OLS | α={alpha:.4f} (p={alpha_pvalue:.4f}) | "
            f"β={beta_ols:.4f} (p={beta_pvalue:.4f}) | R²={rsquared:.4f} | "
            f"模型: {model_type} | 原因: {model_reason} | ADF p={adf_pvalue:.4f}"
        )

        return {
            'alpha': alpha,
            'beta': beta_ols,
            'spread': spread,  # 用于Z-score计算的价差序列
            'adf_pvalue': adf_pvalue,
            'alpha_pvalue': alpha_pvalue,
            'beta_pvalue': beta_pvalue,
            'rsquared': rsquared,
            'model_type': model_type,
            'use_alpha': use_alpha,
            'model_reason': model_reason
        }

    except Exception as e:
        logger.debug(f"双窗口OLS计算失败：{type(e).__name__}: {str(e)}", exc_info=True)
        return None


def calculate_zscore_ols(
    base_klines: List[Dict],
    alt_klines: List[Dict],
    window: int = None,
    beta_window: int = None,
    cointegration_result: Optional[Dict] = None
) -> Optional[float]:
    """
    基于OLS价差的Z-score计算（更科学的方法）

    公式：zscore = (current_spread - spread_mean) / spread_std

    其中 spread 来自 OLS 回归残差，而非简单价格比率。

    Args:
        base_klines: 基础币种K线数据
        alt_klines: 目标币种K线数据
        window: Z-score统计窗口大小（默认从配置读取）
        beta_window: OLS回归窗口大小（默认从配置读取）
        cointegration_result: 预计算的协整结果（可选）

    Returns:
        float: Z-score值，失败返回None
    """
    # 应用默认值
    if window is None:
        window = ZSCORE_WINDOW
    if beta_window is None:
        beta_window = BETA_WINDOW
    
    try:
        # 如果未提供协整结果，自动计算
        if cointegration_result is None:
            cointegration_result = calculate_cointegration_params_dual_window(
                base_klines, alt_klines, beta_window, window
            )
            if cointegration_result is None:
                return None

        # 从协整结果中提取价差序列
        spread = cointegration_result.get('spread')
        if spread is None or len(spread) < 2:
            logger.warning("价差序列无效，无法计算Z-score")
            return None

        # 计算统计量（使用前N-1期避免样本偏差）
        spread_mean = spread.iloc[:-1].mean()
        spread_std = spread.iloc[:-1].std()
        current_spread = spread.iloc[-1]

        # 验证统计量有效性
        if pd.isna(spread_mean) or pd.isna(spread_std):
            logger.warning("统计量包含NaN")
            return None

        if spread_std == 0 or np.isnan(spread_std):
            logger.warning("标准差为0或NaN")
            return None

        # 计算当前Z-score
        zscore = (current_spread - spread_mean) / spread_std

        if np.isnan(zscore) or np.isinf(zscore):
            logger.warning("Z-score为NaN或Inf")
            return None

        return float(zscore)

    except Exception as e:
        logger.warning(f"OLS Z-score计算失败：{type(e).__name__}: {str(e)}", exc_info=True)
        return None


# =====================================================
# 异常检测
# =====================================================

def detect_anomaly(
    zscore: float,
    threshold: float = 2.0
) -> Tuple[bool, str]:
    """
    基于Z-score的异常检测

    判断规则:
    - |zscore| > threshold: 异常信号
    - zscore > threshold: 目标币种相对高估 → 做空方向
    - zscore < -threshold: 目标币种相对低估 → 做多方向

    Args:
        zscore: Z-score值
        threshold: 异常阈值（默认2.0，即2倍标准差）

    Returns:
        (is_anomaly, direction): 是否异常，交易方向
    """
    abs_zscore = abs(zscore)

    if abs_zscore < threshold:
        return False, 'none'

    # 确定交易方向
    if zscore > threshold:
        direction = 'short'  # 做空（目标币种高估，价格回归预期下跌）
    else:
        direction = 'long'   # 做多（目标币种低估，价格回归预期上涨）

    return True, direction


# =====================================================
# 综合分析
# =====================================================

def analyze_pair_advanced(
    base_klines: List[Dict],
    alt_klines: List[Dict],
    beta_window: int = None,
    zscore_window: int = None,
    zscore_threshold: float = 2.0,
    enable_health_monitor: bool = True,
    stats_period_key: Optional[Tuple[str, str]] = None
) -> Dict:
    """
    高级配对分析（完整算法）

    流程：
    1. 数据预处理和相关性分析
    2. Old方法：全量OLS协整分析
    3. New方法：双窗口OLS协整分析
    4. 健康监控（如果启用且周期为4h/60d）
    5. Z-score计算（基于OLS价差）
    6. 异常检测
    7. 信号强度评估

    Args:
        base_klines: 基础币种K线数据
        alt_klines: 目标币种K线数据
        beta_window: OLS回归窗口大小（默认从配置读取）
        zscore_window: Z-score计算窗口大小（默认从配置读取）
        zscore_threshold: Z-score异常阈值（默认2.0）
        enable_health_monitor: 是否启用健康监控（默认True）
        stats_period_key: 统计周期键，如 ('4h', '60d')，用于判断是否启用健康监控

    Returns:
        Dict: {
            'correlation': float,
            'cointegration_old': {
                'passed': bool,
                'alpha': float,
                'beta': float,
                'adf_pvalue': float,
                'model_type': str,
                'use_alpha': bool
            },
            'cointegration_new': {
                'passed': bool,
                'alpha': float,
                'beta': float,
                'adf_pvalue': float,
                'model_type': str,
                'use_alpha': bool
            },
            'health_monitor': {
                'long_window': {...},
                'short_window': {...},
                'score_diff': float
            } or None,
            'zscore': float,
            'is_anomaly': bool,
            'trading_direction': str,
            'signal_strength': str
        }
    """
    # 应用默认值
    if beta_window is None:
        beta_window = BETA_WINDOW
    if zscore_window is None:
        zscore_window = ZSCORE_WINDOW
    
    result = {
        'correlation': 0.0,
        'cointegration_old': {
            'passed': False,
            'alpha': None,
            'beta': None,
            'adf_pvalue': 1.0,
            'model_type': None,
            'use_alpha': False
        },
        'cointegration_new': {
            'passed': False,
            'alpha': None,
            'beta': None,
            'adf_pvalue': 1.0,
            'model_type': None,
            'use_alpha': False
        },
        'health_monitor': None,
        'zscore': 0.0,
        'is_anomaly': False,
        'trading_direction': 'none',
        'signal_strength': 'none'
    }

    try:
        # 1. 相关性分析
        correlation = calculate_correlation(base_klines, alt_klines)
        result['correlation'] = correlation

        # 2. Old方法：全量OLS协整分析
        coint_old = calculate_cointegration_params_ols(base_klines, alt_klines)
        if coint_old:
            result['cointegration_old'] = {
                'passed': coint_old['adf_pvalue'] < 0.05,
                'alpha': coint_old['alpha'],
                'beta': coint_old['beta'],
                'adf_pvalue': coint_old['adf_pvalue'],
                'model_type': coint_old['model_type'],
                'use_alpha': coint_old['use_alpha'],
                'alpha_pvalue': coint_old.get('alpha_pvalue'),
                'beta_pvalue': coint_old.get('beta_pvalue'),
                'rsquared': coint_old.get('rsquared')
            }

        # 3. New方法：双窗口OLS协整分析
        coint_new = calculate_cointegration_params_dual_window(
            base_klines, alt_klines, beta_window, zscore_window
        )
        if coint_new:
            result['cointegration_new'] = {
                'passed': coint_new['adf_pvalue'] < 0.05,
                'alpha': coint_new['alpha'],
                'beta': coint_new['beta'],
                'adf_pvalue': coint_new['adf_pvalue'],
                'model_type': coint_new['model_type'],
                'use_alpha': coint_new['use_alpha'],
                'alpha_pvalue': coint_new.get('alpha_pvalue'),
                'beta_pvalue': coint_new.get('beta_pvalue'),
                'rsquared': coint_new.get('rsquared')
            }

        # 4. 健康监控（仅在配置的监控周期启用）
        if enable_health_monitor and stats_period_key:
            timeframe, window_str = stats_period_key
            if timeframe == HEALTH_MONITOR_PERIOD[0] and window_str == HEALTH_MONITOR_PERIOD[1]:
                try:
                    from utils.coingetation_more_check import CointegrationHealthMonitor

                    base_prices = prepare_price_series(base_klines)
                    alt_prices = prepare_price_series(alt_klines)

                    # 对齐数据
                    aligned = pd.DataFrame({
                        'base': base_prices,
                        'alt': alt_prices
                    }).dropna()

                    if len(aligned) >= HEALTH_MONITOR_LONG_WINDOW:
                        log_base_series = np.log(aligned['base'])
                        log_alt_series = np.log(aligned['alt'])

                        # 长期监控（配置周期）
                        monitor_long = CointegrationHealthMonitor(
                            window=HEALTH_MONITOR_LONG_WINDOW,
                            enable_diagnostics=True,
                            state_thresholds=HEALTH_MONITOR_STATE_THRESHOLDS
                        )
                        result_long = monitor_long.update(log_base_series, log_alt_series)

                        # 短期监控（配置周期）
                        monitor_short = CointegrationHealthMonitor(
                            window=HEALTH_MONITOR_SHORT_WINDOW,
                            enable_diagnostics=True,
                            state_thresholds=HEALTH_MONITOR_STATE_THRESHOLDS
                        )
                        result_short = monitor_short.update(log_base_series, log_alt_series)

                        result['health_monitor'] = {
                            'long_window': result_long,
                            'short_window': result_short,
                            'score_diff': result_long['health_score'] - result_short['health_score']
                        }

                        logger.debug(
                            f"健康监控 | 长期得分: {result_long['health_score']:.1f} | "
                            f"短期得分: {result_short['health_score']:.1f} | "
                            f"状态: {result_long['state']} / {result_short['state']}"
                        )

                except Exception as e:
                    logger.warning(f"健康监控失败：{e}")

        # 5. Z-score计算（基于OLS价差）
        if coint_new:
            zscore = calculate_zscore_ols(
                base_klines,
                alt_klines,
                window=zscore_window,
                beta_window=beta_window,
                cointegration_result=coint_new
            )
            if zscore is not None:
                result['zscore'] = zscore

        # 6. 异常检测
        is_anomaly, direction = detect_anomaly(result['zscore'], zscore_threshold)
        result['is_anomaly'] = is_anomaly
        result['trading_direction'] = direction

        # 7. 信号强度评估
        if is_anomaly:
            abs_zscore = abs(result['zscore'])
            if abs_zscore > ZSCORE_THRESHOLDS['strong']:
                result['signal_strength'] = 'strong'
            elif abs_zscore > ZSCORE_THRESHOLDS['medium']:
                result['signal_strength'] = 'medium'
            else:
                result['signal_strength'] = 'weak'

        return result

    except Exception as e:
        logger.error(f"高级配对分析失败: {e}", exc_info=True)
        return result


def analyze_multi_period(
    price_data_cache: Dict[Tuple[str, str], Dict],
    base_symbol: Optional[str] = None,
    target_symbol: Optional[str] = None,
    beta_window: int = None,
    zscore_window: int = None,
    cointegration_threshold: int = None,
    zscore_thresholds: Optional[Dict[str, float]] = None
) -> Optional[Dict]:
    """
    多周期Z-score验证算法（提取自 multi_coins.py）

    执行多周期验证，确保3个周期的协整性和Z-score符号一致性。
    这是实现统一多周期验证逻辑的核心函数。

    Args:
        price_data_cache: 多周期数据缓存
            {
                ('5m', '7d'): {'base_prices': pd.Series, 'alt_prices': pd.Series},
                ('1h', '30d'): {'base_prices': pd.Series, 'alt_prices': pd.Series},
                ('4h', '60d'): {'base_prices': pd.Series, 'alt_prices': pd.Series}
            }
        beta_window: OLS回归窗口（默认从配置读取）
        zscore_window: Z-score计算窗口（默认从配置读取）
        cointegration_threshold: 协整通过门槛（默认从配置读取）
        zscore_thresholds: Z-score阈值字典（默认从配置读取）
            {
                'long': 0.2,    # 4h 长周期
                'middle': 1.5,  # 1h 中周期
                'short': 1.8    # 5m 短周期
            }

    Returns:
        Dict: {
            'passed': bool,  # 是否通过多周期验证
            'zscore_list': [zscore_5m, zscore_1h, zscore_4h],
            'cointegration_count': int,  # 协整通过数量（Old+New，共6个结果）
            'direction': str,  # 'long' | 'short' | 'none'
            'details': {
                ('5m', '7d'): {
                    'correlation': float,
                    'cointegration_old': {...},
                    'cointegration_new': {...},
                    'zscore': float,
                    'is_anomaly': bool
                },
                ...
            }
        }
        或 None（验证失败）

    验证逻辑：
    1. 遍历3个周期，分别执行：
       - Old方法：全量OLS协整分析
       - New方法：双窗口OLS协整分析
       - Z-score计算（基于OLS价差）
    2. 统计协整通过数量（Old + New，共6个结果）
    3. 验证：协整通过数 >= cointegration_threshold（默认从配置读取）
    4. 验证：3个周期Z-score符号一致
    5. 验证：3个周期Z-score都超过各自阈值
    """
    # 应用默认值
    if beta_window is None:
        beta_window = BETA_WINDOW
    if zscore_window is None:
        zscore_window = ZSCORE_WINDOW
    if cointegration_threshold is None:
        cointegration_threshold = COINTEGRATION_THRESHOLD
    if zscore_thresholds is None:
        zscore_thresholds = ZSCORE_THRESHOLDS

    # 构建日志前缀（target_symbol vs base_symbol）
    log_prefix = ""
    if target_symbol and base_symbol:
        log_prefix = f"[{target_symbol} vs {base_symbol}] "

    # 辅助函数：提取健康状态摘要
    def get_health_status_summary(details_dict: Dict) -> str:
        """从分析详情中提取健康状态摘要"""
        try:
            details_4h_60d = details_dict.get(('4h', '60d'), {})
            health_monitor = details_4h_60d.get('health_monitor')
            
            if health_monitor is None:
                return "健康: N/A"
            
            long_score = health_monitor.get('long_window', {}).get('health_score', 0)
            short_score = health_monitor.get('short_window', {}).get('health_score', 0)
            
            return f"健康: 长期{long_score:.1f}/短期{short_score:.1f}"
        except Exception:
            return "健康: N/A"

    # 验证输入数据
    required_periods = REQUIRED_PERIODS
    for period_key in required_periods:
        if period_key not in price_data_cache:
            logger.warning(f"{log_prefix}缺少必需周期数据: {period_key}")
            return None

    # 存储结果
    zscore_list = []  # [zscore_5m, zscore_1h, zscore_4h]
    cointegration_count = 0  # 协整通过的总数量（Old+New）
    details = {}

    # 遍历3个周期进行分析
    for period_key in required_periods:
        price_data = price_data_cache[period_key]
        base_prices = price_data['base_prices']
        alt_prices = price_data['alt_prices']

        # 转换为K线格式（用于兼容现有函数）
        base_klines = [{'time': t, 'close': p} for t, p in base_prices.items()]
        alt_klines = [{'time': t, 'close': p} for t, p in alt_prices.items()]

        # 数据验证
        if len(base_klines) < MIN_DATA_POINTS or len(alt_klines) < MIN_DATA_POINTS:
            logger.warning(f"{log_prefix}周期 {period_key} 数据点不足{MIN_DATA_POINTS}个")
            return None

        # 执行高级分析（包含Old和New方法）
        analysis_result = analyze_pair_advanced(
            base_klines=base_klines,
            alt_klines=alt_klines,
            beta_window=beta_window,
            zscore_window=zscore_window,
            zscore_threshold=2.0,  # 内部阈值，外部再验证
            enable_health_monitor=True,
            stats_period_key=period_key
        )

        # 保存详细结果
        details[period_key] = analysis_result

        # 统计协整通过数量（Old + New）
        coint_old = analysis_result.get('cointegration_old', {})
        coint_new = analysis_result.get('cointegration_new', {})

        if coint_old.get('passed', False):
            cointegration_count += 1
        if coint_new.get('passed', False):
            cointegration_count += 1

        # 提取Z-score
        zscore = analysis_result.get('zscore')
        if zscore is None:
            logger.warning(f"{log_prefix}周期 {period_key} Z-score计算失败")
            return None

        zscore_list.append(zscore)

        logger.debug(
            f"周期 {period_key} 分析完成 | "
            f"Old协整: {coint_old.get('passed')} (p={coint_old.get('adf_pvalue'):.4f}) | "
            f"New协整: {coint_new.get('passed')} (p={coint_new.get('adf_pvalue'):.4f}) | "
            f"Z-score: {zscore:.2f}"
        )

    # 验证1: 协整通过数量检查
    if cointegration_count < cointegration_threshold:
        logger.info(
            f"❌ {log_prefix}多周期验证失败 | 原因: 协整不足 | "
            f"协整: {cointegration_count}/6 (需要≥{cointegration_threshold}) | "
            f"Z-score: 5m={zscore_list[0]:.2f}, 1h={zscore_list[1]:.2f}, 4h={zscore_list[2]:.2f} | "
            f"{get_health_status_summary(details)}"
        )
        return {
            'passed': False,
            'zscore_list': zscore_list,
            'cointegration_count': cointegration_count,
            'direction': 'none',
            'details': details,
            'fail_reason': f'cointegration_count ({cointegration_count}) < threshold ({cointegration_threshold})'
        }

    # 提取3个周期的Z-score
    zscore_5m, zscore_1h, zscore_4h = zscore_list

    # 验证2: Z-score符号一致性检查
    if not ((zscore_5m >= 0) == (zscore_1h >= 0) == (zscore_4h >= 0)):
        # 添加符号标注
        sign_5m = "正" if zscore_5m >= 0 else "负"
        sign_1h = "正" if zscore_1h >= 0 else "负"
        sign_4h = "正" if zscore_4h >= 0 else "负"
        
        logger.info(
            f"❌ {log_prefix}多周期验证失败 | 原因: Z-score符号不一致 | "
            f"协整: {cointegration_count}/6 | "
            f"Z-score: 5m={zscore_5m:.2f}({sign_5m}), 1h={zscore_1h:.2f}({sign_1h}), 4h={zscore_4h:.2f}({sign_4h}) | "
            f"{get_health_status_summary(details)}"
        )
        return {
            'passed': False,
            'zscore_list': zscore_list,
            'cointegration_count': cointegration_count,
            'direction': 'none',
            'details': details,
            'fail_reason': 'zscore sign inconsistency'
        }

    # 验证3: Z-score阈值检查
    long_threshold = zscore_thresholds['long']
    middle_threshold = zscore_thresholds['middle']
    short_threshold = zscore_thresholds['short']

    if not (abs(zscore_4h) > long_threshold and
            abs(zscore_1h) > middle_threshold and
            abs(zscore_5m) > short_threshold):
        # 计算达标情况
        if abs(zscore_5m) > short_threshold:
            status_5m = "✓"
        else:
            gap_5m = short_threshold - abs(zscore_5m)
            status_5m = f"缺{gap_5m:.2f}"
        
        if abs(zscore_1h) > middle_threshold:
            status_1h = "✓"
        else:
            gap_1h = middle_threshold - abs(zscore_1h)
            status_1h = f"缺{gap_1h:.2f}"
        
        if abs(zscore_4h) > long_threshold:
            status_4h = "✓"
        else:
            gap_4h = long_threshold - abs(zscore_4h)
            status_4h = f"缺{gap_4h:.2f}"
        
        logger.info(
            f"❌ {log_prefix}多周期验证失败 | 原因: Z-score阈值不足 | "
            f"协整: {cointegration_count}/6 | "
            f"Z-score: 5m={abs(zscore_5m):.2f}({status_5m}), 1h={abs(zscore_1h):.2f}({status_1h}), 4h={abs(zscore_4h):.2f}({status_4h}) | "
            f"阈值: 5m>{short_threshold}, 1h>{middle_threshold}, 4h>{long_threshold} | "
            f"{get_health_status_summary(details)}"
        )
        return {
            'passed': False,
            'zscore_list': zscore_list,
            'cointegration_count': cointegration_count,
            'direction': 'none',
            'details': details,
            'fail_reason': 'zscore threshold not met'
        }

    # 所有验证通过，确定交易方向
    direction = 'long' if zscore_4h < 0 else 'short'  # 基于长周期Z-score

    logger.info(
        f"✅ {log_prefix}多周期验证通过 | 协整通过数: {cointegration_count}/6 | "
        f"Z-score: [{zscore_5m:.2f}, {zscore_1h:.2f}, {zscore_4h:.2f}] | "
        f"方向: {direction}"
    )

    return {
        'passed': True,
        'zscore_list': zscore_list,
        'cointegration_count': cointegration_count,
        'direction': direction,
        'details': details
    }


# =====================================================
# 导出接口
# =====================================================

__all__ = [
    # 数据预处理
    'prepare_price_series',

    # 相关性分析
    'calculate_correlation',

    # 协整检验
    'calculate_cointegration_params_ols',
    'calculate_cointegration_params_dual_window',

    # Z-score计算
    'calculate_zscore_ols',

    # 异常检测
    'detect_anomaly',

    # 综合分析
    'analyze_pair_advanced',
    'analyze_multi_period'
]
