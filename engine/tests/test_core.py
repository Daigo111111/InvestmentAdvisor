from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advisor import crypto  # noqa: E402
from advisor.analysis import fund_advisor as fa  # noqa: E402
from advisor.analysis.sentiment import score_text  # noqa: E402
from advisor.analysis.stock_advisor import advise_stock  # noqa: E402
from advisor.config import RiskSettings  # noqa: E402
from advisor.data.fund import fee_rate_for_days, parse_fee_period  # noqa: E402

TODAY = date(2026, 11, 9)


def _nav(values) -> pd.DataFrame:
    idx = pd.bdate_range(end="2026-11-06", periods=len(values))
    v = pd.Series(values, index=idx, dtype=float)
    return pd.DataFrame({"nav": v, "pct": v.pct_change().fillna(0) * 100, "acc_nav": v})


def _ctx(nav, est, holding, **kw):
    base = {"code": "000001", "name": "测试基金", "type": "混合型-偏股", "category": "equity", "nav": nav,
            "est_pct": est, "holding": fa.normalize_holding(holding, nav),
            "fee_table": [(0, 7, 0.015), (7, 365, 0.005), (365, float("inf"), 0.0)],
            "sector_pct": 0.5, "rank_pct": 0.5, "total_value": 1e6, "cash": 1e5, "portfolio_dd": 0.0}
    base.update(kw)
    return base


def test_crypto_roundtrip():
    obj = {"funds": [{"code": "005827", "amount": 1000.5}], "中文": "持仓"}
    env = crypto.encrypt_obj(obj, "pw-123")
    assert crypto.decrypt_obj(env, "pw-123") == obj


def test_fee_period_parse():
    assert parse_fee_period("小于等于6天") == (0, 7)
    assert parse_fee_period("大于等于7天，小于等于29天") == (7, 30)
    assert parse_fee_period("大于等于1年，小于2年") == (365, 730)
    table = [(0, 7, 0.015), (7, 30, 0.0075), (30, float("inf"), 0.0)]
    assert fee_rate_for_days(table, 3) == 0.015 and fee_rate_for_days(table, 10) == 0.0075


def test_sentiment_negation_and_overlap():
    pos, _ = score_text("公司发布业绩预增公告")
    neg, _ = score_text("控股股东拟减持")
    negated, _ = score_text("公司未减持")
    assert pos > 0 and neg < 0 and negated > 0
    s, hits = score_text("政策支持")  # 长词优先，“支持”不重复计分
    assert hits == ["政策支持"] and s == 2
    tariff, _ = score_text("11月10日起继续暂停实施24%的对美加征关税税率")
    assert tariff > 0


def test_dip_buy_in_uptrend():
    nav = _nav(np.linspace(1.0, 1.3, 200))
    adv = fa.advise(_ctx(nav, -2.0, {"shares": 10000, "cost_nav": 1.1, "buy_date": "2025-01-01"}), RiskSettings(), TODAY)
    assert adv["action"] == "加仓" and adv["ratio"] > 0


def test_stop_loss_in_downtrend():
    nav = _nav(np.linspace(1.3, 1.0, 200))
    adv = fa.advise(_ctx(nav, -1.0, {"shares": 10000, "cost_nav": 1.4, "buy_date": "2025-01-01"}), RiskSettings(), TODAY)
    assert adv["action"] in ("卖出", "减仓") and adv["level"] == "高" and adv["fee"] is not None


def test_short_holding_fee_guard():
    nav = _nav(np.r_[np.linspace(1.0, 1.6, 150), np.linspace(1.6, 1.4, 50)])
    h = {"shares": 10000, "cost_nav": 1.0,
         "lots": [{"date": "2026-01-02", "shares": 9000}, {"date": "2026-11-05", "shares": 1000}]}
    adv = fa.advise(_ctx(nav, 0.5, h), RiskSettings(), TODAY)
    assert adv["action"] == "不动" and any("7 天" in x for x in adv["reasons"])


def test_amount_profit_normalize():
    nav = _nav([1.0] * 10 + [2.0])
    h = fa.normalize_holding({"amount": 2000, "profit": 500}, nav)
    assert h["shares"] == 1000 and abs(h["cost_nav"] - 1.5) < 1e-9


def test_stock_trailing_stop_rounds_to_lots():
    idx = pd.bdate_range(end="2026-11-06", periods=120)
    close = pd.Series(np.r_[np.linspace(10, 20, 100), np.linspace(20, 15, 20)], index=idx)
    hist = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1})
    adv = advise_stock({"code": "600000", "shares": 300, "cost": 12}, hist, None, 0.0, [], 1e5, RiskSettings(), TODAY)
    assert adv["action"] in ("卖出", "减仓") and adv["shares"] % 100 == 0 and adv["shares"] > 0
