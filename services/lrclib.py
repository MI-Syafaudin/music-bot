"""
High-Performance LRCLIB Synced Lyrics Client.
Implements bounded streams, memory-safe parsing, and sub-second binary search synchronization.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from typing import Final
import aiohttp
import orjson

from utils.logging import LOGGER

LRC_LINE_REGEX: Final[re.Pattern[str]] = re.compile(
    r"\[(\d{2}):(\d{2}(?:\.\d+)?)\](.*)"
)
MAX_LYRICS_PAYLOAD_BYTES: Final[int] = 512 * 1024  # 512 KB bound


@dataclass(slots=True)
class LrcLine:
    """A single line of synchronized lyrics with timestamp."""
    timestamp_sec: float
    text: str


@dataclass(slots=True)
class SyncedLyricsResult:
    """Parsed lyrics document containing synced and plain formats."""
    track_name: str
    artist_name: str
    duration: float
    instrumental: bool
    lines: list[LrcLine]
    plain_lyrics: str | None

    def get_line_index_at(self, current_seconds: float) -> int:
        """
        Performs O(log N) binary search to find the active lyric line index
        corresponding to the playback position.
        """
        if not self.lines:
            return -1

        timestamps = [line.timestamp_sec for line in self.lines]
        idx = bisect.bisect_right(timestamps, current_seconds) - 1
        return max(0, idx)


class LrcLibClient:
    """Async API Client for LRCLIB."""

    BASE_URL: Final[str] = "https://lrclib.net/api"

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._internal_session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        if self._internal_session is None or self._internal_session.closed:
            timeout = aiohttp.ClientTimeout(total=6.0, connect=3.0)
            self._internal_session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": "EnterpriseDiscordMusicBot/1.0 (AudioSystemsArchitect)"},
            )
        return self._internal_session

    async def close(self) -> None:
        """Closes internal aiohttp session if one was created."""
        if self._internal_session and not self._internal_session.closed:
            await self._internal_session.close()

    async def fetch_lyrics(
        self,
        track_name: str,
        artist_name: str,
        duration_sec: int | None = None,
    ) -> SyncedLyricsResult | None:
        """
        Fetches synced lyrics from LRCLIB.
        Applies chunked bounded read to prevent DoS/OOM on rogue responses.
        """
        session = await self._get_session()
        params: dict[str, str | int] = {
            "track_name": track_name,
            "artist_name": artist_name,
        }
        if duration_sec and duration_sec > 0:
            params["duration"] = duration_sec

        data: dict | None = None
        url = f"{self.BASE_URL}/get"

        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    raw_bytes = bytearray()
                    async for chunk in resp.content.iter_chunked(16 * 1024):
                        raw_bytes.extend(chunk)
                        if len(raw_bytes) > MAX_LYRICS_PAYLOAD_BYTES:
                            LOGGER.warning("LRCLIB payload exceeded limit (%d bytes)", len(raw_bytes))
                            return None
                    data = orjson.loads(raw_bytes)
                elif resp.status == 404:
                    # Fallback to search endpoint
                    data = await self._fallback_search(session, f"{track_name} {artist_name}")
                else:
                    LOGGER.warning("LRCLIB API returned HTTP %s for %s - %s", resp.status, track_name, artist_name)
                    return None
        except Exception as e:
            LOGGER.error("Failed to query LRCLIB: %s", e)
            return None

        if not data:
            return None

        return self._parse_response(data)

    async def _fallback_search(self, session: aiohttp.ClientSession, query: str) -> dict | None:
        """Executes a search query when exact match /get returns 404."""
        url = f"{self.BASE_URL}/search"
        try:
            async with session.get(url, params={"q": query}) as resp:
                if resp.status != 200:
                    return None
                raw_bytes = bytearray()
                async for chunk in resp.content.iter_chunked(16 * 1024):
                    raw_bytes.extend(chunk)
                    if len(raw_bytes) > MAX_LYRICS_PAYLOAD_BYTES:
                        return None
                results = orjson.loads(raw_bytes)
                if isinstance(results, list) and results:
                    return results[0]
        except Exception:
            return None
        return None

    @staticmethod
    def _parse_response(data: dict) -> SyncedLyricsResult:
        """Parses LRC format into a structured SyncedLyricsResult."""
        synced_text = data.get("syncedLyrics") or ""
        plain_text = data.get("plainLyrics")
        lines: list[LrcLine] = []

        if synced_text:
            for match in LRC_LINE_REGEX.finditer(synced_text):
                minutes = int(match.group(1))
                seconds = float(match.group(2))
                text = match.group(3).strip()
                lines.append(LrcLine(timestamp_sec=minutes * 60 + seconds, text=text))

            lines.sort(key=lambda item: item.timestamp_sec)

        return SyncedLyricsResult(
            track_name=data.get("trackName") or data.get("name") or "Unknown",
            artist_name=data.get("artistName") or "Unknown",
            duration=float(data.get("duration") or 0.0),
            instrumental=bool(data.get("instrumental", False)),
            lines=lines,
            plain_lyrics=plain_text,
        )
