"""
Lyrics Synchronization and Parsing Unit Tests.
"""

from services.lrclib import LrcLibClient, SyncedLyricsResult


def test_lrc_parsing_and_binary_search() -> None:
    raw_data = {
        "trackName": "Sample Track",
        "artistName": "Sample Artist",
        "duration": 180.0,
        "instrumental": False,
        "syncedLyrics": (
            "[00:05.00] Line one\n"
            "[00:10.50] Line two\n"
            "[00:20.00] Line three\n"
            "[00:35.25] Outro line\n"
        ),
        "plainLyrics": "Line one\nLine two\nLine three\nOutro line",
    }

    result = LrcLibClient._parse_response(raw_data)
    assert len(result.lines) == 4
    assert result.lines[0].text == "Line one"
    assert result.lines[0].timestamp_sec == 5.0

    # Binary search tests
    assert result.get_line_index_at(2.0) == 0
    assert result.get_line_index_at(7.0) == 0
    assert result.get_line_index_at(10.5) == 1
    assert result.get_line_index_at(15.0) == 1
    assert result.get_line_index_at(25.0) == 2
    assert result.get_line_index_at(40.0) == 3
