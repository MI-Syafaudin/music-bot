"""
High-Resolution Cover Art Renderer & Progress Bar Formatter.
Renders clean, high-resolution album cover artwork entirely in-memory using Pillow without disk I/O.
Displays progress bar, song title, EQ, and platform separately in Discord's embed UI for real-time updates.
"""

from __future__ import annotations

import asyncio
import io
import os
from typing import Any, Final
import aiohttp
from PIL import Image, ImageDraw, ImageOps

from utils.logging import LOGGER

MAX_IMAGE_BYTES: Final[int] = 5 * 1024 * 1024  # 5 MB security bound

PLATFORM_COLORS: Final[dict[str, int]] = {
    "spotify": 0x1DB954,
    "youtube": 0xFF0000,
    "youtubemusic": 0xFF0000,
    "applemusic": 0xFC3C44,
    "tidal": 0x00FFFF,
    "deezer": 0xA238FF,
    "soundcloud": 0xFF5500,
    "default": 0x5865F2,
}

PLATFORM_META: Final[dict[str, dict[str, Any]]] = {
    "spotify": {
        "name": "Spotify",
        "emoji": "🟢",
        "color": 0x1DB954,
        "badge": "SPOTIFY",
    },
    "youtube": {
        "name": "YouTube",
        "emoji": "🔴",
        "color": 0xFF0000,
        "badge": "YOUTUBE",
    },
    "youtubemusic": {
        "name": "YouTube Music",
        "emoji": "🔴",
        "color": 0xFF0000,
        "badge": "YT MUSIC",
    },
    "applemusic": {
        "name": "Apple Music",
        "emoji": "🍎",
        "color": 0xFC3C44,
        "badge": "APPLE MUSIC",
    },
    "tidal": {
        "name": "Tidal",
        "emoji": "💎",
        "color": 0x00FFFF,
        "badge": "TIDAL",
    },
    "deezer": {
        "name": "Deezer",
        "emoji": "🟣",
        "color": 0xA238FF,
        "badge": "DEEZER",
    },
    "soundcloud": {
        "name": "SoundCloud",
        "emoji": "☁️",
        "color": 0xFF5500,
        "badge": "SOUNDCLOUD",
    },
    "default": {
        "name": "Music Player",
        "emoji": "🎵",
        "color": 0x5865F2,
        "badge": "MUSIC",
    },
}


