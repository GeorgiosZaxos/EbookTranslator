from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from ebook_translator.ingestion.package_utils import (
    EpubPackageError,
    repair_missing_manifest_resources,
    validate_manifest_resources,
)


CONTAINER = b'''<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="EPUB/OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>'''

OPF = b'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Test</dc:title></metadata>
  <manifest>
    <item id="nav" href="deVi_9780804169387_epub3_nav_r1.xhtml"
          media-type="application/xhtml+xml" properties="nav"/>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="chapter"/></spine>
</package>'''


class FakeItem:
    def __init__(self, content: bytes):
        self.content = content

    def get_content(self) -> bytes:
        return self.content


class FakeBook:
    def __init__(self, items: dict[str, FakeItem]):
        self.items = items

    def get_item_with_id(self, item_id: str):
        return self.items.get(item_id)


def _write_base_epub(path: Path) -> None:
    """Create a small EPUB whose nav XHTML is deliberately absent from the ZIP."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("EPUB/OEBPS/content.opf", OPF)
        archive.writestr("EPUB/OEBPS/chapter.xhtml", b"<html><body>Chapter</body></html>")


def test_repair_restores_missing_nav_from_translated_in_memory_item(tmp_path: Path):
    output = tmp_path / "translated.epub"
    _write_base_epub(output)
    translated_nav = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><body><nav>Ενότητα</nav></body></html>'
    ).encode("utf-8")
    book = FakeBook({"nav": FakeItem(translated_nav)})

    repaired = repair_missing_manifest_resources(output, book)

    assert repaired == ["EPUB/OEBPS/deVi_9780804169387_epub3_nav_r1.xhtml"]
    with zipfile.ZipFile(output) as archive:
        assert archive.read(repaired[0]) == translated_nav
        assert archive.namelist()[0] == "mimetype"
        assert archive.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
    validate_manifest_resources(output)


def test_manifest_validator_reports_missing_member(tmp_path: Path):
    output = tmp_path / "broken.epub"
    _write_base_epub(output)
    with pytest.raises(EpubPackageError, match="deVi_9780804169387_epub3_nav_r1.xhtml"):
        validate_manifest_resources(output)


def test_repair_refuses_to_create_unrecoverable_manifest_resource(tmp_path: Path):
    output = tmp_path / "broken.epub"
    _write_base_epub(output)
    with pytest.raises(EpubPackageError, match="Cannot repair EPUB"):
        repair_missing_manifest_resources(output, FakeBook({}))
