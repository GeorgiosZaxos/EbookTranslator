"""Glossary placeholder protection and restoration."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class Glossary:
    """Protect glossary terms during translation, then restore target terms."""

    def __init__(self, path: str = "") -> None:
        self.entries: list[tuple[str, str]] = []
        if path:
            self.load(Path(path))

    def load(self, path: Path) -> None:
        """Load source=target lines; ignore comments and malformed entries."""
        self.entries.clear()
        if not path.exists():
            logger.warning("Glossary file does not exist: %s", path)
            return
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            source, target = (part.strip() for part in line.split("=", 1))
            if source and target:
                self.entries.append((source, target))
        self.entries.sort(key=lambda item: len(item[0]), reverse=True)
        logger.info("Loaded %d glossary terms", len(self.entries))

    def protect(self, text: str) -> tuple[str, dict[str, str]]:
        """Replace exact case-insensitive source terms with stable placeholders."""
        mapping: dict[str, str] = {}
        result = text
        for index, (source, target) in enumerate(self.entries):
            placeholder = f"ZXQGLOSSARY{index:05d}QXZ"
            pattern = re.compile(re.escape(source), re.IGNORECASE)
            result, count = pattern.subn(placeholder, result)
            if count:
                mapping[placeholder] = target
        return result, mapping

    @staticmethod
    def restore(text: str, mapping: dict[str, str]) -> str:
        """Restore glossary placeholders without interpreting replacement backslashes."""
        for placeholder, target in mapping.items():
            text = text.replace(placeholder, target)
        return text


def select_glossary_path(
    source_language: str,
    target_language: str,
    english_greek_path: str,
    greek_english_path: str,
    legacy_path: str = "",
) -> str:
    """Select the matching English/Greek glossary for a translation direction.

    Auto-detect→Greek uses English→Greek, while Auto-detect→English uses
    Greek→English. Other language pairs retain compatibility with the legacy
    single-glossary setting.
    """
    source = (source_language or "").strip().casefold()
    target = (target_language or "").strip().casefold()

    if target == "greek" and source in {"english", "auto-detect", "auto detect"}:
        return english_greek_path
    if target == "english" and source in {"greek", "auto-detect", "auto detect"}:
        return greek_english_path
    return legacy_path
