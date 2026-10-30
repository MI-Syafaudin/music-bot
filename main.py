"""
Enterprise Discord Music Bot Entrypoint.
Orchestrates uvloop, orjson, AutoShardedBot with zero-caching, Lavalink v4 pool,
WAL-mode SQLite persistence, and automated crash recovery.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import Final
import discord
from discord.ext import commands
import uvloop
import wavelink

from audio.recovery import CrashRecoveryManager
from cogs.filters import FiltersCog
from cogs.lyrics import LyricsCog
from cogs.music import MusicCog
from config import CONFIG, BotConfig
from database.connection import DatabaseManager
from database.repository import AudioRepository
from utils.logging import LOGGER


class EnterpriseMusicBot(commands.AutoShardedBot):
    """
    Production-grade AutoSharded Discord bot with zero member caching and minimal intents.
    """

    def __init__(self, config: BotConfig) -> None:
        self.config = config

        # Standard default intents (guilds, voice_states, etc.) without privileged requirements
        intents = discord.Intents.default()

        super().__init__(
            command_prefix="!",
            intents=intents,
            member_cache_flags=discord.MemberCacheFlags.none(),  # Zero member caching
            max_messages=None,  # Zero message caching
            chunk_guilds_at_startup=False,
        )

        self.db_manager = DatabaseManager(self.config.database.db_path)
        self.repository: AudioRepository = None  # type: ignore
        self.recovery_manager: CrashRecoveryManager = None  # type: ignore

    async def setup_hook(self) -> None:
        """Initializes database, connects audio nodes, and registers slash commands."""
        LOGGER.info("Starting Enterprise Music Bot setup hook...")

        # 1. Initialize SQLite with WAL Mode
        await self.db_manager.initialize()
        self.repository = AudioRepository(self.db_manager.connection)
        self.recovery_manager = CrashRecoveryManager(
            bot=self,
            repository=self.repository,
            interval=self.config.audio.persistence_interval,
        )

        # 2. Connect to Lavalink v4 Node Pool
        node = wavelink.Node(
            uri=self.config.lavalink.uri,
            password=self.config.lavalink.password,
            identifier=self.config.lavalink.identifier,
            inactive_player_timeout=300,
        )
        await wavelink.Pool.connect(nodes=[node], client=self)
        LOGGER.info("Connected to Lavalink pool on %s", self.config.lavalink.uri)

        # 3. Load Cogs
        await self.add_cog(MusicCog(self))
        await self.add_cog(FiltersCog(self))
        await self.add_cog(LyricsCog(self))
        LOGGER.info("Music, Filters, and Lyrics cogs registered successfully.")

        # 4. Sync Global Application Slash Commands
        try:
            synced = await self.tree.sync()
            LOGGER.info("Synced %d global application slash commands.", len(synced))
        except Exception as e:
            LOGGER.error("Failed to sync slash commands: %s", e)

    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload) -> None:
        """Triggered when the Lavalink v4 node completes handshake and session setup."""
        LOGGER.info(
            "Lavalink node '%s' is READY! (Resumed session: %s)",
            payload.node.identifier,
            payload.resumed,
        )

        # Execute automated crash recovery for any unclosed audio sessions
        recovered = await self.recovery_manager.recover_sessions()
        if recovered > 0:
            LOGGER.info("Crash recovery restored %d active audio sessions.", recovered)

        # Start periodic state persistence worker
        self.recovery_manager.start()

    async def on_ready(self) -> None:
        """Triggered when Discord gateway handshake is complete."""
        LOGGER.info(
            "Logged into Discord as %s (ID: %s) across %d guild(s) and %d shard(s).",
            self.user,
            self.user.id if self.user else "Unknown",
            len(self.guilds),
            self.shard_count or 1,
        )

    async def close(self) -> None:
        """Performs clean, graceful teardown of all subsystem resources."""
        LOGGER.info("Shutting down Enterprise Music Bot gracefully...")

        # Stop crash recovery worker
        if self.recovery_manager:
            self.recovery_manager.stop()

        # Disconnect Lavalink pool
        try:
            await wavelink.Pool.close()
            LOGGER.info("Lavalink pool connections closed.")
        except Exception as e:
            LOGGER.warning("Error closing Lavalink pool: %s", e)

        # Close SQLite WAL database
        await self.db_manager.close()

        # Close bot connection
        await super().close()
        LOGGER.info("Bot shutdown completed.")


def main() -> None:
    """Application entrypoint with uvloop runtime installation."""
    # Install uvloop for high-throughput event-loop
    uvloop.install()

    if not CONFIG.token:
        LOGGER.critical(
            "DISCORD_TOKEN environment variable is not configured! Please provide a valid token in .env."
        )
        sys.exit(1)

    bot = EnterpriseMusicBot(CONFIG)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_signal() -> None:
        LOGGER.info("Received termination signal. Initiating shutdown...")
        asyncio.create_task(bot.close())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(bot.start(CONFIG.token))
    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt received.")
    finally:
        loop.run_until_complete(bot.close())
        loop.close()


if __name__ == "__main__":
    main()
