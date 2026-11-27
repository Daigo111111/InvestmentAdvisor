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
    _throttle()
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


# ---------- 通用行情（A股 / 港股 / 美股指数 / 汇率），供基金估值模型使用 ----------
# 统一用腾讯行情代码：A股/指数 sh000922、港股 hkHSTECH / hk00700、美股指数 usNDX、汇率 whUSDCNY

def kline_code(sym: str) -> str:
    """K线接口的代码：美股需写成 us.NDX，其余与行情代码相同。"""
    return "us." + sym[2:] if sym.startswith("us") and not sym.startswith("us.") else sym


_last_call = [0.0]


def _throttle(gap: float = 0.25) -> None:
    """连续请求之间留间隔，避免触发行情网站的防火墙限流。"""
    import time
    wait = _last_call[0] + gap - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()


@retry(times=2)
def _tx_kline_raw(sym: str, n: int) -> list:
    _throttle()
    k = kline_code(sym)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={k},day,,,{n},qfq"
    d = requests.get(url, headers=UA, timeout=15).json()["data"][k]
    return d.get("qfqday") or d.get("day") or []


def _sina_daily(sym: str) -> pd.Series | None:
    """新浪日线（腾讯被限流时的备用源）。"""
    _throttle()
    if sym.startswith(("sh000", "sz399")):
        df = ak.stock_zh_index_daily(symbol=sym)
    elif sym.startswith(("sh5", "sz1")):
        df = ak.fund_etf_hist_sina(symbol=sym)
    elif sym.startswith(("sh", "sz")):
        df = ak.stock_zh_a_daily(symbol=sym, adjust="qfq")
    elif sym.startswith("hk") and sym[2:].isdigit():
        df = ak.stock_hk_daily(symbol=sym[2:], adjust="qfq")
    elif sym.startswith("hk"):
        df = ak.stock_hk_index_daily_sina(symbol=sym[2:])
    elif sym.startswith("us"):
        df = ak.index_us_stock_sina(symbol="." + sym[2:].lstrip("."))
    else:
        return None
    s = pd.Series(df["close"].astype(float).values, index=pd.to_datetime(df["date"]))
    return s.sort_index().tail(400)


@cached(12 * 3600)
def tx_kline(sym: str, n: int = 320) -> pd.Series:
    """日K收盘价（A股/港股前复权；美股为指数），腾讯优先、新浪备用。index=日期。"""
    rows = []
    try:
        rows = _tx_kline_raw(sym, n)
    except Exception:  # noqa: BLE001 腾讯失败或被限流时用新浪
        rows = []
    if len(rows) >= 30:
        s = pd.Series([float(r[2]) for r in rows], index=pd.to_datetime([r[0] for r in rows]))
    else:
        s = _sina_daily(sym)
        if s is None or len(s) < 30:
            raise ValueError(f"{sym} 日K数据不足")
    return s[~s.index.duplicated(keep="last")].sort_index()


@retry()
def _tx_any(syms: list[str]) -> dict[str, dict]:
    txt = requests.get("https://qt.gtimg.cn/q=" + ",".join(syms), headers=UA, timeout=15).content.decode("gbk", "ignore")
    out = {}
    for line in txt.split(";"):
        if '="' not in line:
            continue
        key = line.split("=", 1)[0].strip().replace("v_", "")
        f = line.split('="', 1)[1].strip('"\n ').split("~")
        if key.startswith("wh"):  # 汇率：f[3] 最新价，f[6] 昨收
            price, prev = num(f[3]), num(f[6]) if len(f) > 6 else None
            pct = (price / prev - 1) * 100 if price and prev else None
            t = f[5] if len(f) > 5 else ""
        else:
            if len(f) < 33:
                continue
            pct, t = num(f[32]), f[30]
        if pct is not None:
            out[key] = {"pct": pct, "date": "".join(ch for ch in t if ch.isdigit())[:8]}
    return out


def quotes_any(syms: list[str]) -> dict[str, dict]:
    """批量实时涨跌幅（%）及行情日期 YYYYMMDD。"""
    syms = list(dict.fromkeys(syms))
    out: dict[str, dict] = {}
    for i in range(0, len(syms), 60):
        out.update(_tx_any(syms[i:i + 60]))
    return out


def holding_symbol(code: str) -> str | None:
    """基金持仓代码 → 行情代码：6 位数字为 A 股，5 位数字为港股；美股个股暂无可靠日K，返回 None。"""
    c = str(code).strip().upper()
    if c.isdigit() and len(c) == 6:
        return market_prefix(c) + c
    if c.isdigit() and len(c) <= 5:
        return "hk" + c.zfill(5)
    return None
