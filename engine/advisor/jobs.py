"""定时任务：morning(09:00) / close(14:10) / evening(20:30) / weekly(周六) / refresh(持仓变更后)。"""
from __future__ import annotations

from datetime import date

import pandas as pd

from . import DISCLAIMER, __version__, llm, messages, notify
from .analysis import allocation as al
from .analysis import rotation as rt
from .analysis import screener as sc
from .analysis.backtest import allocation_backtest
from .analysis.fund_switch import switch_plan
from .analysis.sentiment import analyze_news
from .analysis.taxonomy import ZONE_NAMES
from .data import market as mk
from .data import news as nw
from .pipeline import analyze_funds, analyze_stocks, estimate_check, fund_backtests
from .portfolio import Store, portfolio_summary, risk_of
from .util import log, now_cst, r, safe

JOBS = ("morning", "close", "evening", "weekly", "refresh")


def _news_section(h: dict) -> dict:
    news = safe(nw.market_news, pd.DataFrame(), "market_news")
    names = safe(mk.stock_names, {}, "stock_names")
    res = analyze_news(news, names) if not news.empty else {"items": [], "board_heat": {}, "stock_heat": {}}
    hot = sorted(({"board": b, **v} for b, v in res["board_heat"].items()), key=lambda x: -x["score"])
    held = {str(s["code"]).zfill(6): s.get("name", "") for s in h.get("stocks", [])}
    watch = [{"code": c, "name": held[c] or names.get(c, c), "title": v["titles"][0]}
             for c, v in res["stock_heat"].items() if c in held and v["titles"]]
    top = res["items"][:8]
    fallback = "\n".join(f"· {'利好' if i['score'] > 0 else '利空'}｜{i['title']}" for i in top if i["score"]) or ""
    digest = llm.enhance("news_digest", top, fallback)
    return {"items": res["items"], "hot_boards": hot[:15], "cold_boards": hot[-8:][::-1], "watch": watch,
            "digest": digest, "stock_heat": res["stock_heat"]}


def _stock_value_rough(stocks: list[dict]) -> float:
    if not stocks:
        return 0.0
    q = safe(lambda: mk.quotes([s["code"] for s in stocks]), pd.DataFrame(), "quotes")
    return sum(float(s.get("shares") or 0) * float(q.loc[str(s["code"]).zfill(6), "price"]
                                                    if str(s["code"]).zfill(6) in q.index else s.get("cost") or 0)
               for s in stocks)


def _prev_dd(state: dict) -> float:
    vals = [p["value"] / p["cost"] for p in state.get("portfolio", []) if p.get("cost")]
    return vals[-1] / max(vals) - 1 if vals else 0.0


def _allocation(rep: dict, risk, board_pct: dict) -> dict:
    mkt = rep.get("market") or {}
    regime = mkt.get("regime", "均衡")
    pdd = rep.get("portfolio", {}).get("drawdown") or 0.0
    target = al.target_weights(regime, risk, board_pct, pdd)
    cur: dict[str, float] = {"fixed": rep.get("portfolio", {}).get("cash", 0) or 0}
    for f in rep.get("funds", []):
        z = al.classify_fund(f["name"], f.get("category", "equity"), f["metrics"].get("sector") or "")
        cur[z] = cur.get(z, 0) + (f["metrics"]["value"] or 0)
    from .analysis.taxonomy import zone_of_board
    for s in rep.get("stocks", []):
        z = zone_of_board(s["metrics"].get("board") or "")
        cur[z] = cur.get(z, 0) + (s["metrics"]["value"] or 0)
    total = rep.get("portfolio", {}).get("total") or sum(cur.values())
    return {"regime": regime, "equity_target": r(al.equity_target(regime, risk, pdd), 3), "target": target,
            "current": {k: r(v / total, 4) if total else 0 for k, v in cur.items()},
            "rebalance": al.rebalance(target, cur, total) if total else [],
            "note": f"在最大回撤 {risk.max_drawdown:.0%} 约束下，按市场状态「{regime}」配置权益仓位"}


