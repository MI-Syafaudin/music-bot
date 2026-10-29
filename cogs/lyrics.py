"""
Lyrics Cog: Slash command to view real-time synchronized and plain lyrics via LRCLIB.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import discord
from discord import app_commands
from discord.ext import commands

from audio.player import MusicPlayer
from services.lrclib import LrcLibClient
from ui.lyrics_view import SyncedLyricsView
from utils.logging import LOGGER

if TYPE_CHECKING:
    from main import EnterpriseMusicBot


class LyricsCog(commands.Cog, name="Lyrics"):
    """Lyrics lookup and real-time synchronized lyrics display."""

    def __init__(self, bot: EnterpriseMusicBot) -> None:
        self.bot = bot
        self.client = LrcLibClient()

    async def cog_unload(self) -> None:
        await self.client.close()

    @app_commands.command(name="lyrics", description="Tampilkan lirik lagu tersinkronisasi real-time (LRC) via LRCLIB.")
    @app_commands.describe(query="Judul lagu & artis (opsional; otomatis mendeteksi lagu yang sedang diputar)")
    async def lyrics(self, interaction: discord.Interaction, query: str | None = None) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore

        if query is None:
            if not player or not player.current:
                await interaction.response.send_message(
                    "❌ Tidak ada lagu yang sedang diputar. Masukkan judul lagu secara manual: `/lyrics query:Judul Lagu Artis`.",
                    ephemeral=True,
                )
                return

            # Open interactive real-time synchronized view
            view = SyncedLyricsView(player)
            embed = await view.get_lyrics_embed()
            await interaction.response.send_message(embed=embed, view=view)
            return

        # Manual lookup
        await interaction.response.defer(thinking=True)
        result = await self.client.fetch_lyrics(track_name=query, artist_name="")
        if not result or (not result.lines and not result.plain_lyrics):
            await interaction.followup.send(f"❌ Lirik untuk query **`{query}`** tidak ditemukan di database LRCLIB.")
            return

        embed = discord.Embed(
            title=f"📜 {result.track_name} - {result.artist_name}",
            color=discord.Color.blurple(),
        )

        content = result.plain_lyrics
        if not content and result.lines:
            content = "\n".join([line.text for line in result.lines])

        if content and len(content) > 4000:
            content = content[:3950] + "\n...[Lirik dipotong karena batas karakter]"

        embed.description = content or "Lirik tidak tersedia."
        await interaction.followup.send(embed=embed)
