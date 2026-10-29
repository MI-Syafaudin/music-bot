-- Enterprise SQLite Schema with WAL mode for crash recovery and user presets

CREATE TABLE IF NOT EXISTS player_sessions (
    guild_id INTEGER PRIMARY KEY,
    voice_channel_id INTEGER NOT NULL,
    text_channel_id INTEGER NOT NULL,
    current_track_json TEXT,
    position_ms INTEGER NOT NULL DEFAULT 0,
    volume INTEGER NOT NULL DEFAULT 80,
    paused INTEGER NOT NULL DEFAULT 0,
    autoplay_mode INTEGER NOT NULL DEFAULT 0,
    active_filters_json TEXT,
    queue_json TEXT NOT NULL DEFAULT '[]',
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_player_sessions_updated ON player_sessions(updated_at);

CREATE TABLE IF NOT EXISTS custom_eq_presets (
    user_id INTEGER NOT NULL,
    preset_name TEXT NOT NULL,
    gain_60hz REAL NOT NULL,
    gain_230hz REAL NOT NULL,
    gain_910hz REAL NOT NULL,
    gain_4khz REAL NOT NULL,
    gain_14khz REAL NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (user_id, preset_name)
);

CREATE INDEX IF NOT EXISTS idx_custom_eq_user ON custom_eq_presets(user_id);
