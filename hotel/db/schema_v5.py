"""Migration 5: scans of guest ID documents, and in-app alerts for staff."""

MIGRATION_5 = """
-- ------------------------------------------------------------ guest ID / passport scans (private; never public)
CREATE TABLE guest_documents (
    id           INTEGER PRIMARY KEY,
    guest_id     INTEGER NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL DEFAULT 'passport',
    content_type TEXT NOT NULL,
    data         BLOB NOT NULL,
    uploaded_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_guest_documents_guest ON guest_documents(guest_id);

-- ------------------------------------------------------------ alerts shown under the bell in the staff portals
-- An alert goes either to one person (user_id) or to everyone holding a permission.
CREATE TABLE staff_alerts (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
    permission TEXT NOT NULL DEFAULT '',
    title      TEXT NOT NULL,
    body       TEXT NOT NULL DEFAULT '',
    link       TEXT NOT NULL DEFAULT '',
    actor_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_staff_alerts_created ON staff_alerts(created_at);

CREATE TABLE staff_alert_reads (
    alert_id INTEGER NOT NULL REFERENCES staff_alerts(id) ON DELETE CASCADE,
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (alert_id, user_id)
);
"""
