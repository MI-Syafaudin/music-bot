"""
Music Cog: Primary slash commands for playback, queue management, volume, and autoplay.
Provides modern, sleek Discord Embed UI and reliable audio connectivity with self-deafen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import discord
from discord import app_commands
from discord.ext import commands
import wavelink

from audio.player import MusicPlayer
from audio.resolver import AudioResolver
from audio.sponsorblock import SponsorBlockManager
from config import CONFIG
from ui.card import PLATFORM_META, create_progress_bar, format_time
from utils.logging import LOGGER
from utils.permissions import can_bypass_vote_skip
from utils.security import sanitize_seek_timestamp, SecurityValidationError

if TYPE_CHECKING:
    from main import EnterpriseMusicBot


class MusicCog(commands.Cog, name="Music"):
    """Core enterprise music commands and event listeners."""

    def __init__(self, bot: EnterpriseMusicBot) -> None:
        self.bot = bot

    # ---------------- Helper Methods ----------------

    async def _ensure_voice(
        self, interaction: discord.Interaction
    ) -> tuple[MusicPlayer | None, str | None]:
        """Validates that user is connected to a voice channel and retrieves/connects the player with self-deaf."""
        if not interaction.guild:
            return None, "❌ Perintah ini hanya dapat dijalankan di dalam server (guild)."

        user = interaction.user
        if not isinstance(user, discord.Member) or not user.voice or not user.voice.channel:
            return None, "❌ Anda harus bergabung ke dalam Voice Channel terlebih dahulu!"

        voice_channel = user.voice.channel
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore

        if player is None:
            # Connect player with self_deaf=True to ensure reliable audio output and avoid packet drops
            player = await voice_channel.connect(cls=MusicPlayer, self_deaf=True)  # type: ignore
            player.text_channel = interaction.channel  # type: ignore
            try:
                await player.set_volume(CONFIG.audio.default_volume)
            except Exception as e:
                LOGGER.debug("Error setting initial volume: %s", e)
        elif player.channel.id != voice_channel.id:
            # Check if bot is playing alone
            listeners = [m for m in player.channel.members if not m.bot]
            if not listeners:
                await player.move_to(voice_channel)
            else:
                return None, f"❌ Bot sedang digunakan di channel suara <#{player.channel.id}>."

        return player, None

    # ---------------- Slash Commands ----------------

    @app_commands.command(name="play", description="Putar lagu atau playlist dari Spotify, YouTube Music, Apple Music, dll.")
    @app_commands.describe(query="Judul lagu atau link resmi (Spotify/YouTube/Apple Music/Tidal/Deezer/SoundCloud)")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer(thinking=True)

        player, err = await self._ensure_voice(interaction)
        if err or not player:
            await interaction.followup.send(err or "❌ Gagal menginisialisasi pemutar musik.")
            return

        try:
            results: wavelink.Search = await AudioResolver.resolve(query)
        except SecurityValidationError as e:
            await interaction.followup.send(f"⚠️ {e}")
            return
        except Exception as e:
            LOGGER.error("Resolution error for '%s': %s", query, e)
            await interaction.followup.send("❌ Terjadi kesalahan saat mencari lagu atau link tersebut.")
            return

        if not results:
            await interaction.followup.send("❌ Tidak ditemukan hasil pencarian untuk lagu tersebut.")
            return

        # Setup SponsorBlock if not already done
        await player.setup_sponsorblock()

        if isinstance(results, wavelink.Playlist):
            # Enqueue all tracks in playlist
            for track in results.tracks:
                player.queue.put(track)

            if not player.playing:
                first_track = player.queue.get()
                await player.play(first_track)

            embed = discord.Embed(
                title="📑 Playlist Ditambahkan ke Antrean",
                description=(
                    f"### `{results.name}`\n"
                    f"• **Jumlah Lagu:** `{len(results.tracks)} lagu`\n"
                    f"• **Pemohon:** {interaction.user.mention}"
                ),
                color=discord.Color.brand_green(),
            )
            embed.set_footer(text="Enterprise Music • Playlist Terdaftar")
            await interaction.followup.send(embed=embed)
        else:
            # Single or list of tracks
            track: wavelink.Playable = results[0]
            if not player.playing:
                await player.play(track)
                # When player starts playing, on_wavelink_track_start will send the rich visual Now Playing card
                source_key = (track.source or "").lower().replace(" ", "").replace("_", "")
                meta = PLATFORM_META.get(source_key, PLATFORM_META["default"])
                embed = discord.Embed(
                    title=f"▶️ Memulai Pemutaran",
                    description=f"[{track.title}]({track.uri or 'https://discord.com'})\n**Artis:** `{track.author}`",
                    color=meta["color"],
                )
                if track.artwork:
                    embed.set_thumbnail(url=track.artwork)
                await interaction.followup.send(embed=embed)
            else:
                player.queue.put(track)
                duration_str = format_time(track.length)
                source_key = (track.source or "").lower().replace(" ", "").replace("_", "")
                meta = PLATFORM_META.get(source_key, PLATFORM_META["default"])

                embed = discord.Embed(
                    title="🎶 Lagu Ditambahkan ke Antrean",
                    description=(
                        f"### [{track.title}]({track.uri or 'https://discord.com'})\n"
                        f"• **Artis:** `{track.author}`\n"
                        f"• **Durasi:** `{duration_str}`\n"
                        f"• **Posisi Antrean:** `#{len(player.queue)}`\n"
                        f"• **Pemohon:** {interaction.user.mention}"
                    ),
                    color=meta["color"],
                )
                if track.artwork:
                    embed.set_thumbnail(url=track.artwork)
                embed.set_footer(text=f"Platform: {meta['name']}")
                await interaction.followup.send(embed=embed)

    @app_commands.command(name="pause", description="Jeda (pause) pemutaran audio saat ini.")
    async def pause(self, interaction: discord.Interaction) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore
        if not player or not player.playing:
            await interaction.response.send_message("❌ Tidak ada lagu yang sedang diputar.", ephemeral=True)
            return

        await player.pause(True)
        if hasattr(player, "now_playing_view") and player.now_playing_view:
            player.now_playing_view.sync_view_states()
        if player.now_playing_message:
            try:
                embed = player.build_now_playing_embed()
                await player.now_playing_message.edit(embed=embed, view=getattr(player, "now_playing_view", None))
            except Exception:
                pass
        await interaction.response.send_message("⏸️ Lagu telah dijeda.", ephemeral=True)

    @app_commands.command(name="resume", description="Lanjutkan pemutaran audio yang sedang dijeda.")
    async def resume(self, interaction: discord.Interaction) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore
        if not player or not player.current:
            await interaction.response.send_message("❌ Tidak ada lagu yang sedang diputar.", ephemeral=True)
            return

        await player.pause(False)
        if hasattr(player, "now_playing_view") and player.now_playing_view:
            player.now_playing_view.sync_view_states()
        if player.now_playing_message:
            try:
                embed = player.build_now_playing_embed()
                await player.now_playing_message.edit(embed=embed, view=getattr(player, "now_playing_view", None))
            except Exception:
                pass
        await interaction.response.send_message("▶️ Pemutaran lagu dilanjutkan.", ephemeral=True)

    @app_commands.command(name="skip", description="Lewati lagu saat ini.")
    async def skip(self, interaction: discord.Interaction) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore
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

        if can_bypass_vote_skip(member, vc, player.dj_role_name):
            await player.skip()
            await interaction.response.send_message("⏭️ Lagu dilewati.", ephemeral=True)
            return

        quorum_reached, current_votes, quorum = player.add_vote_skip(member.id)
        if quorum_reached:
            await player.skip()
            await interaction.response.send_message(f"⏭️ Kuorum tercapai ({current_votes}/{quorum} suara)! Lagu dilewati.", ephemeral=True)
        else:
            await interaction.response.send_message(f"🗳️ Suara skip dicatat! ({current_votes}/{quorum} suara diperlukan).", ephemeral=True)

    @app_commands.command(name="seek", description="Pindah ke menit/detik tertentu pada lagu (MM:SS).")
    @app_commands.describe(timestamp="Format MM:SS atau HH:MM:SS (contoh: 02:30)")
    async def seek(self, interaction: discord.Interaction, timestamp: str) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore
        if not player or not player.current:
            await interaction.response.send_message("❌ Tidak ada lagu yang sedang diputar.", ephemeral=True)
            return

        try:
            target_ms = sanitize_seek_timestamp(timestamp, player.current.length)
            await player.seek(target_ms)
            formatted = format_time(target_ms)
            if hasattr(player, "now_playing_view") and player.now_playing_view:
                player.now_playing_view.sync_view_states()
            if player.now_playing_message:
                embed = player.build_now_playing_embed()
                await player.now_playing_message.edit(embed=embed, view=getattr(player, "now_playing_view", None))
            await interaction.response.send_message(f"⏩ Waktu lagu digeser ke `{formatted}`.", ephemeral=True)
        except SecurityValidationError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="stop", description="Hentikan pemutaran, hapus antrean, dan putuskan sambungan bot.")
    async def stop(self, interaction: discord.Interaction) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore
        if not player:
            await interaction.response.send_message("❌ Bot tidak sedang memutar lagu.", ephemeral=True)
            return

        player.queue.clear()
        await player.destroy()
        await interaction.response.send_message("⏹️ Pemutaran dihentikan dan antrean dibersihkan.", ephemeral=True)

    @app_commands.command(name="queue", description="Lihat daftar antrean lagu saat ini.")
    async def queue(self, interaction: discord.Interaction) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore
        if not player or not player.current:
            await interaction.response.send_message("❌ Antrean sedang kosong.", ephemeral=True)
            return

        curr = player.current
        bar = create_progress_bar(player.position, curr.length, length=12, is_paused=player.paused)

        embed = discord.Embed(
            title="🎶 Antrean Lagu Server",
            description=(
                f"**Sedang Diputar:**\n"
                f"[{curr.title}]({curr.uri or 'https://discord.com'})\n"
                f"👤 `{curr.author}`\n"
                f"{bar}\n"
            ),
            color=discord.Color.blurple(),
        )

        if player.queue.is_empty:
            embed.add_field(
                name="Antrean Berikutnya",
                value="*Tidak ada lagu berikutnya dalam antrean. Gunakan `/play` untuk menambah lagu.*",
                inline=False,
            )
        else:
            queue_list = []
            for idx, track in enumerate(list(player.queue)[:10], start=1):
                t_str = format_time(track.length)
                queue_list.append(f"`{idx:02d}.` **[{track.title}]({track.uri or 'https://discord.com'})** (`{t_str}`) - `{track.author}`")
            remaining = len(player.queue) - 10
            if remaining > 0:
                queue_list.append(f"*...dan {remaining} lagu lainnya.*")
            embed.add_field(
                name=f"Daftar Antrean ({len(player.queue)} lagu)",
                value="\n".join(queue_list),
                inline=False,
            )

        embed.set_footer(text=f"Volume: {player.volume}% • Mode Loop: {player.loop_mode.title()}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="nowplaying", description="Tampilkan kartu visual Now-Playing lagu saat ini.")
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore
        if not player or not player.current:
            await interaction.response.send_message("❌ Tidak ada lagu yang sedang diputar.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        player.text_channel = interaction.channel  # type: ignore
        await player.send_now_playing_card()
        await interaction.followup.send("🎶 Kartu visual Now-Playing diperbarui.", ephemeral=True)

    @app_commands.command(name="autoplay", description="Aktifkan/nonaktifkan Smart Autoplay (Radio Mode).")
    async def autoplay(self, interaction: discord.Interaction) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore
        if not player:
            await interaction.response.send_message("❌ Bot tidak sedang aktif di voice channel.", ephemeral=True)
            return

        if player.autoplay == wavelink.AutoPlayMode.enabled:
            player.autoplay = wavelink.AutoPlayMode.disabled
            await interaction.response.send_message("📻 **Smart Autoplay dimatikan.**", ephemeral=True)
        else:
            player.autoplay = wavelink.AutoPlayMode.enabled
            await interaction.response.send_message("📻 **Smart Autoplay diaktifkan!** Rekomendasi lagu sejenis akan diputar otomatis.", ephemeral=True)

        if player.now_playing_message:
            try:
                embed = player.build_now_playing_embed()
                await player.now_playing_message.edit(embed=embed)
            except Exception:
                pass

    @app_commands.command(name="volume", description="Atur tingkat volume pemutar audio (0 - 150%).")
    @app_commands.describe(level="Persentase volume (0 - 150)")
    async def volume(self, interaction: discord.Interaction, level: int) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore
        if not player:
            await interaction.response.send_message("❌ Bot tidak sedang aktif di voice channel.", ephemeral=True)
            return

        clamped = max(0, min(150, level))
        await player.set_volume(clamped)
        if player.now_playing_message:
            try:
                embed = player.build_now_playing_embed()
                await player.now_playing_message.edit(embed=embed)
            except Exception:
                pass
        await interaction.response.send_message(f"🔊 Volume diatur ke `{clamped}%`.", ephemeral=True)

    @app_commands.command(name="shuffle", description="Acak urutan antrean lagu.")
    async def shuffle(self, interaction: discord.Interaction) -> None:
        player: MusicPlayer | None = getattr(interaction.guild, "voice_client", None)  # type: ignore
        if not player or player.queue.is_empty:
            await interaction.response.send_message("❌ Antrean masih kosong.", ephemeral=True)
            return

        player.queue.shuffle()
        if player.now_playing_message:
            try:
                embed = player.build_now_playing_embed()
                await player.now_playing_message.edit(embed=embed)
            except Exception:
                pass
        await interaction.response.send_message("🔀 Antrean lagu berhasil diacak.", ephemeral=True)

    # ---------------- Wavelink Event Listeners ----------------

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload) -> None:
        """Triggered when a track starts playing."""
        player: MusicPlayer | None = payload.player  # type: ignore
        if not player:
            return

        player.reset_vote_skips()
        LOGGER.info("Track started in guild %s: %s", player.guild.id, payload.track.title)

        # Trigger pure album cover card and modern Embed
        await player.send_now_playing_card()

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload) -> None:
        """Triggered when a track finishes playing."""
        player: MusicPlayer | None = payload.player  # type: ignore
        if not player:
            return

        LOGGER.info("Track ended in guild %s: %s", player.guild.id, payload.track.title)

        # Handle loop modes
        if player.loop_mode == "track" and player.current:
            await player.play(player.current)
            return
        elif player.loop_mode == "queue" and player.current:
            player.queue.put(player.current)

        # If queue is empty and autoplay is off, player will be idle
        if player.queue.is_empty and player.autoplay == wavelink.AutoPlayMode.disabled:
            if player.now_playing_message:
                try:
                    embed = discord.Embed(
                        title="⏹️ Antrean Selesai",
                        description="Semua lagu dalam antrean telah selesai diputar.",
                        color=discord.Color.dark_embed(),
                    )
                    await player.now_playing_message.edit(embed=embed, view=None)
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_wavelink_extra_event(self, payload: wavelink.ExtraEventPayload) -> None:
        """Handles SponsorBlock SegmentSkipped events natively without chat spam."""
        event_type = payload.data.get("type")
        if event_type == "SegmentSkipped":
            segment = payload.data.get("segment", {})
            notice = SponsorBlockManager.format_skipped_notice(segment)
            LOGGER.info("SponsorBlock event: %s", notice)
            # Log event only - do not send message to text channel to avoid cluttering chat

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload) -> None:
        """Triggered when a track fails to decode or stream audio (e.g. YouTube block or format error)."""
        player: MusicPlayer | None = payload.player  # type: ignore
        LOGGER.error(
            "Track exception in guild %s: %s (Track: %s)",
            player.guild.id if player else "Unknown",
            payload.exception,
            payload.track.title,
        )
        if player and player.text_channel:
            embed = discord.Embed(
                title="⚠️ Gagal Memutar Output Audio",
                description=(
                    f"Lagu **{payload.track.title}** tidak dapat diputar:\n`{payload.exception}`\n\n"
                    "💡 *Pastikan Lavalink menggunakan v4.2+ (protokol DAVE) dan plugin YouTube terbaru.*"
                ),
                color=discord.Color.red(),
            )
            try:
                await player.text_channel.send(embed=embed)
            except Exception:
                pass

        if player and not player.queue.is_empty:
            next_track = player.queue.get()
            await player.play(next_track)

    @commands.Cog.listener()
    async def on_wavelink_track_stuck(self, payload: wavelink.TrackStuckEventPayload) -> None:
        """Triggered when audio packet output is stuck or unresponsive."""
        player: MusicPlayer | None = payload.player  # type: ignore
        LOGGER.warning(
            "Track stuck in guild %s: %s (Threshold: %sms)",
            player.guild.id if player else "Unknown",
            payload.track.title,
            payload.threshold,
        )
        if player and not player.queue.is_empty:
            next_track = player.queue.get()
            await player.play(next_track)
