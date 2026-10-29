"""
High-Resolution Dynamic Now-Playing Card Renderer.
Renders adaptive graphics entirely in-memory using Pillow without disk I/O.
Offloaded via asyncio.to_thread for non-blocking event-loop operation.
"""

from __future__ import annotations

import asyncio
import io
import os
from typing import Final
import aiohttp
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from utils.logging import LOGGER

MAX_IMAGE_BYTES: Final[int] = 5 * 1024 * 1024  # 5 MB security bound

PLATFORM_COLORS: Final[dict[str, tuple[int, int, int]]] = {
    "spotify": (29, 185, 84),
    "youtube": (255, 0, 0),
    "youtubemusic": (255, 0, 0),
    "applemusic": (252, 60, 68),
    "tidal": (0, 255, 255),
    "deezer": (162, 56, 255),
    "soundcloud": (255, 85, 0),
}

FONT_CANDIDATES: Final[list[str]] = [
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/OpenSans-Regular.ttf",
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf",
]


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Safely loads an installed TrueType font or falls back to Pillow default."""
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _format_time(ms: int) -> str:
    """Formats milliseconds into MM:SS or HH:MM:SS string."""
    total_seconds = max(0, ms // 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


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


def _render_card_sync(
    title: str,
    author: str,
    position_ms: int,
    duration_ms: int,
    cover_bytes: bytes | None,
    platform_name: str,
    preset_name: str,
    volume: int,
    autoplay: bool,
) -> io.BytesIO:
    """
    Synchronous card rendering logic executed in worker thread.
    Guarantees all Pillow images are strictly closed.
    """
    width, height = 1000, 360
    card_margin = 16
    radius = 28

    canvas: Image.Image | None = None
    draw: ImageDraw.ImageDraw | None = None
    cover_img: Image.Image | None = None
    mask: Image.Image | None = None
    output_buffer = io.BytesIO()

    try:
        # Determine dominant ambient color if cover is available
        ambient_color = (20, 24, 38)
        if cover_bytes:
            with io.BytesIO(cover_bytes) as raw_bio:
                try:
                    with Image.open(raw_bio) as temp_cover:
                        # Downsample to 1x1 to extract dominant color
                        small = temp_cover.resize((1, 1), Image.Resampling.BOX)
                        r, g, b = small.convert("RGB").getpixel((0, 0))
                        small.close()
                        # Dim ambient color for dark theme aesthetic
                        ambient_color = (int(r * 0.25) + 12, int(g * 0.25) + 12, int(b * 0.25) + 16)
                except Exception:
                    pass

        # Create base canvas with smooth gradient/ambient fill
        canvas = Image.new("RGBA", (width, height), (12, 14, 20, 255))
        draw = ImageDraw.Draw(canvas)

        # Draw card container
        card_box = [card_margin, card_margin, width - card_margin, height - card_margin]
        draw.rounded_rectangle(
            card_box,
            radius=radius,
            fill=ambient_color,
            outline=(60, 68, 92, 220),
            width=2,
        )

        # ---------------- Cover Art Section ----------------
        cover_size = 260
        cover_x = card_margin + 30
        cover_y = card_margin + 25

        if cover_bytes:
            with io.BytesIO(cover_bytes) as raw_bio:
                try:
                    with Image.open(raw_bio) as raw_img:
                        cover_img = ImageOps.fit(
                            raw_img.convert("RGBA"),
                            (cover_size, cover_size),
                            Image.Resampling.LANCZOS,
                        )
                except Exception:
                    cover_img = None

        if cover_img is None:
            # Fallback sleek geometric cover
            cover_img = Image.new("RGBA", (cover_size, cover_size), (35, 40, 58, 255))
            c_draw = ImageDraw.Draw(cover_img)
            c_draw.text(
                (cover_size // 2, cover_size // 2),
                "♪",
                fill=(120, 130, 165, 255),
                font=_get_font(72),
                anchor="mm",
            )

        # Create rounded mask for cover art
        mask = Image.new("L", (cover_size, cover_size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([0, 0, cover_size, cover_size], radius=20, fill=255)

        # Paste masked cover art onto canvas
        canvas.paste(cover_img, (cover_x, cover_y), mask)

        # Subtle border around cover art
        draw.rounded_rectangle(
            [cover_x, cover_y, cover_x + cover_size, cover_y + cover_size],
            radius=20,
            outline=(90, 100, 130, 180),
            width=2,
        )

        # ---------------- Metadata Section ----------------
        content_x = cover_x + cover_size + 35
        max_text_width = width - content_x - 40

        # Platform Badge
        clean_platform = platform_name.lower().replace(" ", "").replace("_", "")
        badge_bg = PLATFORM_COLORS.get(clean_platform, (99, 102, 241))
        badge_text = platform_name.upper()

        badge_font = _get_font(13)
        badge_padding_x = 12
        badge_height = 24
        # Calculate badge width safely
        bbox = badge_font.getbbox(badge_text)
        b_width = (bbox[2] - bbox[0]) + (badge_padding_x * 2)

        badge_y = cover_y + 4
        draw.rounded_rectangle(
            [content_x, badge_y, content_x + b_width, badge_y + badge_height],
            radius=12,
            fill=badge_bg,
        )
        draw.text(
            (content_x + badge_padding_x, badge_y + 4),
            badge_text,
            fill=(255, 255, 255),
            font=badge_font,
        )

        # Status Badges (EQ Preset, Vol, Autoplay)
        info_font = _get_font(12)
        badges_info = [
            f"EQ: {preset_name.title()}",
            f"VOL: {volume}%",
            f"AUTOPLAY: {'ON' if autoplay else 'OFF'}",
        ]
        curr_badge_x = content_x + b_width + 12
        for b_str in badges_info:
            b_box = info_font.getbbox(b_str)
            w = (b_box[2] - b_box[0]) + 16
            draw.rounded_rectangle(
                [curr_badge_x, badge_y, curr_badge_x + w, badge_y + badge_height],
                radius=12,
                fill=(45, 52, 72, 200),
                outline=(75, 85, 115, 200),
                width=1,
            )
            draw.text(
                (curr_badge_x + 8, badge_y + 4),
                b_str,
                fill=(200, 210, 230),
                font=info_font,
            )
            curr_badge_x += w + 8

        # Track Title
        title_font = _get_font(28)
        truncated_title = title
        while title_font.getbbox(truncated_title)[2] > max_text_width and len(truncated_title) > 3:
            truncated_title = truncated_title[:-4] + "..."

        title_y = badge_y + 36
        draw.text(
            (content_x, title_y),
            truncated_title,
            fill=(255, 255, 255),
            font=title_font,
        )

        # Artist / Author
        artist_font = _get_font(20)
        truncated_artist = author
        while artist_font.getbbox(truncated_artist)[2] > max_text_width and len(truncated_artist) > 3:
            truncated_artist = truncated_artist[:-4] + "..."

        artist_y = title_y + 42
        draw.text(
            (content_x, artist_y),
            truncated_artist,
            fill=(160, 175, 205),
            font=artist_font,
        )

        # ---------------- Progress Bar Section ----------------
        progress_y = cover_y + cover_size - 40
        bar_width = max_text_width
        bar_height = 8

        # Safe progress ratio
        ratio = (position_ms / duration_ms) if duration_ms > 0 else 0.0
        ratio = max(0.0, min(1.0, ratio))

        # Progress bar track
        draw.rounded_rectangle(
            [content_x, progress_y, content_x + bar_width, progress_y + bar_height],
            radius=4,
            fill=(45, 52, 72, 255),
        )

        # Filled progress
        fill_width = max(bar_height, int(bar_width * ratio))
        draw.rounded_rectangle(
            [content_x, progress_y, content_x + fill_width, progress_y + bar_height],
            radius=4,
            fill=(99, 102, 241, 255),
        )

        # Progress handle knob
        knob_radius = 7
        knob_x = content_x + fill_width
        draw.ellipse(
            [knob_x - knob_radius, progress_y + (bar_height // 2) - knob_radius,
             knob_x + knob_radius, progress_y + (bar_height // 2) + knob_radius],
            fill=(255, 255, 255),
            outline=(99, 102, 241),
            width=2,
        )

        # Time labels
        time_font = _get_font(14)
        elapsed_str = _format_time(position_ms)
        total_str = _format_time(duration_ms)

        time_y = progress_y + 16
        draw.text((content_x, time_y), elapsed_str, fill=(180, 190, 215), font=time_font)
        t_box = time_font.getbbox(total_str)
        t_w = t_box[2] - t_box[0]
        draw.text((content_x + bar_width - t_w, time_y), total_str, fill=(180, 190, 215), font=time_font)

        # Save to BytesIO in memory
        canvas.save(output_buffer, format="PNG", optimize=True)
        output_buffer.seek(0)
        return output_buffer

    finally:
        # Strict memory-safety cleanup: close all Pillow images
        if cover_img is not None:
            cover_img.close()
        if mask is not None:
            mask.close()
        if canvas is not None:
            canvas.close()


async def render_now_playing_card(
    title: str,
    author: str,
    position_ms: int,
    duration_ms: int,
    cover_bytes: bytes | None,
    platform_name: str,
    preset_name: str,
    volume: int,
    autoplay: bool,
) -> io.BytesIO:
    """
    Renders high-resolution visual card asynchronously on a threadpool worker.
    """
    return await asyncio.to_thread(
        _render_card_sync,
        title=title,
        author=author,
        position_ms=position_ms,
        duration_ms=duration_ms,
        cover_bytes=cover_bytes,
        platform_name=platform_name,
        preset_name=preset_name,
        volume=volume,
        autoplay=autoplay,
    )
