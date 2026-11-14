"""持股管理：ATR 移动止损、仓位上限、超买止盈、新闻风险、回调加仓。"""
from __future__ import annotations

import math
from datetime import date

import pandas as pd

from ..config import RiskSettings
from ..util import r
from . import indicators as ind


def advise_stock(h: dict, hist: pd.DataFrame, quote: dict | None, news_score: float, news_items: list,
                 total_value: float, risk: RiskSettings, today: date, board: str = "", board_pct: float | None = None) -> dict:
    close = hist["close"].copy()
    price = float(quote["price"]) if quote and quote.get("price") else float(close.iloc[-1])
    if quote and quote.get("price"):
        close.loc[pd.Timestamp(today)] = price
    shares = float(h.get("shares") or 0)
    cost = float(h.get("cost") or price)
    value = shares * price
    weight = value / total_value if total_value else 0
    ret_hold = price / cost - 1 if cost else 0
    a = ind.atr(hist) or price * 0.03
    since = close[close.index >= pd.Timestamp(h["buy_date"])] if h.get("buy_date") else close.tail(60)
    high = float(since.max()) if len(since) else price
    stop = high - risk.stock_atr_mult * a
    trend, rsi, m20 = ind.trend_state(close), ind.rsi(close), ind.ma(close, 20)

    action, ratio, level, reasons, rule = "持有", 0.0, "中", [], "hold"
    if price < stop and trend == -1:
        action, ratio, level, rule = "卖出", 1.0, "高", "atr_stop_full"
        reasons.append(f"跌破 ATR 移动止损位 {stop:.2f}（高点 {high:.2f} − {risk.stock_atr_mult}×ATR），且趋势转空")
    elif price < stop:
        action, ratio, level, rule = "减仓", 0.5, "高", "atr_stop_half"
        reasons.append(f"跌破 ATR 移动止损位 {stop:.2f}，先减半")
    elif ret_hold <= -0.15 and trend == -1:
        action, ratio, level, rule = "卖出", 1.0, "高", "loss_stop"
        reasons.append(f"亏损 {ret_hold:.1%} 且空头排列，执行止损")
    elif news_score <= -4:
        action, ratio, level, rule = "减仓", 0.3, "高", "bad_news"
        reasons.append(f"近期负面新闻集中（情绪分 {news_score:.1f}），降低风险暴露")
    elif weight > risk.single_stock_cap * 1.2:
        ratio = 1 - risk.single_stock_cap / weight
        action, rule = "减仓", "over_cap"
        reasons.append(f"单只仓位 {weight:.1%} 超过上限 {risk.single_stock_cap:.0%}，减至上限以内")
    elif (rsi or 50) > 80 and ret_hold > 0.30:
        action, ratio, level, rule = "减仓", 0.25, "低", "overbought"
        reasons.append(f"RSI {rsi:.0f} 严重超买，浮盈 {ret_hold:.1%}，分批止盈 25%")
    elif trend == 1 and m20 and abs(price / m20 - 1) <= 0.02 and weight < risk.single_stock_cap * 0.7 and news_score >= 0:
        add_w = min(risk.single_stock_cap - weight, 0.03)
        action, ratio, rule = "加仓", add_w * total_value / value if value else 0, "ma20_add"
        reasons.append(f"多头趋势中回踩 20 日均线 {m20:.2f}，可加仓约 {add_w:.1%} 总资产")
    else:
        reasons.append({1: "趋势向上，继续持有", 0: "震荡整理，持有观察", -1: "趋势偏弱，未破止损位，谨慎持有"}[trend])
    if board and board_pct is not None:
        reasons.append(f"所属板块「{board}」强度分位 {board_pct:.0%}")

    lots_held = int(shares // 100)
    if action == "卖出":
        trade_shares = shares
    elif action == "减仓":
        n = max(1, round(lots_held * ratio)) if lots_held else 0
        trade_shares = n * 100
        if lots_held and n >= lots_held:
            reasons.append("仅持有少量手数，减仓即清仓")
    elif action == "加仓":
        trade_shares = max(1, math.ceil(shares * ratio / 100)) * 100
    else:
        trade_shares = 0
    if h.get("buy_date") == today.isoformat() and action in ("减仓", "卖出"):
        reasons.append("今日买入的股票 T+1 才能卖出")
    return {"code": h["code"], "name": h.get("name", h["code"]), "action": action, "rule": rule, "ratio": r(ratio, 2),
            "shares": int(trade_shares), "amount": r(trade_shares * price, 0), "level": level, "reasons": reasons,
            "news": news_items,
            "metrics": {"price": r(price), "cost": r(cost), "ret_hold": r(ret_hold, 4), "value": r(value, 2),
                        "weight": r(weight, 4), "stop": r(stop), "atr": r(a, 3), "trend": trend, "rsi": r(rsi, 1),
                        "news_score": r(news_score, 1), "board": board}}
