"""
DSP and Equalizer Unit Tests.
Verifies 5-to-15 band interpolation, preset filters, and serialization.
"""

from audio.dsp import (
    PresetType,
    create_filters_for_preset,
    create_filters_from_5_bands,
    deserialize_filters,
    interpolate_5_to_15_bands,
    serialize_filters,
)


def test_interpolate_5_to_15_bands() -> None:
    bands = interpolate_5_to_15_bands(
        gain_60hz=0.20,
        gain_230hz=0.10,
        gain_910hz=0.00,
        gain_4khz=-0.05,
        gain_14khz=0.15,
    )
    assert len(bands) == 15
    # Sub-bass inherits 60Hz
    assert bands[0] == 0.20
    assert bands[1] == 0.20
    assert bands[2] == 0.20

    # Anchors
    assert bands[5] == 0.10
    assert bands[8] == 0.00
    assert bands[11] == -0.05
    assert bands[14] == 0.15

    # Check that all bands fall within valid gain bounds
    for b in bands:
        assert -0.25 <= b <= 1.0


def test_preset_filters_generation() -> None:
    # Test Flat
    f_flat = create_filters_for_preset(PresetType.FLAT)
    eq_payload = f_flat.equalizer.payload
    for b in eq_payload.values():
        assert b["gain"] == 0.0

    # Test Nightcore
    f_nc = create_filters_for_preset(PresetType.NIGHTCORE)
    assert f_nc.timescale.payload["pitch"] == 1.25
    assert f_nc.timescale.payload["speed"] == 1.15

    # Test 8D Audio
    f_8d = create_filters_for_preset(PresetType.EIGHT_D)
    assert f_8d.rotation.payload["rotationHz"] == 0.2


def test_filter_serialization_cycle() -> None:
    original = create_filters_for_preset(PresetType.NIGHTCORE)
    serialized = serialize_filters(original)
    assert "timescale" in serialized

    restored = deserialize_filters(serialized)
    assert restored.timescale.payload["pitch"] == 1.25
