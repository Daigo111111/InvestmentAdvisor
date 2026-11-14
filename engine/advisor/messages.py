"""推送消息（Markdown）。飞书与 WxPusher 共用同一份内容。"""
from __future__ import annotations

from . import DISCLAIMER

ICON = {"卖出": "▼", "减仓": "▽", "加仓": "▲", "不动": "·", "持有": "·"}


def _pct(v, n=2, sign=True) -> str:
    if v is None:
        return "-"
    return f"{v:+.{n}f}%" if sign else f"{v:.{n}f}%"


def _p(v, n=1) -> str:
    return "-" if v is None else f"{v * 100:+.{n}f}%"


def fund_lines(funds: list[dict]) -> list[str]:
    act = [f for f in funds if f["action"] != "不动"]
    still = [f for f in funds if f["action"] == "不动"]
    lines = []
    for f in act:
        m = f["metrics"]
        fee = f" · 赎回费约{f['fee']['fee']:.0f}元" if f.get("fee") else ""
        lines.append(f"{ICON[f['action']]} **{f['action']} {int(f['ratio'] * 100)}%** {f['name']}（约{f['amount']:.0f}元{fee}）\n"
                     f"　今日估 {_pct(m['est_pct'])} · 持有 {_p(m['ret_hold'])} · {f['reasons'][0]}")
    if still:
        lines.append("· 不动：" + "、".join(f"{f['name']}({_pct(f['metrics']['est_pct'])})" for f in still))
    return lines


def stock_lines(stocks: list[dict]) -> list[str]:
    lines = []
    for s in stocks:
        m = s["metrics"]
        head = f"{ICON.get(s['action'], '·')} **{s['action']}** {s['name']} {m['price']}（{_p(m['ret_hold'])}）"
        if s["action"] in ("卖出", "减仓", "加仓"):
            head += f" {s['shares']}股≈{s['amount']:.0f}元"
        lines.append(head + f"\n　{s['reasons'][0]} · 止损位 {m['stop']}")
    return lines


def close_message(rep: dict, late: bool) -> tuple[str, str, str]:
    pf = rep.get("portfolio", {})
    parts = []
    if late:
        parts.append("【注意】本次运行已接近或超过 15:00，今日操作可能按下一交易日净值确认。")
    parts.append(f"组合估值 **{pf.get('total', 0):,.0f}** 元 · 累计 {_p(pf.get('ret'))} · 回撤 {_p(pf.get('drawdown'))}")
    funds = rep.get("funds", [])
    if funds:
        parts.append("**基金**（15:00 前申赎按今日净值确认）\n" + "\n".join(fund_lines(funds)))
    stocks = rep.get("stocks", [])
    if stocks:
        parts.append("**股票**\n" + "\n".join(stock_lines(stocks)))
    sw = [f["name"] for f in funds if f.get("switch")]
    if sw:
        parts.append("【换基】" + "、".join(sw) + "（详见报告「换基建议」）")
    parts.append(f"<font color='grey'>{DISCLAIMER[:60]}…</font>")
    n_act = sum(1 for f in funds if f["action"] != "不动") + sum(1 for s in stocks if s["action"] != "持有")
    color = "red" if n_act else "green"
    return f"尾盘决策：{n_act} 项需要操作" if n_act else "尾盘决策：今日无需操作", "\n\n".join(parts), color


def morning_message(rep: dict) -> tuple[str, str, str]:
    mkt = rep.get("market", {})
    news = rep.get("news", {})
    parts = [f"市场状态：**{mkt.get('regime', '-')}**（沪深300 {mkt.get('hs300', '-')}，60日线 {mkt.get('ma60', '-')}，"
             f"近20日 {_p(mkt.get('mom20'))}）"]
    if news.get("digest"):
        parts.append("**要闻解读**\n" + news["digest"])
    hot = news.get("hot_boards", [])[:6]
    if hot:
        parts.append("**新闻热度板块**：" + "、".join(f"{b['board']}({b['score']:+.0f})" for b in hot))
    watch = news.get("watch", [])
    if watch:
        parts.append("**与你持仓相关**\n" + "\n".join(f"· {w['name']}：{w['title']}" for w in watch[:6]))
    return "早报 · " + rep.get("meta", {}).get("date", ""), "\n\n".join(parts), "blue"


def evening_message(rep: dict) -> tuple[str, str, str]:
    pf = rep.get("portfolio", {})
    hist = pf.get("history", [])
    day = ""
    if len(hist) >= 2:
        day = f" · 今日 {hist[-1]['value'] - hist[-2]['value']:+,.0f} 元"
    parts = [f"组合 **{pf.get('total', 0):,.0f}** 元{day} · 累计 {_p(pf.get('ret'))} · 回撤 {_p(pf.get('drawdown'))}"]
    chk = rep.get("est_check", [])
    if chk:
        parts.append("**估值误差**：" + "、".join(f"{c['name']} 估{_pct(c['est'])}/实{_pct(c['actual'])}" for c in chk))
    zones = rep.get("zones", {})
    picks = [z[0] for z in zones.values() if z]
    if picks:
        parts.append("**明日关注**（各专区首选）\n" + "\n".join(
            f"· [{p['zone_name']}] {p['name']} {p['price']}，{p['reasons'][0]}" for p in picks))
    return "晚间复盘 · " + rep.get("meta", {}).get("date", ""), "\n\n".join(parts), "purple"


def weekly_message(rep: dict) -> tuple[str, str, str]:
    rot = rep.get("rotation", {})
    parts = []
    if rot.get("top"):
        parts.append("**强势板块**：" + "、".join(f"{b['board']}({_p(b['r20'])})" for b in rot["top"][:5]))
        parts.append("**弱势板块**：" + "、".join(f"{b['board']}({_p(b['r20'])})" for b in rot["bottom"][:5]))
    for p in rep.get("switch", [])[:3]:
        parts.append(f"【换基】**{p['board']}**：" + "、".join(f"{f['name']}({f['code']}) 近1年{_pct(f['r1y'])}" for f in p["funds"]))
    alloc = rep.get("allocation", {})
    acts = [a for a in alloc.get("rebalance", []) if a["action"] != "保持"]
    if acts:
        parts.append("**再平衡**：" + "；".join(f"{a['action']}{a['name']} {abs(a['amount']):,.0f}元" for a in acts))
    bt = rep.get("backtest", {}).get("allocation")
    if bt:
        s = bt["strategy"]
        parts.append(f"**策略回测**（{bt['start'][:4]}至今）：年化 {_p(s['cagr'])}，最大回撤 {_p(s['mdd'])}，"
                     f"沪深300 年化 {_p(bt['hs300']['cagr'])}/回撤 {_p(bt['hs300']['mdd'])}")
    return "周报 · 板块轮动与配置", "\n\n".join(parts) or "本周无新数据", "indigo"
