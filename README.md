# Standalone Ebook Translator

[![Python](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PyQt6-41cd52)](https://pypi.org/project/PyQt6/)
[![Licence](https://img.shields.io/badge/licence-GPL--3.0--only-orange)](LICENSE)

A desktop application that translates EPUB books, SRT subtitles and PGN chess games — without Calibre.
It runs on free public translation endpoints (no API key) or on any OpenAI-compatible endpoint,
including a local Ollama install.

The architecture and workflow are inspired by
[bookfere/Ebook-Translator-Calibre-Plugin](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin).
**This is an independent implementation, not a port of that plugin**, and it contains no copied upstream
source files. See [UPSTREAM_NOTICES.md](UPSTREAM_NOTICES.md).

Current version: **1.0.0** — see [CHANGELOG.md](CHANGELOG.md) for the release history.

---

## Highlights

- **Full-text EPUB translation** — XHTML text nodes, document titles, metadata (title/description/subjects),
  EPUB 3 navigation and EPUB 2 NCX/TOC labels, image alt text and accessibility descriptions.
  Inline formatting and hyperlinks are preserved because individual text nodes are replaced, not whole paragraphs.
- **No key required** — Google Translate Free (new/HTML/legacy) and DeepL Free Web work out of the box.
- **Bring your own model** — any OpenAI-compatible `/chat/completions` endpoint, e.g. Ollama at
  `http://localhost:11434/v1`.
- **Resume after a crash** — append-only JSON Lines checkpoints are flushed per translated unit and reused on restart.
- **Directional glossaries** — separate English→Greek and Greek→English term files with placeholder protection.
- **Parallel translation** — 1–10 workers, capped per provider, with a responsive Qt UI and an in-window log panel.
- **Output validation** — the generated EPUB is checked for ZIP integrity, `mimetype`, OPF manifest completeness,
  and is reopened with EbookLib before the checkpoint is discarded.

## Supported formats

| Format | Input | What gets translated | Preserved |
|---|---|---|---|
| EPUB | `.epub` | Text nodes, metadata, TOC/navigation labels, image alt and ARIA labels, filename stem | Markup, inline tags, hyperlinks, images, authors, identifiers, dates, URLs |
| SRT | `.srt` | Subtitle text | Sequence numbers, timestamps |
| PGN | `.pgn` | Brace-delimited `{ comments }` | Moves and all other notation |

## Translation providers

| Provider | API key | Max workers | Notes |
|---|---|---|---|
| Google Translate (Free – New) | no | 3 | Default and recommended |
| Google Translate (Free – HTML) | no | 3 | Fallback endpoint |
| Google Translate (Free – Legacy) | no | 3 | Fallback endpoint |
| DeepL (Free – Web) | no | 1 | Forced serial to reduce throttling |
| Microsoft Edge (Free – Experimental) | no | 2 | Upstream endpoint has returned HTTP 404 |
| OpenAI-compatible / Ollama | optional | up to 10 | Set endpoint + model (default `llama3`) |

Free endpoints are unofficial web interfaces, not guaranteed public APIs. Availability, rate limits and terms
can change, and requests may be throttled or blocked.

## Requirements

- Python 3.13 or newer
- Developed on Windows 11; other desktop platforms should work (settings fall back to `~/.config`)
- Optional: a reachable OpenAI-compatible endpoint, or Ollama running locally

## Installation

```bash
git clone https://github.com/GeorgiosZaxos/EbookTranslator.git
cd EbookTranslator
```

**Windows (PowerShell)**

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m ebook_translator
```

**Linux / macOS**

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m ebook_translator
```

Or install the project and use the console script:

```bash
pip install -e .
ebook-translator
```

## Usage

1. Pick a **Provider**. `Google Translate (Free - New)` needs no key or endpoint.
2. Set **Source language** (or `Auto-detect`) and **Target language**.
3. Adjust **Parallel workers**, **Segment size**, **Timeout**, **Temperature** and **Max tokens** if needed.
   For an OpenAI-compatible provider also set **Endpoint** and **Model**, and optionally an **API key**.
4. **Browse…** for an `.epub`, `.srt` or `.pgn` file and choose the output path with **Save as…**.
5. Click **Start translation**. Progress and log output appear in the window.

Settings on the main screen save automatically. The **API key is held in memory for the current session only**
and is never written to the settings file.

### Controls and logging

- **Stop** requests a cooperative stop; the job ends once the active network request finishes.
- **Exit** closes the application, but keeps the window open until a running provider request can stop safely.
- **Clear log** (button or *File → Clear log*) empties the panel.
- The **Log level** selector (DEBUG…CRITICAL) is saved and restored between launches.
- Console logging handlers are removed on purpose: log records go to the in-window panel, not to the shell
  or the IDE run console. Severity levels are colour-coded.
- The window opens centred at 90% of the available screen area.

### Glossaries

The main window has independent **English → Greek** and **Greek → English** glossary fields, each with a
Browse button. On first launch, editable starter files are created under the per-user data directory, so
upgrades never overwrite your terminology. The matching file is selected from the language pair
(`Auto-detect → Greek` uses English → Greek; `Auto-detect → English` uses Greek → English). For other pairs,
the legacy single-glossary setting still applies as a fallback.

Each glossary is a UTF-8 text file with one exact mapping per line:

```text
# Lines beginning with '#' are comments
Hobbit=Χόμπιτ
The Shire=Το Σάιρ
One Ring=Το Ένα Δαχτυλίδι
```

Longer phrases are matched before shorter terms. Source terms are swapped for protected placeholders before
translation and restored as the configured target terms afterwards.

### Resuming an interrupted EPUB job

EPUB jobs write a checkpoint to a dot-prefixed `.translation_progress` folder beside the source book. The
checkpoint identity includes the source file SHA-256, language pair, provider/model settings, segment size and
glossary, so a changed book or changed settings starts a separate checkpoint instead of mixing results.

Every completed text node, metadata value and navigation label is flushed to disk before progress advances.
On restart, finished units are restored and only the unfinished ones are requested again. The checkpoint is
deleted only after the output EPUB passes validation; if generation or validation fails, progress stays on disk
for the next attempt.

Missing resources referenced by the OPF manifest are repaired from the translated in-memory EbookLib item,
with conservative archive and source fallbacks. If a resource cannot be recovered, the job fails and reports the
missing manifest paths.

Exactly-once delivery cannot be guaranteed if the process dies after a provider responds but before the
response is checkpointed; every durably checkpointed unit is reused.

SRT and PGN jobs run sequentially and do not use checkpoints.

## Settings and data locations

| What | Where |
|---|---|
| Settings | `%APPDATA%\EbookTranslator\settings.json` (`~/.config/EbookTranslator/` elsewhere) |
| Glossaries | `%APPDATA%\EbookTranslator\glossaries\English-Greek.txt`, `Greek-English.txt` |
| Job progress | `<source folder>/.translation_progress/<book>.<job-id>.jsonl` (removed after successful validation) |

Bundled starter glossaries live in [`glossaries/`](glossaries).

## Project structure

```text
ebook_translator/
  __main__.py             python -m ebook_translator entry point
  app.py                  Application bootstrap
  config.py               Persisted settings dataclass
  domain.py               Translation data contracts
  logging_config.py       Logging setup
  text_utils.py           Entity decoding and safe filenames
  gui/
    main_window.py        PyQt6 main window, settings and log panel
    settings_dialog.py    Standalone provider/language dialog (not wired into the main window)
  ingestion/
    epub.py               EPUB parsing and reconstruction
    package_utils.py      OPF/ZIP consistency and missing-resource repair
    text_formats.py       SRT and PGN adapters
  translation/
    free_online.py        Google, DeepL and Microsoft Edge free adapters
    providers.py          Provider interface and OpenAI-compatible adapter
    glossary.py           Glossary replacement and restoration
    service.py            Retry, cache and translation orchestration
  persistence/
    cache.py              Thread-safe in-memory cache
    checkpoint.py         Append-only JSON Lines job checkpoints
  workers/
    translation_worker.py QThread worker and output naming
tests/                    pytest suite
glossaries/               Bundled starter glossary templates
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

Tests cover EPUB namespace extraction, EPUB package repair and manifest validation, checkpoints,
the in-memory cache, directional glossary selection, the translation service and text utilities.

Design conventions worth keeping:

- New providers are separate adapter classes, not provider-specific branches inside existing code.
- Persistent job state stays in the JSON Lines checkpoints; the translation cache is in-memory and per-run.
- Translated content is written through text nodes so markup and links survive.

## Known limitations

- Text baked into raster images is not OCR-translated (alt text and accessible descriptions are translated).
- Author names, publishers, identifiers, dates, URLs, code samples and structural EPUB attributes are
  preserved rather than translated.
- Unusual EPUB navigation structures or proprietary metadata extensions may not expose labels to EbookLib.
- Encrypted EPUB resources, font obfuscation and malformed-package recovery are not implemented.
- Free public endpoints may throttle, block or disappear; Microsoft Edge Free is experimental.
- The GUI runs one translation job at a time; parallel workers operate within that single job.
- Native Gemini, Anthropic and paid DeepL adapters are not implemented yet.
- Translation quality depends on the chosen provider, model and prompt. Review output before publishing.

## Licence and attribution

Distributed under **GNU GPL-3.0-only**, consistent with the upstream project's licence. See [LICENSE](LICENSE).

- Upstream inspiration: https://github.com/bookfere/Ebook-Translator-Calibre-Plugin
- Upstream copyright and licensing notices remain applicable to any upstream-derived code.
- This project is a new implementation and bundles no copied upstream source files.

No warranty. Respect the terms of service of any translation endpoint you use.
