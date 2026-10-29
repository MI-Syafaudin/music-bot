"""
SponsorBlock Integration for Lavalink v4.
Automatically skips non-music segments (sponsors, self-promo, intros, outros, silence).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final
from utils.logging import LOGGER

if TYPE_CHECKING:
    import discord
    import wavelink


SPONSORBLOCK_CATEGORIES: Final[list[str]] = [
    "sponsor",
    "selfpromo",
    "interaction",
    "intro",
    "outro",
    "preview",
    "music_offtopic",
    "filler",
]


class SponsorBlockManager:
    """Manages SponsorBlock category filters and segment skip notifications."""

    @classmethod
    async def configure_player(cls, player: wavelink.Player) -> bool:
        """
        Sends configuration payload to Lavalink node to enable SponsorBlock for this player.
        PUT /v4/sessions/{sessionId}/players/{guildId}/sponsorblock/categories
        """
        if not player.node or not player.node.session_id or not player.guild:
            return False

        path = f"v4/sessions/{player.node.session_id}/players/{player.guild.id}/sponsorblock/categories"
        try:
            await player.node.send(
                method="PUT",
                path=path,
                data=SPONSORBLOCK_CATEGORIES,
            )
            LOGGER.debug("SponsorBlock categories applied for guild %s", player.guild.id)
            return True
        except Exception as e:
            # If the plugin is not installed on the Lavalink node, fail gracefully without breaking playback
            LOGGER.debug("SponsorBlock configuration not applied or plugin not active: %s", e)
            return False

    @classmethod
    def format_skipped_notice(cls, segment_data: dict[str, Any]) -> str:
        """Formats a human-friendly notification string for skipped segments."""
        category = segment_data.get("category", "sponsor")
        start_ms = segment_data.get("start", 0)
        end_ms = segment_data.get("end", 0)
        duration_sec = max(0.0, (end_ms - start_ms) / 1000.0)

        friendly_names = {
            "sponsor": "Sponsor",
            "selfpromo": "Self-Promotion",
            "interaction": "Interaction Reminder",
            "intro": "Intro Segment",
            "outro": "Outro Segment",
            "preview": "Recap/Preview",
            "music_offtopic": "Non-Music Section",
            "filler": "Filler Content",
        }
        cat_name = friendly_names.get(category, category.replace("_", " ").title())
        return f"⏭️ **SponsorBlock:** Melewati `{cat_name}` ({duration_sec:.1f} detik)"
