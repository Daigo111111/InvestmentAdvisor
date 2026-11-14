from __future__ import annotations

import akshare as ak
import pandas as pd

from ..util import cached, retry, safe


@cached(15 * 60)
@retry()
def _cls() -> pd.DataFrame:
    df = ak.stock_info_global_cls(symbol="全部")
    return pd.DataFrame({"title": df["标题"].astype(str), "content": df["内容"].astype(str),
                         "time": df["发布日期"].astype(str) + " " + df["发布时间"].astype(str), "source": "财联社"})


@cached(15 * 60)
@retry()
def _em_global() -> pd.DataFrame:
    df = ak.stock_info_global_em()
    return pd.DataFrame({"title": df["标题"].astype(str), "content": df["摘要"].astype(str),
                         "time": df["发布时间"].astype(str), "source": "东方财富", "url": df["链接"].astype(str)})


@cached(15 * 60)
@retry()
def _sina_global() -> pd.DataFrame:
    df = ak.stock_info_global_sina()
    return pd.DataFrame({"title": df["内容"].astype(str).str[:40], "content": df["内容"].astype(str),
                         "time": df["时间"].astype(str), "source": "新浪财经"})


def market_news() -> pd.DataFrame:
    """多源合并的市场快讯，按时间倒序、按标题去重。任一来源失败不影响其他来源。"""
    frames = [safe(f, None, f.__name__) for f in (_cls, _em_global, _sina_global)]
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame(columns=["title", "content", "time", "source", "url"])
    df = pd.concat(frames, ignore_index=True)
    if "url" not in df:
        df["url"] = ""
    df["url"] = df["url"].fillna("")
    df["key"] = df["title"].str.replace(r"[\s【】\[\]：:，,。]", "", regex=True).str[:18]
    df = df.drop_duplicates(subset=["key"]).sort_values("time", ascending=False).drop(columns="key")
    return df.reset_index(drop=True)


@cached(30 * 60)
@retry()
def stock_news(code: str) -> pd.DataFrame:
    df = ak.stock_news_em(symbol=code)
    return pd.DataFrame({"title": df["新闻标题"].astype(str), "content": df["新闻内容"].astype(str),
                         "time": df["发布时间"].astype(str), "source": df["文章来源"].astype(str),
                         "url": df["新闻链接"].astype(str)})
