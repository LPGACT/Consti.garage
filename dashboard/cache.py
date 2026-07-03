# dashboard/cache.py — TTL cache trivial, para no pegarle a la Sheets API
# en cada request del dashboard. No amerita una dependencia nueva.

import time
from typing import Callable, TypeVar

T = TypeVar('T')

_cache: dict = {}


def cached(key: str, ttl_seconds: int, fn: Callable[[], T]) -> T:
    now = time.monotonic()
    entry = _cache.get(key)
    if entry is not None and now - entry[0] < ttl_seconds:
        return entry[1]
    value = fn()
    _cache[key] = (now, value)
    return value
