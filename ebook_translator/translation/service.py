"""Translation orchestration, segmentation, retries and in-memory caching."""

from __future__ import annotations

import logging
import time
import threading

from ebook_translator.domain import TranslationResult
from ebook_translator.persistence.cache import TranslationCache
from ebook_translator.translation.glossary import Glossary
from ebook_translator.translation.providers import TranslationProvider
from ebook_translator.text_utils import decode_entities

logger = logging.getLogger(__name__)


def split_text(text: str, max_chars: int) -> list[str]:
    """Split text near paragraph/sentence boundaries without dropping characters."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        boundary = max(
            remaining.rfind("\n\n", 0, max_chars),
            remaining.rfind(". ", 0, max_chars),
            remaining.rfind(" ", 0, max_chars),
        )
        if boundary < max_chars // 2:
            boundary = max_chars
        else:
            # Keep a sentence delimiter with the preceding segment.
            boundary = boundary + (2 if remaining[boundary:boundary + 2] == "\n\n" else 1)
        chunks.append(remaining[:boundary])
        remaining = remaining[boundary:]
    if remaining:
        chunks.append(remaining)
    return chunks


class TranslationService:
    """Translate text with glossary protection, retries and persistent caching."""

    def __init__(self, provider: TranslationProvider, cache: TranslationCache,
                 endpoint: str, model: str, source_language: str,
                 target_language: str, glossary: Glossary | None = None,
                 max_retries: int = 3, segment_chars: int = 3500) -> None:
        self.provider = provider
        self.cache = cache
        self.endpoint = endpoint
        self.model = model
        self.source_language = source_language
        self.target_language = target_language
        self.glossary = glossary or Glossary()
        self.max_retries = max_retries
        self.segment_chars = segment_chars
        self._key_locks: dict[str, threading.Lock] = {}
        self._key_locks_guard = threading.Lock()

    def translate(self, text: str, progress_callback=None, cancel_event=None) -> str:
        """Translate all segments, emitting progress and respecting cancellation."""
        segments = split_text(text, self.segment_chars)
        translated: list[str] = []
        for index, segment in enumerate(segments, start=1):
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Translation cancelled")
            translated.append(self._translate_one(segment, cancel_event=cancel_event))
            if progress_callback:
                progress_callback(index, len(segments), f"Translated segment {index}/{len(segments)}")
        # Decode HTML/XML entities returned literally by translation services.
        # This prevents strings such as '&#39;' leaking into translated books.
        return decode_entities("".join(translated))

    def _translate_one(self, source_text: str, cancel_event=None) -> str:
        """Translate one segment, coalescing concurrent requests for identical text."""
        key = self.cache.make_key(
            source_text, self.source_language, self.target_language, self.endpoint, self.model
        )
        # Only one worker may miss/translate a given cache key at a time. Other
        # identical targets wait, then reuse the first worker's result.
        with self._key_locks_guard:
            key_lock = self._key_locks.setdefault(key, threading.Lock())

        with key_lock:
            cached = self.cache.get(key)
            if cached is not None:
                logger.debug("Cache hit for segment %s", key[:12])
                return cached

            protected, mapping = self.glossary.protect(source_text)
            last_error: Exception | None = None
            for attempt in range(1, self.max_retries + 1):
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("Translation cancelled")
                try:
                    result = self.provider.translate(
                        protected, self.source_language, self.target_language
                    )
                    result = self.glossary.restore(result, mapping)
                    self.cache.put(
                        key, source_text, result, "provider", self.model,
                        self.source_language, self.target_language,
                    )
                    return result
                except Exception as exc:  # Provider failures are retried with bounded backoff.
                    last_error = exc
                    logger.warning(
                        "Translation attempt %d/%d failed: %s", attempt, self.max_retries, exc
                    )
                    if attempt < self.max_retries:
                        delay = min(2 ** (attempt - 1), 8)
                        # Event.wait makes retry backoff interruptible by Stop.
                        if cancel_event and cancel_event.wait(delay):
                            raise InterruptedError("Translation cancelled")
                        if not cancel_event:
                            time.sleep(delay)
            raise RuntimeError(
                f"Translation failed after {self.max_retries} attempts"
            ) from last_error
