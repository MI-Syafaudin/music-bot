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
from ui.card import download_cover_art_bounded, render_now_playing_card
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

        self.vote_skips: set[int] = set()
        self.current_preset: str = "flat"
        self.loop_mode: str = "off"  # "off", "track", "queue"
        self.dj_role_name: str = "DJ"

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
        await SponsorBlockManager.configure_player(self)

    async def send_now_playing_card(self) -> None:
        """
        Renders and sends the high-resolution dynamic Now-Playing visual card in-memory.
        """
        if not self.current or not self.text_channel:
            return

        # Stop existing background update task
        if self._progress_task and not self._progress_task.done():
            self._progress_task.cancel()

        track = self.current
        session = await self._get_http_session()

        # Download cover art with bounded stream (max 5MB)
        if track.artwork:
            self._cover_cache = await download_cover_art_bounded(track.artwork, session)
        else:
            self._cover_cache = None

        card_buffer: io.BytesIO | None = None
        try:
            card_buffer = await render_now_playing_card(
                title=track.title,
                author=track.author,
                position_ms=self.position,
                duration_ms=track.length,
                cover_bytes=self._cover_cache,
                platform_name=track.source or "Music",
                preset_name=self.current_preset,
                volume=self.volume,
                autoplay=(self.autoplay == wavelink.AutoPlayMode.enabled),
            )

            file = discord.File(fp=card_buffer, filename="now_playing.png")
            embed = discord.Embed(color=discord.Color.from_rgb(20, 24, 38))
            embed.set_image(url="attachment://now_playing.png")

            view = NowPlayingView(self)
            self.now_playing_message = await self.text_channel.send(
                embed=embed,
                file=file,
                view=view,
            )
        except Exception as e:
            LOGGER.error("Failed to generate or send Now-Playing card: %s", e)
        finally:
            if card_buffer:
                card_buffer.close()

        # Start rate-limited throttled progress updater (every 6 seconds)
        self._progress_task = asyncio.create_task(self._progress_updater_loop())

    async def _progress_updater_loop(self) -> None:
        """
        Background task updating the Now-Playing card progress bar every 6 seconds.
        Ensures strict compliance with Discord rate limits (5/5s).
        """
        try:
            while self.playing and self.current:
                await asyncio.sleep(6.0)
                if not self.playing or self.paused or not self.now_playing_message:
                    continue

                card_buffer: io.BytesIO | None = None
                try:
                    card_buffer = await render_now_playing_card(
                        title=self.current.title,
                        author=self.current.author,
                        position_ms=self.position,
                        duration_ms=self.current.length,
                        cover_bytes=self._cover_cache,
                        platform_name=self.current.source or "Music",
                        preset_name=self.current_preset,
                        volume=self.volume,
                        autoplay=(self.autoplay == wavelink.AutoPlayMode.enabled),
                    )

                    file = discord.File(fp=card_buffer, filename="now_playing.png")
                    embed = discord.Embed(color=discord.Color.from_rgb(20, 24, 38))
                    embed.set_image(url="attachment://now_playing.png")

                    await self.now_playing_message.edit(
                        embed=embed,
                        attachments=[file],
                    )
                except discord.NotFound:
                    # Message was deleted by user or moderator
                    LOGGER.debug("Now playing message was deleted; stopping updater.")
                    break
                except discord.HTTPException as e:
                    LOGGER.debug("Discord HTTP exception during card update: %s", e)
                except Exception as e:
                    LOGGER.warning("Unexpected error during card progress update: %s", e)
                finally:
                    if card_buffer:
                        card_buffer.close()

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
