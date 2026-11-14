"""与浏览器 WebCrypto 互通的加密：PBKDF2-SHA256 派生密钥 + AES-256-GCM。

密文格式 {"v":1,"kdf":"PBKDF2-SHA256","iter":N,"salt":b64,"iv":b64,"ct":b64}，
ct 为 密文||16字节tag，与 WebCrypto AES-GCM 输出布局一致。
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .util import clean

ITERATIONS = 210_000


def _key(password: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def encrypt_obj(obj: Any, password: str) -> dict:
    if not password:
        raise ValueError("缺少加密口令 ADVISOR_PASSPHRASE")
    salt, iv = os.urandom(16), os.urandom(12)
    data = json.dumps(clean(obj), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ct = AESGCM(_key(password, salt, ITERATIONS)).encrypt(iv, data, None)
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITERATIONS, "salt": _b64(salt), "iv": _b64(iv), "ct": _b64(ct)}


def decrypt_obj(env: dict, password: str) -> Any:
    salt = base64.b64decode(env["salt"])
    iv = base64.b64decode(env["iv"])
    ct = base64.b64decode(env["ct"])
    key = _key(password, salt, int(env.get("iter", ITERATIONS)))
    return json.loads(AESGCM(key).decrypt(iv, ct, None).decode("utf-8"))


def save_encrypted(path: Path, obj: Any, password: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(encrypt_obj(obj, password)), encoding="utf-8")


def load_encrypted(path: Path, password: str, default: Any = None) -> Any:
    if not path.exists():
        return default
    return decrypt_obj(json.loads(path.read_text(encoding="utf-8")), password)
