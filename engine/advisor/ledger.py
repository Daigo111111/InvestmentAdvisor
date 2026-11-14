"""交易记录（账本）：在录入的初始持仓之上，按日期依次应用买入/卖出，得到当前份额、成本、分笔记录和已实现收益。

交易格式（holdings["trades"] 中每一项）：
  {"id", "date": "YYYY-MM-DD", "asset": "fund"|"stock", "code", "name",
   "side": "buy"|"sell", "amount": 元(可选), "shares": 份额/股数(可选), "price": 成交净值/价格(可选), "fee": 手续费(可选)}
基金买入通常只知道金额，份额按当天（非交易日顺延）的单位净值折算；股票交易需要价格和股数。
持仓条目的 as_of（录入日期）之前的交易视为已包含在初始持仓中，不重复计算。
"""
from __future__ import annotations

import pandas as pd

from .util import r


def trades_for(trades: list[dict], asset: str, code: str, as_of: str | None) -> list[dict]:
    out = [t for t in trades or [] if t.get("asset") == asset and str(t.get("code")).zfill(6) == code]
    if as_of:
        out = [t for t in out if (t.get("date") or "") >= as_of]
    return sorted(out, key=lambda t: (t.get("date") or "", t.get("id") or ""))


def nav_on(nav: pd.DataFrame, d: str) -> tuple[float, bool]:
    """d 当天或之后第一个公布的单位净值；尚未公布时用最新净值并标记 pending。"""
    i = nav.index.searchsorted(pd.Timestamp(d))
    if i >= len(nav):
        return float(nav["nav"].iloc[-1]), True
    return float(nav["nav"].iloc[i]), False


def _fifo_remove(lots: list[dict], qty: float) -> list[dict]:
    out, remain = [], qty
    for lot in sorted(lots, key=lambda l: l.get("date") or "0000"):
        s = float(lot.get("shares") or 0)
        take = min(s, remain)
        remain -= take
        if s - take > 1e-6:
            out.append({**lot, "shares": s - take})
    return out


def apply_fund_trades(h: dict, trades: list[dict], nav: pd.DataFrame) -> dict:
    """h 为 normalize_holding 之后的持仓（shares/cost_nav/lots）。返回新持仓，附 realized/pending/n_trades。"""
    shares = float(h.get("shares") or 0)
    cost = shares * float(h.get("cost_nav") or 0)
    lots = [dict(l) for l in h.get("lots") or []]
    realized, pending, flows = 0.0, False, []
    for t in trades:
        px = float(t["price"]) if t.get("price") else None
        if px is None:
            px, pend = nav_on(nav, t["date"])
            pending = pending or pend
        fee = float(t.get("fee") or 0)
        if t["side"] == "buy":
            amt = float(t.get("amount") or 0) or float(t.get("shares") or 0) * px
            add = float(t["shares"]) if t.get("shares") else max(0.0, amt - fee) / px
            shares += add
            cost += amt
            lots.append({"date": t["date"], "shares": add})
            flows.append((t["date"], -amt))
        else:
            qty = float(t["shares"]) if t.get("shares") else float(t.get("amount") or 0) / px
            qty = min(qty, shares)
            avg = cost / shares if shares else 0.0
            realized += qty * px - fee - avg * qty
            cost -= avg * qty
            shares -= qty
            lots = _fifo_remove(lots, qty)
            flows.append((t["date"], qty * px - fee))
    out = dict(h, shares=shares, lots=lots, realized=r(realized, 2), pending=pending, n_trades=len(trades), flows=flows)
    out["cost_nav"] = cost / shares if shares > 1e-6 else float(h.get("cost_nav") or 0)
    return out


def apply_stock_trades(item: dict, trades: list[dict]) -> dict:
    shares = float(item.get("shares") or 0)
    cost = shares * float(item.get("cost") or 0)
    realized, flows = 0.0, []
    buy_date = item.get("buy_date")
    for t in trades:
        px, qty, fee = float(t.get("price") or 0), float(t.get("shares") or 0), float(t.get("fee") or 0)
        if not px or not qty:
            continue
        if t["side"] == "buy":
            shares += qty
            cost += qty * px + fee
            buy_date = t["date"]  # 移动止损从最近一次买入起算
            flows.append((t["date"], -(qty * px + fee)))
        else:
            qty = min(qty, shares)
            avg = cost / shares if shares else 0.0
            realized += qty * px - fee - avg * qty
            cost -= avg * qty
            shares -= qty
            flows.append((t["date"], qty * px - fee))
    return dict(item, shares=shares, cost=(cost / shares if shares > 1e-6 else item.get("cost")),
                buy_date=buy_date, realized=r(realized, 2), n_trades=len(trades), flows=flows)


def cash_after_trades(cash: float, cash_as_of: str | None, flows: list[tuple[str, float]]) -> float:
    """可用现金 = 录入的现金 + 录入日（含）之后的买卖资金流（买入为负、卖出为正）。"""
    return cash + sum(f for d, f in flows if not cash_as_of or d >= cash_as_of)


def merge_items(base: list[dict], trades: list[dict], asset: str) -> list[dict]:
    """只通过交易记录新增、没有初始持仓的标的，补一个空的初始持仓。"""
    items = [dict(x, code=str(x["code"]).zfill(6)) for x in base or []]
    have = {x["code"] for x in items}
    for t in trades or []:
        c = str(t.get("code") or "").zfill(6)
        if t.get("asset") == asset and c not in have and t.get("side") == "buy":
            items.append({"code": c, "name": t.get("name") or c, "shares": 0, "cost_nav": None, "cost": None,
                          "lots": [], "as_of": None})
            have.add(c)
    return items
