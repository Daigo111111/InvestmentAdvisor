"""推送渠道：飞书群机器人（可选签名校验）、WxPusher（微信）。未配置的渠道自动跳过。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

import requests

from .config import env, pages_url
from .util import log


def _feishu_sign(secret: str, ts: int) -> str:
    key = f"{ts}\n{secret}".encode("utf-8")
    return base64.b64encode(hmac.new(key, b"", digestmod=hashlib.sha256).digest()).decode()


def send_feishu(title: str, md: str, color: str = "blue") -> bool:
    url = env("FEISHU_WEBHOOK")
    if not url:
        return False
    elements = [{"tag": "markdown", "content": md[:9000]}]
    if pages_url():
        elements.append({"tag": "action", "actions": [{"tag": "button", "type": "primary",
                                                        "text": {"tag": "plain_text", "content": "打开完整报告"},
                                                        "url": pages_url()}]})
    body: dict = {"msg_type": "interactive", "card": {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": color},
        "elements": elements}}
    if env("FEISHU_SECRET"):
        ts = int(time.time())
        body.update({"timestamp": str(ts), "sign": _feishu_sign(env("FEISHU_SECRET"), ts)})
    try:
        resp = requests.post(url, json=body, timeout=15).json()
        ok = resp.get("code", resp.get("StatusCode", -1)) == 0
        if not ok:
            log.error("飞书推送失败: %s", resp)
        return ok
    except Exception as e:  # noqa: BLE001
        log.error("飞书推送异常: %s", e)
        return False


def send_wxpusher(title: str, md: str) -> bool:
    token, uids = env("WXPUSHER_APP_TOKEN"), [u for u in env("WXPUSHER_UIDS").split(",") if u.strip()]
    if not token or not uids:
        return False
    body = {"appToken": token, "content": f"## {title}\n\n{md}", "summary": title[:95], "contentType": 3,
            "uids": [u.strip() for u in uids]}
    if pages_url():
        body["url"] = pages_url()
    try:
        resp = requests.post("https://wxpusher.zjiecode.com/api/send/message", json=body, timeout=15).json()
        ok = resp.get("success", False)
        if not ok:
            log.error("WxPusher 推送失败: %s", resp)
        return ok
    except Exception as e:  # noqa: BLE001
        log.error("WxPusher 推送异常: %s", e)
        return False


def push(title: str, md: str, color: str = "blue") -> dict:
    return {"feishu": send_feishu(title, md, color), "wxpusher": send_wxpusher(title, md)}
