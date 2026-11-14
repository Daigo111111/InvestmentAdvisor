"""规则版新闻情绪：关键词词典打分 + 板块/个股归因。后续可替换为大模型（见 llm.py）。"""
from __future__ import annotations

import re

import pandas as pd

from .taxonomy import BOARD_KEYWORDS

POSITIVE = {
    "业绩预增": 3, "净利润增长": 2, "超预期": 2, "大幅增长": 2, "扭亏": 2, "创新高": 1.5, "中标": 2, "签订": 1,
    "订单": 1.5, "回购": 2, "增持": 2, "分红": 1, "提高分红": 2, "获批": 2, "上市许可": 2, "突破": 1.5,
    "政策支持": 2, "利好": 2, "补贴": 1.5, "降准": 2, "降息": 2, "刺激": 1.5, "扩大内需": 1.5, "以旧换新": 1.5,
    "国产替代": 1.5, "量产": 1.5, "涨价": 1.5, "提价": 1.5, "供不应求": 2, "景气": 1.5, "加速": 1, "放量": 1,
    "收购": 1, "战略合作": 1, "首发": 1, "落地": 1, "支持": 0.5, "增长": 0.5, "上调评级": 2, "买入评级": 1,
}
NEGATIVE = {
    "业绩预亏": -3, "预亏": -3, "亏损扩大": -2.5, "净利润下降": -2, "不及预期": -2, "下滑": -1.5, "减持": -2.5,
    "清仓": -2, "立案": -3, "调查": -1.5, "处罚": -2, "违规": -2, "退市": -3, "ST": -2, "问询函": -1,
    "暴雷": -3, "违约": -2.5, "诉讼": -1.5, "冻结": -2, "制裁": -2, "关税": -1.5, "加征": -1.5, "限制": -1,
    "降价": -1, "价格战": -1.5, "产能过剩": -1.5, "库存高企": -1.5, "下调评级": -2, "终止": -1.5, "暂停": -1,
    "召回": -1.5, "跌停": -1.5, "爆仓": -2, "收紧": -1, "利空": -2, "风险提示": -1, "解禁": -1,
}
_NEGATORS = ("未", "不", "没有", "并非", "否认")
_LEXICON = sorted({**POSITIVE, **NEGATIVE}.items(), key=lambda kv: -len(kv[0]))
# 短语级规则优先于单词：如“暂停加征关税”整体是利好，不能按“加征”“关税”计为利空
_PHRASES = [
    (re.compile(r"(暂停|取消|豁免|下调|降低)[^。；]{0,12}(关税|加征)"), 3.0),
    (re.compile(r"(加征|上调|提高)[^。；]{0,8}关税"), -2.5),
    (re.compile(r"(终止|取消)[^。；]{0,6}(减持|回购)"), 0.0),
]


def score_text(text: str) -> tuple[float, list[str]]:
    """返回 (情绪分, 命中词)。短语规则优先，长词优先匹配，已匹配片段不重复计分；命中词前 2 字内有否定词时反向计分。"""
    text = text or ""
    total, hits = 0.0, []
    for pat, s in _PHRASES:
        for m in pat.finditer(text):
            total += s
            hits.append(m.group(0)[:10])
        text = pat.sub(lambda m: "□" * len(m.group(0)), text)
    for w, s in _LEXICON:
        for m in re.finditer(re.escape(w), text):
            pre = text[max(0, m.start() - 2):m.start()]
            total += -s if any(n in pre for n in _NEGATORS) else s
            hits.append(w)
        text = text.replace(w, "□" * len(w))
    return total, list(dict.fromkeys(hits))


def tag_boards(text: str) -> list[str]:
    return [b for b, kws in BOARD_KEYWORDS.items() if any(k in text for k in kws)]


def analyze_news(news: pd.DataFrame, stock_names: dict[str, str] | None = None) -> dict:
    """对快讯逐条打分并聚合到板块与个股。"""
    items, board_heat, stock_heat = [], {}, {}
    name_to_code = {n: c for c, n in (stock_names or {}).items() if len(n) >= 2}
    for _, row in news.iterrows():
        text = f"{row['title']} {row['content']}"
        s, hits = score_text(text)
        boards = tag_boards(text)
        stocks = [c for n, c in name_to_code.items() if n in text][:5]
        for b in boards:
            h = board_heat.setdefault(b, {"count": 0, "score": 0.0})
            h["count"] += 1
            h["score"] += s
        for c in stocks:
            h = stock_heat.setdefault(c, {"count": 0, "score": 0.0, "titles": []})
            h["count"] += 1
            h["score"] += s
            if len(h["titles"]) < 3:
                h["titles"].append(row["title"][:60])
        if hits or boards:
            items.append({"title": row["title"][:80], "time": row["time"], "source": row["source"],
                          "url": row.get("url", ""), "score": round(s, 1), "hits": hits[:5], "boards": boards[:4],
                          "stocks": stocks})
    items.sort(key=lambda x: abs(x["score"]), reverse=True)
    return {"items": items[:40], "board_heat": board_heat, "stock_heat": stock_heat}


def stock_sentiment(news: pd.DataFrame) -> tuple[float, list[dict]]:
    """个股新闻情绪（近期新闻累计分），返回 (分数, 最相关新闻)。"""
    out, total = [], 0.0
    for _, row in news.head(20).iterrows():
        s, hits = score_text(f"{row['title']} {row['content']}")
        total += s
        if hits:
            out.append({"title": row["title"][:60], "time": row["time"], "score": round(s, 1), "url": row.get("url", "")})
    return total, out[:5]
