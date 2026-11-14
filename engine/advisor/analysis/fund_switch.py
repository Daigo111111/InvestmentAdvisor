"""换基建议：从强势板块中筛选主题基金，按收益、回撤、费率综合打分。"""
from __future__ import annotations

import pandas as pd

from ..data import fund as fd
from ..util import r, safe
from . import indicators as ind
from .taxonomy import BOARD_KEYWORDS

_EXCLUDE = ("债", "货币", "后端", "QDII", "FOF", "定开", "持有期", "封闭")


def candidates_for_board(board: str, rank: pd.DataFrame, flist: pd.DataFrame, n: int = 3,
                         exclude: set[str] | None = None) -> list[dict]:
    kws = [k for k in BOARD_KEYWORDS.get(board, [board]) if len(k) >= 2 and k.isascii() is False][:4] or [board]
    types = flist.set_index("code")["type"]
    df = rank[rank["name"].map(lambda s: any(k in str(s) for k in kws)).astype(bool)].copy()
    if df.empty:
        return []
    df = df[~df["name"].map(lambda s: any(x in str(s) for x in _EXCLUDE)).astype(bool)]
    df["type"] = df["code"].map(types)
    df = df[df["type"].fillna("").str.contains("股票|混合|指数")]
    df = df.dropna(subset=["r3m", "r6m", "r1y"])
    df = df[(df["r3m"] > 0) & (df["r6m"] > 0) & ~df["code"].isin(exclude or set())]
    if df.empty:
        return []
    # A/C 份额只保留一只（名称去掉末尾 A/C 后去重，保留近1年更高者）
    df["base"] = df["name"].str.replace(r"[A-Z]$", "", regex=True)
    df = df.sort_values("r1y", ascending=False).drop_duplicates("base")
    df["score"] = (0.30 * ind.pct_rank(df["r3m"]) + 0.30 * ind.pct_rank(df["r6m"]) + 0.25 * ind.pct_rank(df["r1y"])
                   + 0.15 * (1 - ind.pct_rank(df["fee"].fillna(df["fee"].median()))))
    top = df.sort_values("score", ascending=False).head(n * 2)
    out = []
    for _, x in top.iterrows():
        nav = safe(lambda c=x["code"]: fd.fund_nav(c), None, f"fund_nav {x['code']}")
        mdd = vol = None
        if nav is not None and len(nav) > 60:
            s = nav["acc_nav"].tail(250)
            mdd, vol = ind.max_drawdown(s), ind.ann_vol(s, 250)
        out.append({"code": x["code"], "name": x["name"], "type": x["type"], "r3m": r(x["r3m"]), "r6m": r(x["r6m"]),
                    "r1y": r(x["r1y"]), "fee": r(x["fee"]), "mdd_1y": r(mdd, 4), "vol_1y": r(vol, 4),
                    "score": r(x["score"] * 100, 1)})
    # 收益相近时回撤更小者优先
    out.sort(key=lambda d: (d["score"] or 0) + 20 * (d["mdd_1y"] or -0.3), reverse=True)
    return out[:n]


def switch_plan(rotation: pd.DataFrame, n_boards: int = 3, exclude: set[str] | None = None) -> list[dict]:
    if rotation.empty:
        return []
    rank = fd.fund_rank_all()
    flist = fd.fund_list()
    plans = []
    picks = rotation[~rotation["overheat"] & (rotation["r60"] > 0) & (rotation["trend"] >= 0)].head(n_boards * 2)
    for board, row in picks.iterrows():
        if len(plans) >= n_boards:
            break
        cands = candidates_for_board(board, rank, flist, exclude=exclude)
        if cands:
            plans.append({"board": board, "score": r(row["score"] * 100, 1), "r20": r(row["r20"], 4),
                          "r60": r(row["r60"], 4), "funds": cands,
                          "why": f"{board} 近20日 {row['r20']:.1%}、近60日 {row['r60']:.1%}，综合强度排名前列"})
    return plans