def run(job: str, demo: bool = False, push: bool = True, force: bool = False) -> dict:
    assert job in JOBS, job
    now = now_cst()
    today: date = now.date()
    tstr = today.isoformat()
    if not force and job not in ("weekly", "refresh") and not safe(lambda: mk.is_trade_day(today), True, "calendar"):
        log.info("%s 非交易日，跳过 %s", tstr, job)
        return {}
    store = Store(demo)
    h = store.holdings()
    risk = risk_of(h)
    state = store.state()
    rep = store.report() or {}
    cash = float(h.get("cash") or 0)

    rep["market"] = safe(al.market_regime, rep.get("market", {}), "market_regime")
    rep["news"] = safe(lambda: _news_section(h), rep.get("news", {}), "news")
    heat = rep["news"].get("board_heat") or {b["board"]: b for b in rep["news"].get("hot_boards", [])}

    board_pct = {k: v.get("pct", 0.5) for k, v in rep.get("rotation", {}).get("all", {}).items()}
    if job != "morning":
        rot_df = safe(lambda: rt.board_scores(heat), pd.DataFrame(), "rotation")
        if not rot_df.empty:
            rep["rotation"] = rt.to_report(rot_df)
            board_pct = rot_df["pct"].to_dict()
    else:
        rot_df = pd.DataFrame()

    if job in ("close", "evening", "refresh"):
        intraday = job == "close" or (job == "refresh" and now.hour * 100 + now.minute < 1500 and now.hour >= 9)
        sv = _stock_value_rough(h.get("stocks", []))
        rep["funds"] = analyze_funds(h.get("funds", []), risk, today, intraday, board_pct, sv, cash, _prev_dd(state))
        fv = sum(f["metrics"]["value"] or 0 for f in rep["funds"])
        rep["stocks"] = analyze_stocks(h.get("stocks", []), risk, today, fv, cash, board_pct)
        rep["portfolio"] = portfolio_summary(rep["funds"], rep["stocks"], cash, state, tstr, record=(job == "evening"))
        if job == "close":
            ests = state.setdefault("estimates", {})
            ests[tstr] = {f["code"]: f["metrics"]["est_pct"] for f in rep["funds"] if f["metrics"]["est_pct"] is not None}
            for k in sorted(ests)[:-30]:
                ests.pop(k)
        if job == "evening":
            rep["est_check"] = estimate_check(state, rep["funds"], tstr)

    if job in ("evening", "weekly") or not rep.get("zones"):
        uni = safe(sc.build_universe, None, "universe")
        if uni is not None:
            zones = safe(lambda: sc.screen(uni, board_pct, rep["news"].get("stock_heat", {})), {}, "screen")
            zones["catalyst"] = safe(lambda: sc.catalyst_picks(rep["news"].get("stock_heat", {}), uni), [], "catalyst")
            rep["zones"] = zones
            rep["zone_names"] = ZONE_NAMES
            rep["universe_period"] = uni.attrs.get("period")

    need_switch = any(f.get("switch") for f in rep.get("funds", []))
    if (job == "weekly" or need_switch or not rep.get("switch")) and not rot_df.empty:
        held = {str(f["code"]).zfill(6) for f in h.get("funds", [])}
        rep["switch"] = safe(lambda: switch_plan(rot_df, exclude=held), rep.get("switch", []), "switch_plan")

    if rep.get("portfolio"):
        rep["allocation"] = safe(lambda: _allocation(rep, risk, board_pct), rep.get("allocation", {}), "allocation")

    if job == "weekly" or not rep.get("backtest"):
        bt = rep.setdefault("backtest", {})
        bt["allocation"] = safe(lambda: allocation_backtest(risk), bt.get("allocation"), "allocation_backtest")
    if job in ("weekly", "refresh") or (rep.get("funds") and not any(f.get("backtest") for f in rep["funds"])):
        fund_backtests(rep.get("funds", []), risk)

    rep["news"].pop("stock_heat", None)
    rep["news"].pop("board_heat", None)
    rep["meta"] = {"date": tstr, "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"), "job": job, "version": __version__,
                   "demo": demo, "llm": llm.enabled(), "disclaimer": DISCLAIMER,
                   "risk": {k: getattr(risk, k) for k in risk.__dataclass_fields__}}
    store.save_report(rep)
    store.save_state(state)

    if push and job != "refresh":
        if job == "close":
            title, md, color = messages.close_message(rep, late=now.hour * 100 + now.minute >= 1455)
        else:
            title, md, color = getattr(messages, f"{job}_message")(rep)
        res = notify.push(("[演示] " if demo else "") + title, md, color)
        log.info("推送结果 %s", res)
        rep["meta"]["push"] = res
    return rep
