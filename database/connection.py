"""
Async SQLite Connection Manager with WAL (Write-Ahead Logging) optimization.
"""

from __future__ import annotations

import pathlib
from typing import AsyncGenerator
import aiosqlite
from utils.logging import LOGGER

SCHEMA_FILE = pathlib.Path(__file__).parent / "schema.sql"


class DatabaseManager:
    """Manages SQLite connection lifecycle with WAL mode and high-performance pragmas."""

    def __init__(self, db_path: str = "bot_music.db") -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Initializes connection, enforces WAL mode, and applies migrations."""
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        # Production SQLite pragmas
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute("PRAGMA synchronous=NORMAL;")
        await self._db.execute("PRAGMA cache_size=-64000;")  # 64MB cache
        await self._db.execute("PRAGMA busy_timeout=5000;")
        await self._db.execute("PRAGMA foreign_keys=ON;")

        # Apply schema
        schema_text = SCHEMA_FILE.read_text(encoding="utf-8")
        await self._db.executescript(schema_text)
        await self._db.commit()
        LOGGER.info("SQLite initialized successfully at %s with WAL mode enabled.", self.db_path)

    async def close(self) -> None:
        """Closes the underlying database connection gracefully."""
        if self._db is not None:
            await self._db.close()
            self._db = None
            LOGGER.info("SQLite connection closed gracefully.")

    @property
    def connection(self) -> aiosqlite.Connection:
        """Returns the active database connection."""
        if self._db is None:
            raise RuntimeError("DatabaseManager has not been initialized. Call initialize() first.")
        return self._db
