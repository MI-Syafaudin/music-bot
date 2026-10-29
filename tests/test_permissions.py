"""
Permissions and Vote-Skip Logic Unit Tests.
"""

from unittest.mock import MagicMock
from utils.permissions import calculate_vote_quorum, can_bypass_vote_skip, has_dj_permission


def test_calculate_vote_quorum() -> None:
    # 0 or 1 listener requires 1 vote
    assert calculate_vote_quorum(0) == 1
    assert calculate_vote_quorum(1) == 1

    # 50% + 1 formula: (listeners // 2) + 1
    assert calculate_vote_quorum(2) == 2
    assert calculate_vote_quorum(3) == 2
    assert calculate_vote_quorum(4) == 3
    assert calculate_vote_quorum(5) == 3
    assert calculate_vote_quorum(10) == 6


def test_has_dj_permission() -> None:
    member = MagicMock()
    member.guild_permissions.administrator = False
    member.guild_permissions.manage_guild = False

    role_dj = MagicMock()
    role_dj.name = "DJ"

    role_member = MagicMock()
    role_member.name = "Member"

    # With normal role
    member.roles = [role_member]
    assert has_dj_permission(member, "DJ") is False

    # With DJ role
    member.roles = [role_member, role_dj]
    assert has_dj_permission(member, "DJ") is True

    # With administrator
    member.roles = [role_member]
    member.guild_permissions.administrator = True
    assert has_dj_permission(member, "DJ") is True
