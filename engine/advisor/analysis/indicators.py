from __future__ import annotations

import math

import numpy as np
import pandas as pd


def ret(s: pd.Series, n: int) -> float | None:
    s = s.dropna()
    if len(s) <= n:
        return None
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1)


def ma(s: pd.Series, n: int) -> float | None:
    s = s.dropna()
    return float(s.tail(n).mean()) if len(s) >= n else None


def trend_state(s: pd.Series) -> int:
    """+1 多头排列(价>MA20>MA60)，-1 空头排列，0 震荡。"""
    p, m20, m60 = (float(s.dropna().iloc[-1]) if len(s.dropna()) else None), ma(s, 20), ma(s, 60)
    if p is None or m20 is None or m60 is None:
        return 0
    if p > m20 > m60:
        return 1
    if p < m20 < m60:
        return -1
    return 0


def rsi(s: pd.Series, n: int = 14) -> float | None:
    d = s.dropna().diff().dropna()
    if len(d) < n:
        return None
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    if dn == 0:
        return 100.0
    return float(100 - 100 / (1 + up / dn))


def ann_vol(s: pd.Series, n: int = 60) -> float | None:
    r = s.dropna().pct_change().dropna().tail(n)
    return float(r.std() * math.sqrt(252)) if len(r) >= 10 else None


def max_drawdown(s: pd.Series) -> float:
    s = s.dropna()
    if s.empty:
        return 0.0
    return float((s / s.cummax() - 1).min())


def drawdown_from_peak(s: pd.Series) -> float:
    s = s.dropna()
    return float(s.iloc[-1] / s.max() - 1) if len(s) else 0.0


def atr(df: pd.DataFrame, n: int = 14) -> float | None:
    if len(df) < n + 1:
        return None
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return float(tr.tail(n).mean())


def cagr(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) < 2:
        return 0.0
    years = (s.index[-1] - s.index[0]).days / 365.25
    return float((s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1) if years > 0 else 0.0


def sharpe(s: pd.Series, rf: float = 0.015) -> float:
    r = s.dropna().pct_change().dropna()
    if r.std() == 0 or r.empty:
        return 0.0
    return float((r.mean() * 252 - rf) / (r.std() * math.sqrt(252)))


def pct_rank(values: pd.Series) -> pd.Series:
    """横截面百分位(0~1)，越大越好；缺失值记 0.5。"""
    return values.rank(pct=True).fillna(0.5)


def tanh_score(x: float | None, scale: float) -> float:
    return 0.0 if x is None or (isinstance(x, float) and np.isnan(x)) else float(np.tanh(x / scale))
