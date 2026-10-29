"""
Persistence Repository for Session Crash Recovery and Custom Equalizers.
Leverages orjson for Rust-speed zero-copy JSON parsing and dumping.
"""

from __future__ import annotations

import time
from typing import Any
import aiosqlite
import orjson

from database.models import CustomEQPreset, SavedPlayerSession
from utils.logging import LOGGER


class AudioRepository:
    """Provides high-throughput async repository methods for audio state persistence."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self.db = db

    # -------------------------------------------------------------------------
    # Player Session State (Crash Recovery)
    # -------------------------------------------------------------------------

    async def save_session(
        self,
        guild_id: int,
        voice_channel_id: int,
        text_channel_id: int,
        current_track: dict[str, Any] | None,
        position_ms: int,
        volume: int,
        paused: bool,
        autoplay_mode: int,
        active_filters: dict[str, Any] | None,
        queue_items: list[dict[str, Any]],
    ) -> None:
        """Upserts a real-time snapshot of the active player session."""
        track_json = orjson.dumps(current_track).decode("utf-8") if current_track else None
        filters_json = orjson.dumps(active_filters).decode("utf-8") if active_filters else None
        queue_json = orjson.dumps(queue_items).decode("utf-8")
        now = time.time()

        query = """
        INSERT INTO player_sessions (
            guild_id, voice_channel_id, text_channel_id, current_track_json,
            position_ms, volume, paused, autoplay_mode, active_filters_json,
            queue_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            voice_channel_id = excluded.voice_channel_id,
            text_channel_id = excluded.text_channel_id,
            current_track_json = excluded.current_track_json,
            position_ms = excluded.position_ms,
            volume = excluded.volume,
            paused = excluded.paused,
            autoplay_mode = excluded.autoplay_mode,
            active_filters_json = excluded.active_filters_json,
            queue_json = excluded.queue_json,
            updated_at = excluded.updated_at;
        """
        await self.db.execute(
            query,
            (
                guild_id,
                voice_channel_id,
                text_channel_id,
                track_json,
                position_ms,
                volume,
                1 if paused else 0,
                autoplay_mode,
                filters_json,
                queue_json,
                now,
            ),
        )
        await self.db.commit()

    async def load_all_sessions(self) -> list[SavedPlayerSession]:
        """Fetches all active player sessions from the database for crash recovery."""
        query = "SELECT * FROM player_sessions ORDER BY updated_at DESC;"
        sessions: list[SavedPlayerSession] = []

        async with self.db.execute(query) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                current_track = (
                    orjson.loads(row["current_track_json"])
                    if row["current_track_json"]
                    else None
                )
                active_filters = (
                    orjson.loads(row["active_filters_json"])
                    if row["active_filters_json"]
                    else None
                )
                queue_items = (
                    orjson.loads(row["queue_json"]) if row["queue_json"] else []
                )

                sessions.append(
                    SavedPlayerSession(
                        guild_id=row["guild_id"],
                        voice_channel_id=row["voice_channel_id"],
                        text_channel_id=row["text_channel_id"],
                        current_track=current_track,
                        position_ms=row["position_ms"],
                        volume=row["volume"],
                        paused=bool(row["paused"]),
                        autoplay_mode=row["autoplay_mode"],
                        active_filters=active_filters,
                        queue_items=queue_items,
                        updated_at=row["updated_at"],
                    )
                )

        return sessions

    async def delete_session(self, guild_id: int) -> None:
        """Removes the persistent record when playback finishes or disconnects cleanly."""
        query = "DELETE FROM player_sessions WHERE guild_id = ?;"
        await self.db.execute(query, (guild_id,))
        await self.db.commit()

    # -------------------------------------------------------------------------
    # Custom Equalizer Presets
    # -------------------------------------------------------------------------

    async def save_custom_preset(self, preset: CustomEQPreset) -> None:
        """Saves or updates a custom 5-band equalizer preset for a user."""
        query = """
        INSERT INTO custom_eq_presets (
            user_id, preset_name, gain_60hz, gain_230hz, gain_910hz, gain_4khz, gain_14khz, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, preset_name) DO UPDATE SET
            gain_60hz = excluded.gain_60hz,
            gain_230hz = excluded.gain_230hz,
            gain_910hz = excluded.gain_910hz,
            gain_4khz = excluded.gain_4khz,
            gain_14khz = excluded.gain_14khz,
            created_at = excluded.created_at;
        """
        await self.db.execute(
            query,
            (
                preset.user_id,
                preset.preset_name.lower().strip(),
                preset.gain_60hz,
                preset.gain_230hz,
                preset.gain_910hz,
                preset.gain_4khz,
                preset.gain_14khz,
                preset.created_at,
            ),
        )
        await self.db.commit()

    async def get_custom_preset(self, user_id: int, preset_name: str) -> CustomEQPreset | None:
        """Retrieves a specific custom preset for a user."""
        query = """
        SELECT * FROM custom_eq_presets
        WHERE user_id = ? AND preset_name = ?;
        """
        async with self.db.execute(query, (user_id, preset_name.lower().strip())) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return CustomEQPreset(
                user_id=row["user_id"],
                preset_name=row["preset_name"],
                gain_60hz=row["gain_60hz"],
                gain_230hz=row["gain_230hz"],
                gain_910hz=row["gain_910hz"],
                gain_4khz=row["gain_4khz"],
                gain_14khz=row["gain_14khz"],
                created_at=row["created_at"],
            )

    async def list_custom_presets(self, user_id: int) -> list[CustomEQPreset]:
        """Lists all saved presets for a user."""
        query = "SELECT * FROM custom_eq_presets WHERE user_id = ? ORDER BY preset_name ASC;"
        async with self.db.execute(query, (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [
                CustomEQPreset(
                    user_id=row["user_id"],
                    preset_name=row["preset_name"],
                    gain_60hz=row["gain_60hz"],
                    gain_230hz=row["gain_230hz"],
                    gain_910hz=row["gain_910hz"],
                    gain_4khz=row["gain_4khz"],
                    gain_14khz=row["gain_14khz"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    async def delete_custom_preset(self, user_id: int, preset_name: str) -> bool:
        """Deletes a custom preset by name. Returns True if a record was removed."""
        query = "DELETE FROM custom_eq_presets WHERE user_id = ? AND preset_name = ?;"
        cursor = await self.db.execute(query, (user_id, preset_name.lower().strip()))
        await self.db.commit()
        return cursor.rowcount > 0
