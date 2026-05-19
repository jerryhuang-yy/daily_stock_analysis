# -*- coding: utf-8 -*-
"""
均线简报模块

不依赖 AI 分析，只输出：现价、MA5、MA20 及判断信号。
适用于盘中快速推送，通过 CUSTOM_WEBHOOK_URLS 发送到钉钉等渠道。
"""
import logging
from datetime import datetime
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# 固定关注的大盘指数（代码, 显示名称）
_MAIN_INDICES = [
    ("sh000001", "上证指数"),
    ("sh000300", "沪深300"),
    ("sz399006", "创业板指"),
]


def _judge(price: float, ma5: float, ma20: float) -> Tuple[str, str]:
    """返回 (信号文字, emoji)。"""
    above_ma5 = price >= ma5
    above_ma20 = price >= ma20
    ma5_above_ma20 = ma5 >= ma20

    if above_ma5 and ma5_above_ma20:
        return "多头排列", "🟢"
    if above_ma5 and not ma5_above_ma20:
        return "反弹整理", "🟡"
    if not above_ma5 and ma5_above_ma20:
        return "回调整理", "🟡"
    return "空头排列", "🔴"


def _fmt(price: Optional[float]) -> str:
    if price is None:
        return "N/A"
    if price >= 1000:
        return f"{price:.2f}"
    if price >= 10:
        return f"{price:.3f}"
    return f"{price:.4f}"


def _pct(val: Optional[float]) -> str:
    if val is None:
        return ""
    sign = "+" if val >= 0 else ""
    return f" {sign}{val:.2f}%"


def _fetch_stock_data(fm, stock_code: str) -> dict:
    """
    返回 dict，包含 name/price/change_pct/ma5/ma20，任意字段可能为 None。
    单只股票失败不抛异常。
    """
    result = {"name": stock_code, "price": None, "change_pct": None, "ma5": None, "ma20": None}

    # 实时行情 → 现价、涨跌幅、股票名称
    try:
        quote = fm.get_realtime_quote(stock_code, log_final_failure=False)
        if quote:
            if quote.price:
                result["price"] = quote.price
            if quote.change_pct is not None:
                result["change_pct"] = quote.change_pct
            if getattr(quote, "name", None):
                result["name"] = quote.name
    except Exception as e:
        logger.debug("获取 %s 实时行情失败: %s", stock_code, e)

    # 日线数据 → MA5/MA20，若实时价格缺失则用昨收兜底
    try:
        df, _ = fm.get_daily_data(stock_code, days=30)
        if df is not None and not df.empty:
            row = df.iloc[-1]
            result["ma5"] = row.get("ma5") if hasattr(row, "get") else getattr(row, "ma5", None)
            result["ma20"] = row.get("ma20") if hasattr(row, "get") else getattr(row, "ma20", None)
            if result["price"] is None:
                close = row.get("close") if hasattr(row, "get") else getattr(row, "close", None)
                result["price"] = close
    except Exception as e:
        logger.debug("获取 %s 日线数据失败: %s", stock_code, e)

    return result


def _render_line(label: str, data: dict) -> str:
    price = data["price"]
    ma5 = data["ma5"]
    ma20 = data["ma20"]

    if price is None or ma5 is None or ma20 is None:
        return f"- **{label}** 数据暂缺"

    signal, emoji = _judge(price, ma5, ma20)
    return (
        f"- **{label}** {_fmt(price)}{_pct(data['change_pct'])} "
        f"| MA5:{_fmt(ma5)} MA20:{_fmt(ma20)} "
        f"| {emoji} {signal}"
    )


def run_simple_report(config) -> bool:
    """
    生成均线简报并通过 CUSTOM_WEBHOOK_URLS 推送。

    Returns:
        True 表示至少有一个渠道推送成功。
    """
    from data_provider.base import DataFetcherManager
    from src.notification_sender.custom_webhook_sender import CustomWebhookSender

    now = datetime.now()
    time_label = now.strftime("%m-%d %H:%M")

    fm = DataFetcherManager()

    lines = [f"## 📊 均线简报 {time_label}\n"]

    # --- 大盘指数 ---
    lines.append("**大盘指数**\n")
    for code, display_name in _MAIN_INDICES:
        data = _fetch_stock_data(fm, code)
        lines.append(_render_line(display_name, data))

    lines.append("")

    # --- 自选股 ---
    stock_list = list(config.stock_list or [])
    if stock_list:
        lines.append("**自选股**\n")
        for code in stock_list:
            data = _fetch_stock_data(fm, code)
            name = data["name"]
            label = f"{name}({code})" if name != code else code
            lines.append(_render_line(label, data))

    content = "\n".join(lines)

    sender = CustomWebhookSender(config)
    ok = sender.send_to_custom(content)
    if ok:
        logger.info("均线简报推送成功")
    else:
        logger.warning("均线简报推送失败，请检查 CUSTOM_WEBHOOK_URLS 配置")
    return ok
