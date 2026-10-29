"""
Real-Time DSP Equalizer and Filter Engine.
Supports 15-band precision EQ, custom 5-band interpolated builder, and special DSP effects (8D, Nightcore, Vaporwave).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
import wavelink
from utils.security import sanitize_gain


class PresetType(StrEnum):
    FLAT = "flat"
    BASSBOOST = "bassboost"
    POP = "pop"
    ROCK = "rock"
    CLASSICAL = "classical"
    ELECTRONIC = "electronic"
    NIGHTCORE = "nightcore"
    VAPORWAVE = "vaporwave"
    EIGHT_D = "8d_audio"
    VOCAL_BOOST = "vocal_boost"


# Standard 15-band EQ presets
PRESET_BANDS: dict[PresetType, list[float]] = {
    PresetType.FLAT: [0.0] * 15,
    PresetType.BASSBOOST: [
        0.20, 0.15, 0.10, 0.05, 0.0, 0.0, -0.02, -0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    ],
    PresetType.POP: [
        -0.02, 0.02, 0.06, 0.08, 0.10, 0.08, 0.04, 0.0, 0.02, 0.04, 0.06, 0.08, 0.06, 0.02, 0.0
    ],
    PresetType.ROCK: [
        0.15, 0.12, 0.06, 0.02, -0.04, -0.06, -0.04, 0.0, 0.04, 0.08, 0.10, 0.12, 0.14, 0.12, 0.10
    ],
    PresetType.CLASSICAL: [
        0.08, 0.06, 0.04, 0.02, 0.0, 0.0, 0.02, 0.04, 0.04, 0.06, 0.08, 0.10, 0.12, 0.10, 0.08
    ],
    PresetType.ELECTRONIC: [
        0.22, 0.18, 0.12, 0.04, -0.02, -0.04, 0.02, 0.06, 0.10, 0.12, 0.14, 0.16, 0.18, 0.16, 0.12
    ],
    PresetType.VOCAL_BOOST: [
        -0.10, -0.08, -0.04, 0.0, 0.08, 0.16, 0.22, 0.22, 0.18, 0.12, 0.06, 0.0, -0.02, -0.04, -0.06
    ],
}


def interpolate_5_to_15_bands(
    gain_60hz: float,
    gain_230hz: float,
    gain_910hz: float,
    gain_4khz: float,
    gain_14khz: float,
) -> list[float]:
    """
    Interpolates 5 user frequency handles into Lavalink's 15 bands:
    - 60Hz   -> Band 2
    - 230Hz  -> Band 5
    - 910Hz  -> Band 8
    - 4kHz   -> Band 11
    - 14kHz  -> Band 14
    Bands 0 and 1 inherit 60Hz sub-bass gain.
    """
    g60 = sanitize_gain(gain_60hz)
    g230 = sanitize_gain(gain_230hz)
    g910 = sanitize_gain(gain_910hz)
    g4k = sanitize_gain(gain_4khz)
    g14k = sanitize_gain(gain_14khz)

    anchors: dict[int, float] = {
        2: g60,
        5: g230,
        8: g910,
        11: g4k,
        14: g14k,
    }

    bands = [0.0] * 15
    bands[0] = g60
    bands[1] = g60

    anchor_keys = [2, 5, 8, 11, 14]
    for i in range(len(anchor_keys) - 1):
        k1, k2 = anchor_keys[i], anchor_keys[i + 1]
        v1, v2 = anchors[k1], anchors[k2]
        for b in range(k1, k2 + 1):
            t = (b - k1) / (k2 - k1)
            bands[b] = sanitize_gain(v1 + t * (v2 - v1))

    return bands


def create_filters_for_preset(preset: PresetType | str) -> wavelink.Filters:
    """Creates and configures a wavelink.Filters instance according to preset."""
    name = str(preset).lower()
    filters = wavelink.Filters()
    filters.reset()

    if name == PresetType.NIGHTCORE:
        filters.timescale.set(pitch=1.25, speed=1.15, rate=1.0)
    elif name == PresetType.VAPORWAVE:
        filters.timescale.set(pitch=0.80, speed=0.85, rate=1.0)
    elif name == PresetType.EIGHT_D:
        filters.rotation.set(rotation_hz=0.2)
    elif name in PRESET_BANDS:
        gains = PRESET_BANDS[PresetType(name)]
        payload = [{"band": i, "gain": gains[i]} for i in range(15)]
        filters.equalizer.set(bands=payload)
    else:
        # Default flat
        filters.equalizer.set(bands=[{"band": i, "gain": 0.0} for i in range(15)])

    return filters


def create_filters_from_5_bands(
    g60: float, g230: float, g910: float, g4k: float, g14k: float
) -> wavelink.Filters:
    """Creates a wavelink.Filters instance with custom interpolated bands."""
    gains = interpolate_5_to_15_bands(g60, g230, g910, g4k, g14k)
    filters = wavelink.Filters()
    filters.reset()
    payload = [{"band": i, "gain": gains[i]} for i in range(15)]
    filters.equalizer.set(bands=payload)
    return filters


def serialize_filters(filters: wavelink.Filters) -> dict[str, Any]:
    """Serializes the active filter configuration to a dictionary for persistence."""
    return filters()


def deserialize_filters(data: dict[str, Any] | None) -> wavelink.Filters:
    """Restores a wavelink.Filters instance from persisted dictionary data."""
    if not data:
        f = wavelink.Filters()
        f.reset()
        return f
    return wavelink.Filters(data=data)
