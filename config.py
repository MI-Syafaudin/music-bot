"""
Core Configuration Module for Enterprise Discord Music Bot.
Defines typed, immutable configuration classes using slotted dataclasses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final
from dotenv import load_dotenv

# Load local environment variables from .env if present
load_dotenv()


@dataclass(slots=True, frozen=True)
class LavalinkConfig:
    """Lavalink v4 node connection configuration."""
    uri: str
    password: str
    identifier: str


@dataclass(slots=True, frozen=True)
class AudioConfig:
    """Audio playback and DSP default configurations."""
    default_volume: int = 80
    max_volume: int = 150
    progress_update_interval: float = 6.0  # Discord rate limit safe
    persistence_interval: float = 10.0
    max_image_bytes: int = 5 * 1024 * 1024  # 5 MB safety bound
    enable_sponsorblock: bool = True
    default_autoplay: bool = False
    dj_role_name: str = "DJ"
    vote_skip_ratio: float = 0.5


@dataclass(slots=True, frozen=True)
class DatabaseConfig:
    """SQLite persistence configuration."""
    db_path: str = "bot_music.db"
    enable_wal: bool = True


@dataclass(slots=True, frozen=True)
class BotConfig:
    """Master application configuration container."""
    token: str
    client_id: int | None
    lavalink: LavalinkConfig
    audio: AudioConfig
    database: DatabaseConfig

    @classmethod
    def from_env(cls) -> BotConfig:
        """Construct configuration instance validated from environment."""
        token: str = os.getenv("DISCORD_TOKEN", "").strip()
        client_id_str: str = os.getenv("DISCORD_CLIENT_ID", "").strip()
        client_id: int | None = int(client_id_str) if client_id_str.isdigit() else None

        lavalink_uri: str = os.getenv("LAVALINK_URI", "http://127.0.0.1:2333").strip()
        lavalink_pass: str = os.getenv("LAVALINK_PASSWORD", "youshallnotpass").strip()
        lavalink_id: str = os.getenv("LAVALINK_IDENTIFIER", "primary-node").strip()

        default_vol: int = int(os.getenv("DEFAULT_VOLUME", "80"))
        sponsorblock_enabled: bool = os.getenv("SPONSORBLOCK_ENABLED", "true").lower() in ("true", "1", "yes")
        autoplay_default: bool = os.getenv("AUTOPLAY_DEFAULT", "false").lower() in ("true", "1", "yes")
        persistence_interval: float = float(os.getenv("PERSISTENCE_INTERVAL_SECONDS", "10.0"))
        db_path: str = os.getenv("DATABASE_PATH", "bot_music.db").strip()
        dj_role: str = os.getenv("DJ_ROLE_NAME", "DJ").strip()
        vote_ratio: float = float(os.getenv("VOTE_SKIP_PERCENTAGE", "0.5"))

        return cls(
            token=token,
            client_id=client_id,
            lavalink=LavalinkConfig(
                uri=lavalink_uri,
                password=lavalink_pass,
                identifier=lavalink_id,
            ),
            audio=AudioConfig(
                default_volume=default_vol,
                progress_update_interval=6.0,
                persistence_interval=persistence_interval,
                enable_sponsorblock=sponsorblock_enabled,
                default_autoplay=autoplay_default,
                dj_role_name=dj_role,
                vote_skip_ratio=vote_ratio,
            ),
            database=DatabaseConfig(
                db_path=db_path,
                enable_wal=True,
            ),
        )


# Global immutable configuration singleton
CONFIG: Final[BotConfig] = BotConfig.from_env()
