"""
Real-Time Synced Lyrics Interactive View.
Dynamically displays synced LRC lyric lines matched against current player position.
"""

from __future__ import annotations

import asyncio
import weakref
from typing import TYPE_CHECKING
import discord

from services.lrclib import LrcLibClient, SyncedLyricsResult
from utils.logging import LOGGER

if TYPE_CHECKING:
    from audio.player import MusicPlayer


class SyncedLyricsView(discord.ui.View):
    """Interactive view for real-time synced lyrics scrolling."""

    def __init__(self, player: MusicPlayer) -> None:
        super().__init__(timeout=180.0)
        self._player_ref = weakref.ref(player)
        self._lyrics_client = LrcLibClient()
        self._lyrics_cache: SyncedLyricsResult | None = None
        self._update_task: asyncio.Task | None = None
        self._message: discord.InteractionMessage | None = None
        self._show_plain = False

    @property
    def player(self) -> MusicPlayer | None:
        return self._player_ref()

    async def get_lyrics_embed(self) -> discord.Embed:
        """Fetches and builds the lyrics display embed."""
        player = self.player
        if not player or not player.current:
            return discord.Embed(
                title="Lirik Lagu",
                description="❌ Tidak ada lagu yang sedang diputar.",
                color=discord.Color.red(),
            )

        track = player.current
        if self._lyrics_cache is None:
            duration_sec = track.length // 1000 if track.length else None
            self._lyrics_cache = await self._lyrics_client.fetch_lyrics(
                track_name=track.title,
                artist_name=track.author,
                duration_sec=duration_sec,
            )

        if not self._lyrics_cache:
            return discord.Embed(
                title=f"📜 Lirik: {track.title}",
                description="ℹ️ Lirik tersinkronisasi tidak ditemukan di database LRCLIB.",
                color=discord.Color.dark_gray(),
            )

        embed = discord.Embed(
            title=f"📜 {self._lyrics_cache.track_name} - {self._lyrics_cache.artist_name}",
            color=discord.Color.blurple(),
        )

        if self._show_plain:
            content = self._lyrics_cache.plain_lyrics or "Lirik polos tidak tersedia."
            if len(content) > 4000:
                content = content[:3950] + "\n...[Lirik dipotong]"
            embed.description = content
            return embed

        # Synced lyrics window calculation
        lines = self._lyrics_cache.lines
        if not lines:
            embed.description = self._lyrics_cache.plain_lyrics or "Lirik tersinkronisasi tidak tersedia."
            return embed

        pos_sec = player.position / 1000.0
        current_idx = self._lyrics_cache.get_line_index_at(pos_sec)

        start_idx = max(0, current_idx - 2)
        end_idx = min(len(lines), current_idx + 4)

        display_text = []
        for i in range(start_idx, end_idx):
            line = lines[i]
            mins = int(line.timestamp_sec // 60)
            secs = int(line.timestamp_sec % 60)
            timestamp = f"[{mins:02d}:{secs:02d}]"

            if i == current_idx:
                display_text.append(f"▶ **{timestamp} {line.text}**")
            elif i < current_idx:
                display_text.append(f"*`{timestamp}` {line.text}*")
            else:
                display_text.append(f"`{timestamp}` {line.text}")

        embed.description = "\n\n".join(display_text) or "..."
        embed.set_footer(text=f"Posisi: {int(pos_sec // 60):02d}:{int(pos_sec % 60):02d} • Sinkronisasi Otomatis")
        return embed

    @discord.ui.button(label="Refresh Lirik", emoji="🔄", style=discord.ButtonStyle.primary)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = await self.get_lyrics_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Toggle Plain / Synced", emoji="📑", style=discord.ButtonStyle.secondary)
    async def btn_toggle_plain(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._show_plain = not self._show_plain
        embed = await self.get_lyrics_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        if self._update_task and not self._update_task.done():
            self._update_task.cancel()
        await self._lyrics_client.close()
