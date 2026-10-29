"""
SQLite WAL Mode and Persistence Repository Unit Tests.
"""

import os
import tempfile
import pytest
from database.connection import DatabaseManager
from database.models import CustomEQPreset
from database.repository import AudioRepository


@pytest.mark.asyncio
async def test_sqlite_wal_and_repository() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        manager = DatabaseManager(db_path)
        await manager.initialize()

        # Check PRAGMA journal_mode is WAL
        async with manager.connection.execute("PRAGMA journal_mode;") as cursor:
            row = await cursor.fetchone()
            assert row[0].lower() == "wal"

        repo = AudioRepository(manager.connection)

        # 1. Test Session Snapshot & Recovery
        sample_track = {
            "encoded": "sample_encoded_track_str",
            "info": {
                "identifier": "track123",
                "isSeekable": True,
                "author": "Sample Artist",
                "length": 210000,
                "isStream": False,
                "position": 0,
                "title": "Sample Song",
                "uri": "https://music.youtube.com/watch?v=track123",
                "artworkUrl": None,
                "isrc": None,
                "sourceName": "youtube",
            },
            "pluginInfo": {},
            "userData": {},
        }

        await repo.save_session(
            guild_id=111222333,
            voice_channel_id=444555,
            text_channel_id=777888,
            current_track=sample_track,
            position_ms=45000,
            volume=85,
            paused=False,
            autoplay_mode=1,
            active_filters={"equalizer": []},
            queue_items=[sample_track],
        )

        sessions = await repo.load_all_sessions()
        assert len(sessions) == 1
        s = sessions[0]
        assert s.guild_id == 111222333
        assert s.voice_channel_id == 444555
        assert s.position_ms == 45000
        assert s.volume == 85
        assert s.current_track is not None
        assert s.current_track["info"]["title"] == "Sample Song"
        assert len(s.queue_items) == 1

        # Delete session
        await repo.delete_session(111222333)
        sessions_after = await repo.load_all_sessions()
        assert len(sessions_after) == 0

        # 2. Test Custom EQ Presets
        preset = CustomEQPreset(
            user_id=999888,
            preset_name="my_heavy_bass",
            gain_60hz=0.5,
            gain_230hz=0.3,
            gain_910hz=0.0,
            gain_4khz=0.1,
            gain_14khz=0.2,
            created_at=1700000000.0,
        )
        await repo.save_custom_preset(preset)

        retrieved = await repo.get_custom_preset(999888, "my_heavy_bass")
        assert retrieved is not None
        assert retrieved.gain_60hz == 0.5
        assert retrieved.preset_name == "my_heavy_bass"

        presets_list = await repo.list_custom_presets(999888)
        assert len(presets_list) == 1

        deleted = await repo.delete_custom_preset(999888, "my_heavy_bass")
        assert deleted is True

        await manager.close()

    finally:
        # Cleanup temporary files (including WAL and SHM if present)
        for ext in ("", "-wal", "-shm"):
            p = db_path + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
