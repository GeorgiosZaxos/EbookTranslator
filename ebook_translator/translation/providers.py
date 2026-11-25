"""Translation provider contracts and OpenAI-compatible implementation."""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod

import requests

logger = logging.getLogger(__name__)


class TranslationProvider(ABC):
    """Provider interface used by the orchestration service."""

    max_concurrency = 3

    @abstractmethod
    def translate(self, text: str, source_language: str, target_language: str,
                  context: str = "") -> str:
        raise NotImplementedError


class OpenAICompatibleProvider(TranslationProvider):
    """Chat-completions adapter for OpenAI-compatible services and Ollama."""

    def __init__(self, endpoint: str, model: str, api_key: str = "",
                 temperature: float = 0.2, max_tokens: int = 4096,
                 timeout: int = 120) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._thread_local = threading.local()

    @property
    def session(self) -> requests.Session:
        """Use a separate requests session per translation worker."""
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            self._thread_local.session = session
        return session

    def translate(self, text: str, source_language: str, target_language: str,
                  context: str = "") -> str:
        """Submit one translation request and return the assistant content."""
        system_prompt = (
            "You are a professional literary translator. Translate faithfully and naturally. "
            "Preserve paragraph boundaries, names, numbers, punctuation and meaning. "
            "Do not add explanations, notes, quotation marks, or commentary. "
            "Return only the translation."
        )
        if source_language and source_language != "Auto-detect":
            system_prompt += f" Source language: {source_language}."
        system_prompt += f" Target language: {target_language}."
        user_prompt = text
        if context:
            user_prompt = f"Context for consistency (do not translate this context):\n{context}\n\nText:\n{text}"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        url = f"{self.endpoint}/chat/completions"
        logger.debug("Sending translation request to %s using model %s", url, self.model)
        response = self.session.post(url, headers=headers, json=payload, timeout=self.timeout)
        if not response.ok:
            logger.error("Provider returned HTTP %s: %s", response.status_code, response.text[:1000])
            response.raise_for_status()
        data = response.json()
        try:
            result = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected chat-completions response: {data!r}") from exc
        if not isinstance(result, str) or not result.strip():
            raise RuntimeError("Provider returned an empty translation")
        return result.strip()
