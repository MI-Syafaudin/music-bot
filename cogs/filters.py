"""
Filters & Equalizer Cog: Manages 15-band EQ presets, DSP filters, and SQLite-backed custom user presets.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
import discord
from discord import app_commands
from discord.ext import commands

from audio.dsp import (
    PresetType,
    create_filters_for_preset,
    create_filters_from_5_bands,
)
from database.models import CustomEQPreset
from utils.logging import LOGGER
from utils.security import sanitize_gain

if TYPE_CHECKING:
    from audio.player import MusicPlayer
    from main import EnterpriseMusicBot


class FiltersCog(commands.GroupCog, group_name="filter"):
    """Equalizer presets, DSP effects, and custom equalizer builder commands."""

    def __init__(self, bot: EnterpriseMusicBot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="preset", description="Terapkan preset Equalizer atau efek DSP instan.")
    @app_commands.describe(preset="Pilih salah satu preset audio")
    @app_commands.choices(
        preset=[
            app_commands.Choice(name="🎵 Flat (Netral)", value=PresetType.FLAT),
            app_commands.Choice(name="🔊 Bassboost (Heavy Lows)", value=PresetType.BASSBOOST),
            app_commands.Choice(name="🎤 Pop (Vokal Jernih)", value=PresetType.POP),
            app_commands.Choice(name="🎸 Rock (Punch & Highs)", value=PresetType.ROCK),
            app_commands.Choice(name="🎻 Classical (Warm Acoustic)", value=PresetType.CLASSICAL),
            app_commands.Choice(name="⚡ Electronic (Sub-bass & Treble)", value=PresetType.ELECTRONIC),
            app_commands.Choice(name="🌙 Nightcore (Speed +15%, Pitch Up)", value=PresetType.NIGHTCORE),
            app_commands.Choice(name="🌊 Vaporwave (Speed -15%, Pitch Down)", value=PresetType.VAPORWAVE),
            app_commands.Choice(name="🎧 8D Audio (Rotasi Suara 360°)", value=PresetType.EIGHT_D),
            app_commands.Choice(name="🗣️ Vocal Boost (Peningkatan Vokal 250Hz-2.5kHz)", value=PresetType.VOCAL_BOOST),
        ]
    )
    async def preset(self, interaction: discord.Interaction, preset: app_commands.Choice[str]) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore
        if not player:
            await interaction.response.send_message("❌ Bot tidak sedang aktif di voice channel.", ephemeral=True)
            return

        filters = create_filters_for_preset(preset.value)
        await player.set_filters(filters)
        player.current_preset = preset.name

        await interaction.response.send_message(
            f"🎛️ Preset audio diterapkan: **{preset.name}**."
        )

    @app_commands.command(
        name="custom",
        description="Atur 5 pita frekuensi utama (-0.25 s/d +1.0) dan simpan preset opsional.",
    )
    @app_commands.describe(
        gain_60hz="Sub-bass / kick (-0.25 s/d 1.0)",
        gain_230hz="Bass / warmth (-0.25 s/d 1.0)",
        gain_910hz="Midrange vokal/gitar (-0.25 s/d 1.0)",
        gain_4khz="Presence / clarity (-0.25 s/d 1.0)",
        gain_14khz="Treble / air (-0.25 s/d 1.0)",
        save_as="Nama preset untuk disimpan ke database (opsional)",
    )
    async def custom(
        self,
        interaction: discord.Interaction,
        gain_60hz: float,
        gain_230hz: float,
        gain_910hz: float,
        gain_4khz: float,
        gain_14khz: float,
        save_as: str | None = None,
    ) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore
        if not player:
            await interaction.response.send_message("❌ Bot tidak sedang aktif di voice channel.", ephemeral=True)
            return

        # Sanitize all gains
        g60 = sanitize_gain(gain_60hz)
        g230 = sanitize_gain(gain_230hz)
        g910 = sanitize_gain(gain_910hz)
        g4k = sanitize_gain(gain_4khz)
        g14k = sanitize_gain(gain_14khz)

        filters = create_filters_from_5_bands(g60, g230, g910, g4k, g14k)
        await player.set_filters(filters)
        player.current_preset = save_as or "Custom"

        saved_text = ""
        if save_as:
            preset_name = save_as.strip().lower()
            preset_obj = CustomEQPreset(
                user_id=interaction.user.id,
                preset_name=preset_name,
                gain_60hz=g60,
                gain_230hz=g230,
                gain_910hz=g910,
                gain_4khz=g4k,
                gain_14khz=g14k,
                created_at=time.time(),
            )
            await self.bot.repository.save_custom_preset(preset_obj)
            saved_text = f"\n💾 Disimpan ke database sebagai preset `{preset_name}`."

        await interaction.response.send_message(
            f"🎛️ **Custom Equalizer Diterapkan!**\n"
            f"• 60Hz: `{g60:+0.2f}`\n"
            f"• 230Hz: `{g230:+0.2f}`\n"
            f"• 910Hz: `{g910:+0.2f}`\n"
            f"• 4kHz: `{g4k:+0.2f}`\n"
            f"• 14kHz: `{g14k:+0.2f}`"
            f"{saved_text}"
        )

    @app_commands.command(name="load", description="Muat preset equalizer custom yang pernah Anda simpan.")
    @app_commands.describe(name="Nama preset tersimpan")
    async def load(self, interaction: discord.Interaction, name: str) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore
        if not player:
            await interaction.response.send_message("❌ Bot tidak sedang aktif di voice channel.", ephemeral=True)
            return

        clean_name = name.strip().lower()
        preset_obj = await self.bot.repository.get_custom_preset(interaction.user.id, clean_name)
        if not preset_obj:
            await interaction.response.send_message(f"❌ Preset `{clean_name}` tidak ditemukan dalam database Anda.", ephemeral=True)
            return

        filters = create_filters_from_5_bands(
            preset_obj.gain_60hz,
            preset_obj.gain_230hz,
            preset_obj.gain_910hz,
            preset_obj.gain_4khz,
            preset_obj.gain_14khz,
        )
        await player.set_filters(filters)
        player.current_preset = preset_obj.preset_name

        await interaction.response.send_message(
            f"🎛️ Berhasil memuat preset **`{preset_obj.preset_name}`**!\n"
            f"• 60Hz: `{preset_obj.gain_60hz:+0.2f}` | 230Hz: `{preset_obj.gain_230hz:+0.2f}` | "
            f"910Hz: `{preset_obj.gain_910hz:+0.2f}` | 4kHz: `{preset_obj.gain_4khz:+0.2f}` | "
            f"14kHz: `{preset_obj.gain_14khz:+0.2f}`"
        )

    @app_commands.command(name="list", description="Lihat daftar semua preset equalizer custom milik Anda.")
    async def list_presets(self, interaction: discord.Interaction) -> None:
        presets = await self.bot.repository.list_custom_presets(interaction.user.id)
        if not presets:
            await interaction.response.send_message("ℹ️ Anda belum memiliki preset equalizer tersimpan.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🎛️ Preset Equalizer Milik {interaction.user.display_name}",
            color=discord.Color.gold(),
        )
        for p in presets:
            embed.add_field(
                name=f"📌 {p.preset_name}",
                value=f"60Hz: `{p.gain_60hz:+0.2f}` | 230Hz: `{p.gain_230hz:+0.2f}` | 910Hz: `{p.gain_910hz:+0.2f}` | 4k: `{p.gain_4khz:+0.2f}` | 14k: `{p.gain_14khz:+0.2f}`",
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="delete", description="Hapus preset custom yang tersimpan.")
    @app_commands.describe(name="Nama preset yang ingin dihapus")
    async def delete_preset(self, interaction: discord.Interaction, name: str) -> None:
        clean_name = name.strip().lower()
        success = await self.bot.repository.delete_custom_preset(interaction.user.id, clean_name)
        if success:
            await interaction.response.send_message(f"🗑️ Preset `{clean_name}` berhasil dihapus.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Preset `{clean_name}` tidak ditemukan.", ephemeral=True)

    @app_commands.command(name="reset", description="Reset semua filter audio dan equalizer ke orisinil (Flat).")
    async def reset(self, interaction: discord.Interaction) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore
        if not player:
            await interaction.response.send_message("❌ Bot tidak sedang aktif di voice channel.", ephemeral=True)
            return

        filters = create_filters_for_preset(PresetType.FLAT)
        await player.set_filters(filters)
        player.current_preset = "flat"
        await interaction.response.send_message("🔄 Seluruh filter DSP dan Equalizer telah direset ke orisinil.")
