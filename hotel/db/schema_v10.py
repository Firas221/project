"""Migration 10: staff rosters and attendance."""

MIGRATION_10 = """
-- planned work: who works when
CREATE TABLE roster_shifts (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    work_date  TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time   TEXT NOT NULL,                 -- earlier than start_time means the shift ends the next morning
    note       TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_roster_date ON roster_shifts(work_date, user_id);

-- actual work: clock in, clock out
CREATE TABLE attendance (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    clock_in   TEXT NOT NULL,
    clock_out  TEXT,
    note       TEXT NOT NULL DEFAULT '',
    edited_by  INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX idx_attendance_user ON attendance(user_id, clock_in);
"""
