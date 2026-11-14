"""大模型接口预留。默认不启用（纯规则）；配置环境变量后即可接入任意 OpenAI 兼容接口。

  LLM_PROVIDER=openai_compat
  LLM_BASE_URL=https://api.deepseek.com/v1         # 或千帆 https://qianfan.baidubce.com/v2
  LLM_API_KEY=...
  LLM_MODEL=deepseek-chat                           # 或 ernie-speed-128k 等

调用方统一使用 enhance(task, payload, fallback)：未配置或调用失败时返回 fallback（规则结果），
保证接入大模型不会影响原有流程。
"""
from __future__ import annotations

import json
from typing import Protocol

import requests

from .config import env
from .util import log

SYSTEM_PROMPT = ("你是严谨的投资研究助理。只依据提供的数据作答，不编造数据；结论简洁，"
                 "必须提示风险，不承诺收益。")

PROMPTS = {
    "news_digest": "以下是今日市场快讯与规则打分结果(JSON)。请用 5 条以内要点总结对 A 股各板块的影响：\n{data}",
    "fund_reason": "以下是一只基金的量化指标与规则建议(JSON)。请用 2~3 句话解释建议理由：\n{data}",
    "stock_reason": "以下是一只股票的基本面、技术面和新闻(JSON)。请用 2~3 句话说明推荐理由与主要风险：\n{data}",
    "ocr_parse": "以下是持仓截图 OCR 文本，请提取基金名称/代码、持有金额、持有收益，输出 JSON 数组：\n{data}",
}


class LLMProvider(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...


class OpenAICompatProvider:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model

    def complete(self, system: str, prompt: str) -> str:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "temperature": 0.2,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


def get_provider() -> LLMProvider | None:
    if env("LLM_PROVIDER") == "openai_compat" and env("LLM_API_KEY"):
        return OpenAICompatProvider(env("LLM_BASE_URL", "https://api.deepseek.com/v1"), env("LLM_API_KEY"),
                                    env("LLM_MODEL", "deepseek-chat"))
    return None


def enabled() -> bool:
    return get_provider() is not None


def enhance(task: str, payload: object, fallback: str) -> str:
    p = get_provider()
    if p is None:
        return fallback
    try:
        data = json.dumps(payload, ensure_ascii=False, default=str)[:6000]
        return p.complete(SYSTEM_PROMPT, PROMPTS[task].format(data=data))
    except Exception as e:  # noqa: BLE001 大模型失败时回退规则结果
        log.warning("LLM 调用失败，回退规则结果: %s", e)
        return fallback
