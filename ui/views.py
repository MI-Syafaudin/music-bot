"""
Interactive Discord UI Views with Weak References and Safe Controls.
Includes NowPlayingView, SeekModal, EQSelectView, and CustomEQModal.
Eliminates spammy chat notifications on button clicks by updating messages in-place or deferring silently.
"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING, Any
import discord
import wavelink

from audio.dsp import (
    PresetType,
    create_filters_for_preset,
    create_filters_from_5_bands,
)
from database.models import CustomEQPreset
from ui.card import format_time
from utils.logging import LOGGER
from utils.permissions import can_bypass_vote_skip, calculate_vote_quorum
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
            await interaction.response.defer()
            return

        time_str = self.timestamp.value.strip()
        try:
            target_ms = sanitize_seek_timestamp(time_str, player.current.length)
            await player.seek(target_ms)
            if hasattr(player, "now_playing_view") and player.now_playing_view:
                player.now_playing_view.sync_view_states()
            if player.now_playing_message:
                embed = player.build_now_playing_embed()
                await player.now_playing_message.edit(embed=embed, view=getattr(player, "now_playing_view", None))
        except Exception as e:
            LOGGER.error("Error seeking via modal: %s", e)

        # Acknowledge without sending notification text
        await interaction.response.defer()


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
            await interaction.response.defer()
            return

        try:
            val_60 = sanitize_gain(float(self.g_60hz.value.strip()))
            val_230 = sanitize_gain(float(self.g_230hz.value.strip()))
            val_910 = sanitize_gain(float(self.g_910hz.value.strip()))
            val_4k = sanitize_gain(float(self.g_4khz.value.strip()))
            val_14k = sanitize_gain(float(self.g_14khz.value.strip()))
        except ValueError:
            await interaction.response.defer()
            return

        # Apply interpolated filters
        filters = create_filters_from_5_bands(val_60, val_230, val_910, val_4k, val_14k)
        await player.set_filters(filters)
        player.current_preset = self.preset_name or "Custom"

        # Save to database if requested and repository available
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
            try:
                await bot.repository.save_custom_preset(preset_obj)
            except Exception as e:
                LOGGER.warning("Failed to save custom preset: %s", e)

        if player.now_playing_message:
            try:
                embed = player.build_now_playing_embed()
                await player.now_playing_message.edit(embed=embed)
            except Exception:
                pass

        await interaction.response.defer()


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
            discord.SelectOption(label="Electronic", value=PresetType.ELECTRONIC, description="Sub-bass dalam & synths jernih", emoji="⚡"),
            discord.SelectOption(label="Nightcore", value=PresetType.NIGHTCORE, description="Kecepatan +15%, nada lebih tinggi", emoji="🌙"),
            discord.SelectOption(label="Vaporwave", value=PresetType.VAPORWAVE, description="Tempo santai -15%, nada retro", emoji="🌊"),
            discord.SelectOption(label="8D Audio", value=PresetType.EIGHT_D, description="Rotasi suara 360 derajat", emoji="🎧"),
            discord.SelectOption(label="Vocal Boost", value=PresetType.VOCAL_BOOST, description="Penegasan frekuensi vokal 250Hz-2.5kHz", emoji="🗣️"),
        ],
    )
    async def select_preset(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        player = self._player_ref()
        if not player:
            await interaction.response.defer()
            return

        choice = select.values[0]
        filters = create_filters_for_preset(choice)
        await player.set_filters(filters)
        player.current_preset = choice

        # Update the main player message embed in-place
        if player.now_playing_message:
            try:
                embed = player.build_now_playing_embed()
                await player.now_playing_message.edit(embed=embed)
            except Exception:
                pass

        await interaction.response.defer()

    @discord.ui.button(label="Custom EQ Builder", style=discord.ButtonStyle.primary, emoji="🛠️")
    async def open_builder(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self._player_ref()
        if not player:
            await interaction.response.defer()
            return

        await interaction.response.send_modal(CustomEQModal(player))


class SeekSelect(discord.ui.Select):
    """
    Interactive seek dropdown slider allowing users to jump directly to percentages or timestamps.
    Dynamically updates its placeholder and options as the song progresses.
    """

    def __init__(self, player: MusicPlayer) -> None:
        self._player_ref = weakref.ref(player)
        super().__init__(
            placeholder=self._build_placeholder(player),
            min_values=1,
            max_values=1,
            options=self._build_options(player),
            row=0,
        )

    def _build_placeholder(self, player: MusicPlayer | None) -> str:
        if not player or not player.current or player.current.length <= 0:
            return "📍 Geser Posisi Lagu (Seek Slider)..."
        pos = player.position
        dur = player.current.length
        ratio = max(0.0, min(1.0, pos / dur))
        pct = int(ratio * 100)
        icon = "⏸️" if player.paused else "▶️"
        return f"📍 {icon} {format_time(pos)} / {format_time(dur)} ({pct}%) • Klik untuk Geser"

    def _build_options(self, player: MusicPlayer | None) -> list[discord.SelectOption]:
        if not player or not player.current or player.current.length <= 0:
            return [
                discord.SelectOption(
                    label="Custom Timestamp (MM:SS)",
                    value="custom",
                    emoji="🎯",
                    description="Input waktu spesifik secara manual",
                )
            ]

        dur = player.current.length
        milestones = [0, 15, 30, 50, 70, 85, 95]
        options: list[discord.SelectOption] = []
        for pct in milestones:
            target_ms = int(dur * (pct / 100.0))
            t_str = format_time(target_ms)
            desc = "Awal lagu" if pct == 0 else ("Pertengahan lagu" if pct == 50 else f"Posisi {pct}% lagu")
            emoji = "⏮️" if pct == 0 else ("▶️" if pct == 50 else "🔘")
            options.append(
                discord.SelectOption(
                    label=f"{pct}% ({t_str})",
                    value=str(target_ms),
                    description=desc,
                    emoji=emoji,
                )
            )

        options.append(
            discord.SelectOption(
                label="Custom Timestamp...",
                value="custom",
                description="Buka modal dialog MM:SS / HH:MM:SS",
                emoji="🎯",
            )
        )
        return options

    def sync_state(self, player: MusicPlayer | None) -> None:
        """Syncs placeholder and options with current player position."""
        self.placeholder = self._build_placeholder(player)
        self.options = self._build_options(player)

    async def callback(self, interaction: discord.Interaction) -> None:
        player = self._player_ref()
        if not player or not player.current:
            await interaction.response.defer()
            return

        choice = self.values[0]
        if choice == "custom":
            await interaction.response.send_modal(SeekModal(player))
            return

        try:
            target_ms = int(choice)
            await player.seek(target_ms)
            view = self.view
            if view and hasattr(view, "sync_view_states"):
                view.sync_view_states()
            embed = player.build_now_playing_embed()
            await interaction.response.edit_message(embed=embed, view=view)
        except Exception as e:
            LOGGER.error("Error seeking via select: %s", e)
            await interaction.response.defer()


class NowPlayingView(discord.ui.View):
    """
    Main interactive control view for currently playing track.
    Implements weakref to Player to guarantee zero circular reference memory leaks.
    Updates controls in-place and eliminates chat-cluttering notification popups.
    """

    def __init__(self, player: MusicPlayer) -> None:
        super().__init__(timeout=None)
        self._player_ref = weakref.ref(player)
        self.seek_select = SeekSelect(player)
        self.add_item(self.seek_select)
        self.sync_view_states()

    @property
    def player(self) -> MusicPlayer | None:
        return self._player_ref()

    def sync_view_states(self) -> None:
        """Synchronizes button labels, styles, emojis, and seek select state to player."""
        player = self.player
        if not player:
            return

        # Synchronize seek select dropdown
        self.seek_select.sync_state(player)

        # Play/Pause button state
        self.btn_play_pause.emoji = "▶️" if player.paused else "⏸️"
        self.btn_play_pause.style = (
            discord.ButtonStyle.secondary if player.paused else discord.ButtonStyle.primary
        )

        # Loop button state
        loop_labels = {"off": "Loop: Off", "track": "Loop: Track", "queue": "Loop: Queue"}
        self.btn_loop.label = loop_labels.get(player.loop_mode, "Loop: Off")
        self.btn_loop.style = (
            discord.ButtonStyle.success if player.loop_mode != "off" else discord.ButtonStyle.secondary
        )

        # Autoplay button state
        is_auto = player.autoplay == wavelink.AutoPlayMode.enabled
        self.btn_autoplay.label = f"Autoplay: {'On' if is_auto else 'Off'}"
        self.btn_autoplay.style = (
            discord.ButtonStyle.success if is_auto else discord.ButtonStyle.secondary
        )

    def _sync_button_states(self) -> None:
        """Backward compatibility alias."""
        self.sync_view_states()

    # ---------------- Row 1: Playback & Fast Seek Controls ----------------

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player:
            await interaction.response.defer()
            return

        if not player.queue.history.is_empty:
            prev_track = player.queue.history.peek()
            player.queue.put_at(0, prev_track)
            await player.skip()

        await interaction.response.defer()

    @discord.ui.button(label="-15s", emoji="⏪", style=discord.ButtonStyle.secondary, row=1)
    async def btn_rewind(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player or not player.current:
            await interaction.response.defer()
            return

        new_pos = max(0, player.position - 15000)
        await player.seek(new_pos)
        self.sync_view_states()
        embed = player.build_now_playing_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, row=1)
    async def btn_play_pause(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player or not player.current:
            await interaction.response.defer()
            return

        await player.pause(not player.paused)
        self.sync_view_states()
        embed = player.build_now_playing_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="+15s", emoji="⏩", style=discord.ButtonStyle.secondary, row=1)
    async def btn_forward(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player or not player.current:
            await interaction.response.defer()
            return

        new_pos = min(player.current.length, player.position + 15000)
        await player.seek(new_pos)
        self.sync_view_states()
        embed = player.build_now_playing_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_skip(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player or not player.current or not interaction.guild:
            await interaction.response.defer()
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            member = interaction.guild.get_member(interaction.user.id) or member

        vc = player.channel
        if not vc:
            await player.skip()
            await interaction.response.defer()
            return

        # Check bypass permission or vote skip
        if can_bypass_vote_skip(member, vc, player.dj_role_name):
            await player.skip()
        else:
            quorum_reached, _, _ = player.add_vote_skip(member.id)
            if quorum_reached:
                await player.skip()

        await interaction.response.defer()

    # ---------------- Row 2: Secondary Controls ----------------

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=2)
    async def btn_stop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player:
            await interaction.response.defer()
            return

        player.queue.clear()
        await player.destroy()

        embed = discord.Embed(
            title="⏹️ Pemutaran Dihentikan",
            description="Pemutar musik telah dimatikan dan antrean dibersihkan.",
            color=discord.Color.dark_embed(),
        )
        try:
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception:
            await interaction.response.defer()

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=2)
    async def btn_shuffle(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player or player.queue.is_empty:
            await interaction.response.defer()
            return

        player.queue.shuffle()
        self.sync_view_states()
        embed = player.build_now_playing_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Loop: Off", emoji="🔁", style=discord.ButtonStyle.secondary, row=2)
    async def btn_loop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player:
            await interaction.response.defer()
            return

        modes = ["off", "track", "queue"]
        next_mode = modes[(modes.index(player.loop_mode) + 1) % len(modes)]
        player.loop_mode = next_mode
        self.sync_view_states()
        embed = player.build_now_playing_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Autoplay: Off", emoji="📻", style=discord.ButtonStyle.secondary, row=2)
    async def btn_autoplay(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player:
            await interaction.response.defer()
            return

        new_state = (
            wavelink.AutoPlayMode.disabled
            if player.autoplay == wavelink.AutoPlayMode.enabled
            else wavelink.AutoPlayMode.enabled
        )
        player.autoplay = new_state
        self.sync_view_states()
        embed = player.build_now_playing_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="EQ", emoji="🎛️", style=discord.ButtonStyle.secondary, row=2)
    async def btn_equalizer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player:
            await interaction.response.defer()
            return

        await interaction.response.send_message(
            "🎛️ **Pilih Preset Equalizer atau Bangun Custom EQ:**",
            view=EQSelectView(player),
            ephemeral=True,
        )

    # ---------------- Row 3: Utility Controls ----------------

    @discord.ui.button(label="Lyrics", emoji="📜", style=discord.ButtonStyle.secondary, row=3)
    async def btn_lyrics(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player or not player.current:
            await interaction.response.defer()
            return

        from ui.lyrics_view import SyncedLyricsView
        view = SyncedLyricsView(player)
        initial_embed = await view.get_lyrics_embed()
        await interaction.response.send_message(embed=initial_embed, view=view, ephemeral=True)

    @discord.ui.button(label="Seek", emoji="🎯", style=discord.ButtonStyle.secondary, row=3)
    async def btn_seek_modal(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player = self.player
        if not player or not player.current:
            await interaction.response.defer()
            return

        await interaction.response.send_modal(SeekModal(player))
