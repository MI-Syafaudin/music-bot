"""
Slotted Dataclasses for Database Entities and Audio State Models.
Guarantees memory-safety, zero circular dictionary overhead, and optimal speed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CustomEQPreset:
    """User-defined 5-point equalizer settings."""
    user_id: int
    preset_name: str
    gain_60hz: float
    gain_230hz: float
    gain_910hz: float
    gain_4khz: float
    gain_14khz: float
    created_at: float

    def to_tuple(self) -> tuple[float, float, float, float, float]:
        """Returns ordered gain values for frequency bands."""
        return (
            self.gain_60hz,
            self.gain_230hz,
            self.gain_910hz,
            self.gain_4khz,
            self.gain_14khz,
        )


@dataclass(slots=True)
class QueueItemState:
    """Serialized representation of a queued track for persistence."""
    encoded: str
    title: str
    author: str
    uri: str | None
    length: int
    requester_id: int | None = None


@dataclass(slots=True)
class SavedPlayerSession:
    """Complete snapshot of a playing audio player for crash recovery."""
    guild_id: int
    voice_channel_id: int
    text_channel_id: int
    current_track: dict[str, Any] | None
    position_ms: int
    volume: int
    paused: bool
    autoplay_mode: int
    active_filters: dict[str, Any] | None
    queue_items: list[dict[str, Any]]
    updated_at: float
