import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
import nolds

from utils.config import (
    HEALTH_MONITOR_LONG_WINDOW,
    HEALTH_MONITOR_MAX_HALFLIFE,
    HEALTH_MONITOR_MIN_HALFLIFE,
    HEALTH_MONITOR_SCORE_WEIGHTS,
    HEALTH_MONITOR_STATE_THRESHOLDS
)


class CointegrationHealthMonitor:
    """
    协整健康监控器 - 观察期优化版本
    - 4H 级别结构监控
    - 输出健康得分 (0-34) + 状态 + 诊断信息
    - 修复：使用滚动窗口替代失效的历史累积机制
    - 新增：模型诊断和异常原因追踪
    """

    # ===== 状态枚举 =====
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    DANGER = "DANGER"
    DEAD = "DEAD"

    def __init__(
        self,
        window=HEALTH_MONITOR_LONG_WINDOW,
        max_halflife=HEALTH_MONITOR_MAX_HALFLIFE,
        min_halflife=HEALTH_MONITOR_MIN_HALFLIFE,
        state_thresholds=HEALTH_MONITOR_STATE_THRESHOLDS,
        enable_diagnostics=True,
    ):
        """
        初始化健康监控器

        Args:
            window: 滚动窗口大小（建议100或200）
            max_halflife: 最大半衰期阈值（期数）
            min_halflife: 最小半衰期阈值（期数）
            state_thresholds: 状态阈值 (HEALTHY, WARNING, DANGER)
            enable_diagnostics: 是否启用诊断信息
        """
        self.window = window
        self.max_halflife = max_halflife
        self.min_halflife = min_halflife
        self.state_thresholds = state_thresholds
        self.enable_diagnostics = enable_diagnostics

    # ==========================================================
    # 主入口
    # ==========================================================
    def update(self, log_base: pd.Series, log_alt: pd.Series):
        """
        更新健康监控数据

        Args:
            log_base: 基准币种对数价格序列（BASE）
            log_alt: 目标币种对数价格序列（ALT）

        Returns:
            dict: {
                'health_score': 综合得分(0-34),
                'state': 健康状态,
                'adf_pvalue': ADF检验p值,
                'halflife': 半衰期,
                'halflife_reason': 半衰期计算原因,
                'beta': 协整系数,
                'phi': 一阶自相关系数,  # 新增
                'hurst': Hurst指数,     # 新增
                'scores': {各分项得分},
                'diagnostics': {诊断信息} (可选)
            }
        """
        if len(log_base) < self.window or len(log_alt) < self.window:
            raise ValueError(f"数据不足：需要 {self.window} 期，实际 {len(log_base)} 期")

        # 统一回归方向：ALT ~ BASE（与 new/old 方法一致）
        log_base = log_base[-self.window:]
        log_alt = log_alt[-self.window:]

        # 计算基础参数
        beta, spread, beta_model = self._estimate_beta_and_spread(log_base, log_alt)

        # 计算各项得分
        adf_score, adf_pvalue = self._adf_strength_score(spread)
        halflife_score, halflife, halflife_reason, ar1_model = self._halflife_score(spread)
        stability_score, stability_details = self._stability_score(spread, log_base, log_alt)
        
        # 新增：计算 Hurst 指数
        hurst, hurst_reason = self._calculate_hurst_external(spread)
        
        # 新增：提取 phi 值（一阶自相关系数）
        phi = None
        if ar1_model is not None:
            try:
                phi = ar1_model.params.iloc[1]
            except (IndexError, AttributeError):
                pass

        # 综合得分（使用配置的权重）
        weights = HEALTH_MONITOR_SCORE_WEIGHTS
        health_score = (
            weights[0] * adf_score
            + weights[1] * halflife_score
            + weights[2] * stability_score
        )

        state = self._state_from_score(health_score)

        result = {
            "health_score": round(health_score, 2),
            "state": state,
            "adf_pvalue": round(adf_pvalue, 4),
            "halflife": round(halflife, 2) if not np.isinf(halflife) else "inf",
            "halflife_reason": halflife_reason,
            "beta": round(beta, 4),
            "phi": round(phi, 4) if phi is not None else None,  # 新增
            "hurst": round(hurst, 4) if not np.isnan(hurst) else None,  # 新增
            "scores": {
                "adf": round(adf_score, 2),
                "halflife": round(halflife_score, 2),
                "stability": round(stability_score, 2),
            },
            "stability_details": stability_details,
        }

        # 添加诊断信息
        if self.enable_diagnostics:
            result["diagnostics"] = self._get_diagnostics(
                spread, beta_model, ar1_model, stability_details
            )
            # 在诊断信息中添加 Hurst 相关细节
            if not np.isnan(hurst):
                result["diagnostics"]["hurst_reason"] = hurst_reason

        return result

    # ==========================================================
    # 内部组件
    # ==========================================================
    def _estimate_beta_and_spread(self, log_base, log_alt):
        """估算协整系数和价差（log_base=BASE, log_alt=ALT）"""
        X = sm.add_constant(log_base)
        model = sm.OLS(log_alt, X).fit()
        beta = model.params.iloc[1]
        spread = log_alt - beta * log_base
        return beta, spread, model

    # ---------------- ADF 强度评分 ----------------
    def _adf_strength_score(self, spread):
        """
        ADF 平稳性检验评分 (0-40分)

        评分规则：
        - p > 0.1: 0分（不平稳）
        - p < 0.01: 40分（强平稳）
        - 0.01 <= p <= 0.1: 线性插值
        """
        try:
            adf_stat, pvalue, *_ = adfuller(spread, autolag="AIC")
        except Exception as e:
            return 0, 1.0  # ADF失败，返回最差得分

        if pvalue > 0.1:
            score = 0
        elif pvalue < 0.01:
            score = 40
        else:
            # 线性插值
            score = 40 * (0.1 - pvalue) / (0.1 - 0.01)

        return score, pvalue

    # ---------------- 半衰期评分 ----------------
    def _halflife_score(self, spread):
        """
        半衰期评分 (0-30分) - 增强稳健性检验

        评分规则：
        - halflife <= min_halflife: 30分（快速均值回归）
        - halflife >= max_halflife: 0分（均值回归太慢）
        - 中间值：线性插值

        Returns:
            (score, halflife, reason, model)
        """
        try:
            spread_lag = spread.shift(1).iloc[1:]
            delta = spread.diff().iloc[1:]

            model = sm.OLS(delta, sm.add_constant(spread_lag)).fit()
            phi = model.params.iloc[1]
            phi_pvalue = model.pvalues.iloc[1]
            rsquared = model.rsquared

            # 稳健性检验1：phi 不显著
            if phi_pvalue > 0.05:
                return 0, np.inf, "PHI_NOT_SIGNIFICANT", model

            # 稳健性检验2：AR(1) 拟合优度太低
            # 阈值从0.2降低到0.05（2026-01-14优化）
            if rsquared < 0.05:
                return 0, np.inf, "AR1_POOR_FIT", model

            # 稳健性检验3：phi 边界条件
            if phi >= 0:
                return 0, np.inf, "NO_MEAN_REVERSION", model
            elif phi <= -1:  # 修正：从-2改为-1
                return 0, np.inf, "OVER_CORRECTION", model

            # 计算半衰期
            try:
                halflife = np.log(2) / np.log(1 / (1 + phi))
            except (ZeroDivisionError, ValueError):
                return 0, np.inf, "CALCULATION_ERROR", model

            # 处理异常值
            if np.isnan(halflife) or np.isinf(halflife):
                return 0, np.inf, "HALFLIFE_INVALID", model

            # 评分
            if halflife <= self.min_halflife:
                score = 30
                reason = "VERY_FAST"
            elif halflife >= self.max_halflife:
                score = 0
                reason = "TOO_SLOW"
            else:
                score = 30 * (
                    (self.max_halflife - halflife)
                    / (self.max_halflife - self.min_halflife)
                )
                reason = "NORMAL"

            return score, halflife, reason, model

        except Exception as e:
            return 0, np.inf, f"EXCEPTION_{type(e).__name__}", None

    # ---------------- 去趋势处理 ----------------
    def _detrend_series(self, series: pd.Series) -> np.ndarray:
        """
        去除序列的线性趋势

        Args:
            series: 输入序列

        Returns:
            去趋势后的数组
        """
        values = series.dropna().values
        n = len(values)

        # 使用线性回归去趋势
        X = np.arange(n).reshape(-1, 1)
        y = values.reshape(-1, 1)

        # 简单线性回归（使用 numpy，避免依赖 sklearn）
        # y = a + b*x
        x_mean = X.mean()
        y_mean = y.mean()

        # 计算斜率 b
        numerator = np.sum((X.flatten() - x_mean) * (y.flatten() - y_mean))
        denominator = np.sum((X.flatten() - x_mean) ** 2)
        b = numerator / denominator if denominator != 0 else 0

        # 计算截距 a
        a = y_mean - b * x_mean

        # 计算趋势线
        trend = a + b * X.flatten()

        # 去趋势
        detrended = values - trend

        return detrended

    # ---------------- Hurst 指数计算 ----------------
    def _detrend_values(self, values: np.ndarray) -> np.ndarray:
        """
        去除数组的线性趋势（直接处理 numpy array）

        Args:
            values: 输入数组

        Returns:
            去趋势后的数组
        """
        n = len(values)
        X = np.arange(n)
        x_mean = X.mean()
        y_mean = values.mean()

        numerator = np.sum((X - x_mean) * (values - y_mean))
        denominator = np.sum((X - x_mean) ** 2)
        b = numerator / denominator if denominator != 0 else 0
        a = y_mean - b * x_mean

        trend = a + b * X
        return values - trend

    def _calculate_hurst_external(self, spread: pd.Series, detrend: bool = True) -> tuple[float, str]:
        """
        使用 nolds 库计算 Hurst 指数（R/S 分析）

        Args:
            spread: 价差序列（协整残差，应为平稳的 I(0) 序列）
            detrend: 是否去趋势（默认 True）

        Returns:
            (hurst_value, reason)
            - hurst_value: Hurst 指数，理论范围 [0, 1]
              H < 0.5: 均值回归（anti-persistent）
              H = 0.5: 随机游走
              H > 0.5: 趋势延续（persistent）
            - reason: 计算状态说明

        Note:
            直接在价差序列上计算 Hurst（不做差分），因为协整残差本身应为平稳序列。
            对平稳序列取差分属于过度差分，会改变 Hurst 指数的物理含义。
        """
        try:
            # 直接使用价差序列（不做差分）
            values = spread.dropna().values
            n = len(values)

            # 数据量检查（R/S 分析需要足够数据点，建议至少 100 个）
            if n < 100:
                return np.nan, "INSUFFICIENT_DATA"

            # 先去趋势（在原始序列上），避免趋势被误判为持续性
            if detrend:
                values = self._detrend_values(values)

            # 标准差检查 - 在去趋势后进行
            if np.std(values) < 1e-10:
                return np.nan, "CONSTANT_SERIES"

            # 使用 nolds 库计算 Hurst 指数
            # nvals: 分段数量，默认 None 让 nolds 自动选择
            # fit: 使用 RANSAC 拟合更稳健（对异常值不敏感）
            hurst = nolds.hurst_rs(
                values,
                nvals=None,      # 自动选择分段数量
                fit='RANSAC',    # 使用 RANSAC 拟合（更稳健）
                debug_plot=False,
                plot_file=None
            )

            # 边界检查
            if np.isnan(hurst) or np.isinf(hurst):
                return np.nan, "CALCULATION_ERROR"

            # Hurst 指数理论范围 [0, 1]，超出范围则截断并标记
            if hurst < 0 or hurst > 1:
                return float(np.clip(hurst, 0, 1)), "HURST_CLIPPED"

            return float(hurst), "SUCCESS"

        except Exception as e:
            return np.nan, f"EXCEPTION_{type(e).__name__}"

    # ---------------- 稳定性评分（修复版）----------------
    def _stability_score(self, spread, log_base, log_alt):
        """
        稳定性评分 (0-30分) - 使用滚动窗口替代历史累积

        评分维度：
        1. β稳定性 (0-10分)：滚动窗口中β的变异系数
        2. 均值漂移 (0-10分)：前后期均值变化
        3. ADF持续性 (0-10分)：多个子窗口的ADF通过率
        """
        score = 0
        details = {}

        # --- β 稳定性 (0-10分) 滚动窗口计算 ---
        beta_stability_score, beta_cv = self._calc_beta_stability(log_base, log_alt)
        score += beta_stability_score
        details["beta_cv"] = round(beta_cv, 4) if not np.isnan(beta_cv) else None
        details["beta_stability_score"] = round(beta_stability_score, 2)

        # --- 均值漂移 (0-10分) ---
        mean_shift_score, mean_shift_ratio = self._calc_mean_shift(spread)
        score += mean_shift_score
        details["mean_shift_ratio"] = round(mean_shift_ratio, 4)
        details["mean_shift_score"] = round(mean_shift_score, 2)

        # --- ADF 持续性 (0-10分) 滚动窗口计算 ---
        adf_consistency_score, adf_pass_rate = self._calc_adf_consistency(spread)
        score += adf_consistency_score
        details["adf_pass_rate"] = round(adf_pass_rate, 4)
        details["adf_consistency_score"] = round(adf_consistency_score, 2)

        return score, details

    def _calc_beta_stability(self, log_base, log_alt):
        """
        计算β稳定性（滚动窗口）

        方法：将窗口分为5段，每段独立计算β，然后计算变异系数
        """
        try:
            window_size = len(log_base)
            segment_size = window_size // 5

            if segment_size < 20:  # 每段至少20期数据
                return 0, np.nan

            betas = []
            for i in range(5):
                start = i * segment_size
                end = start + segment_size if i < 4 else window_size

                seg_log_base = log_base.iloc[start:end]
                seg_log_alt = log_alt.iloc[start:end]

                if len(seg_log_base) < 20:
                    continue

                X = sm.add_constant(seg_log_base)
                model = sm.OLS(seg_log_alt, X).fit()
                betas.append(model.params.iloc[1])

            if len(betas) < 4:
                return 0, np.nan

            beta_mean = np.abs(np.mean(betas))
            if beta_mean < 1e-10:
                return 0, np.nan

            beta_cv = np.std(betas) / beta_mean

            # 评分
            if beta_cv < 0.05:
                score = 10
            elif beta_cv < 0.15:
                score = 5
            else:
                score = 0

            return score, beta_cv

        except Exception:
            return 0, np.nan

    def _calc_mean_shift(self, spread):
        """
        计算均值漂移

        方法：比较前20%和后20%数据的均值差异
        """
        try:
            window_size = len(spread)
            segment_size = max(20, window_size // 5)

            old_mean = spread[:segment_size].mean()
            recent_mean = spread[-segment_size:].mean()
            spread_std = spread.std()

            if spread_std < 1e-10:
                return 0, np.nan

            mean_shift_ratio = abs(recent_mean - old_mean) / spread_std

            # 评分
            if mean_shift_ratio < 0.5:
                score = 10
            elif mean_shift_ratio < 1.5:
                score = 5
            else:
                score = 0

            return score, mean_shift_ratio

        except Exception:
            return 0, np.nan

    def _calc_adf_consistency(self, spread):
        """
        计算 ADF 持续性（滚动窗口）

        方法：在窗口内取5个子窗口，分别做ADF检验，计算通过率
        """
        try:
            window_size = len(spread)
            sub_window_sizes = [
                window_size,
                int(window_size * 0.8),
                int(window_size * 0.6),
                int(window_size * 0.4),
                int(window_size * 0.2),
            ]

            adf_results = []
            for size in sub_window_sizes:
                if size < 30:  # 子窗口至少30期
                    continue

                sub_spread = spread[-size:]
                try:
                    _, pvalue, *_ = adfuller(sub_spread, autolag="AIC")
                    adf_results.append(int(pvalue < 0.05))
                except Exception as e:
                    # 修复QUAL-02: 只捕获Exception，避免拦截系统信号
                    continue

            if len(adf_results) == 0:
                return 0, 0

            pass_rate = sum(adf_results) / len(adf_results)
            score = 10 * pass_rate

            return score, pass_rate

        except Exception:
            return 0, 0

    # ---------------- 状态判断 ----------------
    def _state_from_score(self, score):
        """根据得分判断健康状态"""
        high, mid, low = self.state_thresholds

        if score >= high:
            return self.HEALTHY
        elif score >= mid:
            return self.WARNING
        elif score >= low:
            return self.DANGER
        else:
            return self.DEAD

    # ---------------- 诊断信息 ----------------
    def _get_diagnostics(self, spread, beta_model, ar1_model, stability_details):
        """
        生成诊断信息

        Returns:
            dict: 包含模型质量、数据质量和异常警告
        """
        diagnostics = {
            "model_quality": {},
            "data_quality": {},
            "warnings": [],
        }

        # 模型质量
        if beta_model is not None:
            diagnostics["model_quality"]["beta_rsquared"] = round(beta_model.rsquared, 3)
            diagnostics["model_quality"]["beta_model_valid"] = beta_model.rsquared > 0.3

        if ar1_model is not None:
            diagnostics["model_quality"]["ar1_rsquared"] = round(ar1_model.rsquared, 3)
            diagnostics["model_quality"]["ar1_model_valid"] = ar1_model.rsquared > 0.05
            diagnostics["model_quality"]["phi"] = round(ar1_model.params.iloc[1], 4)
            diagnostics["model_quality"]["phi_pvalue"] = round(ar1_model.pvalues.iloc[1], 4)

        # 数据质量
        diagnostics["data_quality"]["spread_std"] = round(spread.std(), 4)
        diagnostics["data_quality"]["spread_mean"] = round(spread.mean(), 4)
        diagnostics["data_quality"]["spread_skewness"] = round(spread.skew(), 3)
        diagnostics["data_quality"]["spread_kurtosis"] = round(spread.kurtosis(), 3)

        # 稳定性细节
        diagnostics["stability_breakdown"] = stability_details

        # 异常警告
        warnings = self._check_warnings(spread, beta_model, ar1_model, stability_details)
        diagnostics["warnings"] = warnings

        return diagnostics

    def _check_warnings(self, spread, beta_model, ar1_model, stability_details):
        """检查异常情况"""
        warnings = []

        # AR(1) 模型质量
        if ar1_model is not None and ar1_model.rsquared < 0.3:
            warnings.append("AR1_LOW_FIT")

        # Beta 模型质量
        if beta_model is not None and beta_model.rsquared < 0.5:
            warnings.append("BETA_LOW_FIT")

        # 数据分布异常
        if abs(spread.skew()) > 2:
            warnings.append("HIGH_SKEWNESS")

        if spread.kurtosis() > 7:
            warnings.append("FAT_TAILS")

        # 波动率突变
        mid = len(spread) // 2
        if mid > 20:
            first_half_std = spread[:mid].std()
            second_half_std = spread[mid:].std()
            if max(first_half_std, second_half_std) / min(first_half_std, second_half_std) > 2:
                warnings.append("VOLATILITY_REGIME_CHANGE")

        # 稳定性问题
        if stability_details.get("beta_cv") is not None:
            if stability_details["beta_cv"] > 0.2:
                warnings.append("BETA_UNSTABLE")

        if stability_details.get("mean_shift_ratio") is not None:
            if stability_details["mean_shift_ratio"] > 1.5:
                warnings.append("MEAN_SHIFT_LARGE")

        if stability_details.get("adf_pass_rate") is not None:
            if stability_details["adf_pass_rate"] < 0.5:
                warnings.append("ADF_INCONSISTENT")

        return warnings
