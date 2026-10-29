"""
Security Unit Tests.
Verifies SSRF prevention, music domain whitelist, seek timestamp sanitization, and gain bounds.
"""

import pytest
from utils.security import (
    is_safe_music_url,
    sanitize_gain,
    sanitize_seek_timestamp,
    SecurityValidationError,
)


def test_allowed_music_urls() -> None:
    valid_urls = [
        "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=3JZ_D3ELwOQ",
        "https://youtu.be/3JZ_D3ELwOQ",
        "https://music.apple.com/us/album/never-gonna-give-you-up/1559523333",
        "https://tidal.com/browse/track/123456",
        "https://www.deezer.com/track/3135556",
        "https://soundcloud.com/artist/track",
    ]
    for url in valid_urls:
        assert is_safe_music_url(url) is True, f"Expected {url} to be valid"


def test_blocked_ssrf_and_invalid_urls() -> None:
    blocked_urls = [
        "http://127.0.0.1:2333",
        "http://localhost:8080",
        "http://169.254.169.254/latest/meta-data/",
        "https://192.168.1.1/admin",
        "file:///etc/passwd",
        "ftp://open.spotify.com/resource",
        "https://evil-attacker.com/song.mp3",
        "javascript:alert(1)",
        "",
    ]
    for url in blocked_urls:
        assert is_safe_music_url(url) is False, f"Expected {url} to be blocked"


def test_sanitize_seek_timestamp() -> None:
    max_ms = 300000  # 5 minutes

    # MM:SS
    assert sanitize_seek_timestamp("02:30", max_ms) == 150000
    assert sanitize_seek_timestamp("0:45", max_ms) == 45000

    # HH:MM:SS
    assert sanitize_seek_timestamp("01:00:00", 7200000) == 3600000

    # Clamping
    assert sanitize_seek_timestamp("10:00", max_ms) == max_ms

    # Invalid formats
    with pytest.raises(SecurityValidationError):
        sanitize_seek_timestamp("invalid", max_ms)

    with pytest.raises(SecurityValidationError):
        sanitize_seek_timestamp("01:99", max_ms)


def test_sanitize_gain() -> None:
    assert sanitize_gain(0.0) == 0.0
    assert sanitize_gain(0.5) == 0.5
    assert sanitize_gain(1.0) == 1.0
    assert sanitize_gain(-0.25) == -0.25

    # Out of bounds clamping
    assert sanitize_gain(2.5) == 1.0
    assert sanitize_gain(-1.0) == -0.25
