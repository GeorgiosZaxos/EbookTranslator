"""Main PyQt6 application window with always-visible translation settings."""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QProgressBar, QSpinBox, QStatusBar, QTextEdit, QVBoxLayout,
    QWidget,
)

from ebook_translator.config import AppConfig, app_data_dir
from ebook_translator.persistence.cache import TranslationCache
from ebook_translator.translation.glossary import Glossary, select_glossary_path
from ebook_translator.translation.providers import OpenAICompatibleProvider
from ebook_translator.translation.free_online import FREE_PROVIDERS
from ebook_translator.translation.service import TranslationService
from ebook_translator.workers.translation_worker import TranslationWorker

logger = logging.getLogger(__name__)


class _LogSignalBridge(QObject):
    """Forward log messages from background threads to the GUI thread."""
    message = pyqtSignal(str)


class _QtLogHandler(logging.Handler):
    """Route all application logging into the GUI log panel."""
    def __init__(self, bridge: _LogSignalBridge) -> None:
        super().__init__(logging.DEBUG)
        self.bridge = bridge
        self.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s", datefmt="%H:%M:%S"
        ))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.message.emit(self.format(record))
        except Exception:
            self.handleError(record)


class MainWindow(QMainWindow):
    """Desktop UI for ebook translation, job control and live diagnostics."""
    PROVIDERS = (
        ("Google Translate (Free - New)", "google_free_new"),
        ("Google Translate (Free - HTML)", "google_free_html"),
        ("Google Translate (Free - Legacy)", "google_free_legacy"),
        ("DeepL (Free - Web, unofficial)", "deepl_free"),
        ("Microsoft Edge (Free - Experimental)", "microsoft_edge_free"),
        ("OpenAI-compatible / Ollama", "openai_compatible"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Standalone Ebook Translator")
        self._set_initial_window_geometry()
        self._log_bridge = _LogSignalBridge(self)
        self._log_bridge.message.connect(self._append_log, Qt.ConnectionType.QueuedConnection)
        self._qt_log_handler = _QtLogHandler(self._log_bridge)
        logging.getLogger().addHandler(self._qt_log_handler)

        self.config = AppConfig.load()
        self._initialize_glossary_files()
        self.api_key = ""  # API keys are session-only and never persisted.
        self.worker: TranslationWorker | None = None
        self.source_path: Path | None = None
        self.output_path: Path | None = None
        self._loading_controls = True
        self._build_ui()
        self._loading_controls = False
        self._set_log_level(self.config.log_level, persist=False)
        self._update_job_state(False)
        logger.info("Application interface initialized")

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        self.setCentralWidget(central)

        file_group = QGroupBox("Input and output")
        file_form = QFormLayout(file_group)
        source_row = QHBoxLayout()
        self.source_edit = QLineEdit()
        self.source_edit.setReadOnly(True)
        browse_source = QPushButton("Browse…")
        browse_source.clicked.connect(self._choose_source)
        source_row.addWidget(self.source_edit, 1)
        source_row.addWidget(browse_source)
        file_form.addRow("Input file", source_row)
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        browse_output = QPushButton("Save as…")
        browse_output.clicked.connect(self._choose_output)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(browse_output)
        file_form.addRow("Output file", output_row)
        root.addWidget(file_group)

        # All frequently used settings are available on the main screen.
        settings_group = QGroupBox("Translation settings")
        form = QGridLayout(settings_group)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)

        self.provider_combo = QComboBox()
        for label, key in self.PROVIDERS:
            self.provider_combo.addItem(label, key)
        self.provider_combo.setCurrentIndex(max(0, self.provider_combo.findData(self.config.provider)))
        self.endpoint_edit = QLineEdit(self.config.endpoint)
        self.endpoint_edit.setPlaceholderText("http://localhost:11434/v1")
        # The model is always visible, including when a free web provider is selected.
        self.model_edit = QLineEdit(self.config.model or "llama3")
        self.model_edit.setPlaceholderText("llama3")
        self.model_edit.setToolTip("Model name for Ollama / OpenAI-compatible APIs; always visible.")
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("Optional; session-only")

        self.source_language_combo = QComboBox()
        self.source_language_combo.addItems([
            "Auto-detect", "English", "Greek", "German", "French", "Spanish",
            "Italian", "Dutch", "Japanese", "Chinese",
        ])
        self.source_language_combo.setCurrentText(self.config.source_language)
        self.target_language_combo = QComboBox()
        self.target_language_combo.addItems([
            "Greek", "English", "German", "French", "Spanish", "Italian",
            "Dutch", "Japanese", "Chinese", "Portuguese", "Russian",
        ])
        self.target_language_combo.setCurrentText(self.config.target_language)

        self.parallel_workers_spin = QSpinBox()
        self.parallel_workers_spin.setRange(1, 10)
        self.parallel_workers_spin.setValue(self.config.parallel_workers)
        self.parallel_workers_spin.setToolTip("Provider-specific concurrency limits still apply.")
        self.segment_chars_spin = QSpinBox()
        self.segment_chars_spin.setRange(500, 20000)
        self.segment_chars_spin.setSingleStep(250)
        self.segment_chars_spin.setValue(self.config.segment_chars)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 600)
        self.timeout_spin.setSuffix(" sec")
        self.timeout_spin.setValue(self.config.request_timeout)
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(self.config.temperature)
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(128, 32768)
        self.max_tokens_spin.setSingleStep(256)
        self.max_tokens_spin.setValue(self.config.max_tokens)
        self.english_greek_glossary_edit = QLineEdit(
            self.config.english_greek_glossary_path
        )
        self.english_greek_glossary_edit.setPlaceholderText("English → Greek glossary (.txt)")
        self.greek_english_glossary_edit = QLineEdit(
            self.config.greek_english_glossary_path
        )
        self.greek_english_glossary_edit.setPlaceholderText("Greek → English glossary (.txt)")
        self.english_greek_browse = QPushButton("Browse…")
        self.greek_english_browse = QPushButton("Browse…")
        self.english_greek_browse.clicked.connect(
            lambda: self._choose_glossary(self.english_greek_glossary_edit)
        )
        self.greek_english_browse.clicked.connect(
            lambda: self._choose_glossary(self.greek_english_glossary_edit)
        )
        self.english_greek_control = self._glossary_path_control(
            self.english_greek_glossary_edit, self.english_greek_browse
        )
        self.greek_english_control = self._glossary_path_control(
            self.greek_english_glossary_edit, self.greek_english_browse
        )

        # Two-column settings grid keeps the log panel usable on 90%-screen windows.
        setting_pairs = (
            ("Translation service", self.provider_combo, "API base URL", self.endpoint_edit),
            ("Model (Ollama / API)", self.model_edit, "API key (session only)", self.api_key_edit),
            ("Source language", self.source_language_combo, "Target language", self.target_language_combo),
            ("Parallel workers (EPUB)", self.parallel_workers_spin, "Segment size (characters)", self.segment_chars_spin),
            ("Request timeout", self.timeout_spin, "Temperature", self.temperature_spin),
            ("Maximum output tokens", self.max_tokens_spin, "English → Greek glossary", self.english_greek_control),
        )
        for row, (left_label, left_widget, right_label, right_widget) in enumerate(setting_pairs):
            form.addWidget(QLabel(left_label), row, 0)
            form.addWidget(left_widget, row, 1)
            form.addWidget(QLabel(right_label), row, 2)
            form.addWidget(right_widget, row, 3)
        form.addWidget(QLabel("Greek → English glossary"), len(setting_pairs), 0)
        form.addWidget(self.greek_english_control, len(setting_pairs), 1, 1, 3)
        root.addWidget(settings_group)

        # Persist main-screen settings immediately; the API key remains in memory only.
        for signal in (
            self.provider_combo.currentIndexChanged,
            self.source_language_combo.currentTextChanged,
            self.target_language_combo.currentTextChanged,
            self.parallel_workers_spin.valueChanged,
            self.segment_chars_spin.valueChanged,
            self.timeout_spin.valueChanged,
            self.temperature_spin.valueChanged,
            self.max_tokens_spin.valueChanged,
        ):
            signal.connect(self._save_inline_settings)
        for edit in (self.endpoint_edit, self.model_edit,
                     self.english_greek_glossary_edit, self.greek_english_glossary_edit):
            edit.editingFinished.connect(self._save_inline_settings)
        self.api_key_edit.textChanged.connect(self._update_session_api_key)

        actions = QHBoxLayout()
        self.start_button = QPushButton("Start translation")
        self.start_button.clicked.connect(self._start_translation)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setToolTip("Stop after the active provider request finishes")
        self.stop_button.clicked.connect(self._cancel_translation)
        self.clear_log_button = QPushButton("Clear log")
        self.clear_log_button.clicked.connect(self._clear_log)
        self.exit_button = QPushButton("Exit")
        self.exit_button.clicked.connect(self.close)
        actions.addWidget(self.start_button)
        actions.addWidget(self.stop_button)
        actions.addStretch(1)
        actions.addWidget(self.clear_log_button)  # Placed immediately before Exit.
        actions.addWidget(self.exit_button)
        root.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        root.addWidget(self.progress)
        self.progress_label = QLabel("Ready")
        root.addWidget(self.progress_label)

        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("Application log"))
        log_header.addStretch(1)
        log_header.addWidget(QLabel("Log level:"))
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.log_level_combo.setCurrentText(self.config.log_level.upper())
        self.log_level_combo.currentTextChanged.connect(self._on_log_level_changed)
        log_header.addWidget(self.log_level_combo)
        root.addLayout(log_header)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.log_view.setPlaceholderText("Application messages will appear here…")
        root.addWidget(self.log_view, 1)

        file_menu = self.menuBar().addMenu("&File")
        open_action = file_menu.addAction("Open…")
        open_action.triggered.connect(self._choose_source)
        clear_action = file_menu.addAction("Clear log")
        clear_action.triggered.connect(self._clear_log)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)
        help_menu = self.menuBar().addMenu("&Help")
        about_action = help_menu.addAction("About")
        about_action.triggered.connect(self._about)
        self.setStatusBar(QStatusBar())

    def _initialize_glossary_files(self) -> None:
        """Create editable UTF-8 starter files and migrate old settings.

        The default files live in the user's application-data directory, not
        inside the installation, so upgrades do not overwrite user terminology.
        """
        glossary_dir = app_data_dir() / "glossaries"
        glossary_dir.mkdir(parents=True, exist_ok=True)

        # Migrate the former single glossary according to the saved language pair.
        if self.config.glossary_path and not (
            self.config.english_greek_glossary_path or self.config.greek_english_glossary_path
        ):
            source = self.config.source_language.strip().casefold()
            target = self.config.target_language.strip().casefold()
            if target == "english" and source in {"greek", "auto-detect", "auto detect"}:
                self.config.greek_english_glossary_path = self.config.glossary_path
            else:
                self.config.english_greek_glossary_path = self.config.glossary_path
            logger.info("Migrated legacy glossary setting to a directional glossary")

        templates = {
            "english_greek_glossary_path": (
                "English-Greek.txt",
                "# English → Greek glossary (UTF-8)\n"
                "# One mapping per line: English source term=Greek target term\n"
                "# Longer phrases are matched before shorter terms.\n"
                "# Lines beginning with # are comments.\n"
                "# Example: The Shire=Το Σάιρ\n"
                "# Example: Hobbit=Χόμπιτ\n",
            ),
            "greek_english_glossary_path": (
                "Greek-English.txt",
                "# Greek → English glossary (UTF-8)\n"
                "# One mapping per line: Greek source term=English target term\n"
                "# Longer phrases are matched before shorter terms.\n"
                "# Lines beginning with # are comments.\n"
                "# Example: Το Σάιρ=The Shire\n"
                "# Example: Χόμπιτ=Hobbit\n",
            ),
        }
        for attribute, (filename, content) in templates.items():
            configured_path = getattr(self.config, attribute)
            path = Path(configured_path) if configured_path else (glossary_dir / filename)
            if not configured_path and not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                logger.info("Created starter glossary file: %s", path)
            elif configured_path and not path.exists():
                # Do not silently create files at stale/custom paths from old settings.
                logger.warning("Configured glossary file does not exist: %s", path)
            setattr(self.config, attribute, str(path))
        self.config.save()

    @staticmethod
    def _glossary_path_control(edit: QLineEdit, button: QPushButton) -> QWidget:
        """Build a compact text-path and Browse button control."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        row.addWidget(button)
        return container

    def _choose_glossary(self, edit: QLineEdit) -> None:
        """Select a glossary file without changing the other direction."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select glossary file", edit.text(),
            "Glossary files (*.txt *.tsv *.csv);;All files (*.*)",
        )
        if path:
            edit.setText(path)
            self._save_inline_settings()
            logger.info("Selected glossary file: %s", path)

    def _active_glossary_path(self) -> str:
        """Return the glossary matching the currently selected languages."""
        return select_glossary_path(
            self.source_language_combo.currentText(),
            self.target_language_combo.currentText(),
            self.english_greek_glossary_edit.text().strip(),
            self.greek_english_glossary_edit.text().strip(),
            self.config.glossary_path,
        )

    def _set_initial_window_geometry(self) -> None:
        """Set the window to 90% of available screen dimensions and center it."""
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1100, 850)
            return
        area = screen.availableGeometry()
        width = min(area.width(), max(900, int(area.width() * 0.9)))
        height = min(area.height(), max(700, int(area.height() * 0.9)))
        self.resize(width, height)
        self.move(area.x() + (area.width() - width) // 2,
                  area.y() + (area.height() - height) // 2)

    def _set_log_level(self, level_name: str, *, persist: bool) -> None:
        """Set the GUI logging threshold and optionally save it."""
        level = (level_name or "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            level = "INFO"
        logging.getLogger().setLevel(logging.DEBUG)
        self._qt_log_handler.setLevel(getattr(logging, level))
        logging.getLogger("ebook_translator").setLevel(logging.DEBUG)
        if persist:
            self.config.log_level = level
            self.config.save()
        if self.log_level_combo.currentText() != level:
            self.log_level_combo.blockSignals(True)
            self.log_level_combo.setCurrentText(level)
            self.log_level_combo.blockSignals(False)

    def _on_log_level_changed(self, level: str) -> None:
        self._set_log_level(level, persist=True)
        logger.info("In-app log level changed to %s", level)

    def _append_log(self, message: str) -> None:
        """Insert a log line in a distinct color for each severity."""
        upper = message.upper()
        level = next((name for name in ("CRITICAL", "ERROR", "WARNING", "DEBUG", "INFO")
                      if name in upper), "INFO")
        colors = {
            "DEBUG": "#7A8793", "INFO": "#2474A6", "WARNING": "#B7791F",
            "ERROR": "#C0392B", "CRITICAL": "#FFFFFF",
        }
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(colors[level]))
        if level == "CRITICAL":
            fmt.setBackground(QColor("#922B21"))
            fmt.setFontWeight(700)
        elif level == "ERROR":
            fmt.setFontWeight(600)
        cursor.insertText(message + "\n", fmt)
        self.log_view.setTextCursor(cursor)
        self.log_view.ensureCursorVisible()
        self.statusBar().showMessage(message, 8000)

    def _clear_log(self) -> None:
        """Clear the visible log while preserving the selected filter."""
        self.log_view.clear()
        self.statusBar().showMessage("Application log cleared", 3000)
        logger.info("Application log cleared by user")

    def _save_inline_settings(self, *_args) -> None:
        """Persist visible settings without saving the API key."""
        if self._loading_controls:
            return
        self.config.provider = self.provider_combo.currentData()
        self.config.endpoint = self.endpoint_edit.text().strip()
        self.config.model = self.model_edit.text().strip() or "llama3"
        self.config.source_language = self.source_language_combo.currentText()
        self.config.target_language = self.target_language_combo.currentText()
        self.config.parallel_workers = self.parallel_workers_spin.value()
        self.config.segment_chars = self.segment_chars_spin.value()
        self.config.request_timeout = self.timeout_spin.value()
        self.config.temperature = self.temperature_spin.value()
        self.config.max_tokens = self.max_tokens_spin.value()
        self.config.english_greek_glossary_path = (
            self.english_greek_glossary_edit.text().strip()
        )
        self.config.greek_english_glossary_path = (
            self.greek_english_glossary_edit.text().strip()
        )
        self.config.save()
        logger.debug("Main-screen settings saved")

    def _update_session_api_key(self, value: str) -> None:
        self.api_key = value

    def _choose_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select ebook or text file", "",
            "Supported files (*.epub *.srt *.pgn);;EPUB (*.epub);;"
            "Subtitles (*.srt);;Chess PGN (*.pgn)",
        )
        if not path:
            return
        self.source_path = Path(path)
        self.source_edit.setText(str(self.source_path))
        self.output_path = self.source_path.with_name(
            f"{self.source_path.stem}.{self.config.target_language.lower()}{self.source_path.suffix}"
        )
        self.output_edit.setText(str(self.output_path))
        logger.info("Selected input: %s", self.source_path)

    def _choose_output(self) -> None:
        if not self.source_path:
            QMessageBox.information(self, "Select input", "Select an input file first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Select output file", str(self.output_path or self.source_path),
            "Supported files (*.epub *.srt *.pgn)",
        )
        if path:
            self.output_path = Path(path)
            self.output_edit.setText(path)

    def _create_service(self) -> TranslationService:
        if self.config.provider in FREE_PROVIDERS:
            provider = FREE_PROVIDERS[self.config.provider](timeout=self.config.request_timeout)
        else:
            provider = OpenAICompatibleProvider(
                endpoint=self.config.endpoint, model=self.config.model or "llama3",
                api_key=self.api_key, temperature=self.config.temperature,
                max_tokens=self.config.max_tokens, timeout=self.config.request_timeout,
            )
        cache_endpoint = (f"free-provider://{self.config.provider}"
                          if self.config.provider in FREE_PROVIDERS else self.config.endpoint)
        cache_model = (self.config.provider if self.config.provider in FREE_PROVIDERS
                       else (self.config.model or "llama3"))
        logger.info("Selected translation provider: %s", self.config.provider)
        logger.info("Configured model: %s", self.config.model or "llama3")
        return TranslationService(
            provider=provider, cache=TranslationCache(), endpoint=cache_endpoint,
            model=cache_model, source_language=self.config.source_language,
            target_language=self.config.target_language,
            glossary=Glossary(self._active_glossary_path()),
            max_retries=self.config.max_retries, segment_chars=self.config.segment_chars,
        )

    def _start_translation(self) -> None:
        self._save_inline_settings()
        if not self.source_path or not self.source_path.exists():
            QMessageBox.warning(self, "Missing input", "Select an existing input file.")
            return
        if not self.output_path:
            QMessageBox.warning(self, "Missing output", "Select an output path.")
            return
        if self.source_path.resolve() == self.output_path.resolve():
            QMessageBox.warning(self, "Unsafe output", "Output must not overwrite the source file.")
            return
        if self.config.provider == "openai_compatible" and not self.config.endpoint:
            QMessageBox.warning(self, "Provider settings", "Configure the API base URL first.")
            return
        self.progress.setValue(0)
        logger.info("Starting translation job")
        self.worker = TranslationWorker(
            self.source_path, self.output_path, self._create_service(),
            parallel_workers=self.config.parallel_workers,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.log_message.connect(self._append_log)
        self.worker.completed.connect(self._on_completed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()
        self._update_job_state(True)

    def _on_progress(self, current: int, total: int, message: str) -> None:
        self.progress.setValue(int(current * 100 / total) if total else 0)
        self.progress_label.setText(message)

    def _on_completed(self, output: str) -> None:
        self.progress.setValue(100)
        self.progress_label.setText("Completed")
        self.output_path = Path(output)
        self.output_edit.setText(output)
        logger.info("Translation completed: %s", output)
        self._update_job_state(False)
        QMessageBox.information(self, "Translation complete", f"Output written to:\n{output}")

    def _on_cancelled(self, message: str) -> None:
        self.progress_label.setText("Stopped")
        logger.info("Translation stopped: %s", message)
        self._update_job_state(False)

    def _on_failed(self, message: str) -> None:
        self.progress_label.setText("Failed")
        logger.error("Translation failed: %s", message)
        self._update_job_state(False)
        QMessageBox.critical(self, "Translation failed", message[:3000])

    def _cancel_translation(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            logger.info("Stop requested; waiting for the current provider request to finish")
            self.stop_button.setEnabled(False)

    def _update_job_state(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.exit_button.setEnabled(True)

    def _about(self) -> None:
        QMessageBox.about(
            self, "About Standalone Ebook Translator",
            "Standalone Ebook Translator 0.1.7\n"
            "A standalone implementation inspired by Ebook Translator Calibre Plugin.\n"
            "GPL-3.0-only. No warranty.",
        )

    def closeEvent(self, event) -> None:
        """Cancel active work and avoid destroying a still-running QThread."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            logger.info("Exit requested: stopping the active translation")
            if not self.worker.wait(5000):
                logger.warning("Worker is still stopping; wait for the active request and try Exit again")
                QMessageBox.information(
                    self, "Translation is stopping",
                    "The active provider request has not finished. The application will remain open; "
                    "select Exit again after the worker stops.",
                )
                event.ignore()
                return
        logging.getLogger().removeHandler(self._qt_log_handler)
        self._qt_log_handler.close()
        event.accept()
