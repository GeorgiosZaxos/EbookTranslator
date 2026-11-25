"""Free online translation services matching engines in the upstream plugin.

These endpoints are unofficial/public web-service interfaces, not paid API products.
They may change, throttle requests, or block automated traffic without notice.
"""

from __future__ import annotations

import json
import logging
import random
import uuid
import threading
from urllib.parse import urlencode

import requests

from ebook_translator.translation.providers import TranslationProvider

logger = logging.getLogger(__name__)


def _log_response(service: str, response: requests.Response) -> None:
    """Log HTTP status without logging book text, credentials or full request URLs."""
    logger.info("%s request completed with HTTP %s", service, response.status_code)

GOOGLE_ENDPOINT_NEW = "https://translate-pa.googleapis.com/v1/translate"
GOOGLE_ENDPOINT_HTML = "https://translate-pa.googleapis.com/v1/translateHtml"
GOOGLE_ENDPOINT_OLD = "https://translate.googleapis.com/translate_a/single"
DEEPL_FREE_ENDPOINT = "https://oneshot-free.www.deepl.com/v1/storefront/translate"
MICROSOFT_EDGE_ENDPOINT = "https://edge.microsoft.com/translate/translatetext"

# The original plugin uses its own provider-specific language tables.
# These common ISO mappings cover the principal languages exposed in this GUI.
GOOGLE_CODES = {
    "Auto-detect": "auto", "English": "en", "Greek": "el", "German": "de",
    "French": "fr", "Spanish": "es", "Italian": "it", "Dutch": "nl",
    "Japanese": "ja", "Chinese": "zh-CN", "Portuguese": "pt", "Russian": "ru",
}
DEEPL_CODES = {
    "English": "EN", "Greek": "EL", "German": "DE", "French": "FR",
    "Spanish": "ES", "Italian": "IT", "Dutch": "NL", "Japanese": "JA",
    "Chinese": "ZH", "Portuguese": "PT-PT", "Russian": "RU",
}


class FreeOnlineProvider(TranslationProvider):
    """Common HTTP behavior for free online services."""

    display_name = "Free online service"
    max_concurrency = 3

    def __init__(self, timeout: int = 45) -> None:
        self.timeout = timeout
        self._thread_local = threading.local()

    @property
    def session(self) -> requests.Session:
        """Return one HTTP session per worker thread."""
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0.0.0 Safari/537.36"
                )
            })
            self._thread_local.session = session
        return session

    def _codes(self, source_language: str, target_language: str) -> tuple[str, str]:
        source = GOOGLE_CODES.get(source_language, "auto")
        target = GOOGLE_CODES.get(target_language)
        if not target:
            raise ValueError(f"{self.display_name} does not support target language: {target_language}")
        return source, target


class GoogleFreeNewProvider(FreeOnlineProvider):
    """Google Translate free web endpoint used by GoogleFreeTranslateNew upstream."""

    display_name = "Google Translate (Free - New)"

    def translate(self, text: str, source_language: str, target_language: str,
                  context: str = "") -> str:
        source, target = self._codes(source_language, target_language)
        params = {
            "params.client": "gtx",
            "query.source_language": source,
            "query.target_language": target,
            "query.display_language": "en-US",
            "data_types": "TRANSLATION",
            # Public client key used by the upstream free endpoint.
            "key": "AIzaSyDLEeFI5OtFBwYBIoK_jj5m32rZK5CkCXA",
            "query.text": text,
        }
        response = self.session.get(GOOGLE_ENDPOINT_NEW, params=params, timeout=self.timeout)
        self._raise_for_status(response)
        _log_response(self.display_name, response)
        payload = response.json()
        translated = payload.get("translation")
        if not isinstance(translated, str) or not translated:
            raise RuntimeError(f"Unexpected Google Translate response: {payload!r}")
        return translated

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if not response.ok:
            logger.warning("Google Translate returned HTTP %s", response.status_code)
            response.raise_for_status()


