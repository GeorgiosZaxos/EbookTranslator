"""Background translation worker."""

from __future__ import annotations

import logging
import threading
import traceback
import zipfile
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ebook_translator.ingestion.epub import EpubDocument
from ebook_translator.ingestion.package_utils import validate_manifest_resources
from ebook_translator.ingestion.text_formats import translate_pgn, translate_srt
from ebook_translator.text_utils import safe_filename
from ebook_translator.persistence.checkpoint import TranslationCheckpoint, sha256_file
from ebooklib import epub

logger = logging.getLogger(__name__)


class TranslationWorker(QThread):
    progress = pyqtSignal(int, int, str)
    log_message = pyqtSignal(str)
    completed = pyqtSignal(str)
    cancelled = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, source: Path, output: Path, service, parallel_workers: int = 3) -> None:
        super().__init__()
        self.source = source
        self.output = output
        self.service = service
        self.parallel_workers = max(1, min(int(parallel_workers), 10))
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        """Request cooperative cancellation."""
        self.cancel_event.set()
        logger.info("Cancellation requested for %s", self.source)

    def _progress(self, current: int, total: int, message: str) -> None:
        self.progress.emit(current, total, message)

    def _translated_output_path(self) -> Path:
        """Translate the chosen output basename while retaining its directory/extension."""
        requested_stem = self.output.stem
        source_stem = self.source.stem
        # The normal UI default is source-name.target-language. Translate only
        # the source-name part and retain the language suffix.
        suffix = requested_stem[len(source_stem):] if requested_stem.startswith(source_stem) else ""
        text_to_translate = source_stem if suffix else requested_stem
        translated = self.service.translate(text_to_translate, cancel_event=self.cancel_event)
        safe_stem = safe_filename(translated)
        final_stem = f"{safe_stem}{suffix}"
        candidate = self.output.with_name(f"{final_stem}{self.output.suffix}")
        # A translated title can coincidentally become the source filename.
        # Never allow filename translation to overwrite the original EPUB.
        if candidate.resolve() == self.source.resolve():
            candidate = candidate.with_name(
                f"{candidate.stem}.translated{candidate.suffix}"
            )
        return candidate

    def _checkpoint_identity(self) -> dict:
        """Build a stable identity so incompatible jobs never share progress."""
        provider = self.service.provider
        provider_settings = {
            key: getattr(provider, key)
            for key in ("endpoint", "model", "temperature", "max_tokens")
            if hasattr(provider, key)
        }
        return {
            "source_sha256": sha256_file(self.source),
            "source_language": self.service.source_language,
            "target_language": self.service.target_language,
            "provider": f"{provider.__class__.__module__}.{provider.__class__.__name__}",
            "service_endpoint": self.service.endpoint,
            "service_model": self.service.model,
            "provider_settings": provider_settings,
            "segment_chars": self.service.segment_chars,
            "glossary": [list(entry) for entry in getattr(self.service.glossary, "entries", [])],
            "job_format": "epub-json-checkpoint-v1",
        }

    @staticmethod
    def _validate_epub(path: Path) -> None:
        """Verify ZIP integrity and that EbookLib can reopen the finished EPUB."""
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError("Output EPUB was not created or is empty.")
        with zipfile.ZipFile(path, "r") as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise RuntimeError(f"Output EPUB has a corrupt ZIP member: {bad_member}")
            if "mimetype" not in archive.namelist():
                raise RuntimeError("Output EPUB is missing its mimetype entry.")
            if archive.namelist()[0] != "mimetype":
                raise RuntimeError("Output EPUB must place mimetype as the first ZIP entry.")
            if archive.getinfo("mimetype").compress_type != zipfile.ZIP_STORED:
                raise RuntimeError("Output EPUB mimetype entry must be uncompressed.")
        # Check every OPF manifest reference before invoking EbookLib. This
        # produces a useful error rather than a low-level ZipFile KeyError.
        validate_manifest_resources(path)
        # Reopening catches further package/OPF issues that ZIP validation misses.
        epub.read_epub(str(path))

    def run(self) -> None:
        try:
            suffix = self.source.suffix.lower()
            self.log_message.emit(f"Processing {self.source.name}")
            actual_output = self.output
            if suffix == ".epub":
                # A job checkpoint is tied to the source bytes and all settings
                # that can change translation output. Completed units are reused.
                checkpoint = TranslationCheckpoint(self.source, self._checkpoint_identity())
                translated_output = self._translated_output_path()
                logger.info("Translated output filename: %s", translated_output.name)
                self.log_message.emit(f"Translated output filename: {translated_output.name}")
                actual_output = translated_output
                document = EpubDocument(self.source)
                document.translate(
                    self.service,
                    self._progress,
                    self.cancel_event,
                    checkpoint=checkpoint,
                    max_workers=self.parallel_workers,
                )
                if self.cancel_event.is_set():
                    raise InterruptedError("Translation cancelled before writing the EPUB")
                document.write(actual_output)
                self._validate_epub(actual_output)
                # Delete progress only after the finished EPUB passes validation.
                checkpoint.delete_after_success()
            elif suffix == ".srt":
                translate_srt(self.source, self.output, self.service, self._progress, self.cancel_event)
            elif suffix == ".pgn":
                translate_pgn(self.source, self.output, self.service, self._progress, self.cancel_event)
            else:
                raise ValueError(f"Unsupported input format: {suffix}")
            self.completed.emit(str(actual_output))
        except InterruptedError as exc:
            logger.info("Translation stopped: %s", exc)
            self.cancelled.emit(str(exc))
        except Exception as exc:
            logger.exception("Translation job failed")
            self.failed.emit(f"{exc}\n\n{traceback.format_exc()}")
