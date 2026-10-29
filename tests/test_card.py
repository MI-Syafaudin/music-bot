"""
Now-Playing Card Rendering and Memory-Safety Unit Tests.
"""

import io
import pytest
from ui.card import _render_card_sync, download_cover_art_bounded, MAX_IMAGE_BYTES


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
