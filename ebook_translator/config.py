"""Application settings with user-profile storage."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


def app_data_dir() -> Path:
    """Return a Windows-friendly per-user data directory."""
    base = Path(os.environ.get("APPDATA", Path.home() / ".config"))
    path = base / "EbookTranslator"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class AppConfig:
    provider: str = "google_free_new"
    endpoint: str = "http://localhost:11434/v1"
    model: str = "llama3"
    source_language: str = "Auto-detect"
    target_language: str = "Greek"
    temperature: float = 0.2
    max_tokens: int = 4096
    request_timeout: int = 120
    max_retries: int = 3
    segment_chars: int = 3500
    parallel_workers: int = 3
    # Direction-specific glossaries; glossary_path remains for old settings files.
    english_greek_glossary_path: str = ""
    greek_english_glossary_path: str = ""
    glossary_path: str = ""
    log_level: str = "INFO"

    @classmethod
    def load(cls) -> "AppConfig":
        """Load settings; fall back to safe defaults on malformed files."""
        path = app_data_dir() / "settings.json"
        if not path.exists():
            return cls()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            allowed = {key: value for key, value in payload.items() if key in cls.__dataclass_fields__}
            logger.info("Loaded settings from %s", path)
            return cls(**allowed)
        except (OSError, ValueError, TypeError):
            logger.exception("Could not load settings from %s; defaults will be used", path)
            return cls()

    def save(self) -> None:
        """Persist non-secret settings atomically."""
        path = app_data_dir() / "settings.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        temporary.replace(path)
        logger.info("Saved settings to %s", path)
