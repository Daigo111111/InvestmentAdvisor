"""基金助手：盘中估值 + 操作建议（卖出/减仓/加仓/不动）+ 赎回费 + 换基提示。"""
from __future__ import annotations

from datetime import date

import pandas as pd

from ..config import RiskSettings
from ..data.fund import fee_rate_for_days
from ..util import r
from . import indicators as ind

DEFAULT_POSITION = {"股票型": 0.92, "指数型": 0.95}


def position_factor(ftype: str) -> float:
    """估算用的股票仓位（季报只披露前十大，按基金类型取典型仓位）。"""
    return next((v for k, v in DEFAULT_POSITION.items() if k in (ftype or "")), 0.88)


def estimate_change(holdings: pd.DataFrame, quotes: pd.DataFrame, ftype: str, today: date | None = None) -> dict:
    """用前十大重仓股实时涨跌估算当日净值涨跌幅(%)。只使用当日的行情（停牌/非交易日的行情不计入）。"""
    if holdings.empty or quotes is None or quotes.empty:
        return {"est_pct": None, "coverage": 0.0, "contrib": []}
    pos = position_factor(ftype)
    day = today.strftime("%Y%m%d") if today else None
    rows, wsum, acc = [], 0.0, 0.0
    for _, h in holdings.iterrows():
        code = str(h["code"]).zfill(6)
        if code not in quotes.index or quotes.loc[code, "pct"] is None:
            continue
        if day and not str(quotes.loc[code, "time"]).startswith(day):
            continue
        pct = float(quotes.loc[code, "pct"])
        w = float(h["weight"])
        wsum += w
        acc += w * pct
        rows.append({"code": code, "name": h["name"], "weight": w, "pct": pct, "contrib": round(w * pct / 100, 3)})
    if wsum == 0:
        return {"est_pct": None, "coverage": 0.0, "contrib": []}
    rows.sort(key=lambda x: abs(x["contrib"]), reverse=True)
    return {"est_pct": round(acc / wsum * pos, 2), "coverage": round(min(1.0, wsum / 100 / pos), 2), "contrib": rows}


def normalize_holding(h: dict, nav: pd.DataFrame) -> dict:
    """补齐份额、成本净值和分笔记录。支持只录入「持有金额+持有收益」的情况。"""
    latest = float(nav["nav"].iloc[-1])
    out = dict(h)
    shares = h.get("shares")
    if not shares and h.get("amount"):
        shares = float(h["amount"]) / latest
    shares = float(shares or 0)
    cost = h.get("cost_nav")
    if not cost and h.get("amount") and h.get("profit") is not None and shares:
        cost = (float(h["amount"]) - float(h["profit"])) / shares
    out["shares"] = shares
    out["cost_nav"] = float(cost or latest)
    lots = h.get("lots") or [{"date": h.get("buy_date"), "shares": shares}]
    out["lots"] = [l for l in lots if float(l.get("shares") or 0) > 0]
    return out


def redeem_cost(lots: list[dict], sell_shares: float, nav: float, fee_table, today: date) -> dict:
    """按先进先出估算赎回费。未知买入日期的份额按持有满一年计并标注。"""
    remain, fee, unknown, min_days = sell_shares, 0.0, False, None
    for lot in sorted(lots, key=lambda l: l.get("date") or "0000"):
        if remain <= 0:
            break
        take = min(remain, float(lot["shares"]))
        if lot.get("date"):
            days = (today - date.fromisoformat(lot["date"])).days
        else:
            days, unknown = 365, True
        min_days = days if min_days is None else min(min_days, days)
        fee += take * nav * fee_rate_for_days(fee_table, days)
        remain -= take
    value = sell_shares * nav
    return {"fee": round(fee, 2), "rate": round(fee / value, 4) if value else 0, "min_days": min_days,
            "date_unknown": unknown}


