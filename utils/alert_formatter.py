"""
告警格式化模块 - 多周期配对交易信号告警

将多周期验证结果格式化为丰富的飞书告警内容，包含：
1. 信号概览
2. 多周期Z-score验证（带可视化进度条）
3. 多周期相关性分析表格
4. 协整检验统计表格
5. 协整健康监控（长/短期窗口对比）
6. 风险评估（红/黄/绿三级）
7. 交易建议
"""

from datetime import datetime, timezone
from typing import Dict, Optional, List, Tuple
from utils.logging_config import logger
from utils.config import (
    ZSCORE_THRESHOLDS,
    HEALTH_MONITOR_LONG_WINDOW,
    HEALTH_MONITOR_SHORT_WINDOW,
    HEALTH_MONITOR_STATE_THRESHOLDS,
    ALERT_SIGNAL_STRENGTH,
    ALERT_QUALITY,
    ALERT_CORR,
    ALERT_HURST,
    ALERT_SCORE_DIFF,
    ALERT_RISK_HIGH_HURST,
    ALERT_RISK_MID,
    ALERT_RATING_COUNT_THRESHOLD,
    ALERT_PROGRESS_BAR_WIDTH,
    ALERT_ZSCORE_MAX_VALUE,
)


class AlertFormatter:
    """多周期配对交易信号告警格式化器"""

    # 周期到Z-score阈值类型的映射（复用config.py中的ZSCORE_THRESHOLDS）
    TIMEFRAME_TO_THRESHOLD_TYPE = {
        '5m': 'short',   # 短周期 (默认 1.8)
        '1h': 'middle',  # 中周期 (默认 1.5)
        '4h': 'long'     # 长周期 (默认 0.2)
    }

    def format_rich_alert(
        self,
        symbol: str,
        base_symbol: str,
        timeframe: str,
        multi_period_result: Dict,
        timestamp: Optional[datetime] = None
    ) -> str:
        """
        生成丰富格式的告警内容

        Args:
            symbol: 目标币种
            base_symbol: 基准币种
            timeframe: 触发周期
            multi_period_result: 多周期验证结果
            timestamp: 告警时间（默认当前系统本地时间）

        Returns:
            str: 格式化的Markdown告警内容
        """
        if timestamp is None:
            timestamp = datetime.now()  # 使用本地时间，更友好

        # 提取数据
        zscore_list = multi_period_result.get('zscore_list', [0, 0, 0])
        zscore_5m, zscore_1h, zscore_4h = zscore_list
        direction = multi_period_result.get('direction', 'none')
        cointegration_count = multi_period_result.get('cointegration_count', 0)
        details = multi_period_result.get('details', {})

        # 构建各部分内容
        sections = [
            self._format_header(symbol, base_symbol, timestamp),
            self._format_signal_overview(timeframe, zscore_4h, direction, cointegration_count),
            self._format_zscore_verification(zscore_5m, zscore_1h, zscore_4h),
            self._format_correlation_table(details),
            self._format_cointegration_stats(details, cointegration_count),
            self._format_health_monitor(details),
            self._format_risk_assessment(multi_period_result, details),
            self._format_trading_suggestion(multi_period_result, details),
        ]

        return '\n'.join(filter(None, sections))

    def _format_header(self, symbol: str, base_symbol: str, timestamp: datetime) -> str:
        """格式化头部信息"""
        time_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        return f"""**币种**: {symbol}
        **基准**: {base_symbol}
        **时间**: {time_str}

        ---"""

    def _format_signal_overview(
        self,
        timeframe: str,
        zscore_4h: float,
        direction: str,
        cointegration_count: int
    ) -> str:
        """格式化信号概览"""
        # 计算信号强度
        abs_zscore = abs(zscore_4h)
        if abs_zscore > ALERT_SIGNAL_STRENGTH['extreme']:
            strength = "极强"
            strength_emoji = "🔥🔥🔥"
        elif abs_zscore > ALERT_SIGNAL_STRENGTH['strong']:
            strength = "强"
            strength_emoji = "🔥🔥"
        elif abs_zscore > ALERT_SIGNAL_STRENGTH['medium']:
            strength = "中等"
            strength_emoji = "🔥"
        else:
            strength = "弱"
            strength_emoji = "💨"

        # 信号质量评估
        if cointegration_count >= ALERT_QUALITY['excellent']:
            quality_emoji = "⭐⭐⭐"
            quality_text = "优秀"
        elif cointegration_count >= ALERT_QUALITY['good']:
            quality_emoji = "⭐⭐"
            quality_text = "良好"
        elif cointegration_count >= ALERT_QUALITY['fair']:
            quality_emoji = "⭐"
            quality_text = "一般"
        else:
            quality_emoji = "⚠️"
            quality_text = "较差"

        direction_text = "做多 (Long)" if direction == 'long' else "做空 (Short)"
        direction_emoji = "📈" if direction == 'long' else "📉"

        return f"""**【信号概览】**
        ├─ 触发周期: {timeframe}
        ├─ Z-score: {zscore_4h:+.2f} (偏离{abs_zscore:.1f}倍标准差)
        ├─ 信号强度: {strength_emoji} {strength}
        ├─ 交易方向: {direction_emoji} {direction_text}
        └─ 信号质量: {quality_emoji} {quality_text}

        ---"""

    def _format_zscore_verification(
        self,
        zscore_5m: float,
        zscore_1h: float,
        zscore_4h: float
    ) -> str:
        """格式化多周期Z-score验证"""
        def format_zscore_line(label: str, timeframe: str, zscore: float, threshold: float) -> str:
            status = "✅" if abs(zscore) > threshold else "❌"
            progress = self._make_progress_bar(abs(zscore), max_val=ALERT_ZSCORE_MAX_VALUE, width=ALERT_PROGRESS_BAR_WIDTH)
            return f"├─ {label} ({timeframe}): {zscore:+.2f}  {status}  {progress}"

        # 验证状态
        all_same_sign = (zscore_5m >= 0) == (zscore_1h >= 0) == (zscore_4h >= 0)
        sign_text = "全正" if zscore_4h > 0 else "全负"
        sign_status = f"✅ {sign_text}" if all_same_sign else "❌ 不一致"

        # 趋势特征分析
        trend_feature = self._analyze_trend_feature(zscore_5m, zscore_1h, zscore_4h)

        # 从配置获取阈值（通过周期映射）
        threshold_5m = ZSCORE_THRESHOLDS[self.TIMEFRAME_TO_THRESHOLD_TYPE['5m']]
        threshold_1h = ZSCORE_THRESHOLDS[self.TIMEFRAME_TO_THRESHOLD_TYPE['1h']]
        threshold_4h = ZSCORE_THRESHOLDS[self.TIMEFRAME_TO_THRESHOLD_TYPE['4h']]

        lines = [
            "**【多周期Z-score验证】**",
            format_zscore_line("🕐 短周期", "5m", zscore_5m, threshold_5m),
            format_zscore_line("🕑 中周期", "1h", zscore_1h, threshold_1h),
            format_zscore_line("🕓 长周期", "4h", zscore_4h, threshold_4h),
            f"├─ 符号一致性: {sign_status}",
            f"└─ 趋势特征: {trend_feature}",
            "",
            "---"
        ]
        return '\n'.join(lines)

    def _make_progress_bar(self, value: float, max_val: float = ALERT_ZSCORE_MAX_VALUE, width: int = ALERT_PROGRESS_BAR_WIDTH) -> str:
        """生成ASCII进度条"""
        ratio = min(abs(value) / max_val, 1.0)
        filled = int(ratio * width)
        empty = width - filled
        return f"[{'█' * filled}{'░' * empty}]"

    def _analyze_trend_feature(self, zscore_5m: float, zscore_1h: float, zscore_4h: float) -> str:
        """分析趋势特征"""
        abs_5m = abs(zscore_5m)
        abs_1h = abs(zscore_1h)
        abs_4h = abs(zscore_4h)

        # 判断趋势方向
        if abs_5m > abs_1h > abs_4h:
            return "📈 短强长弱 (短期动能强劲)"
        elif abs_4h > abs_1h > abs_5m:
            return "📉 长强短弱 (趋势延续性好)"
        elif abs_1h > abs_5m and abs_1h > abs_4h:
            return "🔄 中周期主导"
        else:
            return "⚖️ 多周期均衡"

    def _format_correlation_table(self, details: Dict) -> str:
        """格式化多周期相关性分析表格"""
        periods = [
            (('4h', '60d'), '🕓 4h', '60d'),
            (('1h', '30d'), '🕑 1h', '30d'),
            (('5m', '7d'), '🕐 5m', '7d'),
        ]

        lines = [
            "**【多周期相关性分析】**",
            "| 周期 | 相关系数 | 数据窗口 |",
            "|------|----------|----------|",
        ]

        for period_key, label, window in periods:
            detail = details.get(period_key, {})
            corr = detail.get('correlation')
            corr_str = f"{corr:.4f}" if corr is not None else "N/A"

            # 相关系数评级
            if corr is not None:
                if corr > ALERT_CORR['excellent']:
                    corr_str += " 🟢"
                elif corr > ALERT_CORR['good']:
                    corr_str += " 🟡"
                else:
                    corr_str += " 🔴"

            lines.append(f"| {label} | {corr_str} | {window} |")

        lines.extend(["", "---"])
        return '\n'.join(lines)

    def _format_cointegration_stats(self, details: Dict, total_count: int) -> str:
        """格式化协整检验统计"""
        periods = [
            (('5m', '7d'), '5m'),
            (('1h', '30d'), '1h'),
            (('4h', '60d'), '4h'),
        ]

        old_pass = 0
        new_pass = 0
        old_results = []
        new_results = []

        for period_key, label in periods:
            detail = details.get(period_key, {})
            coint_old = detail.get('cointegration_old', {})
            coint_new = detail.get('cointegration_new', {})

            old_passed = coint_old.get('passed', False)
            new_passed = coint_new.get('passed', False)

            if old_passed:
                old_pass += 1
            if new_passed:
                new_pass += 1

            old_results.append(f"{label}{'✅' if old_passed else '❌'}")
            new_results.append(f"{label}{'✅' if new_passed else '❌'}")

        # 构建表格
        lines = [
            "**【协整检验统计】**",
            f"├─ 通过数量: {total_count}/6",
            f"├─ Old方法: {old_pass}/3 ({', '.join(old_results)})",
            f"└─ New方法: {new_pass}/3 ({', '.join(new_results)})",
            "",
        ]

        # 详细表格
        lines.extend([
            "| 方法 | 周期 | p-value | 状态 |",
            "|------|------|---------|------|",
        ])

        for period_key, label in periods:
            detail = details.get(period_key, {})
            coint_old = detail.get('cointegration_old', {})
            coint_new = detail.get('cointegration_new', {})

            old_p = coint_old.get('adf_pvalue', 1.0)
            new_p = coint_new.get('adf_pvalue', 1.0)

            old_status = "✅" if coint_old.get('passed', False) else "❌"
            new_status = "✅" if coint_new.get('passed', False) else "❌"

            lines.append(f"| Old | {label} | {old_p:.4f} | {old_status} |")
            lines.append(f"| New | {label} | {new_p:.4f} | {new_status} |")

        lines.extend(["", "---"])
        return '\n'.join(lines)

    def _format_health_monitor(self, details: Dict) -> str:
        """格式化协整健康监控"""
        # 仅4h周期有健康监控数据
        detail_4h = details.get(('4h', '60d'), {})
        health_monitor = detail_4h.get('health_monitor')

        if not health_monitor:
            return ""

        long_window = health_monitor.get('long_window', {})
        short_window = health_monitor.get('short_window', {})
        score_diff = health_monitor.get('score_diff', 0)

        def format_window_section(title: str, data: Dict, window_size: int) -> List[str]:
            score = data.get('health_score', 0)
            state = data.get('state', 'N/A')
            adf_p = data.get('adf_pvalue', 1.0)
            halflife = data.get('halflife', 'N/A')
            halflife_reason = data.get('halflife_reason', '')
            hurst = data.get('hurst')
            phi = data.get('phi')
            beta = data.get('beta', 0)

            scores = data.get('scores', {})
            adf_score = scores.get('adf', 0)
            hl_score = scores.get('halflife', 0)
            stab_score = scores.get('stability', 0)

            stability_details = data.get('stability_details', {})
            beta_cv = stability_details.get('beta_cv', 0)
            state_emoji = self._get_state_emoji(state)

            lines = [
                f"**{title} ({window_size}期)**",
                f"├─ 综合得分: {score}/34 | 状态: {state_emoji} {state}",
                f"├─ ADF得分: {adf_score}/40 | p-value: {adf_p:.4f}",
                f"├─ 半衰期得分: {hl_score}/30 | {halflife}期",
                f"├─ 稳定性得分: {stab_score}/30 | β变异:{beta_cv:.3f}",
            ]

            # 显示 phi 和 Hurst
            phi_str = f"{phi:.4f}" if phi is not None else "N/A"
            if hurst is not None:
                hurst_status = "🔴 趋势" if hurst > ALERT_HURST['trend'] else ("🟢 均值回复" if hurst < ALERT_HURST['mean_reversion'] else "🟡 随机")
                lines.append(f"├─ phi: {phi_str} | Hurst: {hurst:.3f} ({hurst_status})")
            else:
                lines.append(f"├─ phi: {phi_str}")
            lines.append(f"└─ β系数: {beta:.4f}")

            return lines

        lines = ["**【协整健康监控】** (4h周期)"]
        lines.extend(format_window_section("长期窗口", long_window, HEALTH_MONITOR_LONG_WINDOW))
        lines.append("")
        lines.extend(format_window_section("短期窗口", short_window, HEALTH_MONITOR_SHORT_WINDOW))
        lines.append("")

        # 窗口对比分析
        diff_warning = ""
        if abs(score_diff) > ALERT_SCORE_DIFF['high']:
            diff_warning = " ⚠️ 差异较大"
        elif abs(score_diff) > ALERT_SCORE_DIFF['medium']:
            diff_warning = " 📊 需关注"

        long_score = long_window.get('health_score', 0)
        short_score = short_window.get('health_score', 0)

        if short_score > long_score:
            trend = "📈 短期改善中"
        elif short_score < long_score - ALERT_SCORE_DIFF['deteriorate']:
            trend = "📉 短期恶化中"
        else:
            trend = "➡️ 相对稳定"

        lines.extend([
            "**窗口对比**",
            f"├─ 得分差异: {score_diff:+.1f}{diff_warning}",
            f"└─ 趋势判断: {trend}",
            "",
            "---"
        ])

        return '\n'.join(lines)

    def _get_state_emoji(self, state: str) -> str:
        """获取状态对应的emoji"""
        state_emojis = {
            'HEALTHY': '🟢',
            'WARNING': '🟡',
            'DANGER': '🟠',
            'DEAD': '🔴'
        }
        return state_emojis.get(state, '⚪')

    def _format_risk_assessment(self, multi_period_result: Dict, details: Dict) -> str:
        """格式化风险评估"""
        risk_factors = self._calculate_risk_factors(multi_period_result, details)

        lines = ["**【风险评估】**"]

        # 高风险因素
        if risk_factors['high']:
            lines.append("🔴 **高风险因素**:")
            for factor in risk_factors['high']:
                lines.append(f"   • {factor}")

        # 中等风险因素
        if risk_factors['mid']:
            lines.append("🟡 **中等风险因素**:")
            for factor in risk_factors['mid']:
                lines.append(f"   • {factor}")

        # 有利因素
        if risk_factors['green']:
            lines.append("🟢 **有利因素**:")
            for factor in risk_factors['green']:
                lines.append(f"   • {factor}")

        if not any([risk_factors['high'], risk_factors['mid'], risk_factors['green']]):
            lines.append("   暂无明显风险因素")

        lines.extend(["", "---"])
        return '\n'.join(lines)

    def _calculate_risk_factors(self, multi_period_result: Dict, details: Dict) -> Dict[str, List[str]]:
        """计算风险因素"""
        risk_factors = {
            'high': [],
            'mid': [],
            'green': []
        }

        # 获取健康监控数据
        detail_4h = details.get(('4h', '60d'), {})
        health_monitor = detail_4h.get('health_monitor')
        cointegration_count = multi_period_result.get('cointegration_count', 0)
        zscore_list = multi_period_result.get('zscore_list', [0, 0, 0])

        # ===== 高风险因素检测 =====
        if health_monitor:
            short_window = health_monitor.get('short_window', {})
            long_window = health_monitor.get('long_window', {})
            score_diff = health_monitor.get('score_diff', 0)

            short_score = short_window.get('health_score', 100)
            short_state = short_window.get('state', '')
            long_score = long_window.get('health_score', 100)
            hurst = long_window.get('hurst')
            halflife = long_window.get('halflife')

            # 短期协整得分极低
            if short_score < HEALTH_MONITOR_STATE_THRESHOLDS[2]:  # 10分，高风险阈值
                risk_factors['high'].append(f"短期协整得分极低 ({short_score:.1f})")

            # 长短期得分差异过大
            if abs(score_diff) > ALERT_SCORE_DIFF['high']:
                risk_factors['high'].append(f"长短期得分差异过大 ({score_diff:+.1f})")

            # Hurst指数过高
            if hurst is not None and hurst > ALERT_RISK_HIGH_HURST:
                risk_factors['high'].append(f"Hurst指数过高 ({hurst:.3f}), 趋势性强")

            # 半衰期无穷大
            if halflife == 'inf' or halflife == float('inf'):
                risk_factors['high'].append("半衰期无穷大, 不具均值回复性")

        # New方法全部未通过 (0/3)
        new_pass = sum(
            1 for pk in [('5m', '7d'), ('1h', '30d'), ('4h', '60d')]
            if details.get(pk, {}).get('cointegration_new', {}).get('passed', False)
        )
        if new_pass == 0:
            risk_factors['high'].append("New方法全部未通过 (0/3)")

        # ===== 中等风险因素检测 =====
        # 协整检验通过率低
        if cointegration_count < ALERT_RISK_MID['coint_min']:
            risk_factors['mid'].append(f"协整通过率较低 ({cointegration_count}/6)")

        # Z-score短强长弱
        if len(zscore_list) == 3:
            abs_5m, abs_1h, abs_4h = abs(zscore_list[0]), abs(zscore_list[1]), abs(zscore_list[2])
            if abs_5m > abs_4h * ALERT_RISK_MID['zscore_ratio']:
                risk_factors['mid'].append("短周期Z-score远强于长周期")

        if health_monitor:
            # 短期协整得分 WARNING/DANGER
            if HEALTH_MONITOR_STATE_THRESHOLDS[2] <= short_score < HEALTH_MONITOR_STATE_THRESHOLDS[0]:  # 10-18分，警告区间
                risk_factors['mid'].append(f"短期协整状态: {short_state} ({short_score:.1f})")

            # β系数变异
            stability_details = long_window.get('stability_details', {})
            beta_cv = stability_details.get('beta_cv', 0)
            if beta_cv > ALERT_RISK_MID['beta_cv']:
                risk_factors['mid'].append(f"β系数波动较大 (CV={beta_cv:.3f})")

        # ===== 有利因素检测 =====
        # 多周期Z-score全部同向
        if len(zscore_list) == 3:
            all_same_sign = (zscore_list[0] >= 0) == (zscore_list[1] >= 0) == (zscore_list[2] >= 0)
            if all_same_sign:
                risk_factors['green'].append("多周期Z-score方向一致")

        # 长期窗口协整健康
        if health_monitor and long_score >= HEALTH_MONITOR_STATE_THRESHOLDS[0]:  # 18分，绿色区域
            risk_factors['green'].append(f"长期协整健康 ({long_score:.1f})")

        # 4h相关系数高
        corr_4h = detail_4h.get('correlation')
        if corr_4h is not None and corr_4h > ALERT_CORR['good']:
            risk_factors['green'].append(f"4h相关系数高 ({corr_4h:.4f})")

        # 协整通过率高
        if cointegration_count >= ALERT_QUALITY['good']:
            risk_factors['green'].append(f"协整通过率高 ({cointegration_count}/6)")

        return risk_factors

    def _format_trading_suggestion(self, multi_period_result: Dict, details: Dict) -> str:
        """格式化交易建议"""
        risk_factors = self._calculate_risk_factors(multi_period_result, details)
        rating, reason, suggestion = self._calculate_rating(risk_factors, multi_period_result)

        direction = multi_period_result.get('direction', 'none')
        direction_text = "做多" if direction == 'long' else "做空"

        lines = [
            "**【交易建议】**",
            f"├─ 综合评级: {rating}",
            f"├─ 主要原因: {reason}",
            f"└─ 建议操作: {suggestion}",
            "",
            f"💡 **说明**: 此信号已通过3个周期的协整检验和Z-score验证。建议{direction_text}方向操作，请结合市场整体情况和仓位管理策略进行决策。"
        ]

        return '\n'.join(lines)

    def _calculate_rating(
        self,
        risk_factors: Dict[str, List[str]],
        multi_period_result: Dict
    ) -> Tuple[str, str, str]:
        """
        计算综合评级

        Returns:
            Tuple[str, str, str]: (评级, 主要原因, 建议操作)
        """
        high_count = len(risk_factors['high'])
        mid_count = len(risk_factors['mid'])
        green_count = len(risk_factors['green'])

        direction = multi_period_result.get('direction', 'none')
        direction_text = "做多" if direction == 'long' else "做空"

        if high_count >= ALERT_RATING_COUNT_THRESHOLD:
            return (
                "🔴 高风险",
                "存在多个高风险因素",
                "不建议交易，等待更好信号"
            )
        elif high_count == 1:
            return (
                "⚠️ 谨慎",
                risk_factors['high'][0],
                "需人工判断，建议观望或极小仓位试探"
            )
        elif mid_count >= ALERT_RATING_COUNT_THRESHOLD:
            return (
                "⚠️ 谨慎",
                "存在多个中等风险因素",
                "可考虑小仓位操作，设置严格止损"
            )
        elif mid_count == 1:
            return (
                "🟡 中等",
                risk_factors['mid'][0],
                f"可考虑{direction_text}，建议半仓操作"
            )
        elif green_count >= ALERT_RATING_COUNT_THRESHOLD:
            return (
                "🟢 推荐",
                "多项有利因素确认",
                f"信号质量高，建议{direction_text}操作"
            )
        else:
            return (
                "🟢 推荐",
                "无明显风险因素",
                f"可执行{direction_text}操作"
            )
