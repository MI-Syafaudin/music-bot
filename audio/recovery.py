"""
Crash Recovery and State Persistence Engine.
Periodically saves active audio states to SQLite WAL and resumes exact playback on reboot.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
import discord
import wavelink

from audio.dsp import deserialize_filters
from database.models import SavedPlayerSession
from database.repository import AudioRepository
from utils.logging import LOGGER

if TYPE_CHECKING:
    from audio.player import MusicPlayer
    from main import EnterpriseMusicBot


class CrashRecoveryManager:
    """Manages periodic state saving and post-reboot automated recovery."""

    def __init__(self, bot: EnterpriseMusicBot, repository: AudioRepository, interval: float = 10.0) -> None:
        self.bot = bot
        self.repository = repository
        self.interval = interval
        self._periodic_task: asyncio.Task | None = None

    def start(self) -> None:
        """Starts background periodic snapshot task."""
        if self._periodic_task is None or self._periodic_task.done():
            self._periodic_task = asyncio.create_task(self._snapshot_loop())
            LOGGER.info("Crash recovery background snapshot worker started (interval: %.1fs).", self.interval)

    def stop(self) -> None:
        """Stops background periodic snapshot task."""
        if self._periodic_task and not self._periodic_task.done():
            self._periodic_task.cancel()
            LOGGER.info("Crash recovery background snapshot worker stopped.")

    async def _snapshot_loop(self) -> None:
        """Periodically iterates over active guild players and dumps state to SQLite."""
        try:
            while True:
                await asyncio.sleep(self.interval)
                await self.snapshot_all_active_players()
        except asyncio.CancelledError:
            pass

    async def snapshot_player(self, player: MusicPlayer) -> None:
        """Saves a single player's state immediately."""
        if not player.guild or not player.channel:
            return

        # If player is not playing anything and queue is empty, clean up session
        if not player.current and player.queue.is_empty:
            await self.repository.delete_session(player.guild.id)
            return

        text_channel_id = player.text_channel.id if player.text_channel else 0
        current_track_data = player.current.raw_data if player.current else None
        active_filters_data = player.filters() if player.filters else None

        # Collect raw payloads from all queued tracks
        queue_payloads = [track.raw_data for track in player.queue]

        await self.repository.save_session(
            guild_id=player.guild.id,
            voice_channel_id=player.channel.id,
            text_channel_id=text_channel_id,
            current_track=current_track_data,
            position_ms=player.position,
            volume=player.volume,
            paused=player.paused,
            autoplay_mode=int(player.autoplay.value),
            active_filters=active_filters_data,
            queue_items=queue_payloads,
        )

    async def snapshot_all_active_players(self) -> None:
        """Iterates over all guilds and snapshots active MusicPlayers."""
        for guild in self.bot.guilds:
            player: MusicPlayer | None = getattr(guild, "voice_client", None)  # type: ignore
            if isinstance(player, wavelink.Player) and hasattr(player, "text_channel"):
                try:
                    await self.snapshot_player(player)
                except Exception as e:
                    LOGGER.error("Failed to snapshot player for guild %s: %s", guild.id, e)

    async def recover_sessions(self) -> int:
        """
        Scans SQLite database for saved sessions and re-establishes playback.
        Returns the number of successfully recovered guild sessions.
        """
        saved_sessions: list[SavedPlayerSession] = await self.repository.load_all_sessions()
        if not saved_sessions:
            LOGGER.info("No active crash recovery sessions found in database.")
            return 0

        LOGGER.info("Found %d audio session(s) pending crash recovery...", len(saved_sessions))
        recovered_count = 0

        for session in saved_sessions:
            guild = self.bot.get_guild(session.guild_id)
            if not guild:
                LOGGER.warning("Guild %d not found during recovery; deleting session.", session.guild_id)
                await self.repository.delete_session(session.guild_id)
                continue

            voice_channel = guild.get_channel(session.voice_channel_id)
            if not isinstance(voice_channel, (discord.VoiceChannel, discord.StageChannel)):
                LOGGER.warning("Voice channel %d not found in guild %s; deleting session.", session.voice_channel_id, guild.name)
                await self.repository.delete_session(session.guild_id)
                continue

            text_channel = guild.get_channel(session.text_channel_id)
            if not isinstance(text_channel, discord.TextChannel):
                text_channel = None

            try:
                from audio.player import MusicPlayer

                # Reconnect to voice channel
                player: MusicPlayer = await voice_channel.connect(cls=MusicPlayer)  # type: ignore
                player.text_channel = text_channel

                # Reconstruct queued tracks
                for q_item in session.queue_items:
                    try:
                        t = wavelink.Playable(q_item)
                        player.queue.put(t)
                    except Exception as ex:
                        LOGGER.warning("Failed to restore queued track: %s", ex)

                # Restore settings
                await player.set_volume(session.volume)
                player.autoplay = wavelink.AutoPlayMode(session.autoplay_mode)

                if session.active_filters:
                    restored_filters = deserialize_filters(session.active_filters)
                    await player.set_filters(restored_filters)

                # Reconstruct and resume current track
                if session.current_track:
                    current_playable = wavelink.Playable(session.current_track)
                    await player.play(current_playable, start_time=session.position_ms, paused=session.paused)
                    LOGGER.info(
                        "Recovered track '%s' in guild '%s' at %dms.",
                        current_playable.title,
                        guild.name,
                        session.position_ms,
                    )
                elif not player.queue.is_empty:
                    next_track = player.queue.get()
                    await player.play(next_track)

                recovered_count += 1

                # Send friendly recovery notice to guild text channel
                if text_channel:
                    pos_sec = session.position_ms // 1000
                    mins, secs = pos_sec // 60, pos_sec % 60
                    embed = discord.Embed(
                        title="🔄 Sesi Pemutaran Dipulihkan (Crash Recovery)",
                        description=(
                            f"Bot berhasil mendeteksi dan memulihkan sesi audio yang terputus!\n"
                            f"• **Channel Suara:** <#{voice_channel.id}>\n"
                            f"• **Posisi Lanjutan:** `{mins:02d}:{secs:02d}`\n"
                            f"• **Antrean Tersimpan:** `{len(player.queue)} lagu`"
                        ),
                        color=discord.Color.green(),
                    )
                    await text_channel.send(embed=embed)

            except Exception as e:
                LOGGER.error("Failed to recover session for guild %s: %s", guild.name, e, exc_info=True)
                await self.repository.delete_session(session.guild_id)

        LOGGER.info("Crash recovery process completed: %d session(s) restored.", recovered_count)
        return recovered_count