def advise(ctx: dict, risk: RiskSettings, today: date) -> dict:
    """ctx: code,name,type,category,nav(df),est_pct,holding,fee_table,sector_pct,rank_pct,weight,
    portfolio_dd,cash,total_value。返回建议字典。"""
    nav: pd.DataFrame = ctx["nav"]
    h = ctx["holding"]
    est = ctx.get("est_pct")
    last_nav = float(nav["nav"].iloc[-1])
    cur_nav = last_nav * (1 + (est or 0) / 100)
    acc = nav["acc_nav"].copy()
    if est is not None:
        acc.loc[pd.Timestamp(today)] = float(acc.iloc[-1]) * (1 + est / 100)
    value = h["shares"] * cur_nav
    ret_hold = cur_nav / h["cost_nav"] - 1 if h["cost_nav"] else 0
    first_date = min((l["date"] for l in h["lots"] if l.get("date")), default=None)
    since = acc[acc.index >= pd.Timestamp(first_date)] if first_date else acc.tail(120)
    peak_ret = float(since.max() / since.iloc[0] - 1) if len(since) > 1 else ret_hold
    dd_peak = ind.drawdown_from_peak(since) if len(since) > 1 else 0.0
    trend, rsi = ind.trend_state(acc), ind.rsi(acc)
    mom20, mom60 = ind.ret(acc, 20), ind.ret(acc, 60)
    sector_pct = ctx.get("sector_pct")
    weight = value / ctx["total_value"] if ctx.get("total_value") else 0
    near_dd_limit = ctx.get("portfolio_dd", 0) <= -0.75 * risk.max_drawdown
    days_min = min(((today - date.fromisoformat(l["date"])).days for l in h["lots"] if l.get("date")), default=None)

    action, ratio, reasons, level, rule = "不动", 0.0, [], "中", "hold"
    cat = ctx.get("category", "equity")

    def sell(a: str, rt: float, why: str, lv: str = "中", rl: str = ""):
        nonlocal action, ratio, level, rule
        action, ratio, level, rule = a, rt, lv, rl
        reasons.insert(0, why)

    if cat in ("money", "bond"):
        reasons.append("货币/债券类基金波动小，以长期持有为主")
        if cat == "bond" and dd_peak <= -0.03:
            sell("减仓", 0.3, f"债基从高点回撤 {abs(dd_peak):.1%}，超出正常波动，建议减仓 30% 观察", rl="bond_dd")
    elif ret_hold <= risk.fund_stop_loss * 1.5 and trend <= 0:
        sell("卖出", 1.0, f"持有收益 {ret_hold:.1%} 已远低于止损线 {risk.fund_stop_loss:.0%}，且趋势未企稳", "高", "stop_loss_full")
    elif ret_hold <= risk.fund_stop_loss and trend <= 0:
        sell("减仓", 0.5, f"持有收益 {ret_hold:.1%} 触及止损线 {risk.fund_stop_loss:.0%}，趋势偏弱，先减半控制回撤", "高", "stop_loss_half")
    elif peak_ret >= risk.fund_take_profit * 0.6 and dd_peak <= -risk.trailing_drawdown:
        sell("减仓", 0.33, f"持有期最高收益 {peak_ret:.1%}，已从高点回撤 {abs(dd_peak):.1%}，触发移动止盈，锁定部分利润", rl="trailing_tp")
    elif rsi and rsi > 75 and (est or 0) >= 2.5 and ret_hold > 0.10:
        sell("减仓", 0.2, f"今日估算 +{est:.2f}%，RSI {rsi:.0f} 处于超买区，持有收益 {ret_hold:.1%}，分批止盈 20%", "低", "overbought")
    elif trend == -1 and (mom60 or 0) < -0.08 and (sector_pct is not None and sector_pct < 0.3):
        sell("减仓", 0.3, f"净值空头排列，近60日 {mom60:.1%}，所属板块强度排名靠后，建议减仓并考虑换基", rl="trend_broken")
    elif trend >= 0 and est is not None and est <= risk.dip_buy_threshold and not near_dd_limit \
            and weight < risk.single_fund_cap and float(acc.iloc[-1]) >= (ind.ma(acc, 60) or 0):
        action, ratio, level, rule = "加仓", 0.2 if est <= risk.dip_buy_threshold - 1 else 0.1, "中", "dip_buy"
        reasons.insert(0, f"趋势未破（净值在60日均线上方），今日估算 {est:.2f}%，属于回调买点，可在15:00前小幅加仓")
    if action == "不动":
        reasons.append({1: "净值多头排列，继续持有", 0: "净值震荡，暂无明确信号", -1: "净值偏弱但未触发止损，观察"}[trend])

    if days_min is not None and days_min < 7 and action in ("卖出", "减仓") and level != "高":
        reasons.append(f"最近一笔仅持有 {days_min} 天，7 天内赎回费通常为 1.5%，建议满 7 天后再操作")
        action, ratio, rule = "不动", 0.0, "fee_guard"
    if near_dd_limit and action == "加仓":
        action, ratio, rule = "不动", 0.0, "dd_guard"
        reasons.append("组合回撤接近上限，暂停加仓")
    if action == "加仓" and ctx.get("cash") is not None and ctx["cash"] < value * ratio:
        reasons.append(f"可用现金 {ctx['cash']:.0f} 元不足建议金额，按可用现金执行")

    fee = redeem_cost(h["lots"], h["shares"] * ratio, cur_nav, ctx["fee_table"], today) if action in ("卖出", "减仓") else None
    if fee and fee["date_unknown"]:
        reasons.append("部分份额买入日期未知，赎回费按持有满一年估算")
    switch = cat == "equity" and trend == -1 and (ctx.get("rank_pct") is not None and ctx["rank_pct"] < 0.3)
    if switch:
        reasons.append(f"近3月收益在同类中排名后 {ctx['rank_pct']:.0%}，建议参考「换基建议」")
    return {
        "code": ctx["code"], "name": ctx["name"], "type": ctx.get("type"), "category": cat, "action": action, "rule": rule,
        "ratio": r(ratio, 2),
        "amount": r(value * ratio, 0), "level": level, "reasons": reasons, "switch": bool(switch), "fee": fee,
        "metrics": {"est_pct": est, "est_source": ctx.get("est_source"), "coverage": ctx.get("coverage"),
                    "last_nav": r(last_nav, 4), "est_nav": r(cur_nav, 4), "value": r(value, 2),
                    "nav_date": nav.index[-1].strftime("%Y-%m-%d"), "last_pct": r(float(nav["pct"].iloc[-1])),
                    "ret_hold": r(ret_hold, 4), "peak_ret": r(peak_ret, 4), "dd_peak": r(dd_peak, 4),
                    "trend": trend, "rsi": r(rsi, 1), "mom20": r(mom20, 4), "mom60": r(mom60, 4), "weight": r(weight, 4),
                    "sector": ctx.get("sector"), "sector_pct": r(sector_pct, 2), "rank_pct": r(ctx.get("rank_pct"), 2),
                    "quarter": ctx.get("quarter")},
        "top_holdings": ctx.get("contrib", [])[:10],
    }
