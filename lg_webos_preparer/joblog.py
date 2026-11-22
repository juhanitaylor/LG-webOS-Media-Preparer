"""Logging handlers for a single scan or preparation job."""
from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable


FORMAT = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")


class CallbackHandler(logging.Handler):
    def __init__(self, callback: Callable[[str], None], *, formatted: bool = True):
        super().__init__()
        self.callback = callback
        self.setFormatter(FORMAT if formatted else logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self.callback(self.format(record))


def job_logger(debug: bool = False, handler: logging.Handler | None = None) -> logging.Logger:
    # Each job owns its handlers, even when callers run jobs concurrently.
    logger = logging.Logger("lg_webos_preparer", logging.DEBUG if debug else logging.INFO)
    if handler is None:
        handler = logging.StreamHandler(sys.stderr) if sys.stderr is not None else logging.NullHandler()
        handler.setFormatter(FORMAT)
    logger.addHandler(handler)
    return logger


@contextmanager
def file_log(logger: logging.Logger, folder: Path, mode: str):
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = folder / f"lg_media_{mode}_{stamp}.log"
    handler = logging.FileHandler(path, mode="x", encoding="utf-8", errors="backslashreplace")
    handler.setFormatter(FORMAT)
    logger.addHandler(handler)
    try:
        logger.info("Operational log: %s", path)
        yield
    finally:
        logger.removeHandler(handler)
        handler.close()
