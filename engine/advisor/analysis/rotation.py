"""板块轮动评分：动量(5/20/60日) + 趋势 + 资金流 + 新闻热度，输出强弱排名。"""
from __future__ import annotations

import pandas as pd

from ..data import boards as bd
from ..util import log, now_cst, r, safe
from . import indicators as ind


def board_scores(news_heat: dict | None = None, names: list[str] | None = None) -> pd.DataFrame:
    end = now_cst().strftime("%Y%m%d")
    start = (now_cst() - pd.Timedelta(days=200)).strftime("%Y%m%d")
    names = names or bd.board_names()
    rows = []
    for n in names:
        s = safe(lambda n=n: bd.board_hist(n, start, end), None, f"board_hist {n}")
        if s is None or len(s) < 65:
            continue
        rows.append({"board": n, "r5": ind.ret(s, 5), "r20": ind.ret(s, 20), "r60": ind.ret(s, 60),
                     "trend": ind.trend_state(s), "rsi": ind.rsi(s), "vol": ind.ann_vol(s)})
    if not rows:
        log.error("板块历史数据全部获取失败")
        return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("board")
    summ = safe(bd.board_summary, pd.DataFrame(), "board_summary")
    df["today_pct"] = summ["pct"] if not summ.empty else None
    df["inflow"] = summ["inflow"] if not summ.empty else None
    heat = news_heat or {}
    df["news"] = [heat.get(b, {}).get("score", 0.0) for b in df.index]
    df["news_count"] = [heat.get(b, {}).get("count", 0) for b in df.index]
    df["score"] = (0.15 * ind.pct_rank(df["r5"]) + 0.30 * ind.pct_rank(df["r20"]) + 0.25 * ind.pct_rank(df["r60"])
                   + 0.10 * (df["trend"] + 1) / 2 + 0.10 * ind.pct_rank(df["inflow"].astype(float))
                   + 0.10 * ind.pct_rank(df["news"]))
    df["overheat"] = (ind.pct_rank(df["r20"]) > 0.95) & (df["rsi"].fillna(50) > 78)
    df.loc[df["overheat"], "score"] -= 0.08
    df["pct"] = ind.pct_rank(df["score"])
    return df.sort_values("score", ascending=False)


def to_report(df: pd.DataFrame, n: int = 10) -> dict:
    if df.empty:
        return {"top": [], "bottom": [], "all": {}}

    def row(b, x):
        return {"board": b, "score": r(x["score"] * 100, 1), "pct": r(x["pct"], 3), "r5": r(x["r5"], 4), "r20": r(x["r20"], 4),
                "r60": r(x["r60"], 4), "trend": int(x["trend"]), "today_pct": r(x["today_pct"]),
                "inflow": r(x["inflow"]), "news": r(x["news"], 1), "overheat": bool(x["overheat"])}

    rows = [row(b, x) for b, x in df.iterrows()]
    return {"top": rows[:n], "bottom": rows[-n:][::-1], "all": {x["board"]: x for x in rows}}
