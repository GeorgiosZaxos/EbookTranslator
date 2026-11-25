"""EPUB ZIP/package consistency helpers.

EbookLib may emit an OPF manifest whose relative resource path is not present
in the output ZIP.  This module checks manifest targets and restores missing
resources from the in-memory (already translated) EbookLib book before the
application performs its final EPUB validation.
"""

from __future__ import annotations

import logging
import posixpath
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from lxml import etree

logger = logging.getLogger(__name__)


class EpubPackageError(RuntimeError):
    """Raised when an EPUB package manifest cannot be reconciled with its ZIP."""


def _local_name(element: etree._Element) -> str:
    """Return an XML local-name without depending on namespace prefixes."""
    if not isinstance(element.tag, str):
        return ""
    return etree.QName(element).localname


def _package_paths(archive: zipfile.ZipFile) -> tuple[str, bytes, list[etree._Element]]:
    """Return OPF archive path, OPF bytes and manifest item nodes."""
    names = set(archive.namelist())
    container_name = "META-INF/container.xml"
    if container_name not in names:
        raise EpubPackageError("EPUB is missing META-INF/container.xml")

    try:
        container_root = etree.fromstring(archive.read(container_name))
    except (etree.XMLSyntaxError, KeyError) as exc:
        raise EpubPackageError("EPUB container.xml is invalid") from exc

    rootfile = next(
        (node for node in container_root.iter() if _local_name(node) == "rootfile"),
        None,
    )
    if rootfile is None or not rootfile.get("full-path"):
        raise EpubPackageError("EPUB container.xml does not declare an OPF rootfile")

    opf_path = posixpath.normpath(
        unquote(rootfile.get("full-path", "")).replace("\\", "/")
    )
    if opf_path.startswith("../") or opf_path not in names:
        raise EpubPackageError(f"EPUB package document is missing: {opf_path}")

    try:
        opf_bytes = archive.read(opf_path)
        opf_root = etree.fromstring(opf_bytes)
    except (etree.XMLSyntaxError, KeyError) as exc:
        raise EpubPackageError(f"EPUB package document is invalid: {opf_path}") from exc

    manifest = next(
        (node for node in opf_root.iter() if _local_name(node) == "manifest"),
        None,
    )
    if manifest is None:
        raise EpubPackageError(f"EPUB package document has no manifest: {opf_path}")
    items = [node for node in manifest if _local_name(node) == "item"]
    return opf_path, opf_bytes, items


def _resolve_manifest_href(opf_path: str, href: str) -> str | None:
    """Resolve an OPF href to a normalized ZIP member name.

    External resources are not ZIP members and are ignored here. Fragments and
    query strings are not part of the archive path. Percent-encoded filenames
    are decoded before comparison with ZIP member names.
    """
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        return None
    href_path = unquote(parsed.path).replace("\\", "/")
    if not href_path:
        return None
    if href_path.startswith("/"):
        return posixpath.normpath(href_path.lstrip("/"))
    return posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href_path))


def _book_item_content(book, item_id: str) -> bytes | None:
    """Retrieve an item's current in-memory content by OPF manifest id."""
    try:
        item = book.get_item_with_id(item_id)
    except (AttributeError, KeyError, TypeError):
        item = None
    if item is None:
        return None
    try:
        content = item.get_content()
    except (AttributeError, TypeError):
        content = getattr(item, "content", None)
    if isinstance(content, str):
        return content.encode("utf-8")
    return bytes(content) if content is not None else None


def _fallback_archive_content(
    output_archive: zipfile.ZipFile,
    source_path: Path | None,
    expected_path: str,
) -> bytes | None:
    """Find a unique basename match in output/source ZIPs as a final fallback."""
    basename = posixpath.basename(expected_path)
    output_matches = [name for name in output_archive.namelist()
                      if posixpath.basename(name) == basename]
    if len(output_matches) == 1:
        logger.warning(
            "EPUB resource %s was written under unexpected path %s; restoring expected path",
            expected_path, output_matches[0],
        )
        return output_archive.read(output_matches[0])

    if source_path and source_path.is_file():
        try:
            with zipfile.ZipFile(source_path, "r") as source_archive:
                if expected_path in source_archive.namelist():
                    logger.warning("Restoring missing EPUB resource from source: %s", expected_path)
                    return source_archive.read(expected_path)
                source_matches = [name for name in source_archive.namelist()
                                  if posixpath.basename(name) == basename]
                if len(source_matches) == 1:
                    logger.warning(
                        "Restoring source EPUB resource %s at expected package path %s",
                        source_matches[0], expected_path,
                    )
                    return source_archive.read(source_matches[0])
        except (OSError, zipfile.BadZipFile):
            logger.exception("Could not inspect source EPUB for missing resource %s", expected_path)
    return None


def _rewrite_with_additions(path: Path, additions: dict[str, bytes]) -> None:
    """Atomically rewrite an EPUB ZIP while retaining existing ZIP metadata."""
    if not additions:
        return
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.stem}.", suffix=".repair.tmp", dir=path.parent, delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)

        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(temp_path, "w") as target:
            for info in source.infolist():
                # Preserve each member's timestamp, compression and file attributes.
                target.writestr(info, source.read(info.filename))
            for name, content in additions.items():
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                target.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED)

        temp_path.replace(path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def repair_missing_manifest_resources(
    path: Path,
    book,
    source_path: Path | None = None,
) -> list[str]:
    """Restore missing OPF resources using current translated in-memory items.

    Returns the archive member names that were restored. If a manifest resource
    cannot be recovered, raises EpubPackageError rather than producing an EPUB
    that is known to be invalid.
    """
    path = Path(path)
    with zipfile.ZipFile(path, "r") as archive:
        opf_path, _, manifest_items = _package_paths(archive)
        archive_names = set(archive.namelist())
        additions: dict[str, bytes] = {}
        unresolved: list[str] = []

        for item_node in manifest_items:
            href = item_node.get("href")
            if not href:
                unresolved.append(f"manifest id={item_node.get('id', '?')} has no href")
                continue
            expected_path = _resolve_manifest_href(opf_path, href)
            if expected_path is None or expected_path in archive_names or expected_path in additions:
                continue

            item_id = item_node.get("id", "")
            content = _book_item_content(book, item_id) if item_id else None
            if content is None:
                content = _fallback_archive_content(archive, source_path, expected_path)

            if content is None:
                unresolved.append(expected_path)
                continue
            additions[expected_path] = content
            logger.warning(
                "Restored missing EPUB manifest resource %s (item id=%s)",
                expected_path, item_id or "unknown",
            )

    if unresolved:
        raise EpubPackageError(
            "Cannot repair EPUB: OPF manifest references missing resources: "
            + ", ".join(unresolved)
        )

    _rewrite_with_additions(path, additions)
    return list(additions)


def validate_manifest_resources(path: Path) -> None:
    """Raise EpubPackageError when an OPF manifest target is absent from the ZIP."""
    with zipfile.ZipFile(path, "r") as archive:
        opf_path, _, manifest_items = _package_paths(archive)
        names = set(archive.namelist())
        missing: list[str] = []
        for item_node in manifest_items:
            href = item_node.get("href")
            if not href:
                missing.append(f"manifest id={item_node.get('id', '?')} has no href")
                continue
            resolved = _resolve_manifest_href(opf_path, href)
            if resolved is not None and resolved not in names:
                missing.append(resolved)
        if missing:
            raise EpubPackageError(
                "EPUB OPF manifest references resources absent from the ZIP: "
                + ", ".join(missing)
            )
