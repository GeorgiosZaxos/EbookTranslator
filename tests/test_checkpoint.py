from pathlib import Path

from ebook_translator.persistence.checkpoint import TranslationCheckpoint


def test_checkpoint_round_trip_and_source_hash(tmp_path: Path):
    source = tmp_path / "book.epub"
    source.write_bytes(b"epub source bytes")
    identity = {"source_sha256": "abc", "target_language": "Greek"}

    checkpoint = TranslationCheckpoint(source, identity)
    checkpoint.mark_completed("text:chapter:0", "Hello", "Γεια σου")

    resumed = TranslationCheckpoint(source, identity)
    assert resumed.get("text:chapter:0", "Hello") == "Γεια σου"
    assert resumed.get("text:chapter:0", "Different source") is None


def test_checkpoint_ignores_incomplete_final_record(tmp_path: Path):
    source = tmp_path / "book.epub"
    source.write_bytes(b"epub source bytes")
    identity = {"source_sha256": "abc"}
    checkpoint = TranslationCheckpoint(source, identity)
    checkpoint.mark_completed("unit-1", "One", "Uno")

    with checkpoint.path.open("ab") as stream:
        stream.write(b'{"type":"completed","key":"broken"')

    resumed = TranslationCheckpoint(source, identity)
    assert resumed.get("unit-1", "One") == "Uno"
    # The damaged tail is removed so subsequent records remain valid JSONL.
    resumed.mark_completed("unit-2", "Two", "Dos")
    again = TranslationCheckpoint(source, identity)
    assert again.get("unit-2", "Two") == "Dos"


def test_checkpoint_reuses_identical_text_across_units(tmp_path: Path):
    source = tmp_path / "book.epub"
    source.write_bytes(b"epub source bytes")
    checkpoint = TranslationCheckpoint(source, {"job": "same"})
    checkpoint.mark_completed("chapter-1:0", "Repeated phrase", "Επαναλαμβανόμενη φράση")

    assert checkpoint.get("chapter-2:4", "Repeated phrase") == "Επαναλαμβανόμενη φράση"
    resumed = TranslationCheckpoint(source, {"job": "same"})
    assert resumed.get("chapter-2:4", "Repeated phrase") == "Επαναλαμβανόμενη φράση"
