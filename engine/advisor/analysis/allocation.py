"""资产配置：市场状态判断 → 在最大回撤约束下给出目标仓位 → 与当前持仓对比给出再平衡建议。"""
from __future__ import annotations

import pandas as pd

from ..config import RiskSettings
from ..data import market as mk
from ..util import r
from . import indicators as ind
from .taxonomy import ZONE_BOARDS, ZONE_NAMES

EQUITY_BY_REGIME = {"进攻": 0.90, "均衡": 0.60, "防守": 0.20}
BASE_SPLIT = {"dividend": 0.35, "value": 0.20, "tech": 0.25, "consumer": 0.12, "cyclical": 0.08}
SIGNAL_MA = 60
BRAKE_DD = 0.08  # 组合回撤超过 8% 时权益仓位减半，直到创新高


def regime_from_series(s: pd.Series, n: int = SIGNAL_MA) -> str:
    m = s.rolling(n).mean().iloc[-1]
    mom20 = s.iloc[-1] / s.iloc[-21] - 1
    if s.iloc[-1] > m and mom20 > -0.03:
        return "进攻"
    if s.iloc[-1] < m * 0.97 and mom20 < 0:
        return "防守"
    return "均衡"


def market_regime() -> dict:
    s = mk.index_hist("sh000300")
    reg = regime_from_series(s)
    return {"regime": reg, "hs300": r(float(s.iloc[-1])), "ma60": r(float(s.rolling(SIGNAL_MA).mean().iloc[-1])),
            "mom20": r(ind.ret(s, 20), 4), "mdd_1y": r(ind.max_drawdown(s.tail(250)), 4)}


def equity_target(regime: str, risk: RiskSettings, portfolio_dd: float = 0.0) -> float:
    eq = min(0.90, EQUITY_BY_REGIME[regime] * risk.max_drawdown / 0.20)
    return eq * 0.5 if portfolio_dd <= -BRAKE_DD * risk.max_drawdown / 0.20 else eq


def target_weights(regime: str, risk: RiskSettings, board_pct: dict[str, float], portfolio_dd: float = 0.0) -> dict[str, float]:
    eq = equity_target(regime, risk, portfolio_dd)
    split = dict(BASE_SPLIT)
    for z, bs in ZONE_BOARDS.items():
        vals = [board_pct[b] for b in bs if b in board_pct]
        if vals:
            avg = sum(vals) / len(vals)
            split[z] = max(0.03, split[z] + (0.05 if avg > 0.6 else -0.05 if avg < 0.4 else 0))
    tot = sum(split.values())
    w = {z: r(eq * v / tot, 4) for z, v in split.items()}
    w["fixed"] = r(1 - eq, 4)
    return w


def classify_fund(name: str, category: str, board: str) -> str:
    from .taxonomy import zone_of_board
    if category in ("money", "bond"):
        return "fixed"
    if "红利" in name or "高股息" in name:
        return "dividend"
    if any(k in name for k in ("300", "500", "50", "1000", "A500", "宽基", "价值", "蓝筹")):
        return "value"
    return zone_of_board(board) if board else "value"


def rebalance(target: dict[str, float], current_values: dict[str, float], total: float) -> list[dict]:
    rows = []
    for z, tw in target.items():
        cv = current_values.get(z, 0.0)
        cw = cv / total if total else 0
        diff = tw - cw
        name = "固收/现金" if z == "fixed" else ZONE_NAMES.get(z, z)
        act = "增配" if diff > 0.05 else "减配" if diff < -0.05 else "保持"
        rows.append({"zone": z, "name": name, "target": r(tw, 4), "current": r(cw, 4), "diff": r(diff, 4),
                     "amount": r(diff * total, 0), "action": act})
    return sorted(rows, key=lambda x: -abs(x["diff"] or 0))
