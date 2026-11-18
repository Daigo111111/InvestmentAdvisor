from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advisor import ledger  # noqa: E402
from advisor.analysis import calibration as cal  # noqa: E402
from advisor.analysis import tracking as tk  # noqa: E402


def _nav(values, end="2026-11-06"):
    idx = pd.bdate_range(end=end, periods=len(values))
    return pd.DataFrame({"nav": values, "acc_nav": values}, index=idx)


def test_fund_buy_then_sell_fifo_and_realized():
    nav = _nav([1.0, 1.0, 1.2, 1.2, 1.5])
    d = [x.strftime("%Y-%m-%d") for x in nav.index]
    h = {"shares": 1000.0, "cost_nav": 1.0, "lots": [{"date": "2026-01-05", "shares": 1000.0}]}
    trades = [
        {"date": d[2], "asset": "fund", "code": "000001", "side": "buy", "amount": 1200},  # 1200/1.2 = 1000 份
        {"date": d[4], "asset": "fund", "code": "000001", "side": "sell", "shares": 1500},
    ]
    out = ledger.apply_fund_trades(h, trades, nav)
    assert abs(out["shares"] - 500) < 1e-6
    # 平均成本 (1000+1200)/2000 = 1.1；卖出 1500 份 @1.5 → 已实现 1500*(1.5-1.1) = 600
    assert abs(out["realized"] - 600) < 1e-6 and abs(out["cost_nav"] - 1.1) < 1e-9
    # 先进先出：最早的 1000 份先卖光，剩下的是 d[2] 买入的 500 份
    assert out["lots"] == [{"date": d[2], "shares": 500.0}]
    assert [round(f, 2) for _, f in out["flows"]] == [-1200, 2250]


def test_fund_buy_on_unpublished_day_is_pending():
    nav = _nav([1.0, 1.1])
    out = ledger.apply_fund_trades({"shares": 0, "cost_nav": 1.0, "lots": []},
                                   [{"date": "2099-01-01", "asset": "fund", "code": "x", "side": "buy", "amount": 110}], nav)
    assert out["pending"] and abs(out["shares"] - 100) < 1e-6


def test_stock_trades_and_cash():
    item = {"code": "600000", "shares": 100, "cost": 10.0, "buy_date": "2026-01-01"}
    trades = [{"date": "2026-02-01", "asset": "stock", "code": "600000", "side": "buy", "shares": 100, "price": 12, "fee": 5},
              {"date": "2026-03-01", "asset": "stock", "code": "600000", "side": "sell", "shares": 200, "price": 15, "fee": 5}]
    out = ledger.apply_stock_trades(item, trades)
    assert out["shares"] == 0 and abs(out["realized"] - (3000 - 5 - 2205)) < 1e-6
    assert ledger.cash_after_trades(1000, "2026-02-15", out["flows"]) == 1000 + 2995


def test_trades_before_as_of_are_ignored_and_new_codes_merged():
    trades = [{"date": "2026-01-01", "asset": "fund", "code": "1", "side": "buy", "amount": 1},
              {"date": "2026-03-01", "asset": "fund", "code": "1", "side": "buy", "amount": 1},
              {"date": "2026-03-01", "asset": "fund", "code": "2", "side": "buy", "amount": 1}]
    assert len(ledger.trades_for(trades, "fund", "000001", "2026-02-01")) == 1
    merged = ledger.merge_items([{"code": "000001"}], trades, "fund")
    assert [m["code"] for m in merged] == ["000001", "000002"]


def test_calibration_beta_and_source_choice():
    hist = [{"d": f"d{i}", "own": 1.0 * s, "em": 0.5 * s, "actual": 0.8 * s} for i, s in enumerate([1, -1, 2, -2, 1.5, -0.5])]
    beta, n = cal.beta_of(hist)
    assert n == 6 and abs(beta - 0.8) < 1e-9
    c = cal.calibrate(2.0, 1.0, 0.6, hist)
    assert c["source"] == "重仓股估算" and abs(c["est"] - 1.6) < 1e-9 and "校正" in c["note"]
    assert cal.calibrate(None, 1.0, 0.6, [])["source"] == "东财估值"


def test_record_actual_supports_old_float_format():
    st = {"estimates": {"2026-11-06": {"000001": 1.2}}}
    e = cal.record_actual(st, "2026-11-06", "000001", 1.0)
    assert e["used"] == 1.2 and st["est_hist"]["000001"][0]["actual"] == 1.0


def test_tracking_effect_and_follow(monkeypatch):
    s = pd.Series([1.0, 0.9, 0.85, 0.8, 0.8, 0.8, 0.8], index=pd.bdate_range("2026-10-01", periods=7))
    monkeypatch.setattr(tk, "_series", lambda asset, code: s)
    monkeypatch.setattr(tk.mk, "index_hist", lambda sym: s)
    st = {}
    rep = {"funds": [{"code": "000001", "name": "基金A", "action": "减仓", "rule": "trailing_tp", "ratio": 0.33},
                     {"code": "000002", "name": "基金B", "action": "不动", "rule": "hold"}], "stocks": []}
    tk.record_advice(st, rep, "2026-10-01")
    tk.record_advice(st, rep, "2026-10-01")  # 同日重复运行不重复记录
    assert len(st["signals"]) == 1
    tk.evaluate(st, date(2026, 11, 1))
    assert abs(st["signals"][0]["r5"] - (-0.2)) < 1e-9
    trades = [{"date": "2026-10-02", "code": "000001", "side": "sell"}]
    out = tk.report(st, trades)
    rule = out["rules"][0]
    assert rule["win5"] == 1.0 and abs(rule["avg5"] - 0.2) < 1e-9  # 减仓后下跌 20%，效果为正
    assert out["follow"]["followed"] == 1 and out["recent"][0]["followed"] is True


def test_once_skips_duplicate_run_same_day(monkeypatch):
    from advisor import jobs

    class FakeStore:
        def __init__(self, demo=False):
            pass

        def holdings(self):
            return {"funds": [], "stocks": [], "cash": 0, "settings": {}}

        def state(self):
            return {"done": {"close": "2026-11-17 1412"}}

        def report(self):
            raise AssertionError("重复触发时不应继续执行")

    monkeypatch.setattr(jobs, "Store", FakeStore)
    monkeypatch.setattr(jobs.mk, "is_trade_day", lambda d: True)
    import datetime as dt
    monkeypatch.setattr(jobs, "now_cst", lambda: dt.datetime(2026, 11, 17, 14, 20, tzinfo=dt.timezone(dt.timedelta(hours=8))))
    assert jobs.run("close", once=True) == {}


def test_once_skips_before_window(monkeypatch):
    from advisor import jobs
    import datetime as dt

    class FakeStore:
        def __init__(self, demo=False):
            pass

        def holdings(self):
            return {"funds": [], "stocks": [], "cash": 0, "settings": {}}

        def state(self):
            return {}

        def report(self):
            raise AssertionError("时段之前不应执行")

    monkeypatch.setattr(jobs, "Store", FakeStore)
    monkeypatch.setattr(jobs.mk, "is_trade_day", lambda d: True)
    monkeypatch.setattr(jobs, "now_cst", lambda: dt.datetime(2026, 11, 17, 11, 30, tzinfo=dt.timezone(dt.timedelta(hours=8))))
    assert jobs.run("close", once=True) == {}
