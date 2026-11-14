from __future__ import annotations

from datetime import date

import akshare as ak
import pandas as pd

from ..util import cached, num, retry


def latest_report_period(today: date) -> tuple[str, int]:
    """已过披露截止日的最新报告期，返回 (YYYYMMDD, 该期覆盖月数)。"""
    y = today.year
    candidates = [
        (date(y, 10, 31), f"{y}0930", 9), (date(y, 8, 31), f"{y}0630", 6),
        (date(y, 4, 30), f"{y - 1}1231", 12),
        (date(y - 1, 10, 31), f"{y - 1}0930", 9),
    ]
    for deadline, period, months in candidates:
        if today > deadline:
            # 4/30 后同时可得年报与一季报，优先年报（ROE 口径完整）
            return period, months
    return f"{y - 1}0630", 6


@cached(86400)
@retry()
def fundamentals(period: str) -> pd.DataFrame:
    """业绩报表：ROE、营收/净利同比、毛利率、所处行业。index=code。"""
    df = ak.stock_yjbb_em(date=period)
    df = df.rename(columns={"股票代码": "code", "股票简称": "name", "净资产收益率": "roe",
                            "营业总收入-同比增长": "rev_yoy", "净利润-同比增长": "np_yoy",
                            "销售毛利率": "gross_margin", "每股经营现金流量": "ocf_ps", "每股收益": "eps",
                            "所处行业": "industry"})
    for c in ("roe", "rev_yoy", "np_yoy", "gross_margin", "ocf_ps", "eps"):
        df[c] = df[c].map(num)
    df["code"] = df["code"].astype(str).str.zfill(6)
    return df.drop_duplicates("code").set_index("code")[
        ["name", "industry", "roe", "rev_yoy", "np_yoy", "gross_margin", "ocf_ps", "eps"]]


@cached(86400)
@retry()
def _fhps(period: str) -> pd.DataFrame:
    return ak.stock_fhps_em(date=period)


def dividends_per_share(today: date) -> pd.Series:
    """近一年每股现金分红（上一年年报 + 当年中报），index=code。"""
    total: dict[str, float] = {}
    for period in (f"{today.year - 1}1231", f"{today.year}0630"):
        try:
            df = _fhps(period)
        except Exception:  # noqa: BLE001
            continue
        for code, v in zip(df["代码"].astype(str), df["现金分红-现金分红比例"]):
            per10 = num(v)
            if per10:
                total[code.zfill(6)] = total.get(code.zfill(6), 0.0) + per10 / 10
    return pd.Series(total, dtype=float)


@cached(7 * 86400)
@retry()
def dividend_history() -> pd.DataFrame:
    """历史分红统计：分红次数、上市日期 → 分红稳定度。index=code。"""
    df = ak.stock_history_dividend()
    df = df.rename(columns={"代码": "code", "上市日期": "list_date", "分红次数": "div_times", "年均股息": "avg_div"})
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["list_date"] = pd.to_datetime(df["list_date"], errors="coerce")
    df["div_times"] = df["div_times"].map(num)
    years = ((pd.Timestamp.today() - df["list_date"]).dt.days / 365).clip(lower=1)
    df["div_ratio"] = (df["div_times"] / years).clip(upper=1.5)
    return df.drop_duplicates("code").set_index("code")[["list_date", "div_times", "div_ratio"]]
