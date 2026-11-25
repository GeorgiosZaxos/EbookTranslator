# Standalone Ebook Translator

A standalone PyQt6 desktop application inspired by the document-processing and translation architecture of
[bookfere/Ebook-Translator-Calibre-Plugin](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin).

**This is an independent first implementation, not a complete port of the Calibre plugin.**
It does not require Calibre. It currently supports EPUB, SRT and PGN input, the original plugin's free online translation
endpoints (Google Translate Free, DeepL Free web, and experimental Microsoft Edge Free), an
OpenAI-compatible chat-completions endpoint (including Ollama), resumable JSON progress checkpoints,
glossary substitutions, background translation and EPUB output reconstruction.

## Requirements

- Windows 11 (other platforms should work)
- Python 3.13+
- A reachable OpenAI-compatible API endpoint, or Ollama running locally

## Setup in PyCharm / PowerShell

```powershell
cd D:\Programming\PythonProduction\EbookTranslator
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m ebook_translator
```

Alternatively install the project in editable mode:

```powershell
pip install -e .
ebook-translator
```

## First run

1. Configure the translation service directly in the main window.
2. Select **Google Translate (Free - New)** to use the recommended no-key free online service.
3. Alternatively select Google Translate Free HTML/Legacy or DeepL Free Web.
4. Microsoft Edge Free is included as experimental; its endpoint has been reported to return HTTP 404.
5. Set the source/target languages and parallel worker count. The model field remains visible and defaults to `llama3` for Ollama/API use.
6. Browse for an EPUB, SRT or PGN file and select an output path.
7. Start translation.

The OpenAI-compatible/Ollama option remains available but is not required for the free online services.

The API key is kept in memory for the current application session. It is not written to the settings file.

## Application controls and logging

Application logs are displayed in the **Application log** panel inside the window.
The app removes console logging handlers so routine INFO, WARNING, ERROR, and DEBUG
messages are not written to the PyCharm Run console or shell. Use **Stop** to request
a cooperative stop after the active network request completes. Use **Exit** to close
the application; if a provider request is still running, the window remains open until
the worker can stop safely.

## Current implementation scope (0.1.8)

- EPUB: translates XHTML text nodes throughout the book, the EPUB title/description/subjects, document titles, table of contents/navigation labels, image alt text and accessibility labels. Inline formatting and hyperlinks are retained.
- SRT: translates subtitle text while preserving sequence numbers and timestamps.
- PGN: translates brace-delimited comments while preserving the rest of the game notation.
- Translation cache: uses a thread-safe in-memory cache during the current run.
- Resumability: writes an append-only JSON Lines checkpoint beside the source EPUB in `.translation_progress`; completed text units are flushed to disk immediately and reused after restart. The checkpoint is deleted only after the generated EPUB passes ZIP, OPF-manifest resource, and EbookLib validation.
- Parallel translation: configurable 1–10 workers (default 3); provider limits are respected, including serial DeepL Free requests.
- Glossaries: separate English→Greek and Greek→English UTF-8 files; automatic direction selection, placeholder protection, and a legacy single-file settings migration.
- Background work: translation runs in a `QThread` with a bounded thread pool for EPUB units; the UI remains responsive.
- Logging: console and GUI log panel, with DEBUG/INFO/WARNING/ERROR levels.

## Known limitations

- Text embedded inside raster images is not OCR-translated. Image alt text and accessible descriptions are translated.
- Author names, publisher names, identifiers, dates, URLs, code samples and structural EPUB attributes are preserved rather than translated.
- Some unusual EPUB navigation structures or proprietary metadata extensions may not expose their labels to EbookLib.
- EPUB encrypted resources, unusual font obfuscation and malformed package recovery are not implemented.
- Free public endpoints are unofficial web interfaces, not guaranteed public APIs. Their availability, rate limits and terms can change. Google/DeepL may throttle or block automated requests.
- Microsoft Edge Free is marked experimental because the upstream endpoint has had reported HTTP 404 failures.
- Only one active translation job is supported by the GUI. Parallel workers operate within that single EPUB job.
- Provider support is currently OpenAI-compatible chat completions. Gemini, Anthropic, DeepL and other native
  provider adapters should be added as separate implementations rather than hidden behind provider-specific
  conditionals.
- Translation quality depends on the selected model and prompt. Review output before publication.

## Project structure

```text
ebook_translator/
  app.py                 Application entry point
  config.py              Runtime settings
  domain.py              Translation data contracts
  logging_config.py      Logging setup
  gui/
    main_window.py       PyQt6 main window
    settings_dialog.py   Provider and language settings
  ingestion/
    epub.py              EPUB parsing and reconstruction
    package_utils.py     OPF manifest/ZIP consistency and missing-resource repair
    text_formats.py      SRT and PGN adapters
  translation/
    glossary.py          Glossary replacement/restoration
    providers.py         Provider interface and OpenAI-compatible adapter
    service.py           Retry, cache and translation orchestration
  persistence/
    cache.py             Thread-safe in-memory cache
    checkpoint.py        Append-only JSON Lines job checkpoints
  workers/
    translation_worker.py QThread worker
```

