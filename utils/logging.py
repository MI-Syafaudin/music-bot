"""
Structured Logging Architecture for Enterprise Music Bot.
"""

from __future__ import annotations

import logging
import sys


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configures structured console logging with custom formatters."""
    logger = logging.getLogger("music_bot")
    if logger.hasHandlers():
        return logger

    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-7s] [%(name)s:%(funcName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Moderate noisy external loggers
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("wavelink").setLevel(logging.INFO)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    return logger


LOGGER = setup_logging()
