"""
Enterprise Music Player Subclass.
Extends wavelink.Player with rate-limited live progress updates, vote-skipping,
weak-referenced view bindings, and memory-safe image caching.
"""

from __future__ import annotations

import asyncio
import io
import weakref
from typing import TYPE_CHECKING, Any
import aiohttp
import discord
import wavelink

from audio.sponsorblock import SponsorBlockManager
from config import CONFIG
from ui.card import (
    download_cover_art_bounded,
    render_now_playing_card,
    create_progress_bar,
    PLATFORM_META,
)
from ui.views import NowPlayingView
from utils.logging import LOGGER
from utils.permissions import calculate_vote_quorum, get_voice_listeners

if TYPE_CHECKING:
    from main import EnterpriseMusicBot


class MusicPlayer(wavelink.Player):
    """
    Production-grade audio player with memory-safe reference management and live controls.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.text_channel: discord.TextChannel | None = None
        self.now_playing_message: discord.Message | None = None
        self.now_playing_view: NowPlayingView | None = None

        self.vote_skips: set[int] = set()
        self.current_preset: str = "flat"
        self.loop_mode: str = "off"  # "off", "track", "queue"
        self.dj_role_name: str = CONFIG.audio.dj_role_name

        self._cover_cache: bytes | None = None
        self._progress_task: asyncio.Task | None = None
        self._http_session: aiohttp.ClientSession | None = None

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    def reset_vote_skips(self) -> None:
        """Clears all accumulated skip votes for the new track."""
        self.vote_skips.clear()

    def add_vote_skip(self, user_id: int) -> tuple[bool, int, int]:
        """
        Registers a member vote to skip.
        Returns: (quorum_reached, total_votes, quorum_required)
        """
        self.vote_skips.add(user_id)
        channel = self.channel
        if not channel:
            return True, 1, 1

        listeners = get_voice_listeners(channel)
        quorum = calculate_vote_quorum(len(listeners))
        return len(self.vote_skips) >= quorum, len(self.vote_skips), quorum

    async def setup_sponsorblock(self) -> None:
        """Configures SponsorBlock plugin filters on Lavalink node."""
        if CONFIG.audio.enable_sponsorblock:
            await SponsorBlockManager.configure_player(self)

    def build_now_playing_embed(self) -> discord.Embed:
        """
        Builds modern, sleek Discord Embed with minimalist thumbnail cover on the top right,
        song title & author beside the cover, and real-time interactive progress bar below.
        """
        if not self.current:
            return discord.Embed(
                title="🎶 Tidak Ada Lagu",
                description="Tidak ada lagu yang sedang diputar saat ini.",
                color=discord.Color.dark_embed(),
            )

        track = self.current
        source_key = (track.source or "").lower().replace(" ", "").replace("_", "")
        meta = PLATFORM_META.get(source_key, PLATFORM_META["default"])

        embed = discord.Embed(
            title=f"🎵 {track.title}",
            url=track.uri if track.uri else None,
            color=meta["color"],
        )

        embed.set_author(
            name=f"Sedang Memutar • {meta['name']}",
        )

        # Real-time progress bar formatted separately in description
        progress_str = create_progress_bar(
            position_ms=self.position,
            duration_ms=track.length,
            length=14,
            is_paused=self.paused,
        )

        embed.description = (
            f"👤 **Artis / Kreator:** `{track.author}`\n"
            f"📡 **Platform:** `{meta['name']}`\n\n"
            f"**Progress Pemutaran:**\n"
            f"{progress_str}\n"
        )

        loop_labels = {"off": "Mati", "track": "Lagu 🔂", "queue": "Antrean 🔁"}
        loop_display = loop_labels.get(self.loop_mode, self.loop_mode.title())
        autoplay_display = "Aktif 📻" if self.autoplay == wavelink.AutoPlayMode.enabled else "Mati"

        embed.add_field(name="🎛️ Equalizer", value=f"`{self.current_preset.title()}`", inline=True)
        embed.add_field(name="🔊 Volume", value=f"`{self.volume}%`", inline=True)
        embed.add_field(name="🔁 Loop", value=f"`{loop_display}`", inline=True)
        embed.add_field(name="📻 Autoplay", value=f"`{autoplay_display}`", inline=True)
        embed.add_field(name="📑 Antrean", value=f"`{len(self.queue)} Lagu`", inline=True)

        # Minimalist cover thumbnail on top-right:
        if track.artwork:
            embed.set_thumbnail(url=track.artwork)
        else:
            embed.set_thumbnail(url="attachment://cover.png")

        embed.set_footer(text="Enterprise Music • Kualitas Suara Hi-Fi")
        return embed

    async def send_now_playing_card(self) -> None:
        """
        Renders and sends the Now-Playing card with minimalist thumbnail and interactive controls.
        """
        if not self.current or not self.text_channel:
            return

        # Stop existing background update task
        if self._progress_task and not self._progress_task.done():
            self._progress_task.cancel()

        track = self.current
        cover_buffer: io.BytesIO | None = None
        file: discord.File | None = None

        # Download or generate fallback cover only if track has no artwork
        if not track.artwork:
            try:
                cover_buffer = await render_now_playing_card(cover_bytes=None)
                file = discord.File(fp=cover_buffer, filename="cover.png")
            except Exception as e:
                LOGGER.debug("Failed to render fallback cover: %s", e)

        try:
            embed = self.build_now_playing_embed()
            view = NowPlayingView(self)
            self.now_playing_view = view

            # Cleanly remove old now playing message if present to avoid chat clutter
            if self.now_playing_message:
                try:
                    await self.now_playing_message.delete()
                except Exception:
                    pass

            if file:
                self.now_playing_message = await self.text_channel.send(
                    embed=embed,
                    file=file,
                    view=view,
                )
            else:
                self.now_playing_message = await self.text_channel.send(
                    embed=embed,
                    view=view,
                )
        except Exception as e:
            LOGGER.error("Failed to generate or send Now-Playing card: %s", e)
        finally:
            if cover_buffer:
                cover_buffer.close()

        # Start rate-limited throttled progress updater (every 5-6 seconds)
        self._progress_task = asyncio.create_task(self._progress_updater_loop())

    async def _progress_updater_loop(self) -> None:
        """
        Background task updating the Now-Playing progress bar and view in real-time every 5 seconds.
        Updates ONLY the Embed text and View dropdown - zero file uploads, zero image reloading/flicker.
        Strictly conforms to Discord rate limits.
        """
        try:
            interval = CONFIG.audio.progress_update_interval
            while self.playing and self.current:
                await asyncio.sleep(interval)
                if not self.playing or self.paused or not self.now_playing_message:
                    continue

                try:
                    embed = self.build_now_playing_embed()
                    view = self.now_playing_view
                    if view:
                        view.sync_view_states()
                    await self.now_playing_message.edit(embed=embed, view=view)
                except discord.NotFound:
                    # Message was deleted by user or moderator
                    LOGGER.debug("Now playing message was deleted; stopping updater.")
                    break
                except discord.HTTPException as e:
                    LOGGER.debug("Discord HTTP exception during progress update: %s", e)
                except Exception as e:
                    LOGGER.warning("Unexpected error during progress update: %s", e)
        except asyncio.CancelledError:
            pass

    async def destroy(self) -> None:
        """Cleans up internal resources, cancels update loops, and closes sessions."""
        if self._progress_task and not self._progress_task.done():
            self._progress_task.cancel()

        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

        self._cover_cache = None
        await super().disconnect()
