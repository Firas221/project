"""Migration 3: e-mail verification for guest accounts and room-type photos."""

MIGRATION_3 = """
-- ------------------------------------------------------------ users: e-mail verification
ALTER TABLE users ADD COLUMN email_verified_at TEXT;
-- accounts that existed before verification was introduced keep working
UPDATE users SET email_verified_at = created_at;

CREATE TABLE email_verifications (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ------------------------------------------------------------ room-type photos (stored in the database so backups include them)
CREATE TABLE room_photos (
    id           INTEGER PRIMARY KEY,
    room_type_id INTEGER NOT NULL REFERENCES room_types(id) ON DELETE CASCADE,
    content_type TEXT NOT NULL,
    data         BLOB NOT NULL,
    position     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_room_photos_type ON room_photos(room_type_id, position, id);
"""
