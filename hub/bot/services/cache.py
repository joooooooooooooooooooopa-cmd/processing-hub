from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple


class TTLCache:
    def __init__(self, default_ttl: int = 3600):
        self._store: Dict[str, Tuple[Any, float]] = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        if key in self._store:
            value, expires = self._store[key]
            if time.time() < expires:
                return value
            del self._store[key]
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        t = ttl if ttl is not None else self._default_ttl
        self._store[key] = (value, time.time() + t)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def cleanup(self) -> int:
        now = time.time()
        expired = [k for k, (_, exp) in self._store.items() if now >= exp]
        for k in expired:
            del self._store[k]
        return len(expired)

    def clear(self) -> None:
        self._store.clear()


cache = TTLCache()
