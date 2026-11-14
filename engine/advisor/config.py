from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / ".cache"
WEB_DIR = ROOT / "web"

HOLDINGS_ENC = DATA_DIR / "holdings.enc.json"
HOLDINGS_PLAIN = DATA_DIR / "holdings.json"  # 仅本地调试，已 gitignore
DEMO_HOLDINGS = DATA_DIR / "demo_holdings.json"
REPORT_ENC = DATA_DIR / "report.enc.json"
STATE_ENC = DATA_DIR / "state.enc.json"


@dataclass
class RiskSettings:
    """风险参数。可在持仓文件的 settings 字段中覆盖。"""

    max_drawdown: float = 0.20        # 组合最大回撤约束
    target_return: float = 0.20       # 期望年化（仅用于展示与回测对照）
    min_return: float = 0.07          # 可接受年化下限（仅用于展示与回测对照）
    fund_stop_loss: float = -0.12     # 单基金止损线（持有收益率）
    fund_take_profit: float = 0.25    # 止盈观察线
    trailing_drawdown: float = 0.08   # 从持有期高点回撤多少触发移动止盈
    dip_buy_threshold: float = -1.5   # 当日估算跌幅(%)达到多少视为加仓机会
    stock_atr_mult: float = 2.5       # 股票 ATR 移动止损倍数
    single_stock_cap: float = 0.10    # 单只股票占总资产上限
    single_fund_cap: float = 0.25     # 单只基金占总资产上限
    sector_cap: float = 0.35          # 单一板块占总资产上限

    @classmethod
    def from_dict(cls, d: dict | None) -> "RiskSettings":
        s = cls()
        for f in fields(cls):
            if d and f.name in d and d[f.name] is not None:
                setattr(s, f.name, float(d[f.name]))
        return s


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def passphrase() -> str:
    return env("ADVISOR_PASSPHRASE")


def pages_url() -> str:
    return env("PAGES_URL")
