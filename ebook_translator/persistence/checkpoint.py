"""Append-only JSON Lines checkpoints for resumable ebook translation jobs."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def sha256_file(path: Path) -> str:
    """Hash a file incrementally so large EPUBs do not consume extra memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TranslationCheckpoint:
    """Persist each completed target as one fsynced JSON record.

    JSON Lines avoids rewriting an ever-growing JSON object after every
    paragraph. A damaged final line from a sudden power loss is discarded.
    """

    VERSION = 1

    def __init__(self, source: Path, identity: dict[str, Any]) -> None:
        self.source = source
        self.identity = identity
        identity_json = json.dumps(identity, sort_keys=True, ensure_ascii=False)
        self.job_id = hashlib.sha256(identity_json.encode("utf-8")).hexdigest()[:20]
        folder = source.parent / ".translation_progress"
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / f"{source.stem}.{self.job_id}.jsonl"
        self._lock = threading.RLock()
        self._completed: dict[str, dict[str, str]] = {}
        self._by_source: dict[str, str] = {}
        self._initialize_and_load()

    @staticmethod
    def _source_hash(source_text: str) -> str:
        return hashlib.sha256(source_text.encode("utf-8")).hexdigest()

    def _initialize_and_load(self) -> None:
        """Read valid records and truncate only an incomplete/corrupt tail."""
        header = {
            "type": "header",
            "version": self.VERSION,
            "identity": self.identity,
            "source_file": self.source.name,
        }
        if not self.path.exists():
            self._append_record(header)
            logger.info("Created JSON progress checkpoint: %s", self.path)
            return

        valid_lines: list[bytes] = []
        try:
            raw_lines = self.path.read_bytes().splitlines(keepends=True)
            for index, raw_line in enumerate(raw_lines):
                try:
                    record = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    logger.warning("Ignoring damaged checkpoint record at line %d", index + 1)
                    break
                if index == 0:
                    if (record.get("type") != "header"
                            or record.get("version") != self.VERSION
                            or record.get("identity") != self.identity):
                        raise ValueError("Checkpoint header does not match this translation job")
                elif record.get("type") == "completed":
                    key = record.get("key")
                    source_hash = record.get("source_hash")
                    translation = record.get("translation")
                    if all(isinstance(value, str) for value in (key, source_hash, translation)):
                        self._completed[key] = {
                            "source_hash": source_hash,
                            "translation": translation,
                        }
                        self._by_source[source_hash] = translation
                valid_lines.append(raw_line if raw_line.endswith(b"\n") else raw_line + b"\n")
            if not valid_lines:
                raise ValueError("Checkpoint has no valid header")
            # Repair a partial final record before future appends.
            if len(valid_lines) != len(raw_lines) or any(
                not line.endswith(b"\n") for line in raw_lines
            ):
                temporary = self.path.with_suffix(self.path.suffix + ".tmp")
                temporary.write_bytes(b"".join(valid_lines))
                os.replace(temporary, self.path)
            logger.info("Resumed checkpoint with %d completed units", len(self._completed))
        except (OSError, ValueError, TypeError):
            logger.exception("Could not load checkpoint %s; resetting it", self.path)
            self._completed.clear()
            self._by_source.clear()
            self._write_new_header(header)

    def _write_new_header(self, header: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(header, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    def _append_record(self, record: dict[str, Any]) -> None:
        """Append and flush one complete record before returning to the worker."""
        encoded = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self.path.open("ab") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

    def get(self, key: str, source_text: str) -> str | None:
        """Return a saved result only if the original text hash still matches."""
        with self._lock:
            source_hash = self._source_hash(source_text)
            record = self._completed.get(key)
            if record and record.get("source_hash") == source_hash:
                return record.get("translation")
            # Identical text can appear in multiple chapters/TOC locations.
            # Reuse the first saved translation and record this unit as complete.
            shared_translation = self._by_source.get(source_hash)
            if shared_translation is not None:
                self._append_record({
                    "type": "completed", "key": key,
                    "source_hash": source_hash,
                    "translation": shared_translation,
                })
                self._completed[key] = {
                    "source_hash": source_hash,
                    "translation": shared_translation,
                }
                return shared_translation
            return None

    def mark_in_progress(self, keys: list[str]) -> None:
        # In-progress work is intentionally not considered complete. On restart
        # it is naturally retried; no large status rewrite is required.
        logger.debug("Submitting %d checkpoint-pending units", len(keys))

    def mark_completed(self, key: str, source_text: str, translation: str) -> None:
        """Durably append one completed translation before advancing progress."""
        with self._lock:
            record = {
                "type": "completed",
                "key": key,
                "source_hash": self._source_hash(source_text),
                "translation": translation,
            }
            self._append_record(record)
            self._completed[key] = {
                "source_hash": record["source_hash"],
                "translation": translation,
            }
            self._by_source[record["source_hash"]] = translation

    def mark_failed(self, key: str) -> None:
        # Failed/in-progress work has no completed record and is retried on resume.
        logger.debug("Translation unit remains pending for retry: %s", key)

    def delete_after_success(self) -> None:
        """Remove the checkpoint only after the finished EPUB is validated."""
        with self._lock:
            try:
                self.path.unlink(missing_ok=True)
                logger.info("Removed completed translation checkpoint: %s", self.path)
            except OSError:
                logger.exception("Could not remove completed checkpoint: %s", self.path)
