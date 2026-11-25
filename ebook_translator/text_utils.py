"""Shared text cleanup helpers for translated ebook content."""

from __future__ import annotations

import html
import re


def decode_entities(value: str) -> str:
    """Decode literal and double-encoded HTML entities such as ``&#39;``."""
    decoded = value
    # A small fixed bound prevents pathological entity expansion loops while
    # handling common double-encoded input (for example &amp;#39;).
    for _ in range(3):
        updated = html.unescape(decoded)
        if updated == decoded:
            break
        decoded = updated
    return decoded


def safe_filename(value: str) -> str:
    """Return a readable filename stem valid on Windows and other platforms."""
    value = decode_entities(value).strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if value.upper() in reserved:
        value = f"_{value}"
    return value[:180] or "translated_book"
