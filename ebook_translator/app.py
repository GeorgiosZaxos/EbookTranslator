"""Application bootstrap."""

import sys
from PyQt6.QtWidgets import QApplication
from ebook_translator.gui.main_window import MainWindow
from ebook_translator.logging_config import configure_logging


def main() -> int:
    """Start the desktop application."""
    # Configure shell-silent logging before any application modules emit logs.
    logger = configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Standalone Ebook Translator")
    app.setOrganizationName("EbookTranslator")
    window = MainWindow()
    logger.info("Starting Standalone Ebook Translator")
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
