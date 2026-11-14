from __future__ import annotations

import re

import akshare as ak
import pandas as pd

from ..util import cached, num, now_cst, retry


@cached(7 * 86400)
@retry()
def fund_list() -> pd.DataFrame:
    df = ak.fund_name_em()
    df = df.rename(columns={"基金代码": "code", "基金简称": "name", "基金类型": "type"})
    return df[["code", "name", "type"]]


def fund_basic(code: str) -> dict:
    df = fund_list()
    row = df[df["code"] == code]
    if row.empty:
        return {"code": code, "name": code, "type": "未知"}
    r0 = row.iloc[0]
    return {"code": code, "name": r0["name"], "type": r0["type"]}


def fund_category(ftype: str) -> str:
    """把东财基金类型归为：equity / bond / money / qdii / fof / other。"""
    t = ftype or ""
    if "QDII" in t or "海外" in t:
        return "qdii"
    if "货币" in t:
        return "money"
    if t.startswith("债券") or ("债" in t and "混合" not in t):
        return "bond"
    if "FOF" in t:
        return "fof"
    if any(k in t for k in ("股票", "混合", "指数")):
        return "equity"
    return "other"


@cached(12 * 3600)
@retry()
def _holdings_year(code: str, year: str) -> pd.DataFrame:
    return ak.fund_portfolio_hold_em(symbol=code, date=year)


def fund_holdings(code: str) -> tuple[pd.DataFrame, str]:
    """最新一期季报的股票持仓（通常前十大）。返回 (df[code,name,weight], 季度)。"""
    y = now_cst().year
    for year in (str(y), str(y - 1)):
        try:
            df = _holdings_year(code, year)
        except Exception:  # noqa: BLE001 新基金/债基可能没有股票持仓
            continue
        if df is None or df.empty:
            continue
        quarters = sorted(df["季度"].unique(), key=_quarter_key)
        latest = quarters[-1]
        d = df[df["季度"] == latest].copy()
        d = d.rename(columns={"股票代码": "code", "股票名称": "name", "占净值比例": "weight"})
        d["weight"] = d["weight"].map(lambda v: num(v, 0.0))
        d = d.sort_values("weight", ascending=False).head(10)
        return d[["code", "name", "weight"]].reset_index(drop=True), latest
    return pd.DataFrame(columns=["code", "name", "weight"]), ""


def _quarter_key(q: str) -> tuple[int, int]:
    m = re.search(r"(\d{4})年(\d)季度", q)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


@cached(3 * 3600)
@retry()
def fund_nav(code: str) -> pd.DataFrame:
    """单位净值与累计净值。index=日期，列 nav / acc_nav / pct。"""
    unit = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
    unit = unit.rename(columns={"净值日期": "date", "单位净值": "nav", "日增长率": "pct"})
    unit["date"] = pd.to_datetime(unit["date"])
    unit = unit.set_index("date")[["nav", "pct"]].astype(float)
    try:
        acc = ak.fund_open_fund_info_em(symbol=code, indicator="累计净值走势")
        acc = acc.rename(columns={"净值日期": "date", "累计净值": "acc_nav"})
        acc["date"] = pd.to_datetime(acc["date"])
        unit = unit.join(acc.set_index("date")["acc_nav"].astype(float), how="left")
    except Exception:  # noqa: BLE001
        unit["acc_nav"] = unit["nav"]
    unit["acc_nav"] = unit["acc_nav"].fillna(unit["nav"])
    return unit.sort_index()


@cached(10 * 60)
@retry()
def fund_estimation_all() -> pd.DataFrame:
    """东财盘中估值（覆盖部分基金）。返回 index=code，列 est_pct。"""
    df = ak.fund_value_estimation_em(symbol="全部")
    col = next(c for c in df.columns if "估算增长率" in c)
    out = pd.DataFrame({"code": df["基金代码"].astype(str), "est_pct": df[col].map(num)})
    return out.dropna().set_index("code")


@cached(7 * 86400)
@retry()
def _fee_raw(code: str) -> pd.DataFrame:
    return ak.fund_fee_em(symbol=code, indicator="赎回费率")


def _to_days(n: float, unit: str) -> float:
    return n * {"天": 1, "日": 1, "月": 30, "年": 365}.get(unit, 1)


def parse_fee_period(text: str) -> tuple[float, float]:
    """把 '大于等于7天，小于等于29天' 解析为 [lo, hi) 天数区间。"""
    lo, hi = 0.0, float("inf")
    for op, n, unit in re.findall(r"(大于等于|大于|小于等于|小于)\s*(\d+(?:\.\d+)?)\s*(天|日|个月|月|年)", text):
        d = _to_days(float(n), unit.replace("个", ""))
        if op == "大于等于":
            lo = d
        elif op == "大于":
            lo = d + (1 if unit in ("天", "日") else 0)
        elif op == "小于等于":
            hi = d + 1 if unit in ("天", "日") else d
        else:
            hi = d
    return lo, hi


def redeem_fee_table(code: str) -> list[tuple[float, float, float]]:
    """[(最少天数, 最多天数(不含), 费率小数)]，失败时返回通用默认值。"""
    default = [(0, 7, 0.015), (7, 365, 0.005), (365, 730, 0.0025), (730, float("inf"), 0.0)]
    try:
        df = _fee_raw(code)
    except Exception:  # noqa: BLE001
        return default
    rows = []
    for _, row in df.iterrows():
        lo, hi = parse_fee_period(str(row.iloc[0]))
        rate = num(row.iloc[1], 0.0) / 100
        rows.append((lo, hi, rate))
    return rows or default


def fee_rate_for_days(table: list[tuple[float, float, float]], days: int) -> float:
    for lo, hi, rate in table:
        if lo <= days < hi:
            return rate
    return table[-1][2] if table else 0.0


@cached(12 * 3600)
@retry()
def fund_rank_all() -> pd.DataFrame:
    df = ak.fund_open_fund_rank_em(symbol="全部")
    df = df.rename(columns={"基金代码": "code", "基金简称": "name", "近1月": "r1m", "近3月": "r3m",
                            "近6月": "r6m", "近1年": "r1y", "近2年": "r2y", "今年来": "ytd", "手续费": "fee"})
    for c in ("r1m", "r3m", "r6m", "r1y", "r2y", "ytd", "fee"):
        df[c] = df[c].map(num)
    return df[["code", "name", "r1m", "r3m", "r6m", "r1y", "r2y", "ytd", "fee"]]
