"""Logging configuration: console plus a rolling run log."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import config

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else getattr(
        logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO
    )

    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        config.LOG_DIR / "run.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(file_handler)

    # requests/urllib3 are noisy at DEBUG.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
