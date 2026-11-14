"""建议效果追踪：记录每条操作建议，之后用真实行情计算 5 / 20 个交易日的涨跌，统计每条规则的胜率；
并与交易记录对照，比较「照做」与「没照做」的效果。只做统计，不自动修改策略。"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..data import fund as fd
from ..data import market as mk
from ..util import r, safe

RULE_NAMES = {
    "stop_loss_full": "基金·止损清仓", "stop_loss_half": "基金·止损减半", "trailing_tp": "基金·移动止盈",
    "overbought": "超买分批止盈", "trend_broken": "基金·趋势破位减仓", "dip_buy": "基金·回调加仓",
    "bond_dd": "债基·回撤减仓", "atr_stop_full": "股票·ATR止损清仓", "atr_stop_half": "股票·ATR止损减半",
    "loss_stop": "股票·亏损止损", "bad_news": "股票·负面新闻减仓", "over_cap": "股票·超仓位上限减仓",
    "ma20_add": "股票·回踩加仓",
    "zone_dividend": "专区·红利低波", "zone_value": "专区·价值蓝筹", "zone_tech": "专区·科技成长",
    "zone_consumer": "专区·消费医药", "zone_cyclical": "专区·周期资源", "zone_catalyst": "专区·新闻催化",
}
SELL = ("卖出", "减仓")
BUY = ("加仓", "推荐")
HORIZONS = (5, 20)
KEEP_DAYS = 200


def _add(state: dict, sig: dict) -> None:
    sigs = state.setdefault("signals", [])
    if not any(s["id"] == sig["id"] for s in sigs):
        sigs.append(sig)


def record_advice(state: dict, rep: dict, day: str) -> None:
    for asset, key, idle in (("fund", "funds", "不动"), ("stock", "stocks", "持有")):
        for a in rep.get(key, []):
            if a.get("action") in (idle, None) or not a.get("rule"):
                continue
            _add(state, {"id": f"{day}:{asset}:{a['code']}:{a['rule']}", "date": day, "asset": asset,
                         "code": a["code"], "name": a["name"], "action": a["action"], "rule": a["rule"],
                         "ratio": a.get("ratio")})


def record_picks(state: dict, rep: dict, day: str, top: int = 3) -> None:
    for z, picks in (rep.get("zones") or {}).items():
        for p in (picks or [])[:top]:
            _add(state, {"id": f"{day}:pick:{p['code']}:zone_{z}", "date": day, "asset": "stock", "code": p["code"],
                         "name": p["name"], "action": "推荐", "rule": f"zone_{z}", "ratio": None})


def _series(asset: str, code: str) -> pd.Series | None:
    if asset == "fund":
        nav = safe(lambda: fd.fund_nav(code), None, f"nav {code}")
        return None if nav is None else nav["acc_nav"]
    h = safe(lambda: mk.stock_hist(code, 400), None, f"hist {code}")
    return None if h is None else h["close"]


def _fwd(s: pd.Series, d: str, n: int) -> float | None:
    i = s.index.searchsorted(pd.Timestamp(d))
    if i + n >= len(s):
        return None
    return float(s.iloc[i + n] / s.iloc[i] - 1)


def evaluate(state: dict, today: date) -> None:
    sigs = state.get("signals", [])
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    sigs[:] = [s for s in sigs if s["date"] >= cutoff][-600:]
    pending = [s for s in sigs if s.get("r20") is None and s["date"] < today.isoformat()]
    if not pending:
        return
    bench = safe(lambda: mk.index_hist("sh000300"), None, "hs300")
    cache: dict[tuple[str, str], pd.Series | None] = {}
    for s in pending:
        k = (s["asset"], s["code"])
        if k not in cache:
            cache[k] = _series(*k)
        ser = cache[k]
        if ser is None or ser.empty:
            continue
        for n in HORIZONS:
            if s.get(f"r{n}") is None:
                v = _fwd(ser, s["date"], n)
                s[f"r{n}"] = r(v, 4)
                if v is not None and bench is not None:
                    b = _fwd(bench, s["date"], n)
                    s[f"ex{n}"] = r(v - b, 4) if b is not None else None


def _effect(s: dict, n: int) -> float | None:
    """建议的「效果」：买入类看涨幅（推荐看相对沪深300的超额），卖出类看之后少亏/少赚了多少（下跌为正）。"""
    v = s.get(f"ex{n}") if s["action"] == "推荐" else s.get(f"r{n}")
    if v is None:
        return None
    return -v if s["action"] in SELL else v


def _followed(s: dict, trades: list[dict]) -> bool:
    side = "sell" if s["action"] in SELL else "buy"
    d0 = date.fromisoformat(s["date"])
    for t in trades:
        if str(t.get("code")).zfill(6) != s["code"] or t.get("side") != side or not t.get("date"):
            continue
        if 0 <= (date.fromisoformat(t["date"]) - d0).days <= 3:
            return True
    return False


def _summary(rows: list[dict], n: int) -> dict:
    eff = [e for e in (_effect(s, n) for s in rows) if e is not None]
    return {"n": len(eff), "win": r(sum(e > 0 for e in eff) / len(eff), 3) if eff else None,
            "avg": r(sum(eff) / len(eff), 4) if eff else None}


def report(state: dict, trades: list[dict]) -> dict:
    sigs = state.get("signals", [])
    by_rule: dict[str, list[dict]] = {}
    for s in sigs:
        by_rule.setdefault(s["rule"], []).append(s)
    rules = []
    for rule, rows in by_rule.items():
        s5, s20 = _summary(rows, 5), _summary(rows, 20)
        rules.append({"rule": rule, "name": RULE_NAMES.get(rule, rule), "action": rows[0]["action"], "count": len(rows),
                      "n5": s5["n"], "win5": s5["win"], "avg5": s5["avg"],
                      "n20": s20["n"], "win20": s20["win"], "avg20": s20["avg"]})
    rules.sort(key=lambda x: -x["count"])
    actionable = [s for s in sigs if s["action"] != "推荐"]
    yes = [s for s in actionable if _followed(s, trades)]
    no = [s for s in actionable if not _followed(s, trades)]
    recent = sorted(sigs, key=lambda s: s["date"], reverse=True)[:30]
    return {
        "rules": rules,
        "follow": {"total": len(actionable), "followed": len(yes),
                   "yes5": _summary(yes, 5), "no5": _summary(no, 5), "yes20": _summary(yes, 20), "no20": _summary(no, 20)},
        "recent": [{**s, "rule_name": RULE_NAMES.get(s["rule"], s["rule"]), "followed": _followed(s, trades)
                    if s["action"] != "推荐" else None} for s in recent],
        "note": "效果：买入类建议看之后的涨幅（专区推荐看相对沪深300的超额收益），卖出类建议看之后的跌幅（跌得越多说明卖得越对）。"
                "「照做」指建议后 3 天内有同方向的交易记录。样本少于 20 条时胜率参考意义有限。",
    }
