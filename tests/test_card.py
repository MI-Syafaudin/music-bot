"""
Now-Playing Card Rendering and Memory-Safety Unit Tests.
"""

import io
import pytest
from ui.card import (
    _render_card_sync,
    download_cover_art_bounded,
    create_progress_bar,
    format_time,
    MAX_IMAGE_BYTES,
)


def test_card_rendering_without_cover() -> None:
    buf = _render_card_sync(
        title="Testing Track Title",
        author="Great Artist",
        position_ms=45000,
        duration_ms=180000,
        cover_bytes=None,
        platform_name="Spotify",
        preset_name="Bassboost",
        volume=80,
        autoplay=True,
    )
    assert isinstance(buf, io.BytesIO)
    content = buf.getvalue()
    assert len(content) > 1000
    # PNG signature check: \x89PNG\r\n\x1a\n
    assert content.startswith(b"\x89PNG\r\n\x1a\n")
    buf.close()


def test_card_rendering_with_synthetic_cover() -> None:
    from PIL import Image

    # Generate synthetic 100x100 cover
    img = Image.new("RGB", (100, 100), (220, 50, 80))
    cover_io = io.BytesIO()
    img.save(cover_io, format="PNG")
    cover_bytes = cover_io.getvalue()
    img.close()
    cover_io.close()

    buf = _render_card_sync(
        title="Cover Art Song",
        author="Another Musician",
        position_ms=120000,
        duration_ms=240000,
        cover_bytes=cover_bytes,
        platform_name="YouTube Music",
        preset_name="Flat",
        volume=100,
        autoplay=False,
    )
    assert isinstance(buf, io.BytesIO)
    content = buf.getvalue()
    assert len(content) > 1000
    assert content.startswith(b"\x89PNG\r\n\x1a\n")
    buf.close()


def test_create_progress_bar() -> None:
    # Mid-track playing
    bar_playing = create_progress_bar(position_ms=60000, duration_ms=180000, length=16, is_paused=False)
    assert "▶️" in bar_playing
    assert "`01:00`" in bar_playing
    assert "`03:00`" in bar_playing
    assert "🔘" in bar_playing

    # Paused state
    bar_paused = create_progress_bar(position_ms=90000, duration_ms=180000, length=16, is_paused=True)
    assert "⏸️" in bar_paused

    # Zero duration safety
    bar_zero = create_progress_bar(position_ms=0, duration_ms=0, length=16, is_paused=False)
    assert "`00:00`" in bar_zero

    # Overflow position safety
    bar_over = create_progress_bar(position_ms=200000, duration_ms=180000, length=16, is_paused=False)
    assert "🔘" in bar_over


def test_format_time() -> None:
    assert format_time(0) == "00:00"
    assert format_time(65000) == "01:05"
    assert format_time(3665000) == "1:01:05"


def test_seek_select_generation() -> None:
    from unittest.mock import MagicMock
    from ui.views import SeekSelect

    mock_player = MagicMock()
    mock_track = MagicMock()
    mock_track.length = 200000  # 200s
    mock_player.current = mock_track
    mock_player.position = 50000  # 50s (25%)
    mock_player.paused = False

    seek_select = SeekSelect(mock_player)
    assert len(seek_select.options) > 5
    assert "25%" in seek_select.placeholder
    assert any(opt.value == "0" for opt in seek_select.options)
    assert any(opt.value == "custom" for opt in seek_select.options)


def test_seek_select_zero_duration() -> None:
    from unittest.mock import MagicMock
    from ui.views import SeekSelect

    mock_player = MagicMock()
    mock_track = MagicMock()
    mock_track.length = 0
    mock_player.current = mock_track
    mock_player.position = 0
    mock_player.paused = False

    seek_select = SeekSelect(mock_player)
    assert len(seek_select.options) == 1
    assert seek_select.options[0].value == "custom"
