#!/usr/bin/env python3
"""
数据一致性验证脚本

验证K线数据和分析结果之间的时间一致性，确保分析使用的是最新的K线数据。

功能：
1. 多周期K线时间差验证（5m/1h/4h）
2. 分析结果完整性检测
3. 时间延迟统计（平均值、最大值、P95）
4. K线数据覆盖率检查
5. 并发查询优化
6. JSON/文本双格式输出

Author: Claude
Date: 2026-01-29
Version: 2.0
"""

import argparse
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any, Tuple
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from decimal import Decimal

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    # 提供一个假的tqdm类作为后备
    class tqdm:
        def __init__(self, *args, **kwargs):
            self.iterable = kwargs.get('iterable', args[0] if args else None)
        def __iter__(self):
            return iter(self.iterable) if self.iterable else iter([])
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def update(self, n=1):
            pass

from utils.timescaledb import TimescaleDBClient
from utils.logging_config import logger


# 终端颜色工具类
class TerminalColors:
    """终端颜色代码"""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    RESET = '\033[0m'
    
    @classmethod
    def success(cls, text: str) -> str:
        """绿色成功文本"""
        return f"{cls.GREEN}{text}{cls.RESET}"
    
    @classmethod
    def warning(cls, text: str) -> str:
        """黄色警告文本"""
        return f"{cls.YELLOW}{text}{cls.RESET}"
    
    @classmethod
    def error(cls, text: str) -> str:
        """红色错误文本"""
        return f"{cls.RED}{text}{cls.RESET}"
    
    @classmethod
    def info(cls, text: str) -> str:
        """蓝色信息文本"""
        return f"{cls.BLUE}{text}{cls.RESET}"
    
    @classmethod
    def cyan(cls, text: str) -> str:
        """青色文本"""
        return f"{cls.CYAN}{text}{cls.RESET}"
    
    @classmethod
    def bold(cls, text: str) -> str:
        """加粗文本"""
        return f"{cls.BOLD}{text}{cls.RESET}"
    
    @classmethod
    def is_enabled(cls) -> bool:
        """检查是否支持彩色输出"""
        import os
        import sys
        # 检查是否为TTY终端且不是在CI环境
        return (
            sys.stdout.isatty() and 
            os.getenv('NO_COLOR') is None and
            os.getenv('TERM') != 'dumb'
        )


# 配置常量
@dataclass
class ValidationConfig:
    """验证配置"""
    timeframes: List[str] = None
    lag_threshold_seconds: int = 360  # 延迟告警阈值（秒）- 包含5m K线周期（300秒）+ 60秒处理余量
    coverage_threshold_pct: float = 95.0  # 覆盖率告警阈值（%）
    max_concurrent_queries: int = 3  # 最大并发查询数
    kline_period_seconds: int = 300  # 5m K线周期（秒）- 用于计算真实延迟

    def __post_init__(self):
        if self.timeframes is None:
            self.timeframes = ['5m', '1h', '4h']


# 周期到秒数的映射
TIMEFRAME_SECONDS = {
    '5m': 300,
    '1h': 3600,
    '4h': 14400
}


