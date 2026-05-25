"""Shared logging setup for iBackupX."""

from __future__ import annotations

import logging
import pathlib

import colorama

from rich.logging import RichHandler


def setup_logging(destination: str, *, verbose: bool, enable_file: bool) -> logging.Logger:
    """Configure console and file logging and return the root logger."""

    level = logging.DEBUG if verbose else logging.INFO
    colorama.just_fix_windows_console()
    logger = logging.getLogger()
    logger.setLevel(level)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    console_handler = RichHandler(rich_tracebacks=True, show_time=True, show_path=False)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(console_handler)

    if enable_file:
        log_path = pathlib.Path(destination) / "ibackupx.log"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(file_handler)

    return logger
