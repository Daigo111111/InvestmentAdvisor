"""回测：用历史数据检验规则，给出年化、最大回撤、夏普、逐年收益，作为建议可信度的依据。"""
from __future__ import annotations

import pandas as pd

from ..config import RiskSettings
from ..data import market as mk
from ..util import r
from . import indicators as ind
from .allocation import BRAKE_DD, EQUITY_BY_REGIME, regime_from_series

EQ_SPLIT = {"dividend": 0.45, "hs300": 0.30, "growth": 0.25}


def _prices() -> pd.DataFrame:
    return pd.DataFrame({"dividend": mk.csindex_hist("H00922"), "hs300": mk.csindex_hist("H00300"),
                         "growth": mk.index_hist("sz399006"), "bond": mk.index_hist("sh000012")}).dropna()


def _metrics(nav: pd.Series, risk: RiskSettings) -> dict:
    yearly = nav.resample("YE").last().pct_change().dropna()
    first_year = nav.resample("YE").last().iloc[0] / nav.iloc[0] - 1
    yearly = pd.concat([pd.Series([first_year], index=[nav.resample("YE").last().index[0]]), yearly])
    return {"cagr": r(ind.cagr(nav), 4), "mdd": r(ind.max_drawdown(nav), 4), "sharpe": r(ind.sharpe(nav), 2),
            "vol": r(ind.ann_vol(nav, len(nav)), 4),
            "years": {str(k.year): r(v, 4) for k, v in yearly.items()},
            "hit_min": r(float((yearly >= risk.min_return).mean()), 2),
            "hit_target": r(float((yearly >= risk.target_return).mean()), 2)}


def allocation_backtest(risk: RiskSettings, start: str = "2015-01-01") -> dict:
    """与实盘配置规则一致：沪深300 相对 60 日线判断市场状态，周度调仓；组合回撤超阈值时权益减半。"""
    px = _prices()
    px = px[px.index >= pd.Timestamp(start) - pd.Timedelta(days=200)]
    rets = px.pct_change().fillna(0)
    weights = None
    nav, peak, navs = 1.0, 1.0, []
    brake = BRAKE_DD * risk.max_drawdown / 0.20
    for i, d in enumerate(px.index):
        if d < pd.Timestamp(start):
            continue
        if weights is not None:
            nav *= 1 + float((rets.loc[d] * weights).sum())
        peak = max(peak, nav)
        navs.append((d, nav))
        week_end = i + 1 < len(px) and px.index[i + 1].weekday() < d.weekday()
        if weights is None or week_end:  # 周末收盘调仓，下一交易日起生效，避免未来函数
            reg = regime_from_series(px["hs300"].iloc[: i + 1])
            eq = min(0.9, EQUITY_BY_REGIME[reg] * risk.max_drawdown / 0.20)
            if nav / peak - 1 <= -brake:
                eq *= 0.5
            weights = pd.Series({k: eq * v for k, v in EQ_SPLIT.items()} | {"bond": 1 - eq})
    strat = pd.Series(dict(navs))
    bench = px["hs300"][px.index >= pd.Timestamp(start)]
    bench = bench / bench.iloc[0]
    b6040 = (1 + (rets[px.index >= pd.Timestamp(start)][["hs300", "bond"]] * [0.6, 0.4]).sum(axis=1)).cumprod()
    step = max(1, len(strat) // 300)
    return {
        "name": "市场状态择时 + 红利/沪深300/创业板/国债 周度再平衡 + 回撤刹车",
        "start": strat.index[0].strftime("%Y-%m-%d"), "end": strat.index[-1].strftime("%Y-%m-%d"),
        "strategy": _metrics(strat, risk), "hs300": _metrics(bench, risk), "mix6040": _metrics(b6040, risk),
        "curve": [{"d": d.strftime("%Y-%m-%d"), "s": r(v, 4), "b": r(float(bench.get(d, float("nan"))), 4)}
                  for d, v in strat.iloc[::step].items()],
        "note": "中证红利、沪深300 使用全收益指数（含分红再投资），创业板指为价格指数，国债指数含息；未计交易费用和申赎费。"
                "参数经少量调试选定，存在过拟合风险。历史表现不代表未来。",
    }


def fund_timing_backtest(acc_nav: pd.Series, risk: RiskSettings, years: int = 3) -> dict:
    """单基金：站上60日均线持有、跌破或触发止损/移动止盈离场；信号次日执行。对比一直持有。"""
    s = acc_nav.dropna()
    s = s[s.index >= s.index[-1] - pd.Timedelta(days=365 * years + 120)]
    if len(s) < 200:
        return {}
    ma60 = s.rolling(60).mean()
    rets = s.pct_change().fillna(0)
    pos, entry, peak, nav, trades = 0, 0.0, 0.0, 1.0, 0
    navs = []
    start_i = 60
    for i in range(start_i, len(s)):
        nav *= 1 + pos * rets.iloc[i]
        navs.append((s.index[i], nav))
        p = s.iloc[i]
        if pos:
            peak = max(peak, p)
            exit_ = p < ma60.iloc[i] * 0.98 or p / entry - 1 <= risk.fund_stop_loss or \
                (peak / entry - 1 >= risk.fund_take_profit * 0.6 and p / peak - 1 <= -risk.trailing_drawdown)
            if exit_:
                pos = 0
        elif p > ma60.iloc[i] * 1.01:
            pos, entry, peak, trades = 1, p, p, trades + 1
    strat = pd.Series(dict(navs))
    hold = s.iloc[start_i:] / s.iloc[start_i]
    return {"strategy": _metrics(strat, risk), "hold": _metrics(hold, risk), "trades": trades,
            "start": strat.index[0].strftime("%Y-%m-%d")}
