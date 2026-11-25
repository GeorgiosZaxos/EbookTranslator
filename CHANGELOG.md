# Changelog

## 0.1.5
- Added an in-window log-level selector (DEBUG, INFO, WARNING, ERROR, CRITICAL); selection is saved and restored.
- Main window opens centered at 90% of the available screen dimensions.


## 0.1.4
- Route application logging to the in-app log panel and remove shell/console handlers.
- Add explicit Stop and Exit buttons to the main window.
- Make retry backoff interruptible and report stopped jobs separately from failures.
- Prevent cancelled SRT, PGN, and EPUB jobs from writing partial output files.
- Wait safely for the worker during Exit; keep the window open if a provider request is still active.

## 0.1.0 - Initial standalone milestone
- Added PyQt6 desktop shell and provider settings.
- Added OpenAI-compatible translation adapter (Ollama-compatible endpoint supported).
- Added EPUB, SRT and PGN processing adapters.
- Added glossary protection, retry orchestration and SQLite translation cache.
- Added background QThread execution and cancellation flag.

## 0.1.1 - Original free online providers
- Added Google Translate Free new, HTML and legacy endpoint adapters.
- Added DeepL Free web endpoint adapter.
- Added Microsoft Edge Free experimental adapter with explicit 404 handling.
- Added provider selection in PyQt6 settings; Google Free New is the default.

## 0.1.2 - EPUB namespace extraction fix
- Fixed EPUB XHTML block selection for the standard XHTML namespace.
- Added nested-block de-duplication and zero-block failure protection.
- Added regression tests for namespaced EPUB documents.
- Added safe HTTP status logging for free online translation providers.

## 0.1.3 - Complete EPUB text coverage
- Decode literal and double-encoded HTML entities (including `&#39;`) in translated output.
- Translate EPUB filenames, title/description/subject metadata, navigation XHTML, EPUB 2 NCX/TOC and guide labels,
  XHTML text nodes, image descriptions and accessibility labels.
- Preserve inline XHTML elements and hyperlinks by updating individual text nodes
  rather than replacing entire paragraphs.
- Update the EPUB language metadata to the selected target language.


## 0.1.6
- Added configurable parallel EPUB translation (1–10 workers, default 3).
- Enforced provider concurrency limits: DeepL Free 1, Microsoft Edge Free 2, others up to the configured limit.
- Added per-thread HTTP sessions for safe concurrent provider requests.
- Added append-only JSON Lines checkpoints with immediate durable saves per completed EPUB unit.
- Added restart recovery, source/settings fingerprinting, and automatic checkpoint cleanup after EPUB validation.
- Replaced the persistent SQLite translation cache with a thread-safe in-memory cache; JSON progress files are the only persistent job state.


## 0.1.7

- Moved translation settings onto the main screen.
- Kept the model field visible for every provider; default model is `llama3`.
- Added severity-specific colors for DEBUG, INFO, WARNING, ERROR and CRITICAL log entries.
- Added a Clear log button immediately before Exit and a File-menu Clear log command.
- Main-screen settings save automatically; API keys remain session-only.


## 0.1.8

- Added independent English→Greek and Greek→English glossary files on the main screen, each with a Browse button.
- Added UTF-8 starter glossaries in the per-user application data directory and bundled editable templates.
- Automatically selects a glossary from the source/target language pair; preserves compatibility with legacy single-glossary settings.
- Added EPUB OPF manifest validation against actual ZIP members.
- Repairs missing manifest resources from the translated in-memory EbookLib item before final validation.
- Retains the job checkpoint if package resources cannot be recovered or EPUB validation fails.
- Added regression tests for missing EPUB 3 navigation resources, manifest validation and directional glossary selection.
