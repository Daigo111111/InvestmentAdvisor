"""股票助手：全市场基本面筛选 → 分专区打分 → 技术面与新闻复核 → 推荐清单。"""
from __future__ import annotations

import pandas as pd

from ..data import boards as bd
from ..data import fundamentals as fm
from ..data import market as mk
from ..util import log, now_cst, r, safe
from . import indicators as ind
from .taxonomy import ZONE_BOARDS, ZONE_NAMES, em_industry_to_board


def build_universe() -> pd.DataFrame:
    today = now_cst().date()
    period, months = fm.latest_report_period(today)
    f = fm.fundamentals(period)
    f = f[~f["name"].str.contains("ST|退", na=False)]
    q = mk.quotes(f.index.tolist())
    df = f.join(q[["price", "pct", "pe_ttm", "pb", "mv_yi", "turnover"]], how="inner")
    df["roe_ann"] = df["roe"] * 12 / months
    dps = safe(lambda: fm.dividends_per_share(today), pd.Series(dtype=float), "dividends")
    df["dps"] = dps.reindex(df.index)
    df["div_yield"] = (df["dps"] / df["price"]).where(df["price"] > 0)
    hist = safe(fm.dividend_history, pd.DataFrame(), "dividend_history")
    if not hist.empty:
        df = df.join(hist[["div_times", "div_ratio"]], how="left")
    else:
        df["div_times"], df["div_ratio"] = None, None
    boards = safe(bd.board_names, [], "board_names")
    df["board"] = df["industry"].map(lambda x: em_industry_to_board(str(x), boards))
    df = df[(df["mv_yi"] >= 50) & (df["price"] > 0) & (df["roe_ann"].fillna(0) <= 60)]
    # 排名用截断值，避免一次性收益或低基数造成的极端增速主导打分
    df["np_c"] = df["np_yoy"].clip(-100, 200)
    df["rev_c"] = df["rev_yoy"].clip(-100, 200)
    log.info("选股池 %d 只（报告期 %s）", len(df), period)
    df.attrs["period"] = period
    return df


def _zone_filter(df: pd.DataFrame, zone: str) -> pd.DataFrame:
    if zone == "dividend":
        d = df[(df["div_yield"] >= 0.035) & (df["roe_ann"] >= 8) & (df["mv_yi"] >= 100) & (df["div_ratio"].fillna(0) >= 0.7)
               & (df["div_times"].fillna(0) >= 5) & (df["pe_ttm"] > 0) & (df["np_yoy"] > -30)]
        d = d.assign(fscore=0.45 * ind.pct_rank(d["div_yield"]) + 0.25 * ind.pct_rank(d["div_ratio"])
                     + 0.20 * ind.pct_rank(d["roe_ann"]) + 0.10 * (1 - ind.pct_rank(d["pb"])))
    elif zone == "value":
        d = df[(df["mv_yi"] >= 300) & (df["roe_ann"] >= 12) & (df["pe_ttm"].between(0, 25)) & (df["np_yoy"].between(-10, 300))
               & (df["ocf_ps"] > 0)]
        d = d.assign(fscore=0.35 * ind.pct_rank(d["roe_ann"]) + 0.35 * (1 - ind.pct_rank(d["pe_ttm"]))
                     + 0.15 * ind.pct_rank(d["np_c"]) + 0.15 * ind.pct_rank(d["ocf_ps"]))
    elif zone == "tech":
        d = df[df["board"].isin(ZONE_BOARDS["tech"]) & (df["rev_yoy"] >= 15) & (df["np_yoy"] >= 20) & (df["roe_ann"] >= 6)
               & (df["pe_ttm"].between(0, 120))]
        peg = d["pe_ttm"] / d["np_c"].clip(lower=1)
        d = d.assign(fscore=0.30 * ind.pct_rank(d["np_c"]) + 0.25 * ind.pct_rank(d["rev_c"])
                     + 0.25 * (1 - ind.pct_rank(peg)) + 0.20 * ind.pct_rank(d["gross_margin"]))
    elif zone == "consumer":
        d = df[df["board"].isin(ZONE_BOARDS["consumer"]) & (df["roe_ann"] >= 12) & (df["pe_ttm"].between(0, 45))
               & (df["np_yoy"].between(0, 300))]
        d = d.assign(fscore=0.35 * ind.pct_rank(d["roe_ann"]) + 0.25 * ind.pct_rank(d["gross_margin"])
                     + 0.20 * (1 - ind.pct_rank(d["pe_ttm"])) + 0.20 * ind.pct_rank(d["np_c"]))
    elif zone == "cyclical":
        d = df[df["board"].isin(ZONE_BOARDS["cyclical"]) & (df["roe_ann"] >= 8) & (df["pb"].between(0, 4))
               & (df["np_yoy"] > 0) & (df["mv_yi"] >= 100)]
        d = d.assign(fscore=0.35 * ind.pct_rank(d["np_c"]) + 0.30 * ind.pct_rank(d["roe_ann"])
                     + 0.35 * (1 - ind.pct_rank(d["pb"])))
    else:
        return df.iloc[0:0]
    return d.sort_values("fscore", ascending=False)