class GoogleFreeHtmlProvider(FreeOnlineProvider):
    """Google Translate HTML endpoint (GoogleFreeTranslateHtml upstream)."""

    display_name = "Google Translate (Free - HTML)"

    def translate(self, text: str, source_language: str, target_language: str,
                  context: str = "") -> str:
        source, target = self._codes(source_language, target_language)
        headers = {
            "Content-Type": "application/json+protobuf",
            "X-Goog-Api-Key": "AIzaSyATBXajvzQLTDHEQbcpq0Ihe0vWDHmO520",
            "Origin": "https://translate.google.com",
            "Referer": "https://translate.google.com/",
        }
        body = [[[text], source, target], "wt_lib"]
        response = self.session.post(
            GOOGLE_ENDPOINT_HTML, headers=headers, json=body, timeout=self.timeout
        )
        GoogleFreeNewProvider._raise_for_status(response)
        _log_response(self.display_name, response)
        payload = response.json()
        try:
            return payload[0][0]
        except (IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Google HTML response: {payload!r}") from exc


class GoogleFreeLegacyProvider(FreeOnlineProvider):
    """Legacy Google Translate free endpoint (GoogleFreeTranslate upstream)."""

    display_name = "Google Translate (Free - Legacy)"

    def translate(self, text: str, source_language: str, target_language: str,
                  context: str = "") -> str:
        source, target = self._codes(source_language, target_language)
        params = {
            "client": "gtx", "sl": source, "tl": target, "dt": "t",
            "dj": "1", "q": text,
        }
        # The upstream switches to POST for unusually long requests.
        if len(text) <= 1800:
            response = self.session.get(GOOGLE_ENDPOINT_OLD, params=params, timeout=self.timeout)
        else:
            response = self.session.post(GOOGLE_ENDPOINT_OLD, data=params, timeout=self.timeout)
        GoogleFreeNewProvider._raise_for_status(response)
        _log_response(self.display_name, response)
        payload = response.json()
        try:
            return "".join(part["trans"] for part in payload["sentences"])
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"Unexpected legacy Google response: {payload!r}") from exc


class DeepLFreeProvider(FreeOnlineProvider):
    # Keep the unofficial free web endpoint serial to avoid throttling.
    max_concurrency = 1
    """Unofficial DeepL web free endpoint used by DeeplFreeTranslate upstream."""

    display_name = "DeepL (Free - Web)"

    def translate(self, text: str, source_language: str, target_language: str,
                  context: str = "") -> str:
        if target_language not in DEEPL_CODES:
            raise ValueError(f"DeepL free web endpoint does not support: {target_language}")
        source = DEEPL_CODES.get(source_language, "auto")
        instance_id = str(uuid.uuid4())
        body = {
            "app_information": {
                "app_build": "Chrome", "app_version": "any",
                "instance_id": instance_id, "os": "Windows", "os_version": "any",
            },
            "language_model": "next-gen",
            "source_lang": source,
            "text": [text],
            "usage_type": "Translate",
            "target_lang": DEEPL_CODES[target_language],
        }
        headers = {
            "Content-Type": "application/json",
            "Origin": "https://www.deepl.com",
            "Referer": "https://www.deepl.com/",
        }
        response = self.session.post(
            DEEPL_FREE_ENDPOINT, headers=headers, json=body, timeout=self.timeout
        )
        GoogleFreeNewProvider._raise_for_status(response)
        _log_response(self.display_name, response)
        payload = response.json()
        try:
            return payload["translations"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected DeepL free response: {payload!r}") from exc


class MicrosoftEdgeFreeProvider(FreeOnlineProvider):
    max_concurrency = 2
    """Microsoft Edge free translation endpoint used by MicrosoftEdgeTranslate upstream.

    The endpoint has had reported HTTP 404 failures; this adapter is retained as
    an experimental option and should not be assumed operational.
    """

    display_name = "Microsoft Edge (Free - Experimental)"

    def translate(self, text: str, source_language: str, target_language: str,
                  context: str = "") -> str:
        source, target = self._codes(source_language, target_language)
        params = {"isEnterpriseClient": "false", "to": target}
        if source != "auto":
            params["from"] = source
        response = self.session.post(
            MICROSOFT_EDGE_ENDPOINT,
            params=params,
            headers={"Content-Type": "application/json"},
            json=[text],
            timeout=self.timeout,
        )
        if response.status_code == 404:
            raise RuntimeError(
                "Microsoft Edge free translation endpoint returned HTTP 404. "
                "The upstream endpoint may have been retired."
            )
        GoogleFreeNewProvider._raise_for_status(response)
        _log_response(self.display_name, response)
        payload = response.json()
        try:
            return payload[0]["translations"][0]["text"]
        except (IndexError, KeyError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Microsoft Edge response: {payload!r}") from exc


FREE_PROVIDERS = {
    "google_free_new": GoogleFreeNewProvider,
    "google_free_html": GoogleFreeHtmlProvider,
    "google_free_legacy": GoogleFreeLegacyProvider,
    "deepl_free": DeepLFreeProvider,
    "microsoft_edge_free": MicrosoftEdgeFreeProvider,
}
