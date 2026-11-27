"""基金估值模型：每天用最近约 60 个交易日的「实际净值涨跌」回测多种估算方式，自动选出最准的一种。

候选方式：
  - 重仓股组合：季报前十大持仓（A股/港股）按权重加权，再乘以回归系数（吸收股票仓位与非前十大持仓的影响）
  - 跟踪指数：与基金最相关的指数（按名称关键词 + 常用宽基/港股/美股指数），乘以回归系数
QDII 基金的人民币净值还要叠加美元兑人民币汇率变化。
评估方法：用较早的约 2/3 天数拟合系数，在最近 1/3 天数上检验（样本外），按平均绝对误差选最优；最终系数用全部天数重新拟合。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import fund as fd
from ..data import market as mk
from ..util import cached, r, safe

NAMES = {
    "sh000300": "沪深300", "sh000905": "中证500", "sh000852": "中证1000", "sz399006": "创业板指", "sh000688": "科创50",
    "sh000016": "上证50", "sh000922": "中证红利", "sz399997": "中证白酒", "sz399986": "中证银行", "sz399975": "证券公司",
    "sz399989": "中证医疗", "sh000932": "中证消费", "sh000933": "中证医药", "sz399967": "中证军工", "sz399808": "中证新能",
    "hkHSI": "恒生指数", "hkHSTECH": "恒生科技指数", "hkHSCEI": "恒生国企指数",
    "usNDX": "纳斯达克100", "usINX": "标普500", "usIXIC": "纳斯达克综合", "sh513050": "中概互联网ETF",
    "sh000012": "国债指数", "sz399481": "企债指数",
}
KEYWORDS = [
    ("红利", "sh000922"), ("沪深300", "sh000300"), ("中证500", "sh000905"), ("中证1000", "sh000852"), ("创业板", "sz399006"),
    ("科创50", "sh000688"), ("上证50", "sh000016"), ("白酒", "sz399997"), ("银行", "sz399986"), ("证券", "sz399975"),
    ("医疗", "sz399989"), ("消费", "sh000932"), ("医药", "sh000933"), ("军工", "sz399967"), ("新能源", "sz399808"),
    ("恒生科技", "hkHSTECH"), ("恒生互联网", "hkHSTECH"), ("国企", "hkHSCEI"), ("H股", "hkHSCEI"), ("恒生", "hkHSI"),
    ("纳斯达克", "usNDX"), ("纳指", "usNDX"), ("标普", "usINX"), ("中概", "sh513050"), ("互联网", "sh513050"),
]
A_BROAD = ["sh000300", "sh000905", "sh000852", "sz399006", "sh000688", "sh000922"]
OVERSEAS = ["hkHSI", "hkHSTECH", "hkHSCEI", "usNDX", "usINX", "usIXIC", "sh513050"]
FX = "whUSDCNY"
BOND = ["sh000012", "sz399481"]
WINDOW = 60
MIN_DAYS = 20


def candidates(name: str, category: str, holdings: pd.DataFrame) -> list[str]:
    syms = [s for k, s in KEYWORDS if k in (name or "")]
    has_hk = any(str(c).isdigit() and len(str(c)) <= 5 for c in holdings.get("code", []))
    if category == "qdii":
        syms += OVERSEAS
    elif category == "bond":  # 二级债基等含股票仓位的债基：债券指数 + 宽基
        syms += BOND + A_BROAD[:3]
    else:
        syms += A_BROAD + (["hkHSI", "hkHSTECH"] if has_hk else [])
    return list(dict.fromkeys(syms))


def _ret(s: pd.Series) -> pd.Series:
    return s.pct_change().dropna() * 100


def basket_returns(holdings: pd.DataFrame, category: str = "equity") -> tuple[pd.Series | None, list[dict]]:
    """前十大持仓的加权日收益（%），只用能取到行情的 A股/港股。
    QDII 的 6 位数字代码多为韩国/台湾等市场股票（如三星 005930），不能当 A 股处理，跳过。"""
    parts, ws, used = [], [], []
    for _, h in holdings.iterrows():
        code = str(h["code"]).strip()
        if category == "qdii" and code.isdigit() and len(code) == 6:
            continue
        sym = mk.holding_symbol(code)
        if not sym:
            continue
        s = safe(lambda sym=sym: mk.tx_kline(sym), None, f"kline {sym}")
        if s is None:
            continue
        parts.append(_ret(s) * float(h["weight"]))
        ws.append(float(h["weight"]))
        used.append({"symbol": sym, "name": h["name"], "weight": r(float(h["weight"]), 2)})
    if not parts:
        return None, []
    df = pd.concat(parts, axis=1)
    wsum = pd.concat([pd.Series(w, index=p.index) for w, p in zip(ws, parts)], axis=1).where(df.notna()).sum(axis=1)
    return (df.sum(axis=1) / wsum).dropna(), used


def _fit(X: pd.DataFrame, y: pd.Series) -> np.ndarray:
    """无截距最小二乘；系数限制在合理区间，避免过拟合出离谱的权重。"""
    coef, *_ = np.linalg.lstsq(X.values, y.values, rcond=None)
    return np.clip(coef, 0.0, 1.5)


def evaluate(X: pd.DataFrame, y: pd.Series) -> dict | None:
    """X: 各因子日收益(%)，y: 基金净值日涨跌(%)，按日期对齐。样本外（最近 1/3）检验误差，系数用全部样本重拟合。"""
    d = pd.concat([X, y.rename("_y")], axis=1).dropna().tail(WINDOW)
    if len(d) < MIN_DAYS:
        return None
    cols = list(X.columns)
    k = int(len(d) * 2 / 3)
    train, test = d.iloc[:k], d.iloc[k:]
    b = _fit(train[cols], train["_y"])
    pred = test[cols].values @ b
    err = test["_y"].values - pred
    moved = abs(test["_y"].values) >= 0.1
    hit = float(((pred * test["_y"].values) > 0)[moved].mean()) if moved.any() else None
    beta = _fit(d[cols], d["_y"])
    full = d[cols].values @ beta
    check = [{"d": i.strftime("%Y-%m-%d"), "est": r(e, 2), "actual": r(a, 2), "err": r(e - a, 2)}
             for i, e, a in zip(d.index[-10:], full[-10:], d["_y"].values[-10:])]
    return {"betas": [r(float(v), 3) for v in beta], "mae": r(float(abs(err).mean()), 3), "hit": r(hit, 3),
            "n": len(d), "corr": r(float(np.corrcoef(full, d["_y"].values)[0, 1]), 3), "check": check}


def _comp_name(c: dict) -> str:
    return f"重仓股组合（{len(c['holdings'])}只）" if c["kind"] == "basket" else NAMES.get(c["symbol"], c["symbol"])


def select_model(name: str, category: str, holdings: pd.DataFrame, nav: pd.DataFrame) -> dict | None:
    """在单因子（重仓股组合 / 各指数）与两两组合中，选样本外平均误差最小的估算方式。"""
    y = nav["pct"].astype(float)
    y.index = pd.to_datetime(y.index)
    fx = _ret(safe(lambda: mk.tx_kline(FX), pd.Series(dtype=float), "fx")) if category == "qdii" else None
    use_fx = fx is not None and not fx.empty

    def with_fx(x: pd.Series) -> pd.Series:
        if not use_fx:
            return x
        f = fx.reindex(x.index).fillna(0)
        return ((1 + x / 100) * (1 + f / 100) - 1) * 100

    factors: dict[str, tuple[dict, pd.Series]] = {}
    if not holdings.empty:
        bx, used = basket_returns(holdings, category)
        if bx is not None and used:
            factors["basket"] = ({"kind": "basket", "holdings": used}, with_fx(bx))
    for sym in candidates(name, category, holdings):
        s = safe(lambda sym=sym: mk.tx_kline(sym), None, f"kline {sym}")
        if s is not None:
            factors[sym] = ({"kind": "index", "symbol": sym}, with_fx(_ret(s)))
    results = []
    for key, (comp, x) in factors.items():
        ev = evaluate(pd.DataFrame({key: x}), y)
        if ev:
            results.append({"keys": [key], **ev})
    singles = sorted(results, key=lambda m: m["mae"])[:4]
    for i in range(len(singles)):
        for j in range(i + 1, len(singles)):
            ks = singles[i]["keys"] + singles[j]["keys"]
            ev = evaluate(pd.DataFrame({k: factors[k][1] for k in ks}), y)
            # 组合需要明显更准（误差降低 10% 以上）才采用，避免无谓复杂化
            if ev and min(ev["betas"]) >= 0.05 and ev["mae"] < min(singles[i]["mae"], singles[j]["mae"]) * 0.9:
                results.append({"keys": ks, **ev})
    if not results:
        return None
    results.sort(key=lambda m: m["mae"])

    def build(m: dict) -> dict:
        comps = [dict(factors[k][0], beta=b) for k, b in zip(m["keys"], m["betas"])]
        label = " + ".join(f"{_comp_name(c)}×{c['beta']:.2f}" for c in comps)
        return {"components": comps, "name": label, "fx": use_fx, "mae": m["mae"], "hit": m["hit"], "n": m["n"],
                "corr": m["corr"], "check": m["check"]}

    best = build(results[0])
    best["alternatives"] = [{"name": build(m)["name"], "mae": m["mae"], "hit": m["hit"]} for m in results[1:4]]
    return best


def symbols_of(model: dict) -> list[str]:
    syms = []
    for c in model["components"]:
        syms += [h["symbol"] for h in c["holdings"]] if c["kind"] == "basket" else [c["symbol"]]
    return syms + ([FX] if model.get("fx") else [])


def _comp_live(c: dict, quotes: dict[str, dict]) -> tuple[float, str, float] | None:
    if c["kind"] == "basket":
        rows = [(h["weight"], quotes.get(h["symbol"])) for h in c["holdings"]]
        dates = sorted(q["date"] for _, q in rows if q and q.get("date"))
        if not dates:
            return None
        latest = dates[-1]
        ok = [(w, q["pct"]) for w, q in rows if q and q.get("date") == latest]
        if not ok:
            return None
        return (sum(w * p for w, p in ok) / sum(w for w, _ in ok), latest,
                sum(w for w, _ in ok) / sum(h["weight"] for h in c["holdings"]))
    q = quotes.get(c["symbol"])
    return (q["pct"], q["date"], 1.0) if q else None


def live_estimate(model: dict, quotes: dict[str, dict]) -> dict | None:
    """用实时行情套用模型，返回 {est, date(YYYYMMDD), coverage}；与网页端 live.js 的算法一致。"""
    total, dates, cov = 0.0, [], []
    fxp = quotes.get(FX, {}).get("pct") if model.get("fx") else None
    for c in model["components"]:
        v = _comp_live(c, quotes)
        if v is None:
            return None
        x, d, cv = v
        if fxp is not None:
            x = ((1 + x / 100) * (1 + fxp / 100) - 1) * 100
        total += c["beta"] * x
        dates.append(d)
        cov.append(cv)
    return {"est": r(total, 2), "date": max(dates), "coverage": r(min(cov), 2)}


@cached(8 * 3600)
def model_for(code: str, name: str, category: str, day: str) -> dict | None:
    """每天（day 参与缓存键）用最新净值重新回测并选择估算方式。"""
    nav = fd.fund_nav(code)
    hold, _ = safe(lambda: fd.fund_holdings(code), (pd.DataFrame(columns=["code", "name", "weight"]), ""), "holdings")
    return select_model(name, category, hold, nav)