def format_time(ms: int) -> str:
    """Formats milliseconds into MM:SS or HH:MM:SS string."""
    total_seconds = max(0, ms // 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _format_time(ms: int) -> str:
    """Internal alias for backward compatibility."""
    return format_time(ms)


def create_progress_bar(
    position_ms: int,
    duration_ms: int,
    length: int = 16,
    is_paused: bool = False,
) -> str:
    """
    Creates a modern Discord progress bar string with timestamps, status icon, and percentage.
    Example: ▶️ `01:23` ━━━━🔘─────────── `03:45` • **38%**
    """
    pos_str = format_time(position_ms)
    dur_str = format_time(duration_ms)

    ratio = (position_ms / duration_ms) if duration_ms > 0 else 0.0
    ratio = max(0.0, min(1.0, ratio))
    pct = int(ratio * 100)

    knob_idx = min(length - 1, int(ratio * length))
    filled = "━" * knob_idx
    empty = "─" * (length - knob_idx - 1)
    bar = f"{filled}🔘{empty}"

    status_icon = "⏸️" if is_paused else "▶️"
    if duration_ms <= 0:
        return f"{status_icon} `{pos_str}` {bar} `{dur_str}`"
    return f"{status_icon} `{pos_str}` {bar} `{dur_str}` • **{pct}%**"


async def download_cover_art_bounded(
    url: str,
    session: aiohttp.ClientSession,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> bytes | None:
    """
    Downloads cover art with strict chunked size limits to prevent OOM/DoS attacks.
    """
    if not url:
        return None

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
            if resp.status != 200:
                return None

            content_len = resp.headers.get("Content-Length")
            if content_len and int(content_len) > max_bytes:
                LOGGER.warning("Cover art Content-Length exceeds %d bytes", max_bytes)
                return None

            buffer = bytearray()
            async for chunk in resp.content.iter_chunked(64 * 1024):
                buffer.extend(chunk)
                if len(buffer) > max_bytes:
                    LOGGER.warning("Cover art exceeded maximum bounded limit of %d bytes", max_bytes)
                    return None

            return bytes(buffer)
    except Exception as e:
        LOGGER.debug("Failed to download cover art from %s: %s", url, e)
        return None


def _render_cover_sync(cover_bytes: bytes | None) -> io.BytesIO:
    """
    Renders pure, minimalist album cover art in-memory (300x300 px).
    Designed to serve as a clean, high-resolution Discord Embed thumbnail on the right side.
    Strictly closes all Pillow Image objects to prevent memory leaks.
    """
    size = 300
    radius = 24
    canvas: Image.Image | None = None
    draw: ImageDraw.ImageDraw | None = None
    cover_img: Image.Image | None = None
    mask: Image.Image | None = None
    output_buffer = io.BytesIO()

    try:
        if cover_bytes:
            with io.BytesIO(cover_bytes) as raw_bio:
                try:
                    with Image.open(raw_bio) as raw_img:
                        cover_img = ImageOps.fit(
                            raw_img.convert("RGBA"),
                            (size, size),
                            Image.Resampling.LANCZOS,
                        )
                except Exception as e:
                    LOGGER.debug("Failed to decode cover bytes: %s", e)
                    cover_img = None

        if cover_img is None:
            # Minimalist modern vinyl record cover placeholder
            cover_img = Image.new("RGBA", (size, size), (18, 22, 34, 255))
            c_draw = ImageDraw.Draw(cover_img)

            # Draw sleek concentric grooves
            center = size // 2
            for r in range(40, 115, 10):
                c_draw.ellipse(
                    [center - r, center - r, center + r, center + r],
                    outline=(32, 38, 58, 255),
                    width=2,
                )

            # Center vinyl label with brand indigo gradient fill
            c_draw.ellipse(
                [center - 32, center - 32, center + 32, center + 32],
                fill=(88, 101, 242, 255),
                outline=(129, 140, 248, 255),
                width=2,
            )
            # Center spindle hole
            c_draw.ellipse(
                [center - 8, center - 8, center + 8, center + 8],
                fill=(12, 14, 22, 255),
            )

        # Base canvas
        canvas = Image.new("RGBA", (size, size), (12, 14, 22, 0))
        draw = ImageDraw.Draw(canvas)

        # Rounded corner mask
        mask = Image.new("L", (size, size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([0, 0, size, size], radius=radius, fill=255)

        # Paste masked cover art onto canvas
        canvas.paste(cover_img, (0, 0), mask)

        # Sleek modern border outline
        draw.rounded_rectangle(
            [1, 1, size - 2, size - 2],
            radius=radius,
            outline=(80, 90, 125, 200),
            width=2,
        )

        canvas.save(output_buffer, format="PNG", optimize=True)
        output_buffer.seek(0)
        return output_buffer

    finally:
        if cover_img is not None:
            cover_img.close()
        if mask is not None:
            mask.close()
        if canvas is not None:
            canvas.close()


def _render_card_sync(
    title: str = "",
    author: str = "",
    position_ms: int = 0,
    duration_ms: int = 0,
    cover_bytes: bytes | None = None,
    platform_name: str = "Music",
    preset_name: str = "Flat",
    volume: int = 100,
    autoplay: bool = False,
) -> io.BytesIO:
    """
    Renders pure album cover artwork in worker thread.
    Retains full backward compatibility with legacy argument signatures.
    """
    return _render_cover_sync(cover_bytes)


async def render_now_playing_card(
    title: str = "",
    author: str = "",
    position_ms: int = 0,
    duration_ms: int = 0,
    cover_bytes: bytes | None = None,
    platform_name: str = "Music",
    preset_name: str = "Flat",
    volume: int = 100,
    autoplay: bool = False,
) -> io.BytesIO:
    """
    Asynchronously renders pure album cover artwork offloaded to threadpool.
    """
    return await asyncio.to_thread(_render_cover_sync, cover_bytes=cover_bytes)
