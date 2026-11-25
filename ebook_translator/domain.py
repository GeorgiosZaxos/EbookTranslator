"""Small, explicit contracts shared by the translation pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TranslationRequest:
    text: str
    source_language: str
    target_language: str
    context: str = ""


@dataclass(frozen=True)
class TranslationResult:
    source_text: str
    translated_text: str
    provider: str
    model: str
    cached: bool = False
