"""Provider and language settings dialog."""

from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QDoubleSpinBox, QSpinBox,
    QDialogButtonBox, QComboBox, QVBoxLayout, QLabel
)


class SettingsDialog(QDialog):
    """Edit runtime settings; API key remains in memory only."""

    def __init__(self, config, api_key: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Translation settings")
        self.resize(520, 360)
        self.config = config
        self.api_key = api_key

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.provider = QComboBox()
        self.provider.addItem("Google Translate (Free - New)", "google_free_new")
        self.provider.addItem("Google Translate (Free - HTML)", "google_free_html")
        self.provider.addItem("Google Translate (Free - Legacy)", "google_free_legacy")
        self.provider.addItem("DeepL (Free - Web, unofficial)", "deepl_free")
        self.provider.addItem("Microsoft Edge (Free - Experimental)", "microsoft_edge_free")
        self.provider.addItem("OpenAI-compatible / Ollama (API or local)", "openai_compatible")
        provider_index = self.provider.findData(config.provider)
        if provider_index >= 0:
            self.provider.setCurrentIndex(provider_index)
        self.endpoint = QLineEdit(config.endpoint)
        self.model = QLineEdit(config.model)
        self.key = QLineEdit(api_key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.source = QComboBox()
        self.source.addItems(["Auto-detect", "English", "Greek", "German", "French", "Spanish", "Italian", "Dutch", "Japanese", "Chinese"])
        self.source.setCurrentText(config.source_language)
        self.target = QComboBox()
        self.target.addItems(["Greek", "English", "German", "French", "Spanish", "Italian", "Dutch", "Japanese", "Chinese", "Portuguese", "Russian"])
        self.target.setCurrentText(config.target_language)
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.1)
        self.temperature.setValue(config.temperature)
        self.max_tokens = QSpinBox()
        self.max_tokens.setRange(128, 32768)
        self.max_tokens.setValue(config.max_tokens)
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 600)
        self.timeout.setValue(config.request_timeout)
        self.parallel_workers = QSpinBox()
        self.parallel_workers.setRange(1, 10)
        self.parallel_workers.setValue(getattr(config, "parallel_workers", 3))
        self.segment_chars = QSpinBox()
        self.segment_chars.setRange(500, 20000)
        self.segment_chars.setValue(config.segment_chars)
        self.glossary = QLineEdit(config.glossary_path)
        self.glossary.setPlaceholderText("Optional glossary .txt path")

        form.addRow("Translation service", self.provider)
        form.addRow("API base URL (custom provider)", self.endpoint)
        form.addRow("Model", self.model)
        form.addRow("API key (session only)", self.key)
        form.addRow("Source language", self.source)
        form.addRow("Target language", self.target)
        form.addRow("Temperature", self.temperature)
        form.addRow("Maximum output tokens", self.max_tokens)
        form.addRow("Request timeout (seconds)", self.timeout)
        form.addRow("Segment size (characters)", self.segment_chars)
        form.addRow("Parallel workers (EPUB)", self.parallel_workers)
        form.addRow("Glossary file", self.glossary)
        layout.addLayout(form)
        layout.addWidget(QLabel(
            "Free services use public web endpoints without an API key. "
            "They can change, throttle or block automated requests. "
            "Microsoft Edge is experimental because its endpoint has reported 404 errors."
        ))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply(self) -> tuple[object, str]:
        self.config.provider = self.provider.currentData()
        self.config.endpoint = self.endpoint.text().strip()
        self.config.model = self.model.text().strip()
        self.config.source_language = self.source.currentText()
        self.config.target_language = self.target.currentText()
        self.config.temperature = self.temperature.value()
        self.config.max_tokens = self.max_tokens.value()
        self.config.request_timeout = self.timeout.value()
        self.config.segment_chars = self.segment_chars.value()
        self.config.parallel_workers = self.parallel_workers.value()
        self.config.glossary_path = self.glossary.text().strip()
        self.api_key = self.key.text()
        return self.config, self.api_key
