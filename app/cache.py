import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class TTLCache:
    default_ttl_seconds: int = 300
    _store: Dict[str, Tuple[float, Any]] = None

    def __post_init__(self):
        if self._store is None:
            self._store = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if time.time() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        self._store[key] = (time.time() + ttl, value)

    def clear(self) -> None:
        self._store.clear()


cache = TTLCache(default_ttl_seconds=300)
