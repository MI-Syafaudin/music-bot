"""
Permission and Vote-Skip Verification Utilities.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord


def get_voice_listeners(channel: discord.VoiceChannel | discord.StageChannel) -> list[discord.Member]:
    """Returns non-bot members present in the voice channel."""
    return [m for m in channel.members if not m.bot]


def has_dj_permission(
    member: discord.Member,
    dj_role_name: str = "DJ",
) -> bool:
    """
    Checks if a guild member has elevated playback control permissions:
    1. Administrator or Manage Channels permission.
    2. Holds the designated DJ role.
    """
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True

    for role in member.roles:
        if role.name.lower() == dj_role_name.lower():
            return True

    return False


def can_bypass_vote_skip(
    member: discord.Member,
    channel: discord.VoiceChannel | discord.StageChannel,
    dj_role_name: str = "DJ",
) -> bool:
    """
    Determines if a member can bypass vote skipping directly:
    - User has DJ/Admin privileges.
    - User is the sole non-bot listener in the voice channel.
    """
    if has_dj_permission(member, dj_role_name):
        return True

    listeners = get_voice_listeners(channel)
    if len(listeners) <= 1 and (not listeners or listeners[0].id == member.id):
        return True

    return False


def calculate_vote_quorum(listener_count: int, ratio: float = 0.5) -> int:
    """
    Calculates the minimum required votes to skip a track (50% + 1 quorum).
    """
    if listener_count <= 1:
        return 1
    # 50% + 1 formula
    return (listener_count // 2) + 1
