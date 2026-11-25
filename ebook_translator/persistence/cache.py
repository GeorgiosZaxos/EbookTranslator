"""Thread-safe in-memory translation cache.

Persistent restart progress is handled by the per-job JSON checkpoint. This
cache only avoids duplicate requests during the current application run.
"""

from __future__ import annotations

import hashlib
import logging
import threading

logger = logging.getLogger(__name__)


class TranslationCache:
    """Small process-local cache with the same interface as the former SQLite cache."""

    def __init__(self, path=None) -> None:
        self._values: dict[str, str] = {}
        self._lock = threading.RLock()
        logger.debug("Initialized in-memory translation cache")

    @staticmethod
    def make_key(text: str, source: str, target: str, endpoint: str, model: str) -> str:
        raw = "\0".join((text, source, target, endpoint.rstrip("/"), model))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._values.get(key)

    def put(self, key: str, source_text: str, translated_text: str,
            provider: str, model: str, source: str, target: str) -> None:
        with self._lock:
            self._values[key] = translated_text
        logger.debug("Cached translated segment %s in memory", key[:12])
