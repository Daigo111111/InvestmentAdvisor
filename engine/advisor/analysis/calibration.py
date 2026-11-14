"""盘中估值误差校正：用每只基金近 20 个交易日「估算 vs 实际」的记录，
1) 对重仓股估算乘以回归系数 β（修正股票仓位、非前十大持仓带来的系统性偏差）；
2) 比较「重仓股估算」与「东财估值」的历史误差，选更准的来源。"""
from __future__ import annotations

from ..util import clamp, r

MIN_SAMPLES = 5
WINDOW = 20


def _rows(hist: list[dict]) -> list[dict]:
    return [x for x in (hist or [])[-WINDOW:] if x.get("actual") is not None]


def beta_of(hist: list[dict]) -> tuple[float, int]:
    rows = [x for x in _rows(hist) if x.get("own") is not None and abs(x["own"]) >= 0.05]
    if len(rows) < MIN_SAMPLES:
        return 1.0, len(rows)
    num = sum(x["own"] * x["actual"] for x in rows)
    den = sum(x["own"] ** 2 for x in rows)
    return (clamp(num / den, 0.6, 1.4) if den else 1.0), len(rows)


def mae(hist: list[dict], key: str, beta: float = 1.0) -> tuple[float | None, int]:
    rows = [x for x in _rows(hist) if x.get(key) is not None]
    if not rows:
        return None, 0
    return sum(abs(x[key] * beta - x["actual"]) for x in rows) / len(rows), len(rows)


def calibrate(own: float | None, em: float | None, coverage: float, hist: list[dict]) -> dict:
    """返回 {est, source, beta, mae, note}。"""
    beta, nb = beta_of(hist)
    own_c = own * beta if own is not None else None
    mae_own, n_own = mae(hist, "own", beta)
    mae_em, n_em = mae(hist, "em")
    if own_c is None and em is None:
        return {"est": None, "source": None, "beta": beta, "mae": None, "note": ""}
    if own_c is None:
        pick = "em"
    elif em is None:
        pick = "own"
    elif n_own >= MIN_SAMPLES and n_em >= MIN_SAMPLES:
        pick = "own" if mae_own <= mae_em else "em"
    else:
        pick = "em" if coverage < 0.4 else "own"
    est = own_c if pick == "own" else em
    m = mae_own if pick == "own" else mae_em
    n = n_own if pick == "own" else n_em
    notes = []
    if pick == "own" and nb >= MIN_SAMPLES and abs(beta - 1) >= 0.01:
        notes.append(f"已按近{nb}日误差校正×{beta:.2f}")
    if m is not None and n >= MIN_SAMPLES:
        notes.append(f"近{n}日平均误差 {m:.2f}%")
    return {"est": r(est, 2), "source": "重仓股估算" if pick == "own" else "东财估值", "beta": r(beta, 3),
            "mae": r(m, 3), "note": "，".join(notes)}


def record_close(state: dict, day: str, rows: dict[str, dict]) -> None:
    """14:10 记录各基金的原始估值（自算/东财/最终采用），保留最近 30 天。"""
    ests = state.setdefault("estimates", {})
    ests[day] = rows
    for k in sorted(ests)[:-30]:
        ests.pop(k)


def record_actual(state: dict, day: str, code: str, actual: float) -> dict | None:
    """晚间净值公布后，把当日估值与实际涨跌写入误差历史。"""
    e = state.get("estimates", {}).get(day, {}).get(code)
    if e is None:
        return None
    if not isinstance(e, dict):  # 兼容旧格式：只存了最终估值
        e = {"used": e}
    hist = state.setdefault("est_hist", {}).setdefault(code, [])
    hist[:] = [x for x in hist if x.get("d") != day]
    hist.append({"d": day, "own": e.get("own"), "em": e.get("em"), "used": e.get("used"), "actual": actual})
    del hist[:-30]
    return e