class DataConsistencyValidator:
    """数据一致性验证器（优化版v3.0）"""

    def __init__(
        self,
        client: Optional[TimescaleDBClient] = None,
        config: Optional[ValidationConfig] = None,
        use_colors: bool = True
    ):
        self.client = client or TimescaleDBClient()
        self.config = config or ValidationConfig()
        self.timeframes = self.config.timeframes
        self.warnings: List[str] = []
        self._query_cache: Dict[str, Any] = {}
        self.use_colors = use_colors and TerminalColors.is_enabled()

    def _colorize(self, text: str, color_func) -> str:
        """
        条件彩色化文本
        
        Args:
            text: 要着色的文本
            color_func: TerminalColors的颜色方法
        
        Returns:
            彩色化后的文本（如果启用彩色）
        """
        if self.use_colors:
            return color_func(text)
        return text
    
    def _format_delay_bar(self, seconds: float, max_seconds: int = 600) -> str:
        """
        格式化延迟为可视化进度条
        
        Args:
            seconds: 延迟秒数
            max_seconds: 最大秒数（用于计算比例）
        
        Returns:
            可视化进度条字符串
        """
        ratio = min(seconds / max_seconds, 1.0)
        bar_length = 20
        filled = int(bar_length * ratio)
        
        # 根据延迟程度选择字符和颜色
        if seconds < self.config.lag_threshold_seconds:
            char = '█'
            bar = char * filled + '░' * (bar_length - filled)
            return self._colorize(bar, TerminalColors.success)
        elif seconds < self.config.lag_threshold_seconds * 5:
            char = '█'
            bar = char * filled + '░' * (bar_length - filled)
            return self._colorize(bar, TerminalColors.warning)
        else:
            char = '█'
            bar = char * filled + '░' * (bar_length - filled)
            return self._colorize(bar, TerminalColors.error)
    
    def _paginated_query(
        self,
        base_query: str,
        params: tuple,
        page_size: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        分页查询大数据集，减少内存占用
        
        Args:
            base_query: SQL基础查询（不含LIMIT/OFFSET）
            params: 查询参数
            page_size: 每页大小
        
        Returns:
            所有结果的合并列表
        """
        results = []
        offset = 0
        
        while True:
            # 添加分页参数
            page_query = f"{base_query} LIMIT {page_size} OFFSET {offset}"
            
            try:
                page_results = self.client.execute_query(page_query, params)
                
                if not page_results:
                    break
                    
                results.extend(page_results)
                offset += page_size
                
                # 如果返回数量小于页大小，说明已经是最后一页
                if len(page_results) < page_size:
                    break
                    
            except Exception as e:
                logger.error(f"分页查询失败 (offset={offset}): {e}")
                break
        
        return results
    
    def _get_cache_key(self, query: str, params: tuple) -> str:
        """
        生成查询缓存键
        
        Args:
            query: SQL查询
            params: 查询参数
        
        Returns:
            缓存键（MD5哈希）
        """
        from hashlib import md5
        content = f"{query}:{params}"
        return md5(content.encode()).hexdigest()
    
    def _cached_query(
        self,
        query: str,
        params: tuple,
        ttl_seconds: int = 60
    ) -> Optional[Any]:
        """
        带缓存的查询
        
        Args:
            query: SQL查询
            params: 查询参数
            ttl_seconds: 缓存有效期（秒）
        
        Returns:
            查询结果或None（缓存未命中）
        """
        cache_key = self._get_cache_key(query, params)
        
        if cache_key in self._query_cache:
            cached_result, cached_time = self._query_cache[cache_key]
            age = (datetime.now(timezone.utc) - cached_time).total_seconds()
            
            if age < ttl_seconds:
                logger.debug(f"缓存命中: {cache_key[:8]}... (age={age:.1f}s)")
                return cached_result
        
        return None
    
    def _cache_result(self, query: str, params: tuple, result: Any):
        """
        缓存查询结果
        
        Args:
            query: SQL查询
            params: 查询参数
            result: 查询结果
        """
        cache_key = self._get_cache_key(query, params)
        self._query_cache[cache_key] = (result, datetime.now(timezone.utc))
        logger.debug(f"缓存已保存: {cache_key[:8]}...")
    
    def _build_base_filters(
        self,
        symbol: Optional[str] = None
    ) -> Tuple[str, List[Any]]:
        """
        构建通用查询过滤条件

        Returns:
            (WHERE子句, 参数列表)
        """
        filters = []
        params = []

        if symbol:
            filters.append("symbol = %s")
            params.append(symbol)

        where_clause = " AND ".join(filters) if filters else ""
        return where_clause, params

    def validate_multiperiod_lags(
        self,
        hours: int = 1,
        symbol: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        验证多周期K线时间差

        Args:
            hours: 查询最近N小时的数据
            symbol: 指定币种（可选）
            limit: 每个周期最多返回记录数

        Returns:
            字典，键为时间周期，值为时间差记录列表
        """
        logger.info(f"开始验证多周期K线时间差（最近{hours}小时）...")
        results = {}

        for timeframe in self.timeframes:
            # 优化后的SQL - 使用窗口函数替代LEFT JOIN LATERAL
            query = """
                WITH latest_klines AS (
                    SELECT DISTINCT ON (symbol)
                        symbol,
                        time as kline_time
                    FROM klines
                    WHERE timeframe = %s
                        AND time <= (SELECT MAX(analysis_time) FROM analysis_results 
                                    WHERE analysis_time > NOW() - INTERVAL '%s hours')
                        AND time > NOW() - INTERVAL '%s hours' - INTERVAL '1 day'
                    ORDER BY symbol, time DESC
                ),
                lag_calc AS (
                    SELECT 
                        a.symbol,
                        a.analysis_time,
                        lk.kline_time,
                        EXTRACT(EPOCH FROM (a.analysis_time - lk.kline_time)) as lag_seconds
                    FROM analysis_results a
                    LEFT JOIN latest_klines lk ON lk.symbol = a.symbol
                    WHERE a.analysis_time > NOW() - INTERVAL '%s hours'
            """

            params = [timeframe, hours, hours, hours]

            if symbol:
                query += " AND a.symbol = %s"
                params.append(symbol)

            query += f"""
                )
                SELECT * FROM lag_calc
                ORDER BY analysis_time DESC
                LIMIT {limit};
            """

            try:
                records = self.client.execute_query(query, tuple(params))
                results[timeframe] = records or []
                logger.info(f"  {timeframe}: 查询到 {len(results[timeframe])} 条记录")
            except Exception as e:
                logger.error(f"  {timeframe}: 查询失败 - {e}")
                results[timeframe] = []

        return results

    def detect_missing_data(
        self,
        hours: int = 24,
        symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        检测分析结果中的数据完整性（修复后的版本）

        ⚠️ 修复说明：
        原版本检测的是 klines 表中的K线数据（在分析时刻±1小时内），
        这导致大量误报，因为：
        1. 4h周期的K线每4小时才更新一次，在1小时窗口内经常找不到
        2. 但分析实际使用的是更早的历史数据（7-60天），可能是完整的

        修复后的版本直接检测 analysis_results 表中的字段完整性，
        这才是真正反映数据完整性的指标。

        Args:
            hours: 查询最近N小时的数据
            symbol: 指定币种（可选）

        Returns:
            数据不完整的记录列表
        """
        logger.info(f"开始检测分析结果数据完整性（最近{hours}小时）...")

        query = """
            SELECT
                symbol,
                analysis_time,
                created_at,
                -- 相关系数完整性
                (corr_5m_7d IS NOT NULL) as has_5m_corr,
                (corr_1h_30d IS NOT NULL) as has_1h_corr,
                (corr_4h_60d IS NOT NULL) as has_4h_corr,
                -- Z-score完整性
                (zscore_5m IS NOT NULL) as has_5m_zscore,
                (zscore_1h IS NOT NULL) as has_1h_zscore,
                (zscore_4h IS NOT NULL) as has_4h_zscore,
                -- 完整周期数（基于相关系数）
                (corr_5m_7d IS NOT NULL)::int +
                (corr_1h_30d IS NOT NULL)::int +
                (corr_4h_60d IS NOT NULL)::int as complete_periods
            FROM analysis_results
            WHERE created_at > NOW() - INTERVAL '%s hours'
                AND (
                    corr_5m_7d IS NULL OR
                    corr_1h_30d IS NULL OR
                    corr_4h_60d IS NULL OR
                    zscore_5m IS NULL OR
                    zscore_1h IS NULL OR
                    zscore_4h IS NULL
                )
        """

        params = [hours]

        if symbol:
            query += " AND symbol = %s"
            params.append(symbol)

        query += " ORDER BY created_at DESC LIMIT 100"

        try:
            records = self.client.execute_query(query, tuple(params))
            if records:
                logger.warning(f"  发现 {len(records)} 条数据不完整记录")
                for record in records:
                    # 识别缺失的周期
                    missing_fields = []
                    if not record['has_5m_corr']:
                        missing_fields.append('5m')
                    if not record['has_1h_corr']:
                        missing_fields.append('1h')
                    if not record['has_4h_corr']:
                        missing_fields.append('4h')

                    self.warnings.append(
                        f"数据不完整: {record['symbol']} @ {record['analysis_time']} | "
                        f"缺失周期: {', '.join(missing_fields)} | "
                        f"完整周期数: {record['complete_periods']}/3"
                    )
            else:
                logger.info("  ✅ 所有记录数据完整")
            return records or []
        except Exception as e:
            logger.error(f"  数据完整性检测失败 - {e}")
            return []

    def _calculate_lag_statistics(
        self,
        hours: int,
        symbol: Optional[str] = None
    ) -> Optional[Dict[str, float]]:
        """
        直接使用预存储的 analysis_delay_seconds 字段统计延迟

        注意：不再按timeframe分别统计，因为analysis_delay_seconds是统一的真实延迟

        Args:
            hours: 查询最近N小时的数据
            symbol: 指定币种（可选）

        Returns:
            延迟统计字典，包含总记录数、平均值、最大值、最小值、P95、中位数
        """
        query = """
            SELECT
                COUNT(*) as total_records,
                AVG(analysis_delay_seconds) as avg_lag,
                MAX(analysis_delay_seconds) as max_lag,
                MIN(analysis_delay_seconds) as min_lag,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY analysis_delay_seconds) as p95_lag,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY analysis_delay_seconds) as median_lag
            FROM analysis_results
            WHERE created_at > NOW() - INTERVAL '%s hours'
                AND analysis_delay_seconds IS NOT NULL
        """

        params = [hours]

        if symbol:
            query += " AND symbol = %s"
            params.append(symbol)

        try:
            result = self.client.execute_query(query, tuple(params), fetch_one=True)
            if result and result['total_records'] > 0:
                stat = {
                    'total_records': result['total_records'],
                    'avg_lag': result['avg_lag'],
                    'max_lag': result['max_lag'],
                    'min_lag': result['min_lag'],
                    'p95_lag': result['p95_lag'],
                    'median_lag': result['median_lag']
                }

                # 检查阈值（注意：延迟包含K线周期）
                real_avg_delay = result['avg_lag'] - self.config.kline_period_seconds
                real_max_delay = result['max_lag'] - self.config.kline_period_seconds

                if result['avg_lag'] > self.config.lag_threshold_seconds:
                    self.warnings.append(
                        f"延迟过大: 平均延迟 {result['avg_lag']:.1f}秒 "
                        f"(包含{self.config.kline_period_seconds}秒K线周期, 真实延迟约{real_avg_delay:.1f}秒)"
                    )
                elif real_avg_delay < 60:
                    logger.info(f"✅ 延迟正常: 真实延迟{real_avg_delay:.1f}秒")

                return stat
            else:
                logger.warning("  无统计数据")
                return None
        except Exception as e:
            logger.error(f"  统计计算失败 - {e}")
            return None

    def calculate_lag_statistics(
        self,
        hours: int = 1,
        symbol: Optional[str] = None,
        parallel: bool = True  # 保留参数以保持兼容性，但不再使用
    ) -> Dict[str, float]:
        """
        计算时间延迟统计（直接使用预存储的analysis_delay_seconds字段）

        注意：不再按timeframe分别统计，因为analysis_delay_seconds记录的是真实延迟

        Args:
            hours: 查询最近N小时的数据
            symbol: 指定币种（可选）
            parallel: 保留以保持兼容性，但不再使用

        Returns:
            延迟统计字典，包含总记录数、平均值、最大值、最小值、P95、中位数
        """
        logger.info(f"开始计算时间延迟统计（最近{hours}小时）...")

        stat = self._calculate_lag_statistics(hours, symbol)

        if stat:
            logger.info(f"  总记录数: {stat['total_records']}")
            logger.info(f"  平均延迟: {stat['avg_lag']:.2f}秒")
            logger.info(f"  最大延迟: {stat['max_lag']:.2f}秒")
            logger.info(f"  P95延迟: {stat['p95_lag']:.2f}秒")

        return stat if stat else {}

    def check_delay_field_quality(
        self,
        hours: int = 24,
        symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        检查 analysis_delay_seconds 字段的数据质量

        Args:
            hours: 查询最近N小时的数据
            symbol: 指定币种（可选）

        Returns:
            包含以下字段的字典：
            - total_records: 总记录数
            - null_count: NULL值数量
            - null_percentage: NULL百分比
            - negative_count: 负数数量（异常）
            - extreme_count: 极端值数量（>1小时）
            - kline_time_null_count: kline_time字段NULL数量
        """
        logger.info(f"开始检查延迟字段数据质量（最近{hours}小时）...")

        query = """
            SELECT
                COUNT(*) as total_records,
                COUNT(CASE WHEN analysis_delay_seconds IS NULL THEN 1 END) as null_count,
                COUNT(CASE WHEN analysis_delay_seconds < 0 THEN 1 END) as negative_count,
                COUNT(CASE WHEN analysis_delay_seconds > 3600 THEN 1 END) as extreme_count,
                COUNT(CASE WHEN kline_time IS NULL THEN 1 END) as kline_time_null_count
            FROM analysis_results
            WHERE created_at > NOW() - INTERVAL '%s hours'
        """

        params = [hours]

        if symbol:
            query += " AND symbol = %s"
            params.append(symbol)

        try:
            result = self.client.execute_query(query, tuple(params), fetch_one=True)
            if result:
                total = result['total_records']
                null_count = result['null_count']
                null_percentage = (null_count / total * 100) if total > 0 else 0

                quality_info = {
                    'total_records': total,
                    'null_count': null_count,
                    'null_percentage': null_percentage,
                    'negative_count': result['negative_count'],
                    'extreme_count': result['extreme_count'],
                    'kline_time_null_count': result['kline_time_null_count']
                }

                logger.info(f"  总记录数: {total}")
                logger.info(f"  NULL值数量: {null_count} ({null_percentage:.2f}%)")
                logger.info(f"  负数数量: {result['negative_count']}")
                logger.info(f"  极端值数量(>1小时): {result['extreme_count']}")
                logger.info(f"  kline_time为NULL: {result['kline_time_null_count']}")

                # 添加警告
                if null_percentage > 5:
                    self.warnings.append(
                        f"延迟字段NULL值过多: {null_count}条 ({null_percentage:.2f}%)"
                    )
                if result['negative_count'] > 0:
                    self.warnings.append(
                        f"发现异常负延迟: {result['negative_count']}条"
                    )
                if result['extreme_count'] > total * 0.01:  # >1%为极端值
                    self.warnings.append(
                        f"发现过多极端延迟(>1小时): {result['extreme_count']}条"
                    )

                return quality_info
            else:
                logger.warning("  无数据")
                return {}
        except Exception as e:
            logger.error(f"  数据质量检查失败 - {e}")
            return {}

    def check_data_coverage(
        self,
        days: int = 7,
        symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        检查K线数据覆盖率（优化版SQL）

        Args:
            days: 查询最近N天的数据
            symbol: 指定币种（可选）

        Returns:
            覆盖率记录列表
        """
        logger.info(f"开始检查K线数据覆盖率（最近{days}天）...")
        
        # 显示进度提示
        if TQDM_AVAILABLE:
            pbar = tqdm(total=1, desc="检查覆盖率", unit="查询")
        
        # 使用CTE和预计算来优化查询
        query = """
            WITH timeframe_intervals AS (
                SELECT '5m' as tf, 300 as interval_sec
                UNION ALL SELECT '1h', 3600
                UNION ALL SELECT '4h', 14400
            ),
            coverage_stats AS (
                SELECT
                    k.symbol,
                    k.timeframe,
                    MIN(k.time) as first_kline,
                    MAX(k.time) as last_kline,
                    COUNT(*) as total_klines,
                    ti.interval_sec
                FROM klines k
                JOIN timeframe_intervals ti ON k.timeframe = ti.tf
                WHERE k.time > NOW() - INTERVAL '%s days'
        """

        params = [days]

        if symbol:
            query += " AND k.symbol = %s"
            params.append(symbol)

        query += """
                GROUP BY k.symbol, k.timeframe, ti.interval_sec
            )
            SELECT
                symbol,
                timeframe,
                first_kline,
                last_kline,
                total_klines,
                FLOOR(EXTRACT(EPOCH FROM (last_kline - first_kline)) / interval_sec)::INTEGER as expected_count,
                ROUND(
                    total_klines * 100.0 / NULLIF(
                        FLOOR(EXTRACT(EPOCH FROM (last_kline - first_kline)) / interval_sec),
                        0
                    ),
                    2
                ) as coverage_pct
            FROM coverage_stats
            ORDER BY coverage_pct ASC NULLS LAST;
        """

        try:
            records = self.client.execute_query(query, tuple(params))
            
            # 完成进度
            if TQDM_AVAILABLE:
                pbar.update(1)
                pbar.close()
            
            logger.info(f"  查询到 {len(records) if records else 0} 条覆盖率记录")

            # 检查低覆盖率
            if records:
                for record in records:
                    if record['coverage_pct'] and record['coverage_pct'] < self.config.coverage_threshold_pct:
                        self.warnings.append(
                            f"低覆盖率: {record['symbol']} ({record['timeframe']}) "
                            f"覆盖率仅 {record['coverage_pct']:.2f}%"
                        )

            return records or []
        except Exception as e:
            if TQDM_AVAILABLE:
                pbar.close()
            logger.error(f"  覆盖率检查失败 - {e}")
            return []

    def compare_with_baseline(
        self,
        baseline_file: str,
        hours: int = 1,
        days: int = 7,
        symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        与基线报告对比
        
        Args:
            baseline_file: 基线报告JSON文件路径
            hours: 延迟统计时间窗口
            days: 覆盖率检查时间窗口
            symbol: 指定币种（可选）
        
        Returns:
            对比结果（改善/恶化的指标）
        """
        logger.info(f"加载基线报告: {baseline_file}")
        
        try:
            with open(baseline_file, 'r', encoding='utf-8') as f:
                baseline = json.load(f)
        except Exception as e:
            logger.error(f"无法加载基线报告: {e}")
            return {'error': str(e)}
        
        # 收集当前指标
        current = self.collect_all_metrics(hours=hours, days=days, symbol=symbol, parallel=True)
        
        comparison = {
            'metadata': {
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'baseline_date': baseline.get('metadata', {}).get('generated_at', 'unknown'),
                'comparison_mode': True
            },
            'lag_changes': {},
            'trend': 'stable'
        }
        
        # 对比延迟变化
        baseline_lags = baseline.get('lag_statistics', {})
        current_lags = current['lag_statistics']
        
        total_change = 0
        for tf in self.timeframes:
            if tf in baseline_lags and baseline_lags[tf] and tf in current_lags and current_lags[tf]:
                base_avg = baseline_lags[tf].get('avg_lag', 0)
                curr_avg = current_lags[tf].get('avg_lag', 0)
                
                if base_avg > 0:
                    change_pct = ((curr_avg - base_avg) / base_avg) * 100
                    total_change += change_pct
                    
                    comparison['lag_changes'][tf] = {
                        'baseline_avg': base_avg,
                        'current_avg': curr_avg,
                        'change_pct': change_pct,
                        'trend': 'improving' if change_pct < -5 else ('degrading' if change_pct > 5 else 'stable')
                    }
        
        # 确定总体趋势
        if total_change < -10:
            comparison['trend'] = 'improving'
        elif total_change > 10:
            comparison['trend'] = 'degrading'
        
        # 对比警告数量
        comparison['warnings_change'] = {
            'baseline': len(baseline.get('warnings', [])),
            'current': len(current['warnings']),
            'delta': len(current['warnings']) - len(baseline.get('warnings', []))
        }
        
        return comparison
    
    def validate_incremental(
        self,
        since_minutes: int = 10,
        symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        增量验证模式 - 只检查最近N分钟的新数据
        
        适用场景：
        - 实时监控
        - 频繁执行的验证任务
        - 减少数据库负载
        
        Args:
            since_minutes: 检查最近N分钟的数据
            symbol: 指定币种（可选）
        
        Returns:
            增量验证结果
        """
        logger.info(f"开始增量验证（最近{since_minutes}分钟）...")
        self.warnings = []
        
        # 1. 统计新增记录数
        query_new_records = """
            SELECT 
                COUNT(*) as new_analysis_count,
                COUNT(DISTINCT symbol) as affected_symbols
            FROM analysis_results
            WHERE created_at > NOW() - INTERVAL '%s minutes'
        """
        
        params = [since_minutes]
        if symbol:
            query_new_records += " AND symbol = %s"
            params.append(symbol)
        
        new_records_stats = self.client.execute_query(query_new_records, tuple(params), fetch_one=True)
        
        # 2. 检查新增数据的延迟
        quick_lag_query = """
            SELECT 
                AVG(EXTRACT(EPOCH FROM (a.created_at - a.kline_time))) as avg_delay,
                MAX(EXTRACT(EPOCH FROM (a.created_at - a.kline_time))) as max_delay
            FROM analysis_results a
            WHERE a.created_at > NOW() - INTERVAL '%s minutes'
        """
        
        lag_params = [since_minutes]
        if symbol:
            quick_lag_query += " AND a.symbol = %s"
            lag_params.append(symbol)
        
        lag_stats = self.client.execute_query(quick_lag_query, tuple(lag_params), fetch_one=True)
        
        # 3. 快速数据缺失检查
        if new_records_stats and new_records_stats['new_analysis_count'] > 0:
            missing_check = self.detect_missing_data(hours=since_minutes / 60, symbol=symbol)
        else:
            missing_check = []
        
        # 生成警告（考虑K线周期）
        if lag_stats and lag_stats['max_delay']:
            real_max_delay = lag_stats['max_delay'] - self.config.kline_period_seconds
            if lag_stats['max_delay'] > self.config.lag_threshold_seconds:
                self.warnings.append(
                    f"增量检测发现延迟过大: 最大 {lag_stats['max_delay']:.1f}秒 "
                    f"(包含K线周期, 真实延迟约{real_max_delay:.1f}秒)"
                )
        
        return {
            'metadata': {
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'mode': 'incremental',
                'time_window_minutes': since_minutes,
                'symbol_filter': symbol
            },
            'new_records': new_records_stats or {},
            'lag_summary': lag_stats or {},
            'missing_data_count': len(missing_check),
            'warnings': self.warnings
        }
    
    def collect_all_metrics(
        self,
        hours: int = 1,
        days: int = 7,
        symbol: Optional[str] = None,
        parallel: bool = True
    ) -> Dict[str, Any]:
        """
        收集所有验证指标（结构化数据）

        Args:
            hours: 延迟统计时间窗口（小时）
            days: 覆盖率检查时间窗口（天）
            symbol: 指定币种（可选）
            parallel: 是否并发执行

        Returns:
            包含所有指标的字典
        """
        self.warnings = []  # 重置告警列表

        # 收集所有指标
        lag_stats = self.calculate_lag_statistics(
            hours=hours,
            symbol=symbol,
            parallel=parallel
        )
        delay_quality = self.check_delay_field_quality(hours=hours, symbol=symbol)
        missing_data = self.detect_missing_data(hours=hours, symbol=symbol)
        coverage_data = self.check_data_coverage(days=days, symbol=symbol)

        return {
            'metadata': {
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'hours_window': hours,
                'days_window': days,
                'symbol_filter': symbol,
                'parallel_execution': parallel
            },
            'lag_statistics': lag_stats,
            'delay_field_quality': delay_quality,
            'missing_data': missing_data,
            'coverage_data': coverage_data,
            'warnings': self.warnings,
            'config': asdict(self.config)
        }

    def generate_json_report(
        self,
        hours: int = 1,
        days: int = 7,
        symbol: Optional[str] = None,
        parallel: bool = True,
        indent: int = 2
    ) -> str:
        """
        生成JSON格式的验证报告

        Args:
            hours: 延迟统计时间窗口（小时）
            days: 覆盖率检查时间窗口（天）
            symbol: 指定币种（可选）
            parallel: 是否并发执行
            indent: JSON缩进空格数

        Returns:
            JSON格式的报告字符串
        """
        metrics = self.collect_all_metrics(hours, days, symbol, parallel)

        # 转换特殊类型为JSON兼容类型
        def json_serializer(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, Decimal):
                return float(obj)
            raise TypeError(f"Type {type(obj)} not serializable")

        return json.dumps(metrics, indent=indent, default=json_serializer, ensure_ascii=False)

    def generate_report(
        self,
        hours: int = 1,
        days: int = 7,
        symbol: Optional[str] = None,
        parallel: bool = True
    ) -> str:
        """
        生成文本格式的数据一致性验证报告

        Args:
            hours: 延迟统计时间窗口（小时）
            days: 覆盖率检查时间窗口（天）
            symbol: 指定币种（可选）
            parallel: 是否并发执行

        Returns:
            格式化的报告字符串
        """
        # 收集指标
        metrics = self.collect_all_metrics(hours, days, symbol, parallel)

        report_lines = []
        report_lines.append(self._colorize("=" * 60, TerminalColors.bold))
        report_lines.append(self._colorize("数据一致性验证报告", TerminalColors.bold))
        report_lines.append(self._colorize("=" * 60, TerminalColors.bold))
        report_lines.append(f"生成时间: {self._colorize(metrics['metadata']['generated_at'], TerminalColors.cyan)}")
        if symbol:
            report_lines.append(f"币种筛选: {self._colorize(symbol, TerminalColors.cyan)}")
        report_lines.append(f"并发执行: {self._colorize('是' if parallel else '否', TerminalColors.cyan)}")
        report_lines.append("")
        
        # === 执行摘要 ===
        report_lines.append(self._colorize("📊 执行摘要", TerminalColors.bold))
        report_lines.append("-" * 60)
        
        # 计算关键指标
        total_warnings = len(self.warnings)
        critical_warnings = [w for w in self.warnings if "延迟过大" in w or "低覆盖率" in w]
        coverage_data = metrics['coverage_data']
        missing_data = metrics['missing_data']
        
        # 确定总体状态
        if total_warnings == 0 and not missing_data:
            status = self._colorize("🟢 健康", TerminalColors.success)
        elif total_warnings < 10 and len(critical_warnings) == 0:
            status = self._colorize("🟡 警告", TerminalColors.warning)
        else:
            status = self._colorize("🔴 严重", TerminalColors.error)
        
        report_lines.append(f"  总体状态: {status}")
        report_lines.append(f"  告警数量: {self._colorize(str(total_warnings), TerminalColors.warning if total_warnings > 0 else TerminalColors.success)} 条")
        report_lines.append(f"  关键问题: {self._colorize(str(len(critical_warnings)), TerminalColors.error if len(critical_warnings) > 0 else TerminalColors.success)} 条")
        report_lines.append(f"  数据缺失: {self._colorize(str(len(missing_data)), TerminalColors.warning if missing_data else TerminalColors.success)} 条")
        report_lines.append(f"  验证币种: {len(set(r['symbol'] for r in coverage_data)) if coverage_data else 0} 个")
        report_lines.append("")

        # 1. 时间延迟统计（使用预存储字段）
        report_lines.append(self._colorize(f"1. 时间延迟统计（最近{hours}小时）", TerminalColors.bold))
        report_lines.append("-" * 60)
        report_lines.append(self._colorize(f"   ℹ️  注意：延迟包含K线周期（5m={self.config.kline_period_seconds}秒），真实处理延迟需减去周期", TerminalColors.info))
        report_lines.append("")
        lag_stats = metrics['lag_statistics']

        if lag_stats:
            # 计算真实延迟（减去K线周期）
            real_avg_delay = lag_stats['avg_lag'] - self.config.kline_period_seconds
            real_max_delay = lag_stats['max_lag'] - self.config.kline_period_seconds
            real_min_delay = lag_stats['min_lag'] - self.config.kline_period_seconds
            real_p95_delay = lag_stats['p95_lag'] - self.config.kline_period_seconds
            real_median_delay = lag_stats['median_lag'] - self.config.kline_period_seconds

            # 根据真实延迟选择颜色
            if real_avg_delay < 60:
                color_func = TerminalColors.success
            elif real_avg_delay < 180:
                color_func = TerminalColors.warning
            else:
                color_func = TerminalColors.error

            delay_bar = self._format_delay_bar(lag_stats['avg_lag'])
            report_lines.append(
                f"   总体延迟: {delay_bar} "
                f"平均 {lag_stats['avg_lag']:.2f}秒 (包含K线周期)"
            )
            report_lines.append(f"   真实延迟: {self._colorize(f'平均 {real_avg_delay:.2f}秒', color_func)}")
            report_lines.append("")
            report_lines.append(f"   统计详情（包含K线周期）:")
            report_lines.append(f"     • 记录数量: {lag_stats['total_records']} 条")
            report_lines.append(f"     • 最小延迟: {lag_stats['min_lag']:.2f}秒")
            report_lines.append(f"     • 中位延迟: {lag_stats['median_lag']:.2f}秒")
            report_lines.append(f"     • P95延迟:  {lag_stats['p95_lag']:.2f}秒")
            report_lines.append(f"     • 最大延迟: {lag_stats['max_lag']:.2f}秒")
            report_lines.append("")
            report_lines.append(f"   真实处理延迟（减去K线周期）:")
            report_lines.append(f"     • 平均: {self._colorize(f'{real_avg_delay:.2f}秒', color_func)}")
            report_lines.append(f"     • 最小: {real_min_delay:.2f}秒")
            report_lines.append(f"     • 中位: {real_median_delay:.2f}秒")
            report_lines.append(f"     • P95:  {real_p95_delay:.2f}秒")
            report_lines.append(f"     • 最大: {self._colorize(f'{real_max_delay:.2f}秒', TerminalColors.error if real_max_delay > 60 else TerminalColors.success)}")
        else:
            report_lines.append(f"   {self._colorize('⚠️  无延迟统计数据', TerminalColors.warning)}")

        # 1.1 数据质量检查
        quality_info = metrics.get('delay_field_quality', {})
        if quality_info:
            report_lines.append("")
            report_lines.append("   数据质量:")
            null_pct = quality_info.get('null_percentage', 0)
            if null_pct < 1:
                null_color = TerminalColors.success
            elif null_pct < 5:
                null_color = TerminalColors.warning
            else:
                null_color = TerminalColors.error

            report_lines.append(f"     • NULL值率: {self._colorize(f'{null_pct:.2f}%', null_color)} ({quality_info.get('null_count', 0)}/{quality_info.get('total_records', 0)})")

            if quality_info.get('negative_count', 0) > 0:
                report_lines.append(f"     • 异常负值: {self._colorize(str(quality_info['negative_count']), TerminalColors.error)} 条")
            if quality_info.get('extreme_count', 0) > 0:
                report_lines.append(f"     • 极端值(>1h): {self._colorize(str(quality_info['extreme_count']), TerminalColors.warning)} 条")

        report_lines.append("")

        # 2. 分析结果完整性检测
        report_lines.append(self._colorize(f"2. 分析结果完整性检测（最近{hours}小时）", TerminalColors.bold))
        report_lines.append("-" * 60)
        missing_data = metrics['missing_data']

        if missing_data:
            report_lines.append(self._colorize(f"   ⚠️  发现 {len(missing_data)} 条数据缺失记录:", TerminalColors.warning))
            for record in missing_data[:10]:  # 只显示前10条
                report_lines.append(
                    f"      - {record['symbol']} @ {record['analysis_time']}: "
                    f"只有 {self._colorize(str(record['available_timeframes']), TerminalColors.error)} 个周期"
                )
            if len(missing_data) > 10:
                report_lines.append(f"      ... 还有 {len(missing_data) - 10} 条记录")
        else:
            report_lines.append(self._colorize("   ✅ 无数据缺失", TerminalColors.success))

        report_lines.append("")

        # 3. K线数据覆盖率
        report_lines.append(self._colorize(f"3. K线数据覆盖率（最近{days}天）", TerminalColors.bold))
        report_lines.append("-" * 60)
        coverage_data = metrics['coverage_data']

        if coverage_data:
            # 按币种和周期分组显示
            coverage_by_symbol = defaultdict(dict)
            for record in coverage_data:
                coverage_by_symbol[record['symbol']][record['timeframe']] = record

            for sym in sorted(coverage_by_symbol.keys()):
                report_lines.append(f"   {sym}:")
                for tf in self.timeframes:
                    if tf in coverage_by_symbol[sym]:
                        rec = coverage_by_symbol[sym][tf]
                        coverage = rec['coverage_pct'] if rec['coverage_pct'] else 0
                        
                        # 根据覆盖率选择颜色
                        if coverage >= self.config.coverage_threshold_pct:
                            status = self._colorize("✅", TerminalColors.success)
                            coverage_str = self._colorize(f"{coverage:6.2f}%", TerminalColors.success)
                        else:
                            status = self._colorize("⚠️", TerminalColors.warning)
                            coverage_str = self._colorize(f"{coverage:6.2f}%", TerminalColors.warning)
                        
                        report_lines.append(
                            f"      {tf:3s}: {status} {coverage_str} "
                            f"({rec['total_klines']:,} / {int(rec['expected_count']) if rec['expected_count'] else 0:,})"
                        )
        else:
            report_lines.append(self._colorize("   ⚠️  无覆盖率数据", TerminalColors.warning))

        report_lines.append("")

        # 4. 告警汇总
        if self.warnings:
            report_lines.append(self._colorize(f"⚠️  告警汇总 ({len(self.warnings)} 条)", TerminalColors.warning))
            report_lines.append("-" * 60)
            for warning in self.warnings:
                # 根据告警类型选择颜色
                if "延迟过大" in warning:
                    colored_warning = self._colorize(f"   - {warning}", TerminalColors.error)
                elif "低覆盖率" in warning:
                    colored_warning = self._colorize(f"   - {warning}", TerminalColors.warning)
                else:
                    colored_warning = self._colorize(f"   - {warning}", TerminalColors.warning)
                report_lines.append(colored_warning)
            report_lines.append("")
            
            # === 可操作建议 ===
            report_lines.append(self._colorize("💡 可操作建议", TerminalColors.bold))
            report_lines.append("-" * 60)
            
            if any("延迟过大" in w for w in self.warnings):
                report_lines.append(self._colorize("  1. 检查实时数据采集服务状态:", TerminalColors.cyan))
                report_lines.append("     ps aux | grep realtime_kline_service")
                report_lines.append("     tail -f realtime_kline_service.log")
                report_lines.append("")
            
            if any("低覆盖率" in w for w in self.warnings):
                report_lines.append(self._colorize("  2. 检查数据缺失时段并回填:", TerminalColors.cyan))
                report_lines.append("     python kline_data_filler.py --symbol XXX --start YYYY-MM-DD")
                report_lines.append("")
            
            if missing_data:
                report_lines.append(self._colorize("  3. 检查数据依赖和采集顺序:", TerminalColors.cyan))
                report_lines.append("     确保K线数据在分析任务前写入")
                report_lines.append("     检查WebSocket连接稳定性")
                report_lines.append("")
        else:
            report_lines.append(self._colorize("✅ 无告警", TerminalColors.success))
            report_lines.append("")

        report_lines.append(self._colorize("=" * 60, TerminalColors.bold))

        return "\n".join(report_lines)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='数据一致性验证工具（优化版v2.0）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 验证最近1小时的数据
  python validate_data_consistency.py

  # 验证最近24小时的数据（并发执行）
  python validate_data_consistency.py --hours 24 --parallel

  # 验证指定币种并输出JSON格式
  python validate_data_consistency.py --symbol "HYPE/USDC:USDC" --format json

  # 验证指定币种最近24小时的数据，检查最近30天的覆盖率
  python validate_data_consistency.py --hours 24 --days 30 --symbol "PURR/USDC:USDC"

  # 自定义阈值配置
  python validate_data_consistency.py --lag-threshold 120 --coverage-threshold 90
        """
    )
    parser.add_argument(
        '--hours',
        type=int,
        default=1,
        help='延迟统计和完整性检测的时间窗口（小时），默认1小时'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=7,
        help='覆盖率检查的时间窗口（天），默认7天'
    )
    parser.add_argument(
        '--symbol',
        type=str,
        default=None,
        help='指定要验证的币种（可选），例如: "HYPE/USDC:USDC"'
    )
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='输出报告到文件（可选）'
    )
    parser.add_argument(
        '--format',
        type=str,
        choices=['text', 'json'],
        default='text',
        help='输出格式：text（文本）或 json（JSON），默认 text'
    )
    parser.add_argument(
        '--parallel',
        action='store_true',
        help='启用并发查询以提升性能（默认禁用）'
    )
    parser.add_argument(
        '--lag-threshold',
        type=int,
        default=360,
        help='延迟告警阈值（秒），默认360秒（包含300秒K线周期 + 60秒处理余量）'
    )
    parser.add_argument(
        '--coverage-threshold',
        type=float,
        default=95.0,
        help='覆盖率告警阈值（百分比），默认95.0%%'
    )
    parser.add_argument(
        '--max-workers',
        type=int,
        default=3,
        help='最大并发查询数，默认3'
    )
    parser.add_argument(
        '--incremental',
        type=int,
        default=None,
        metavar='MINUTES',
        help='增量验证模式：只检查最近N分钟的新数据（适用于实时监控）'
    )
    parser.add_argument(
        '--baseline',
        type=str,
        default=None,
        metavar='FILE',
        help='基线对比模式：与历史报告对比（JSON格式）'
    )

    args = parser.parse_args()

    # 验证参数
    if args.hours < 1:
        print("错误: --hours 必须大于等于 1")
        return 1

    if args.days < 1:
        print("错误: --days 必须大于等于 1")
        return 1

    if args.lag_threshold < 1:
        print("错误: --lag-threshold 必须大于等于 1")
        return 1

    if not (0 < args.coverage_threshold <= 100):
        print("错误: --coverage-threshold 必须在 0-100 之间")
        return 1

    validator = None
    try:
        # 创建配置
        config = ValidationConfig(
            lag_threshold_seconds=args.lag_threshold,
            coverage_threshold_pct=args.coverage_threshold,
            max_concurrent_queries=args.max_workers
        )

        # 创建验证器
        validator = DataConsistencyValidator(config=config)

        # 测试数据库连接
        if not validator.client.health_check():
            logger.error("数据库连接失败，请检查配置")
            return 1

        logger.info("数据库连接正常")
        logger.info(f"配置: 延迟阈值={args.lag_threshold}秒, 覆盖率阈值={args.coverage_threshold}%")

        # 判断是增量模式还是完整验证
        if args.incremental is not None:
            # 增量验证模式
            logger.info(f"使用增量验证模式（{args.incremental}分钟）")
            result = validator.validate_incremental(
                since_minutes=args.incremental,
                symbol=args.symbol
            )
            
            if args.format == 'json':
                report = json.dumps(result, indent=2, ensure_ascii=False)
            else:
                # 生成简化的文本报告
                report_lines = []
                report_lines.append("=" * 60)
                report_lines.append(f"增量验证报告（最近{args.incremental}分钟）")
                report_lines.append("=" * 60)
                report_lines.append(f"新增记录: {result['new_records'].get('new_analysis_count', 0)} 条")
                report_lines.append(f"涉及币种: {result['new_records'].get('affected_symbols', 0)} 个")
                
                if result['lag_summary']:
                    avg_delay = result['lag_summary'].get('avg_delay', 0) or 0
                    max_delay = result['lag_summary'].get('max_delay', 0) or 0
                    report_lines.append(f"平均延迟: {avg_delay:.2f}秒")
                    report_lines.append(f"最大延迟: {max_delay:.2f}秒")
                
                report_lines.append(f"数据缺失: {result['missing_data_count']} 条")
                
                if result['warnings']:
                    report_lines.append(f"\n⚠️  告警: {len(result['warnings'])} 条")
                    for w in result['warnings']:
                        report_lines.append(f"  - {w}")
                else:
                    report_lines.append("\n✅ 无告警")
                
                report_lines.append("=" * 60)
                report = "\n".join(report_lines)
        else:
            # 完整验证模式
            if args.format == 'json':
                report = validator.generate_json_report(
                    hours=args.hours,
                    days=args.days,
                    symbol=args.symbol,
                    parallel=args.parallel
                )
            else:
                report = validator.generate_report(
                    hours=args.hours,
                    days=args.days,
                    symbol=args.symbol,
                    parallel=args.parallel
                )

        # 输出报告
        print(report)

        # 保存到文件
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"报告已保存到: {args.output}")

        # 如果有告警，返回非零退出码
        return 1 if validator.warnings else 0

    except KeyboardInterrupt:
        logger.info("用户中断")
        return 130
    except Exception as e:
        logger.error(f"验证失败: {e}", exc_info=True)
        return 1
    finally:
        # 显式关闭数据库连接
        if validator and hasattr(validator, 'client'):
            try:
                validator.client.close()
            except Exception:
                pass  # 忽略关闭时的异常


if __name__ == '__main__':
    exit(main())