def _technicals(code: str) -> dict | None:
    h = safe(lambda: mk.stock_hist(code, 400), None, f"hist {code}")
    if h is None or len(h) < 70:
        return None
    c = h["close"]
    a = ind.atr(h)
    return {"trend": ind.trend_state(c), "r20": ind.ret(c, 20), "r60": ind.ret(c, 60), "rsi": ind.rsi(c),
            "vol": ind.ann_vol(c, 250), "mdd_1y": ind.max_drawdown(c.tail(250)), "atr": a, "close": float(c.iloc[-1]),
            "ma60": ind.ma(c, 60)}


def screen(universe: pd.DataFrame, board_pct: dict[str, float], stock_heat: dict, per_zone: int = 5,
           zones: tuple[str, ...] = ("dividend", "value", "tech", "consumer", "cyclical")) -> dict:
    out: dict[str, list] = {}
    used: set[str] = set()
    for z in zones:
        d = _zone_filter(universe, z)
        d = d[~d.index.isin(used)].head(per_zone * 3)
        picks = []
        for code, x in d.iterrows():
            t = _technicals(code)
            if t is None:
                continue
            tech = 0.5 + 0.25 * t["trend"] + 0.25 * ind.tanh_score(t["r60"], 0.2)
            if z == "dividend":  # 红利低波：波动越低越好
                tech = 0.6 * (1 - min(1.0, (t["vol"] or 0.3) / 0.45)) + 0.4 * tech
            if (t["rsi"] or 50) > 80:
                tech -= 0.2
            heat = stock_heat.get(code, {})
            news = 0.5 + 0.5 * ind.tanh_score(heat.get("score"), 4)
            bscore = board_pct.get(x["board"], 0.5)
            score = 0.55 * x["fscore"] + 0.20 * tech + 0.10 * news + 0.15 * bscore
            picks.append(_pick(code, x, t, score, heat, z))
        picks.sort(key=lambda p: p["score"], reverse=True)
        out[z] = picks[:per_zone]
        used |= {p["code"] for p in out[z]}
    return out


def _pick(code: str, x: pd.Series, t: dict, score: float, heat: dict, zone: str) -> dict:
    stop = t["close"] - 2.5 * t["atr"] if t["atr"] else None
    why = []
    if zone == "dividend":
        why.append(f"股息率 {x['div_yield']:.1%}，历史分红 {int(x['div_times'] or 0)} 次")
    why.append(f"ROE(年化) {x['roe_ann']:.1f}%，净利同比 {x['np_yoy']:.1f}%，PE {x['pe_ttm']:.1f}")
    why.append({1: "股价多头排列", 0: "股价震荡整理", -1: "股价偏弱，宜等企稳分批买"}[t["trend"]])
    if heat.get("titles"):
        why.append("近期新闻：" + "；".join(heat["titles"][:2]))
    entry = "回踩 60 日均线附近分批买入" if t["trend"] >= 0 and t["ma60"] and t["close"] > t["ma60"] * 1.08 else "可分 2~3 批建仓"
    return {"code": code, "name": x["name"], "board": x["board"], "zone": zone, "zone_name": ZONE_NAMES[zone],
            "score": r(score * 100, 1), "price": r(x["price"]), "pe": r(x["pe_ttm"], 1), "pb": r(x["pb"]),
            "roe": r(x["roe_ann"], 1), "np_yoy": r(x["np_yoy"], 1), "div_yield": r(x["div_yield"], 4),
            "mv_yi": r(x["mv_yi"], 0), "trend": t["trend"], "r60": r(t["r60"], 4), "vol": r(t["vol"], 4),
            "mdd_1y": r(t["mdd_1y"], 4), "stop": r(stop), "entry": entry, "reasons": why}


def catalyst_picks(stock_heat: dict, universe: pd.DataFrame, n: int = 5) -> list[dict]:
    """新闻催化专区：近期正面新闻集中、且基本面不差的个股。"""
    rows = []
    for code, h in stock_heat.items():
        if h["score"] < 2 or code not in universe.index:
            continue
        x = universe.loc[code]
        if (x["roe_ann"] or 0) < 5:
            continue
        rows.append((h["score"] * min(3, h["count"]), code, x, h))
    rows.sort(key=lambda t: t[0], reverse=True)
    out = []
    for s, code, x, h in rows[:n * 2]:
        t = _technicals(code)
        if t is None:
            continue
        p = _pick(code, x, t, 0.5 + 0.5 * ind.tanh_score(s, 10), h, "value")
        p.update({"zone": "catalyst", "zone_name": ZONE_NAMES["catalyst"]})
        out.append(p)
    return out[:n]
