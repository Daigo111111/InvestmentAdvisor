from __future__ import annotations

import akshare as ak
import pandas as pd

from ..util import cached, num, retry


@cached(10 * 60)
@retry()
def board_summary() -> pd.DataFrame:
    """同花顺行业板块实时概况（涨跌幅、净流入）。index=板块名。"""
    df = ak.stock_board_industry_summary_ths()
    df = df.rename(columns={"板块": "board", "涨跌幅": "pct", "净流入": "inflow", "上涨家数": "up", "下跌家数": "down",
                            "领涨股": "leader", "领涨股-涨跌幅": "leader_pct"})
    for c in ("pct", "inflow", "up", "down", "leader_pct"):
        df[c] = df[c].map(num)
    return df.set_index("board")[["pct", "inflow", "up", "down", "leader", "leader_pct"]]


@cached(7 * 86400)
@retry()
def board_names() -> list[str]:
    return ak.stock_board_industry_name_ths()["name"].tolist()


@cached(12 * 3600)
@retry()
def board_hist(name: str, start: str, end: str) -> pd.Series:
    df = ak.stock_board_industry_index_ths(symbol=name, start_date=start, end_date=end)
    s = pd.Series(df["收盘价"].astype(float).values, index=pd.to_datetime(df["日期"]))
    return s.sort_index()
