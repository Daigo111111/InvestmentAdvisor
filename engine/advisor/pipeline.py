"""分析流水线：把数据层与分析层串起来，产出报告各分区。"""
from __future__ import annotations

from datetime import date

import pandas as pd

from .analysis import fund_advisor as fa
from .analysis.stock_advisor import advise_stock
from .analysis.sentiment import stock_sentiment
from .analysis.taxonomy import em_industry_to_board
from .config import RiskSettings
from .data import boards as bd
from .data import fund as fd
from .data import fundamentals as fm
from .data import market as mk
from .data import news as nw
from .util import log, r, safe


def _industry_map() -> pd.Series:
    period, _ = fm.latest_report_period(date.today())
    f = safe(lambda: fm.fundamentals(period), pd.DataFrame(), "fundamentals")
    return f["industry"] if not f.empty else pd.Series(dtype=str)


def _main_board(holdings: pd.DataFrame, industry: pd.Series, boards: list[str]) -> str:
    w: dict[str, float] = {}
    for _, h in holdings.iterrows():
        b = em_industry_to_board(str(industry.get(str(h["code"]).zfill(6), "")), boards)
        if b:
            w[b] = w.get(b, 0) + float(h["weight"])
    return max(w, key=w.get) if w else ""


def _rank_pct(code: str, rank: pd.DataFrame, flist: pd.DataFrame) -> float | None:
    t = flist.set_index("code")["type"]
    if code not in t.index or rank.empty:
        return None
    peers = rank[rank["code"].map(t).eq(t[code])].dropna(subset=["r3m"])
    if code not in set(peers["code"]):
        return None
    return float(peers["r3m"].rank(pct=True)[peers["code"] == code].iloc[0])


def analyze_funds(items: list[dict], risk: RiskSettings, today: date, intraday: bool, board_pct: dict,
                  other_value: float, cash: float, portfolio_dd: float) -> list[dict]:
    if not items:
        return []
    flist = fd.fund_list()
    rank = safe(fd.fund_rank_all, pd.DataFrame(), "fund_rank")
    est_all = safe(fd.fund_estimation_all, pd.DataFrame(), "fund_estimation") if intraday else pd.DataFrame()
    industry, boards = _industry_map(), safe(bd.board_names, [], "board_names")
    ctxs = []
    for it in items:
        code = str(it["code"]).zfill(6)
        nav = safe(lambda: fd.fund_nav(code), None, f"fund_nav {code}")
        if nav is None or nav.empty:
            log.error("基金 %s 净值获取失败，跳过", code)
            continue
        basic = fd.fund_basic(code)
        hold, quarter = safe(lambda: fd.fund_holdings(code), (pd.DataFrame(columns=["code", "name", "weight"]), ""),
                             f"holdings {code}")
        ctxs.append({"code": code, "name": basic["name"], "type": basic["type"], "category": fd.fund_category(basic["type"]),
                     "nav": nav, "holding": fa.normalize_holding(it, nav), "hold_df": hold, "quarter": quarter})
    all_codes = sorted({c for x in ctxs for c in x["hold_df"]["code"].astype(str)})
    quotes = safe(lambda: mk.quotes(all_codes), pd.DataFrame(), "quotes") if all_codes else pd.DataFrame()
    for x in ctxs:
        latest_is_today = x["nav"].index[-1].date() >= today
        est = {"est_pct": None, "coverage": 0.0, "contrib": []}
        if intraday and not latest_is_today and x["category"] in ("equity", "fof"):
            est = fa.estimate_change(x["hold_df"], quotes, x["type"], today)
        x.update(est)
        x["est_source"] = "重仓股估算" if est["est_pct"] is not None else None
        if intraday and not latest_is_today and not est_all.empty and x["code"] in est_all.index \
                and safe(lambda: mk.is_trade_day(today), True, "calendar"):
            x["est_pct_em"] = float(est_all.loc[x["code"], "est_pct"])
            if x["est_pct"] is None or x["coverage"] < 0.4:
                x["est_pct"], x["est_source"] = x["est_pct_em"], "东财估值"
        if x["category"] == "qdii":
            x["est_pct"], x["est_source"] = None, "QDII 无法用A股估值，净值T+1/T+2公布"
        x["sector"] = _main_board(x["hold_df"], industry, boards)
        x["sector_pct"] = board_pct.get(x["sector"]) if x["sector"] else None
        x["rank_pct"] = safe(lambda: _rank_pct(x["code"], rank, flist), None, "rank_pct")
        x["fee_table"] = fd.redeem_fee_table(x["code"])
        x["value0"] = x["holding"]["shares"] * float(x["nav"]["nav"].iloc[-1]) * (1 + (x["est_pct"] or 0) / 100)
    total = sum(x["value0"] for x in ctxs) + other_value + cash
    out = []
    for x in ctxs:
        x.update({"total_value": total, "cash": cash, "portfolio_dd": portfolio_dd})
        adv = fa.advise(x, risk, today)
        adv["metrics"]["est_pct_em"] = x.get("est_pct_em")
        adv["nav_curve"] = [{"d": d.strftime("%Y-%m-%d"), "v": r(v, 4)} for d, v in x["nav"]["acc_nav"].tail(250).iloc[::2].items()]
        adv["backtest"] = None
        out.append(adv)
    return out


def analyze_stocks(items: list[dict], risk: RiskSettings, today: date, fund_value: float, cash: float,
                   board_pct: dict) -> list[dict]:
    if not items:
        return []
    codes = [str(i["code"]).zfill(6) for i in items]
    q = safe(lambda: mk.quotes(codes), pd.DataFrame(), "quotes")
    industry, boards = _industry_map(), safe(bd.board_names, [], "board_names")
    vals = {c: float(i.get("shares") or 0) * float(q.loc[c, "price"] if c in q.index else i.get("cost") or 0)
            for c, i in zip(codes, items)}
    total = sum(vals.values()) + fund_value + cash
    out = []
    for code, it in zip(codes, items):
        hist = safe(lambda: mk.stock_hist(code, 400), None, f"hist {code}")
        if hist is None or hist.empty:
            continue
        news = safe(lambda: nw.stock_news(code), pd.DataFrame(), f"news {code}")
        score, items_ = stock_sentiment(news) if not news.empty else (0.0, [])
        quote = q.loc[code].to_dict() if code in q.index else None
        board = em_industry_to_board(str(industry.get(code, "")), boards)
        h = dict(it, code=code, name=it.get("name") or (quote or {}).get("name", code))
        out.append(advise_stock(h, hist, quote, score, items_, total, risk, today, board, board_pct.get(board)))
    return out


def estimate_check(state: dict, fund_adv: list[dict], today: str) -> list[dict]:
    """晚间：对比下午估算与当日实际净值涨跌，评估估值误差。"""
    est = state.get("estimates", {}).get(today, {})
    rows = []
    for a in fund_adv:
        m = a["metrics"]
        e = est.get(a["code"])
        if e is None or m.get("nav_date") != today or m.get("last_pct") is None:
            continue
        rows.append({"code": a["code"], "name": a["name"], "est": e, "actual": m["last_pct"],
                     "error": r(e - m["last_pct"])})
    return rows


def fund_backtests(fund_adv: list[dict], risk: RiskSettings) -> None:
    from .analysis.backtest import fund_timing_backtest
    for a in fund_adv:
        nav = safe(lambda: fd.fund_nav(a["code"]), None, "nav")
        if nav is not None:
            a["backtest"] = safe(lambda: fund_timing_backtest(nav["acc_nav"], risk), None, "fund_bt")
