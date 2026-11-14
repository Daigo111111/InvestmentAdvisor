"""分析流水线：把数据层与分析层串起来，产出报告各分区。"""
from __future__ import annotations

from datetime import date

import pandas as pd

from . import ledger
from .analysis import calibration as cal
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


def _snapshot_shares(it: dict, nav: pd.DataFrame) -> dict:
    """只录了「持有金额+收益」时，按录入日（as_of）当时已公布的净值折算份额，而不是按今天的净值。"""
    if it.get("shares") or not it.get("amount") or not it.get("as_of"):
        return it
    past = nav[nav.index <= pd.Timestamp(it["as_of"])]
    if past.empty:
        return it
    ref = float(past["nav"].iloc[-1])
    shares = float(it["amount"]) / ref
    cost = (float(it["amount"]) - float(it.get("profit") or 0)) / shares
    return dict(it, shares=shares, cost_nav=cost)


def prepare_holdings(h: dict) -> dict:
    """应用交易记录，得到当前持仓、可用现金、已清仓标的及其已实现收益。"""
    trades = h.get("trades") or []
    funds, stocks, closed, flows = [], [], [], []
    for it in ledger.merge_items(h.get("funds"), trades, "fund"):
        code = it["code"]
        nav = safe(lambda: fd.fund_nav(code), None, f"fund_nav {code}")
        if nav is None or nav.empty:
            log.error("基金 %s 净值获取失败，跳过", code)
            continue
        hold = fa.normalize_holding(_snapshot_shares(it, nav), nav)
        hold = ledger.apply_fund_trades(hold, ledger.trades_for(trades, "fund", code, it.get("as_of")), nav)
        flows += hold.pop("flows")
        if hold["shares"] <= 1e-6:
            closed.append({"asset": "fund", "code": code, "name": it.get("name") or fd.fund_basic(code)["name"],
                           "realized": hold["realized"]})
            continue
        funds.append({"code": code, "nav": nav, "holding": hold})
    for it in ledger.merge_items(h.get("stocks"), trades, "stock"):
        s = ledger.apply_stock_trades(it, ledger.trades_for(trades, "stock", it["code"], it.get("as_of")))
        flows += s.pop("flows")
        if float(s.get("shares") or 0) <= 0:
            closed.append({"asset": "stock", "code": it["code"], "name": it.get("name") or it["code"],
                           "realized": s["realized"]})
            continue
        stocks.append(s)
    cash = ledger.cash_after_trades(float(h.get("cash") or 0), h.get("cash_as_of"), flows)
    return {"funds": funds, "stocks": stocks, "cash": cash, "closed": closed}


def analyze_funds(items: list[dict], risk: RiskSettings, today: date, intraday: bool, board_pct: dict,
                  other_value: float, cash: float, portfolio_dd: float, state: dict | None = None) -> list[dict]:
    """items 为 prepare_holdings()["funds"]。"""
    if not items:
        return []
    state = state or {}
    flist = fd.fund_list()
    rank = safe(fd.fund_rank_all, pd.DataFrame(), "fund_rank")
    est_all = safe(fd.fund_estimation_all, pd.DataFrame(), "fund_estimation") if intraday else pd.DataFrame()
    trade_day = safe(lambda: mk.is_trade_day(today), True, "calendar")
    industry, boards = _industry_map(), safe(bd.board_names, [], "board_names")
    ctxs = []
    for it in items:
        code = it["code"]
        basic = fd.fund_basic(code)
        hold, quarter = safe(lambda: fd.fund_holdings(code), (pd.DataFrame(columns=["code", "name", "weight"]), ""),
                             f"holdings {code}")
        ctxs.append({"code": code, "name": basic["name"], "type": basic["type"], "category": fd.fund_category(basic["type"]),
                     "nav": it["nav"], "holding": it["holding"], "hold_df": hold, "quarter": quarter})
    all_codes = sorted({c for x in ctxs for c in x["hold_df"]["code"].astype(str)})
    quotes = safe(lambda: mk.quotes(all_codes), pd.DataFrame(), "quotes") if all_codes else pd.DataFrame()
    for x in ctxs:
        latest_is_today = x["nav"].index[-1].date() >= today
        live = intraday and not latest_is_today
        est = {"est_pct": None, "coverage": 0.0, "contrib": []}
        if live and x["category"] in ("equity", "fof"):
            est = fa.estimate_change(x["hold_df"], quotes, x["type"], today)
        x.update(est)
        x["est_own"] = est["est_pct"]
        x["est_pct_em"] = float(est_all.loc[x["code"], "est_pct"]) \
            if live and trade_day and not est_all.empty and x["code"] in est_all.index else None
        c = cal.calibrate(x["est_own"], x["est_pct_em"], x["coverage"], state.get("est_hist", {}).get(x["code"], []))
        x["est_pct"], x["est_source"], x["est_note"], x["est_beta"] = c["est"], c["source"], c["note"], c["beta"]
        if x["category"] == "qdii":
            x["est_pct"], x["est_source"], x["est_note"] = None, "QDII 无法用A股估值，净值T+1/T+2公布", ""
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
        adv["metrics"].update({"est_pct_em": x.get("est_pct_em"), "est_own": x.get("est_own"),
                               "est_note": x.get("est_note"), "realized": x["holding"].get("realized"),
                               "n_trades": x["holding"].get("n_trades"), "pending": x["holding"].get("pending")})
        adv["nav_curve"] = [{"d": d.strftime("%Y-%m-%d"), "v": r(v, 4)} for d, v in x["nav"]["acc_nav"].tail(250).iloc[::2].items()]
        adv["backtest"] = None
        out.append(adv)
    return out


def analyze_stocks(items: list[dict], risk: RiskSettings, today: date, fund_value: float, cash: float,
                   board_pct: dict) -> list[dict]:
    """items 为 prepare_holdings()["stocks"]。"""
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
        adv = advise_stock(h, hist, quote, score, items_, total, risk, today, board, board_pct.get(board))
        adv["metrics"].update({"realized": it.get("realized"), "n_trades": it.get("n_trades")})
        out.append(adv)
    return out


def close_estimates(fund_adv: list[dict]) -> dict[str, dict]:
    return {f["code"]: {"own": f["metrics"].get("est_own"), "em": f["metrics"].get("est_pct_em"),
                        "used": f["metrics"]["est_pct"]}
            for f in fund_adv if f["metrics"].get("est_pct") is not None or f["metrics"].get("est_own") is not None}


def estimate_check(state: dict, fund_adv: list[dict], today: str) -> list[dict]:
    """晚间：对比下午估算与当日实际净值涨跌，写入误差历史（供次日校正），并输出误差表。"""
    rows = []
    for a in fund_adv:
        m = a["metrics"]
        if m.get("nav_date") != today or m.get("last_pct") is None:
            continue
        e = cal.record_actual(state, today, a["code"], m["last_pct"])
        if e is None or e.get("used") is None:
            continue
        rows.append({"code": a["code"], "name": a["name"], "est": e["used"], "own": e.get("own"), "em": e.get("em"),
                     "actual": m["last_pct"], "error": r(e["used"] - m["last_pct"])})
    return rows


def fund_backtests(fund_adv: list[dict], risk: RiskSettings) -> None:
    from .analysis.backtest import fund_timing_backtest
    for a in fund_adv:
        nav = safe(lambda: fd.fund_nav(a["code"]), None, "nav")
        if nav is not None:
            a["backtest"] = safe(lambda: fund_timing_backtest(nav["acc_nav"], risk), None, "fund_bt")
