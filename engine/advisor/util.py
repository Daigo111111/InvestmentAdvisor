from __future__ import annotations

import functools
import hashlib
import logging
import math
import pickle
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .config import CACHE_DIR

log = logging.getLogger("advisor")
CST = timezone(timedelta(hours=8))


def now_cst() -> datetime:
    return datetime.now(CST)


def today_str() -> str:
    return now_cst().strftime("%Y-%m-%d")


_DOWN: set[str] = set()


def retry(times: int = 3, wait: float = 1.0):
    """网络接口容错：失败重试、指数退避；同一接口连续失败后本次运行内熔断，避免反复等待。"""

    def deco(fn: Callable):
        name = f"{fn.__module__}.{fn.__name__}"

        @functools.wraps(fn)
        def wrapper(*a, **kw):
            if _DOWN and name in _DOWN:
                raise ConnectionError(f"{fn.__name__} 已熔断（本次运行内多次失败）")
            last = None
            for i in range(times):
                try:
                    val = fn(*a, **kw)
                    _FAILS.pop(name, None)
                    return val
                except Exception as e:  # noqa: BLE001 第三方数据源异常类型不统一
                    last = e
                    log.warning("%s 第%d次失败: %s", fn.__name__, i + 1, e)
                    if i < times - 1:
                        time.sleep(wait * (2 ** i))
            _FAILS[name] = _FAILS.get(name, 0) + 1
            if _FAILS[name] >= 2:
                _DOWN.add(name)
                log.error("%s 连续失败，本次运行内熔断", fn.__name__)
            raise last  # type: ignore[misc]

        return wrapper

    return deco


_FAILS: dict[str, int] = {}


def cached(ttl_seconds: int):
    """磁盘缓存，避免重复请求数据源（同一次运行和短时间内多次运行）。"""

    def deco(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            key = hashlib.md5(repr((fn.__module__, fn.__name__, a, sorted(kw.items()))).encode()).hexdigest()
            path = CACHE_DIR / f"{fn.__name__}_{key}.pkl"
            if path.exists() and time.time() - path.stat().st_mtime < ttl_seconds:
                try:
                    with path.open("rb") as f:
                        return pickle.load(f)
                except Exception:  # noqa: BLE001 缓存损坏则重新拉取
                    pass
            val = fn(*a, **kw)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as f:
                pickle.dump(val, f)
            return val

        return wrapper

    return deco


def safe(fn: Callable, default: Any = None, label: str = "") -> Any:
    """执行可失败的步骤，失败时记录并返回默认值，保证整份报告不因单个数据源失败而中断。"""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        log.error("步骤失败 %s: %s", label or getattr(fn, "__name__", "?"), e)
        return default


def num(v: Any, default: float | None = None) -> float | None:
    try:
        f = float(str(v).replace("%", "").replace(",", ""))
        return default if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return default


def r(v: float | None, n: int = 2) -> float | None:
    if v is None:
        return None
    f = float(v)
    return None if math.isnan(f) or math.isinf(f) else round(f, n)


def clean(obj: Any) -> Any:
    """递归把 NaN/Inf 转为 None、numpy 类型转为原生类型，保证输出合法 JSON（浏览器 JSON.parse 不接受 NaN）。"""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return obj
    if hasattr(obj, "item"):  # numpy 标量
        obj = obj.item()
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    return obj


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
