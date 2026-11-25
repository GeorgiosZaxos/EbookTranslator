"""EPUB ingestion, comprehensive text translation and package reconstruction.

The implementation translates document text nodes rather than replacing whole
paragraphs. This keeps inline markup, hyperlinks, emphasis and other XHTML
structure intact. EPUB metadata and navigation labels are handled separately.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ebooklib
from ebooklib import epub, ITEM_DOCUMENT
from lxml import etree, html

from ebook_translator.text_utils import decode_entities
from ebook_translator.ingestion.package_utils import repair_missing_manifest_resources

logger = logging.getLogger(__name__)


# Kept as a small compatibility/test helper. The current translator no longer
# relies on block selection; it processes every eligible text node instead.
BLOCK_XPATH = (
    "//*[local-name()='p' or local-name()='h1' or local-name()='h2' "
    "or local-name()='h3' or local-name()='h4' or local-name()='h5' "
    "or local-name()='h6' or local-name()='li' or local-name()='blockquote' "
    "or local-name()='figcaption' or local-name()='dt' or local-name()='dd' "
    "or local-name()='td' or local-name()='th' or local-name()='caption']"
)

# Attributes that normally contain user-visible text. Structural attributes
# such as href, id, class, style and src are intentionally not translated.
TRANSLATABLE_ATTRIBUTES = {
    "alt", "title", "aria-label", "placeholder", "summary", "label",
}
TRANSLATABLE_META_NAMES = {
    "description", "subject", "keywords", "og:title", "og:description",
    "twitter:title", "twitter:description",
}
TARGET_LANGUAGE_CODES = {
    "arabic": "ar", "chinese": "zh", "dutch": "nl", "english": "en",
    "french": "fr", "german": "de", "greek": "el", "hebrew": "he",
    "hindi": "hi", "italian": "it", "japanese": "ja", "korean": "ko",
    "polish": "pl", "portuguese": "pt", "russian": "ru", "spanish": "es",
    "swedish": "sv", "turkish": "tr", "ukrainian": "uk",
}

# Metadata values that are prose or reader-facing labels. Names, identifiers,
# publisher names and dates are deliberately not translated.
TRANSLATABLE_METADATA = ("title", "description", "subject")

# These elements contain code or executable/presentation data, not prose.
SKIP_TEXT_ANCESTORS = {"script", "style", "code", "pre", "svg", "math"}


@dataclass
class TextTarget:
    """One independently editable text node or visible text attribute."""

    item_id: str
    source_text: str
    parent: etree._Element
    is_tail: bool = False
    attribute: str | None = None

    def apply(self, translated: str) -> None:
        """Replace only the target value, preserving surrounding XHTML markup."""
        value = decode_entities(translated)
        if self.attribute:
            self.parent.set(self.attribute, value)
        elif self.is_tail:
            self.parent.tail = value
        else:
            self.parent.text = value


@dataclass
class MetadataTarget:
    """A metadata value with its original EPUB attributes."""

    field: str
    index: int
    source_text: str
    attributes: dict[str, Any]


class EpubDocument:
    """Load an EPUB and translate its readable content without flattening markup."""

    def __init__(self, source_path: Path) -> None:
        self.source_path = source_path
        self.book = epub.read_epub(str(source_path))
        self._documents: dict[str, tuple[object, etree._Element]] = {}
        self._text_targets: list[TextTarget] = []
        self._metadata_targets: list[MetadataTarget] = []
        self._parse_documents()
        self._collect_metadata_targets()
        if not self._text_targets and not self._metadata_targets and not self._toc_has_titles():
            raise ValueError(
                "No translatable EPUB text, metadata or navigation labels were found. "
                "The file may be image-only or use an unsupported structure."
            )
        self._translated_any = False

    @staticmethod
    def _block_nodes(root: etree._Element) -> list[etree._Element]:
        """Return leaf paragraph-like elements for legacy contract tests."""
        selected: list[etree._Element] = []
        descendant_xpath = BLOCK_XPATH.replace("//*", ".//*", 1)
        for node in root.xpath(BLOCK_XPATH):
            if not node.xpath(descendant_xpath):
                selected.append(node)
        return selected

    @staticmethod
    def _local_name(element: etree._Element) -> str:
        """Return an element's local tag name, independent of XML namespace."""
        if not isinstance(element.tag, str):
            return ""
        return etree.QName(element).localname.lower()

    @classmethod
    def _inside_excluded_element(cls, parent: etree._Element) -> bool:
        """Avoid translating code, stylesheets, SVG path data and scripts."""
        current: etree._Element | None = parent
        while current is not None:
            if cls._local_name(current) in SKIP_TEXT_ANCESTORS:
                return True
            current = current.getparent()
        return False

    @staticmethod
    def _clean_source(value: str) -> tuple[str, str, str]:
        """Decode entities and retain whitespace around a text fragment."""
        decoded = decode_entities(value)
        leading = decoded[: len(decoded) - len(decoded.lstrip())]
        trailing = decoded[len(decoded.rstrip()):]
        core = decoded.strip()
        return leading, core, trailing

    def _parse_documents(self) -> None:
        """Collect every readable XHTML text node and translatable attribute."""
        # EPUB 3 navigation XHTML and EPUB 2 NCX are separate EbookLib item
        # types; include them as well as ordinary chapter/document XHTML.
        item_types = [
            ITEM_DOCUMENT,
            getattr(ebooklib, "ITEM_NAVIGATION", None),
            getattr(ebooklib, "ITEM_TOC", None),
        ]
        seen_item_ids: set[str] = set()
        for item_type in item_types:
            if item_type is None:
                continue
            for item in self.book.get_items_of_type(item_type):
                item_id = item.get_id()
                if item_id in seen_item_ids:
                    continue
                seen_item_ids.add(item_id)
                self._parse_content_item(item)

    def _parse_content_item(self, item) -> None:
        """Parse one chapter, EPUB 3 navigation document or EPUB 2 NCX file."""
        content = item.get_content()
        try:
            root = etree.fromstring(
                content,
                parser=etree.XMLParser(
                    recover=True,
                    resolve_entities=False,
                    no_network=True,
                ),
            )
        except etree.XMLSyntaxError:
            root = html.fromstring(content)

        item_id = item.get_id()
        self._documents[item_id] = (item, root)

        # XPath returns smart strings, allowing us to distinguish element
        # text from an element's tail and update only that exact value.
        for text_node in root.xpath("//text()"):
            parent = text_node.getparent()
            if parent is None or not isinstance(parent.tag, str):
                continue
            if self._inside_excluded_element(parent):
                continue
            raw_text = str(text_node)
            _, core, _ = self._clean_source(raw_text)
            if not core:
                continue
            self._text_targets.append(
                TextTarget(
                    item_id=item_id,
                    source_text=raw_text,
                    parent=parent,
                    is_tail=bool(text_node.is_tail),
                )
            )

        # Translate accessibility and image-description text without
        # touching URLs, resource paths or structural attributes.
        for element in root.iter():
            if not isinstance(element.tag, str):
                continue
            if self._inside_excluded_element(element):
                continue
            attribute_names = set(TRANSLATABLE_ATTRIBUTES)
            if self._local_name(element) == "meta":
                meta_name = (element.get("name") or element.get("property") or "").lower()
                if meta_name in TRANSLATABLE_META_NAMES:
                    attribute_names.add("content")
            for attribute in attribute_names:
                value = element.get(attribute)
                if value and value.strip():
                    self._text_targets.append(
                        TextTarget(
                            item_id=item_id,
                            source_text=value,
                            parent=element,
                            attribute=attribute,
                        )
                    )
        logger.info(
            "Loaded EPUB %s: %d content documents, %d text and attribute targets",
            self.source_path.name,
            len(self._documents),
            len(self._text_targets),
        )

    def _toc_has_titles(self) -> bool:
        """Return whether the EPUB contains reader-facing TOC labels."""
        found = False

        def visit(node: Any) -> None:
            nonlocal found
            if found:
                return
            if isinstance(node, (list, tuple)):
                for child in node:
                    visit(child)
            else:
                title = getattr(node, "title", None)
                if isinstance(title, str) and title.strip():
                    found = True
                    return
                children = getattr(node, "children", None)
                if children:
                    visit(children)

        visit(getattr(self.book, "toc", None))
        if found:
            return True
        return any(
            isinstance(item, dict)
            and isinstance(item.get("title"), str)
            and bool(item["title"].strip())
            for item in (getattr(self.book, "guide", []) or [])
        )

    def _collect_metadata_targets(self) -> None:
        """Collect title, description and subject metadata for translation."""
        for field in TRANSLATABLE_METADATA:
            values = self.book.get_metadata("DC", field) or []
            for index, (value, attributes) in enumerate(values):
                if isinstance(value, str) and value.strip():
                    self._metadata_targets.append(
                        MetadataTarget(
                            field=field,
                            index=index,
                            source_text=value,
                            attributes=dict(attributes or {}),
                        )
                    )

    @staticmethod
    def _translate_toc_node(node: Any, service, cancel_event=None) -> int:
        """Translate navigation link/section labels recursively in place."""
        translated_count = 0
        if isinstance(node, (list, tuple)):
            for child in node:
                translated_count += EpubDocument._translate_toc_node(
                    child, service, cancel_event
                )
            return translated_count

        # EbookLib represents TOC entries as Link/Section objects and nested
        # tuples/lists. Their title is the user-visible label; href is not.
        title = getattr(node, "title", None)
        if isinstance(title, str) and title.strip():
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Translation cancelled")
            translated = service.translate(title, cancel_event=cancel_event)
            if translated and translated.strip():
                node.title = decode_entities(translated)
                translated_count += 1
            else:
                raise RuntimeError(f"Translation returned an empty TOC label: {title!r}")

        # Handle custom navigation objects that expose child entries.
        children = getattr(node, "children", None)
        if children:
            translated_count += EpubDocument._translate_toc_node(
                children, service, cancel_event
            )
        return translated_count

    def _replace_metadata_value(self, target: MetadataTarget, translated: str) -> None:
        """Replace one DC metadata entry while preserving its attributes."""
        namespace_uri = getattr(epub, "NAMESPACES", {}).get(
            "DC", "http://purl.org/dc/elements/1.1/"
        )
        metadata = getattr(self.book, "metadata", None)
        if isinstance(metadata, dict):
            namespace = metadata.setdefault(namespace_uri, {})
            values = namespace.get(target.field, [])
            if target.index < len(values):
                values[target.index] = (decode_entities(translated), target.attributes)
                namespace[target.field] = values
                return

        # Fallback for EbookLib variants that expose metadata mutator methods.
        if hasattr(self.book, "set_metadata"):
            self.book.set_metadata("DC", target.field, decode_entities(translated), target.attributes)
            return
        raise RuntimeError(f"Cannot update EPUB metadata field {target.field!r}")

    def translate(
        self,
        service,
        progress_callback=None,
        cancel_event=None,
        checkpoint=None,
        max_workers: int = 1,
    ) -> None:
        """Translate EPUB targets concurrently and checkpoint each completed unit."""
        tasks: list[tuple[str, str, Any, str]] = []

        # Text nodes retain their exact whitespace and parent/child markup.
        for index, target in enumerate(self._text_targets):
            leading, source, trailing = self._clean_source(target.source_text)
            if not source:
                continue
            key = f"text:{target.item_id}:{index}"
            apply = lambda translated, t=target, a=leading, b=trailing: t.apply(
                f"{a}{decode_entities(translated).strip()}{b}"
            )
            tasks.append((key, source, apply, f"EPUB text {target.item_id}"))

        # Metadata fields are separate units so a crash does not repeat them.
        for target in self._metadata_targets:
            key = f"metadata:{target.field}:{target.index}"
            apply = lambda translated, t=target: self._replace_metadata_value(t, translated)
            tasks.append((key, target.source_text.strip(), apply, f"metadata {target.field}"))

        # Collect TOC entries recursively while retaining their hierarchy.
        toc_targets: list[Any] = []
        def collect_titles(node: Any) -> None:
            if isinstance(node, (list, tuple)):
                for child in node:
                    collect_titles(child)
                return
            title = getattr(node, "title", None)
            if isinstance(title, str) and title.strip():
                toc_targets.append(node)
            children = getattr(node, "children", None)
            if children:
                collect_titles(children)
        toc = getattr(self.book, "toc", None)
        if toc:
            collect_titles(toc)
        for index, node in enumerate(toc_targets):
            key = f"toc:{index}"
            tasks.append((
                key, node.title.strip(),
                lambda translated, n=node: setattr(n, "title", decode_entities(translated)),
                "table of contents",
            ))

        guide_targets: list[dict[str, Any]] = []
        for index, guide_item in enumerate(getattr(self.book, "guide", []) or []):
            if isinstance(guide_item, dict):
                title = guide_item.get("title")
                if isinstance(title, str) and title.strip():
                    guide_targets.append(guide_item)
                    tasks.append((
                        f"guide:{index}", title.strip(),
                        lambda translated, g=guide_item: g.__setitem__("title", decode_entities(translated)),
                        "guide label",
                    ))

        if not tasks:
            raise RuntimeError("No translatable EPUB targets were found.")

        total = len(tasks)
        completed = 0
        pending: list[tuple[str, str, Any, str]] = []

        def report(label: str) -> None:
            nonlocal completed
            completed += 1
            if progress_callback:
                progress_callback(completed, total, f"{label} ({completed}/{total})")

        # Restore completed units first. Their translation requests are not repeated.
        for key, source, apply, label in tasks:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Translation cancelled")
            restored = checkpoint.get(key, source) if checkpoint else None
            if restored is not None:
                apply(restored)
                report(f"Restored {label}")
            else:
                pending.append((key, source, apply, label))

        logger.info(
            "EPUB translation plan: %d total units, %d resumed, %d pending",
            total, completed, len(pending),
        )
        if checkpoint and pending:
            checkpoint.mark_in_progress([item[0] for item in pending])

        # Provider-specific limits prevent overload (DeepL Free is serial).
        provider_limit = getattr(service.provider, "max_concurrency", 10)
        worker_count = max(1, min(int(max_workers), int(provider_limit), len(pending) or 1))
        logger.info("Starting %d parallel translation workers", worker_count)

        def translate_one(source: str) -> str:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Translation cancelled before request")
            result = service.translate(source, cancel_event=cancel_event)
            if not result or not result.strip():
                raise RuntimeError("Translation provider returned an empty result")
            return decode_entities(result).strip()

        failures: list[tuple[str, Exception]] = []
        if pending:
            executor = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="ebook-translate")
            future_map = {
                executor.submit(translate_one, source): (key, source, apply, label)
                for key, source, apply, label in pending
            }
            try:
                for future in as_completed(future_map):
                    key, source, apply, label = future_map[future]
                    try:
                        translated = future.result()
                        # Persist before mutating the EPUB or reporting progress.
                        if checkpoint:
                            checkpoint.mark_completed(key, source, translated)
                        apply(translated)
                        report(f"Translated {label}")
                        logger.debug("Completed translation unit %s", key)
                    except InterruptedError as exc:
                        if checkpoint:
                            checkpoint.mark_failed(key)
                        failures.append((key, exc))
                    except Exception as exc:
                        if checkpoint:
                            checkpoint.mark_failed(key)
                        failures.append((key, exc))
                        logger.error("Translation unit %s failed: %s", key, exc)
                    if cancel_event and cancel_event.is_set():
                        # Cancel work that has not started; running requests are
                        # allowed to finish and are checkpointed above.
                        for queued in future_map:
                            if not queued.running() and not queued.done():
                                queued.cancel()
            finally:
                executor.shutdown(wait=True, cancel_futures=True)

        if cancel_event and cancel_event.is_set():
            raise InterruptedError(
                f"Translation stopped. {completed}/{total} units are safely checkpointed."
            )
        if failures:
            first_key, first_error = failures[0]
            raise RuntimeError(
                f"{len(failures)} translation unit(s) failed; progress is saved. "
                f"First failure ({first_key}): {first_error}"
            ) from first_error

        # Set EPUB language metadata only after all translatable units succeed.
        target_language = (getattr(service, "target_language", "") or "").strip()
        if target_language:
            language_code = TARGET_LANGUAGE_CODES.get(target_language.casefold(), target_language)
            namespace_uri = getattr(epub, "NAMESPACES", {}).get(
                "DC", "http://purl.org/dc/elements/1.1/"
            )
            metadata = getattr(self.book, "metadata", {})
            if isinstance(metadata, dict):
                metadata.setdefault(namespace_uri, {})["language"] = [(language_code, {})]
                logger.info("Updated EPUB language metadata to %s", language_code)

        self._translated_any = completed > 0
        logger.info(
            "EPUB translation complete: %d/%d units; %d text/attribute targets, "
            "%d metadata values, %d TOC/guide labels",
            completed, total, len(self._text_targets), len(self._metadata_targets),
            len(toc_targets) + len(guide_targets),
        )

    def write(self, output_path: Path) -> None:
        """Serialize modified XHTML and write the translated EPUB package."""
        if not self._translated_any:
            raise RuntimeError("Refusing to write an EPUB without translated content.")

        for item_id, (item, root) in self._documents.items():
            content = etree.tostring(
                root,
                encoding="utf-8",
                xml_declaration=True,
                method="xml",
            )
            item.set_content(content)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        epub.write_epub(str(output_path), self.book)
        # Reconcile OPF hrefs with the generated ZIP. Some EPUBs with a nested
        # OPF directory expose an EbookLib path mismatch for the EPUB 3 nav item.
        repaired = repair_missing_manifest_resources(
            output_path, self.book, source_path=self.source_path
        )
        if repaired:
            logger.warning("Repaired %d missing EPUB manifest resource(s)", len(repaired))
        logger.info("Wrote translated EPUB: %s", output_path)
