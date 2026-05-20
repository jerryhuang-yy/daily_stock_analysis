# -*- coding: utf-8 -*-
"""
轻量级规则告警引擎

不调用 LLM 和情报搜索，仅基于技术指标触发提醒。
支持四类条件：均线排列、价格突破MA5、涨跌幅阈值、量比异常。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from src.stock_analyzer import TrendAnalysisResult, TrendStatus

logger = logging.getLogger(__name__)


@dataclass
class AlertCondition:
    name: str
    triggered: bool
    message: str


@dataclass
class AlertCheckResult:
    code: str
    name: str
    price: float
    change_pct: Optional[float]
    conditions: List[AlertCondition] = field(default_factory=list)

    @property
    def triggered_conditions(self) -> List[AlertCondition]:
        return [c for c in self.conditions if c.triggered]

    @property
    def has_alerts(self) -> bool:
        return any(c.triggered for c in self.conditions)


class AlertEngine:
    """基于规则的技术面告警引擎"""

    def __init__(
        self,
        change_pct_threshold: float = 5.0,
        volume_ratio_threshold: float = 2.0,
        check_ma_alignment: bool = True,
        check_price_vs_ma5: bool = True,
    ):
        self.change_pct_threshold = change_pct_threshold
        self.volume_ratio_threshold = volume_ratio_threshold
        self.check_ma_alignment = check_ma_alignment
        self.check_price_vs_ma5 = check_price_vs_ma5

    def check(
        self,
        code: str,
        stock_name: str,
        realtime_quote,
        trend_result: Optional[TrendAnalysisResult],
        prev_close: Optional[float] = None,
    ) -> AlertCheckResult:
        """
        检查所有告警条件。

        Args:
            prev_close: 前一交易日收盘价，用于判断价格是否穿越 MA5。
        """
        price = 0.0
        if realtime_quote and getattr(realtime_quote, 'price', None):
            price = float(realtime_quote.price)
        elif trend_result and trend_result.current_price:
            price = float(trend_result.current_price)

        change_pct = getattr(realtime_quote, 'change_pct', None) if realtime_quote else None
        volume_ratio = getattr(realtime_quote, 'volume_ratio', None) if realtime_quote else None

        result = AlertCheckResult(
            code=code,
            name=stock_name,
            price=price,
            change_pct=change_pct,
        )

        # 条件1：MA 排列（多头/空头触发）
        if self.check_ma_alignment and trend_result:
            is_bull = trend_result.trend_status in (TrendStatus.BULL, TrendStatus.STRONG_BULL)
            is_bear = trend_result.trend_status in (TrendStatus.BEAR, TrendStatus.STRONG_BEAR)
            triggered = is_bull or is_bear
            if is_bull:
                msg = f"多头排列 — {trend_result.ma_alignment}"
            elif is_bear:
                msg = f"空头排列 — {trend_result.ma_alignment}"
            else:
                msg = trend_result.ma_alignment or trend_result.trend_status.value
            result.conditions.append(AlertCondition("MA排列", triggered, msg))

        # 条件2：价格突破 MA5（判断穿越事件）
        if self.check_price_vs_ma5 and trend_result and trend_result.ma5 > 0 and price > 0:
            ma5 = trend_result.ma5
            crossed_up = prev_close is not None and prev_close < ma5 and price >= ma5
            crossed_down = prev_close is not None and prev_close > ma5 and price < ma5
            triggered = crossed_up or crossed_down
            if crossed_up:
                msg = f"价格上穿 MA5({ma5:.2f})，偏离 {trend_result.bias_ma5:+.2f}%"
            elif crossed_down:
                msg = f"价格下穿 MA5({ma5:.2f})，偏离 {trend_result.bias_ma5:+.2f}%"
            else:
                direction = "上方" if price >= ma5 else "下方"
                msg = f"价格在 MA5({ma5:.2f}) {direction}，偏离 {trend_result.bias_ma5:+.2f}%"
            result.conditions.append(AlertCondition("价格突破MA5", triggered, msg))

        # 条件3：涨跌幅阈值
        if change_pct is not None:
            triggered = abs(change_pct) >= self.change_pct_threshold
            sign = "+" if change_pct >= 0 else ""
            msg = f"今日 {sign}{change_pct:.2f}%（阈值 ±{self.change_pct_threshold}%）"
            result.conditions.append(AlertCondition("涨跌幅", triggered, msg))

        # 条件4：量比异常
        if volume_ratio is not None:
            triggered = volume_ratio >= self.volume_ratio_threshold
            msg = f"量比 {volume_ratio:.2f}（阈值 {self.volume_ratio_threshold}）"
            result.conditions.append(AlertCondition("量比", triggered, msg))

        return result

    def format_stock_block(self, result: AlertCheckResult) -> str:
        """格式化单只股票的告警内容块"""
        sign = "+" if (result.change_pct or 0) >= 0 else ""
        change_str = f"{sign}{result.change_pct:.2f}%" if result.change_pct is not None else "N/A"
        lines = [f"**{result.name}（{result.code}）** 现价 {result.price:.2f}  {change_str}"]
        for cond in result.conditions:
            prefix = "🔔" if cond.triggered else "·"
            lines.append(f"  {prefix} {cond.name}：{cond.message}")
        return "\n".join(lines)
