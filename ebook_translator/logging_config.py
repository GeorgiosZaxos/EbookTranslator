"""Logging configuration for GUI-only application logging."""

from __future__ import annotations

import logging


def configure_logging(level: int = logging.DEBUG) -> logging.Logger:
    """Configure logging without writing application records to the shell.

    The main window installs a Qt logging handler that displays all records in
    its in-app log panel. Console handlers inherited from development tools or
    previous configuration are removed here.
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Prevent duplicate or shell-directed output from basicConfig/IDE handlers.
    for handler in list(root.handlers):
        if isinstance(handler, logging.StreamHandler):
            root.removeHandler(handler)
            handler.close()

    # Keep detailed diagnostic messages available to the in-app log panel.
    logging.getLogger("ebook_translator").setLevel(level)
    return logging.getLogger("ebook_translator")
