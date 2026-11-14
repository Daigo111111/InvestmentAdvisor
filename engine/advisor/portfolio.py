"""持仓读写与组合层面的计算（估值、收益、回撤、分类）。"""
from __future__ import annotations

import json

from . import crypto
from .config import (DEMO_HOLDINGS, HOLDINGS_ENC, HOLDINGS_PLAIN, REPORT_ENC, STATE_ENC, DATA_DIR, RiskSettings,
                     passphrase)
from .util import clean, log, r

DEMO_REPORT = DATA_DIR / "demo_report.json"
DEMO_STATE = DATA_DIR / "demo_state.json"

EMPTY_HOLDINGS = {"funds": [], "stocks": [], "cash": 0, "settings": {}}


class Store:
    """统一读写持仓/报告/状态。demo 模式使用明文示例数据，正式模式使用口令加密文件。"""

    def __init__(self, demo: bool = False):
        self.demo = demo
        self.pw = passphrase()
        if not demo and not self.pw:
            raise SystemExit("未设置 ADVISOR_PASSPHRASE（加密口令）。本地调试可加 --demo 使用示例数据。")

    def holdings(self) -> dict:
        if self.demo:
            return json.loads(DEMO_HOLDINGS.read_text(encoding="utf-8"))
        if HOLDINGS_PLAIN.exists():
            log.info("使用本地明文持仓 %s", HOLDINGS_PLAIN)
            return json.loads(HOLDINGS_PLAIN.read_text(encoding="utf-8"))
        try:
            return crypto.load_encrypted(HOLDINGS_ENC, self.pw, EMPTY_HOLDINGS)
        except Exception as e:  # noqa: BLE001 InvalidTag 等
            raise SystemExit(f"无法解密 {HOLDINGS_ENC.name}：口令与网页保存持仓时使用的口令不一致（{type(e).__name__}）")

    def save_holdings(self, h: dict) -> None:
        crypto.save_encrypted(HOLDINGS_ENC, h, self.pw)

    def _load(self, plain_path, enc_path, default):
        if self.demo:
            return json.loads(plain_path.read_text(encoding="utf-8")) if plain_path.exists() else default
        try:
            return crypto.load_encrypted(enc_path, self.pw, default)
        except Exception:  # noqa: BLE001 口令更换后旧报告无法解密，重新生成
            log.warning("%s 无法用当前口令解密，将重新生成", enc_path.name)
            return default

    def _save(self, plain_path, enc_path, obj):
        if self.demo:
            plain_path.write_text(json.dumps(clean(obj), ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
        else:
            crypto.save_encrypted(enc_path, obj, self.pw)

    def report(self) -> dict:
        return self._load(DEMO_REPORT, REPORT_ENC, {})

    def save_report(self, rep: dict) -> None:
        self._save(DEMO_REPORT, REPORT_ENC, rep)

    def state(self) -> dict:
        return self._load(DEMO_STATE, STATE_ENC, {"estimates": {}, "portfolio": []})

    def save_state(self, st: dict) -> None:
        self._save(DEMO_STATE, STATE_ENC, st)


def risk_of(h: dict) -> RiskSettings:
    return RiskSettings.from_dict(h.get("settings"))


def portfolio_summary(fund_adv: list[dict], stock_adv: list[dict], cash: float, state: dict, today: str,
                      record: bool, closed: list[dict] | None = None) -> dict:
    fv = sum(a["metrics"]["value"] or 0 for a in fund_adv)
    sv = sum(a["metrics"]["value"] or 0 for a in stock_adv)
    fcost = sum((a["metrics"]["value"] or 0) / (1 + (a["metrics"]["ret_hold"] or 0)) for a in fund_adv)
    scost = sum((a["metrics"]["value"] or 0) / (1 + (a["metrics"]["ret_hold"] or 0)) for a in stock_adv)
    total = fv + sv + cash
    cost = fcost + scost + cash
    realized = sum((a["metrics"].get("realized") or 0) for a in fund_adv + stock_adv) + \
        sum((c.get("realized") or 0) for c in closed or [])
    hist = [p for p in state.get("portfolio", []) if p["date"] != today]
    if record:
        hist.append({"date": today, "value": r(total, 2), "cost": r(cost, 2)})
        state["portfolio"] = hist[-750:]
    series = [p["value"] / p["cost"] if p["cost"] else 1 for p in hist] + ([] if record else [total / cost if cost else 1])
    peak = max(series) if series else 1
    dd = (series[-1] / peak - 1) if series else 0
    return {"total": r(total, 2), "funds": r(fv, 2), "stocks": r(sv, 2), "cash": r(cash, 2), "cost": r(cost, 2),
            "pnl": r(total - cost, 2), "ret": r(total / cost - 1 if cost else 0, 4), "drawdown": r(dd, 4),
            "realized": r(realized, 2), "total_pnl": r(total - cost + realized, 2),
            "history": hist[-250:]}
