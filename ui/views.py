"""
Interactive Discord UI Views with Weak References and Safe Controls.
Includes NowPlayingView, SeekModal, EQSelectView, and CustomEQModal.
"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING, Any
import discord

from audio.dsp import (
    PresetType,
    create_filters_for_preset,
    create_filters_from_5_bands,
)
from database.models import CustomEQPreset
from utils.logging import LOGGER
from utils.permissions import can_bypass_vote_skip, calculate_vote_quorum, get_voice_listeners
from utils.security import sanitize_gain, sanitize_seek_timestamp, SecurityValidationError

if TYPE_CHECKING:
    from audio.player import MusicPlayer
    from main import EnterpriseMusicBot


class SeekModal(discord.ui.Modal, title="Seek ke Waktu Lagu"):
    """Modal dialog for jumping to an exact timestamp in MM:SS or HH:MM:SS format."""

    timestamp = discord.ui.TextInput(
        label="Target Timestamp (MM:SS atau HH:MM:SS)",
        placeholder="Contoh: 02:45 atau 1:15:30",
        min_length=1,
        max_length=10,
        required=True,
    )

    def __init__(self, player: MusicPlayer) -> None:
        super().__init__()
        self._player_ref = weakref.ref(player)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        player = self._player_ref()
        if not player or not player.current:
            await interaction.response.send_message("❌ Tidak ada lagu yang sedang diputar.", ephemeral=True)
            return

        time_str = self.timestamp.value.strip()
        try:
            target_ms = sanitize_seek_timestamp(time_str, player.current.length)
            await player.seek(target_ms)
            formatted = f"{target_ms // 60000:02d}:{(target_ms % 60000) // 1000:02d}"
            await interaction.response.send_message(
                f"⏩ Memindahkan pemutaran ke `{formatted}`.",
                ephemeral=True,
            )
        except SecurityValidationError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        except Exception as e:
            LOGGER.error("Error seeking: %s", e)
            await interaction.response.send_message("❌ Gagal menggeser durasi lagu.", ephemeral=True)


class CustomEQModal(discord.ui.Modal, title="Custom Equalizer Builder"):
    """Modal for custom tuning 5 frequency bands (-0.25 to +1.0) and saving preset."""

    g_60hz = discord.ui.TextInput(
        label="Gain 60Hz Sub-Bass (-0.25 s/d 1.0)",
        placeholder="0.0 (Netral)",
        default="0.0",
        max_length=5,
        required=True,
    )
    g_230hz = discord.ui.TextInput(
        label="Gain 230Hz Bass (-0.25 s/d 1.0)",
        placeholder="0.0 (Netral)",
        default="0.0",
        max_length=5,
        required=True,
    )
    g_910hz = discord.ui.TextInput(
        label="Gain 910Hz Midrange (-0.25 s/d 1.0)",
        placeholder="0.0 (Netral)",
        default="0.0",
        max_length=5,
        required=True,
    )
    g_4khz = discord.ui.TextInput(
        label="Gain 4kHz Presence (-0.25 s/d 1.0)",
        placeholder="0.0 (Netral)",
        default="0.0",
        max_length=5,
        required=True,
    )
    g_14khz = discord.ui.TextInput(
        label="Gain 14kHz Treble (-0.25 s/d 1.0)",
        placeholder="0.0 (Netral)",
        default="0.0",
        max_length=5,
        required=True,
    )

    def __init__(self, player: MusicPlayer, preset_name_to_save: str | None = None) -> None:
        super().__init__()
        self._player_ref = weakref.ref(player)
        self.preset_name = preset_name_to_save

    async def on_submit(self, interaction: discord.Interaction) -> None:
        player = self._player_ref()
        if not player:
            await interaction.response.send_message("❌ Pemutar musik tidak ditemukan.", ephemeral=True)
            return

        try:
            val_60 = sanitize_gain(float(self.g_60hz.value.strip()))
            val_230 = sanitize_gain(float(self.g_230hz.value.strip()))
            val_910 = sanitize_gain(float(self.g_910hz.value.strip()))
            val_4k = sanitize_gain(float(self.g_4khz.value.strip()))
            val_14k = sanitize_gain(float(self.g_14khz.value.strip()))
        except ValueError:
            await interaction.response.send_message("❌ Nilai gain harus berupa angka desimal.", ephemeral=True)
            return

        # Apply interpolated filters
        filters = create_filters_from_5_bands(val_60, val_230, val_910, val_4k, val_14k)
        await player.set_filters(filters)
        player.current_preset = "custom"

        # Save to database if bot repository is available
        saved_msg = ""
        bot: EnterpriseMusicBot = interaction.client  # type: ignore
        if self.preset_name and hasattr(bot, "repository"):
            import time
            preset_obj = CustomEQPreset(
                user_id=interaction.user.id,
                preset_name=self.preset_name,
                gain_60hz=val_60,
                gain_230hz=val_230,
                gain_910hz=val_910,
                gain_4khz=val_4k,
                gain_14khz=val_14k,
                created_at=time.time(),
            )
            await bot.repository.save_custom_preset(preset_obj)
            saved_msg = f" dan disimpan sebagai preset `{self.preset_name}`"

        await interaction.response.send_message(
            f"🎛️ **Custom Equalizer Diterapkan{saved_msg}!**\n"
            f"• 60Hz: `{val_60:+0.2f}` | 230Hz: `{val_230:+0.2f}` | 910Hz: `{val_910:+0.2f}` | "
            f"4kHz: `{val_4k:+0.2f}` | 14kHz: `{val_14k:+0.2f}`",
            ephemeral=True,
        )


class EQSelectView(discord.ui.View):
    """View presenting instant EQ presets and custom builder trigger."""

    def __init__(self, player: MusicPlayer) -> None:
        super().__init__(timeout=90.0)
        self._player_ref = weakref.ref(player)

    @discord.ui.select(
        placeholder="Pilih Preset Equalizer / DSP...",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="Flat", value=PresetType.FLAT, description="Suara orisinil tanpa filter EQ", emoji="🎵"),
            discord.SelectOption(label="Bassboost", value=PresetType.BASSBOOST, description="Peningkatan sub-bass bertenaga", emoji="🔊"),
            discord.SelectOption(label="Pop", value=PresetType.POP, description="Optimasi vokal dan nada cerah", emoji="🎤"),
            discord.SelectOption(label="Rock", value=PresetType.ROCK, description="Punch tebal dan treble tajam", emoji="🎸"),
            discord.SelectOption(label="Classical", value=PresetType.CLASSICAL, description="Kehangatan orkestra & akustik", emoji="🎻"),
            discord.SelectOption(label="Electronic", value=PresetType.ELECTRONIC, description="Sub-bass dalam & synthesizers jernih", emoji="⚡"),
            discord.SelectOption(label="Nightcore", value=PresetType.NIGHTCORE, description="Kecepatan +15%, nada lebih tinggi", emoji="🌙"),
            discord.SelectOption(label="Vaporwave", value=PresetType.VAPORWAVE, description="Tempo santai -15%, nada retro", emoji="🌊"),
            discord.SelectOption(label="8D Audio", value=PresetType.EIGHT_D, description="Rotasi suara 360 derajat", emoji="🎧"),
            discord.SelectOption(label="Vocal Boost", value=PresetType.VOCAL_BOOST, description="Penegasan frekuensi vokal 250Hz-2.5kHz", emoji="🗣️"),
        ],
    )
    async def select_preset(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        player = self._player_ref()
        if not player:
            await interaction.response.send_message("❌ Pemutar musik tidak ditemukan.", ephemeral=True)
            return

        choice = select.values[0]
        filters = create_filters_for_preset(choice)
        await player.set_filters(filters)
        player.current_preset = choice

        await interaction.response.send_message(
            f"🎛️ Preset audio diubah menjadi **{choice.title()}**.",
            ephemeral=True,
        )

    @discord.ui.button(label="Custom EQ Builder", style=discord.ButtonStyle.primary, emoji="🛠️")
    async def open_builder(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self._player_ref()
        if not player:
            await interaction.response.send_message("❌ Pemutar musik tidak ditemukan.", ephemeral=True)
            return

        await interaction.response.send_modal(CustomEQModal(player))


class NowPlayingView(discord.ui.View):
    """
    Main interactive control view for currently playing track.
    Implements weakref to Player to guarantee zero circular reference memory leaks.
    """

    def __init__(self, player: MusicPlayer) -> None:
        super().__init__(timeout=None)
        self._player_ref = weakref.ref(player)

    @property
    def player(self) -> MusicPlayer | None:
        return self._player_ref()

    # ---------------- Row 0: Basic Controls ----------------

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player:
            await interaction.response.send_message("❌ Pemutar musik tidak aktif.", ephemeral=True)
            return

        if not player.queue.history.is_empty:
            prev_track = player.queue.history.peek()
            player.queue.put_at(0, prev_track)
            await player.skip()
            await interaction.response.send_message("⏮️ Memutar lagu sebelumnya.", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ Tidak ada riwayat lagu sebelumnya.", ephemeral=True)

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, row=0)
    async def btn_play_pause(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player:
            await interaction.response.send_message("❌ Pemutar musik tidak aktif.", ephemeral=True)
            return

        await player.pause(not player.paused)
        state_text = "dijeda (paused)" if player.paused else "dilanjutkan (resumed)"
        await interaction.response.send_message(f"⏯️ Lagu **{state_text}**.", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_skip(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player or not player.current or not interaction.guild:
            await interaction.response.send_message("❌ Tidak ada lagu yang sedang diputar.", ephemeral=True)
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            member = interaction.guild.get_member(interaction.user.id) or member

        vc = player.channel
        if not vc:
            await player.skip()
            await interaction.response.send_message("⏭️ Lagu dilewati.", ephemeral=True)
            return

        # Check bypass permission
        if can_bypass_vote_skip(member, vc, player.dj_role_name):
            await player.skip()
            await interaction.response.send_message("⏭️ Lagu dilewati (Bypass DJ/Admin/Solo).", ephemeral=False)
            return

        # Vote skip
        quorum_reached, current_votes, quorum = player.add_vote_skip(member.id)
        if quorum_reached:
            await player.skip()
            await interaction.response.send_message(
                f"⏭️ Kuorum tercapai ({current_votes}/{quorum} suara)! Lagu dilewati.",
                ephemeral=False,
            )
        else:
            await interaction.response.send_message(
                f"🗳️ Suara skip dicatat! ({current_votes}/{quorum} suara diperlukan).",
                ephemeral=False,
            )

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def btn_stop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player:
            await interaction.response.send_message("❌ Pemutar musik tidak aktif.", ephemeral=True)
            return

        player.queue.clear()
        await player.disconnect()
        await interaction.response.send_message("⏹️ Pemutaran dihentikan dan bot keluar.", ephemeral=True)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=0)
    async def btn_shuffle(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player:
            await interaction.response.send_message("❌ Pemutar musik tidak aktif.", ephemeral=True)
            return

        if player.queue.is_empty:
            await interaction.response.send_message("ℹ️ Antrean masih kosong.", ephemeral=True)
            return

        player.queue.shuffle()
        await interaction.response.send_message("🔀 Antrean lagu berhasil diacak.", ephemeral=True)

    # ---------------- Row 1: Seek & Audio Controls ----------------

    @discord.ui.button(label="-15s", emoji="⏪", style=discord.ButtonStyle.secondary, row=1)
    async def btn_rewind(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player or not player.current:
            await interaction.response.send_message("❌ Tidak ada lagu yang sedang diputar.", ephemeral=True)
            return

        new_pos = max(0, player.position - 15000)
        await player.seek(new_pos)
        await interaction.response.send_message("⏪ Mundur 15 detik.", ephemeral=True)

    @discord.ui.button(label="+15s", emoji="⏩", style=discord.ButtonStyle.secondary, row=1)
    async def btn_forward(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player or not player.current:
            await interaction.response.send_message("❌ Tidak ada lagu yang sedang diputar.", ephemeral=True)
            return

        new_pos = min(player.current.length, player.position + 15000)
        await player.seek(new_pos)
        await interaction.response.send_message("⏩ Maju 15 detik.", ephemeral=True)

    @discord.ui.button(label="Seek", emoji="🎯", style=discord.ButtonStyle.secondary, row=1)
    async def btn_seek_modal(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player or not player.current:
            await interaction.response.send_message("❌ Tidak ada lagu yang sedang diputar.", ephemeral=True)
            return

        await interaction.response.send_modal(SeekModal(player))

    @discord.ui.button(label="Equalizer", emoji="🎛️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_equalizer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player:
            await interaction.response.send_message("❌ Pemutar musik tidak aktif.", ephemeral=True)
            return

        await interaction.response.send_message(
            "🎛️ **Pilih Preset Equalizer atau Bangun Custom EQ:**",
            view=EQSelectView(player),
            ephemeral=True,
        )

    @discord.ui.button(label="Lyrics", emoji="📜", style=discord.ButtonStyle.secondary, row=1)
    async def btn_lyrics(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player or not player.current:
            await interaction.response.send_message("❌ Tidak ada lagu yang sedang diputar.", ephemeral=True)
            return

        from ui.lyrics_view import SyncedLyricsView
        view = SyncedLyricsView(player)
        initial_embed = await view.get_lyrics_embed()
        await interaction.response.send_message(embed=initial_embed, view=view, ephemeral=True)

    # ---------------- Row 2: Mode Toggles ----------------

    @discord.ui.button(label="Loop: Off", emoji="🔁", style=discord.ButtonStyle.secondary, row=2)
    async def btn_loop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player:
            await interaction.response.send_message("❌ Pemutar musik tidak aktif.", ephemeral=True)
            return

        modes = ["off", "track", "queue"]
        next_mode = modes[(modes.index(player.loop_mode) + 1) % len(modes)]
        player.loop_mode = next_mode
        button.label = f"Loop: {next_mode.title()}"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Autoplay: Off", emoji="📻", style=discord.ButtonStyle.secondary, row=2)
    async def btn_autoplay(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player:
            await interaction.response.send_message("❌ Pemutar musik tidak aktif.", ephemeral=True)
            return

        import wavelink
        new_state = (
            wavelink.AutoPlayMode.disabled
            if player.autoplay == wavelink.AutoPlayMode.enabled
            else wavelink.AutoPlayMode.enabled
        )
        player.autoplay = new_state
        is_on = new_state == wavelink.AutoPlayMode.enabled
        button.label = f"Autoplay: {'On' if is_on else 'Off'}"
        button.style = discord.ButtonStyle.success if is_on else discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)