## Settings and data

- Settings: `%APPDATA%/EbookTranslator/settings.json`
- Temporary progress: `<source folder>/.translation_progress/<book>.<job-id>.jsonl` (automatically removed after successful EPUB validation)
- Glossaries: `%APPDATA%/EbookTranslator/glossaries/English-Greek.txt` and `Greek-English.txt`; each can also be pointed to a custom file from the main screen.

## Licence and attribution

This derivative project is distributed under **GNU GPL-3.0-only**, consistent with the
upstream repository's GPL-3.0 licence. The upstream project is:

- Repository: https://github.com/bookfere/Ebook-Translator-Calibre-Plugin
- Copyright and licensing notices in upstream files remain applicable to any upstream-derived code.
- This standalone scaffold is marked as a new implementation and does not include copied upstream source files.

See `LICENSE` for the licence text.


### Window and logging preferences

The main window opens centered at 90% of the available screen area. Use the **Log level** selector above the application log to choose DEBUG, INFO, WARNING, ERROR, or CRITICAL. The selection is saved in the user settings and restored on the next launch. Logs remain inside the application.

### Parallel translation and restart recovery (0.1.7)

Open **Settings** and set **Parallel workers (EPUB)** from 1 to 10 (default 3).
Google Free and OpenAI-compatible providers use up to the selected number of workers;
DeepL Free is restricted to one worker to reduce throttling risk, and Microsoft Edge
Free is restricted to two. Each worker uses its own HTTP session.

For EPUB jobs, the application creates a JSON Lines checkpoint in a dedicated dot-prefixed
`.translation_progress` folder beside the source book. Its identity includes the source
file SHA-256, language pair, provider/model settings, segment size and glossary. Each
completed text node, metadata value or navigation label is flushed to the checkpoint
before progress advances. On restart, matching completed units are restored and only
unfinished units are requested again. Failed/in-progress units are retried. A changed
source EPUB or incompatible translation settings creates a separate checkpoint.

The checkpoint is deleted only after the output EPUB passes ZIP integrity checks and
can be reopened by EbookLib. If output generation or validation fails, progress remains
available for another attempt. SRT and PGN remain sequential and do not currently use
job checkpoints. As with any remote translation API, absolute exactly-once delivery cannot
be guaranteed if the process or network fails after the provider completes a request but
before the response is durably checkpointed; all successfully checkpointed units are reused.


### Main-window settings and log display (0.1.7)

Provider, endpoint, model (default `llama3`), source/target languages, parallel workers, segment size, timeout, temperature, output-token limit and glossary path are visible on the main screen. Settings save automatically. The API key is kept in memory for the current session only. Log records use distinct colors by severity, and Clear log is available beside Exit and in the File menu.


## Version 0.1.7 UI changes

Translation settings are displayed on the main screen and saved automatically. The model field is always visible (default `llama3`), even when a free online provider is selected. DEBUG, INFO, WARNING, ERROR and CRITICAL log records have separate colors. Use **Clear log** immediately before **Exit**, or use File → Clear log.


### Direction-specific glossaries (0.1.8)

The main window has independent **English → Greek** and **Greek → English**
glossary path fields with Browse buttons. On first launch, editable starter files
are created in `%APPDATA%/EbookTranslator/glossaries/`. The application chooses
the matching file from the selected source and target languages. Auto-detect →
Greek uses the English → Greek file; Auto-detect → English uses the Greek →
English file. For other language pairs, the former single-glossary setting remains
available as a compatibility fallback.

Each glossary is a UTF-8 text file with one exact mapping per line:

```text
Hobbit=Χόμπιτ
The Shire=Το Σάιρ
One Ring=Το Ένα Δαχτυλίδι
```

Lines beginning with `#` are comments. Longer phrases are matched before shorter
terms. The source terms are replaced with protected placeholders before translation
and restored using the configured target terms afterwards.

### EPUB package repair and validation (0.1.8)

After EbookLib writes the translated book, the application checks every local
resource referenced by the OPF manifest against the actual ZIP members. Missing
resources are restored from the current in-memory book item (which contains the
translated content), with conservative archive/source fallbacks. If a resource
cannot be recovered, the job fails with the missing manifest paths and retains
the JSONL checkpoint. Final validation checks ZIP integrity, the EPUB `mimetype`
entry, all manifest references, and then reopens the EPUB with EbookLib.
