"""SRT and PGN adapters."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

SRT_BLOCK_RE = re.compile(
    r"(?P<head>^\s*\d+\s*\n\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+"
    r"\d{2}:\d{2}:\d{2},\d{3}[^\n]*\n)(?P<body>.*?)(?=\n{2,}|\Z)",
    re.MULTILINE | re.DOTALL,
)


def translate_srt(source: Path, output: Path, service, progress_callback=None, cancel_event=None) -> None:
    """Translate subtitle text while retaining indices and timestamps."""
    content = source.read_text(encoding="utf-8-sig")
    matches = list(SRT_BLOCK_RE.finditer(content))
    result_parts = []
    cursor = 0
    for index, match in enumerate(matches, start=1):
        result_parts.append(content[cursor:match.start()])
        body = match.group("body")
        translated = service.translate(body, cancel_event=cancel_event)
        result_parts.append(match.group("head") + translated)
        cursor = match.end()
        if progress_callback:
            progress_callback(index, len(matches), f"Translated subtitle {index}/{len(matches)}")
    result_parts.append(content[cursor:])
    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Translation cancelled before writing the SRT")
    output.write_text("".join(result_parts), encoding="utf-8")
    logger.info("Wrote translated SRT: %s", output)


def translate_pgn(source: Path, output: Path, service, progress_callback=None, cancel_event=None) -> None:
    """Translate brace comments while leaving PGN headers and move notation intact."""
    content = source.read_text(encoding="utf-8-sig")
    pattern = re.compile(r"\{([^{}]*)\}")
    matches = list(pattern.finditer(content))
    pieces = []
    cursor = 0
    for index, match in enumerate(matches, start=1):
        pieces.append(content[cursor:match.start()])
        translated = service.translate(match.group(1), cancel_event=cancel_event)
        pieces.append("{" + translated + "}")
        cursor = match.end()
        if progress_callback:
            progress_callback(index, len(matches), f"Translated PGN comment {index}/{len(matches)}")
    pieces.append(content[cursor:])
    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Translation cancelled before writing the PGN")
    output.write_text("".join(pieces), encoding="utf-8")
    logger.info("Wrote translated PGN: %s", output)
