from __future__ import annotations

from datetime import date, datetime

import akshare as ak
import pandas as pd
import requests

from ..util import cached, num, retry

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def market_prefix(code: str) -> str:
    c = str(code).zfill(6)
    if c[0] in "69" or c[:2] in ("50", "51", "56", "58", "11"):
        return "sh"
    if c[0] in "48":
        return "bj"
    return "sz"


@cached(7 * 86400)
@retry()
def trade_dates() -> list[str]:
    df = ak.tool_trade_date_hist_sina()
    return [pd.Timestamp(d).strftime("%Y-%m-%d") for d in df["trade_date"]]


def is_trade_day(d: date | datetime | str) -> bool:
    s = d if isinstance(d, str) else d.strftime("%Y-%m-%d")
    return s in set(trade_dates())


def prev_trade_day(d: str) -> str:
    days = [x for x in trade_dates() if x < d]
    return days[-1]


@retry()
def _tencent_batch(codes: list[str]) -> list[dict]:
    q = ",".join(market_prefix(c) + str(c).zfill(6) for c in codes)
    txt = requests.get(f"https://qt.gtimg.cn/q={q}", headers=UA, timeout=15).content.decode("gbk", "ignore")
    rows = []
    for line in txt.split(";"):
        if "~" not in line:
            continue
        f = line.split("=", 1)[1].strip('"\n ').split("~")
        if len(f) < 50:
            continue
        rows.append({
            "code": f[2], "name": f[1], "price": num(f[3]), "prev_close": num(f[4]), "open": num(f[5]),
            "pct": num(f[32]), "high": num(f[33]), "low": num(f[34]), "amount_wan": num(f[37]),
            "turnover": num(f[38]), "pe_ttm": num(f[39]), "float_mv_yi": num(f[44]), "mv_yi": num(f[45]),
            "pb": num(f[46]), "time": f[30],
        })
    return rows


def quotes(codes: list[str], batch: int = 60) -> pd.DataFrame:
    """腾讯行情接口批量拉取实时报价（含 PE/PB/市值）。"""
    codes = list(dict.fromkeys(str(c).zfill(6) for c in codes if c))
    rows: list[dict] = []
    for i in range(0, len(codes), batch):
        rows += _tencent_batch(codes[i:i + batch])
    df = pd.DataFrame(rows)
    return df.set_index("code") if not df.empty else df


@cached(86400)
@retry()
def stock_names() -> dict[str, str]:
    df = ak.stock_info_a_code_name()
    return {str(c).zfill(6): str(n).replace(" ", "") for c, n in zip(df["code"], df["name"])}


@cached(6 * 3600)
@retry()
def _stock_hist_tx(code: str, start: str) -> pd.DataFrame:
    sym = market_prefix(code) + code
    s = f"{start[:4]}-{start[4:6]}-{start[6:]}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,{s},,640,qfq"
    d = requests.get(url, headers=UA, timeout=15).json()["data"][sym]
    k = d.get("qfqday") or d.get("day") or []
    df = pd.DataFrame([row[:6] for row in k], columns=["date", "open", "close", "high", "low", "volume"])
    if df.empty:
        raise ValueError(f"腾讯K线无数据 {code}")
    return df[["date", "open", "high", "low", "close", "volume"]]


@cached(6 * 3600)
@retry()
def _stock_hist_em(code: str, start: str) -> pd.DataFrame:
    df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, adjust="qfq")
    df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"})
    return df[["date", "open", "high", "low", "close", "volume"]]


@cached(6 * 3600)
@retry()
def _stock_hist_sina(code: str, start: str) -> pd.DataFrame:
    df = ak.stock_zh_a_daily(symbol=market_prefix(code) + code, start_date=start, adjust="qfq")
    return df[["date", "open", "high", "low", "close", "volume"]]


def stock_hist(code: str, days: int = 400) -> pd.DataFrame:
    """前复权日线：腾讯 → 东财 → 新浪 依次回退。"""
    start = (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%Y%m%d")
    code = str(code).zfill(6)
    df = None
    for src in (_stock_hist_tx, _stock_hist_em, _stock_hist_sina):
        try:
            df = src(code, start)
            break
        except Exception:  # noqa: BLE001 换下一个数据源
            continue
    if df is None:
        raise ConnectionError(f"{code} 日线全部数据源失败")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").astype(float)


@cached(6 * 3600)
@retry()
def index_hist(symbol: str) -> pd.Series:
    """指数日线收盘价，symbol 如 sh000300。"""
    df = ak.stock_zh_index_daily(symbol=symbol)
    s = pd.Series(df["close"].astype(float).values, index=pd.to_datetime(df["date"]))
    return s.sort_index()


@cached(12 * 3600)
@retry()
def csindex_hist(symbol: str, start: str = "20140101") -> pd.Series:
    """中证指数官网日线，支持全收益指数（如 H00922 中证红利全收益、H00300 沪深300全收益）。"""
    end = pd.Timestamp.today().strftime("%Y%m%d")
    df = ak.stock_zh_index_hist_csindex(symbol=symbol, start_date=start, end_date=end)
    s = pd.Series(df["收盘"].astype(float).values, index=pd.to_datetime(df["日期"]))
    return s.sort_index()


def index_quotes(symbols: list[str]) -> pd.DataFrame:
    """指数实时行情（腾讯接口，symbol 带前缀）。"""
    q = ",".join(symbols)
    txt = requests.get(f"https://qt.gtimg.cn/q={q}", headers=UA, timeout=15).content.decode("gbk", "ignore")
    rows = []
    for line in txt.split(";"):
        if "~" in line:
            f = line.split("=", 1)[1].strip('"\n ').split("~")
            rows.append({"symbol": line.split("=")[0].strip().replace("v_", ""), "name": f[1], "price": num(f[3]), "pct": num(f[32])})
    return pd.DataFrame(rows)
