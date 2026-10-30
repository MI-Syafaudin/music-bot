"""
Multi-Platform Audio Resolver Engine.
Provides SSRF-safe resolution and search across Spotify, YouTube Music, Apple Music, Tidal, Deezer, and SoundCloud
with automatic multi-source fallback to ensure playback reliability.
"""

from __future__ import annotations

from typing import Final
import wavelink
from utils.logging import LOGGER
from utils.security import is_safe_music_url, SecurityValidationError


class AudioResolver:
    """Enterprise multi-platform track and playlist resolver with SSRF safeguards."""

    @staticmethod
    def is_url(query: str) -> bool:
        """Determines if the query is formatted as an HTTP/HTTPS URL."""
        q = query.strip().lower()
        return q.startswith("http://") or q.startswith("https://")

    @classmethod
    async def resolve(
        cls,
        query: str,
        preferred_source: wavelink.TrackSource | str = wavelink.TrackSource.YouTubeMusic,
    ) -> wavelink.Search:
        """
        Resolves query into Playable tracks or Playlist.
        Enforces SSRF check on URLs and wraps LavaSrc plugin capabilities.
        Implements intelligent multi-source fallback (YTMusic -> YouTube -> SoundCloud).
        """
        clean_query = query.strip()
        if not clean_query:
            return []

        if cls.is_url(clean_query):
            # Strict SSRF and whitelist verification
            if not is_safe_music_url(clean_query):
                LOGGER.warning("Blocked unsafe or unverified URL: %s", clean_query)
                raise SecurityValidationError(
                    "URL ditolak: Hanya URL HTTPS dari Spotify, YouTube Music, Apple Music, "
                    "Tidal, Deezer, atau SoundCloud yang diizinkan demi keamanan sistem."
                )

            LOGGER.info("Resolving direct verified URL: %s", clean_query)
            try:
                result: wavelink.Search = await wavelink.Playable.search(clean_query)
                return result
            except wavelink.LavalinkLoadException as e:
                LOGGER.error("Lavalink failed to load URL %s: %s", clean_query, e)
                raise

        # Multi-source search fallback pipeline
        sources_to_try: list[wavelink.TrackSource | str] = [preferred_source]
        if preferred_source != wavelink.TrackSource.YouTube:
            sources_to_try.append(wavelink.TrackSource.YouTube)
        if preferred_source != wavelink.TrackSource.SoundCloud:
            sources_to_try.append(wavelink.TrackSource.SoundCloud)

        last_error: Exception | None = None
        for source in sources_to_try:
            LOGGER.info("Executing text search for '%s' using source %s", clean_query, source)
            try:
                result = await wavelink.Playable.search(clean_query, source=source)
                if result:
                    return result
            except Exception as e:
                LOGGER.warning("Search with source %s failed: %s; trying fallback...", source, e)
                last_error = e

        if last_error:
            raise last_error
        return []
