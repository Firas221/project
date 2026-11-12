"""Migration 7: waitlist, stop-sell dates, rooms held back from online sale."""

MIGRATION_7 = """
-- people waiting for a room on dates that are full
CREATE TABLE waitlist (
    id             INTEGER PRIMARY KEY,
    guest_id       INTEGER REFERENCES guests(id) ON DELETE SET NULL,
    name           TEXT NOT NULL,
    phone          TEXT NOT NULL DEFAULT '',
    email          TEXT NOT NULL DEFAULT '',
    room_type_id   INTEGER REFERENCES room_types(id) ON DELETE CASCADE,   -- NULL: any room type
    check_in       TEXT NOT NULL,
    check_out      TEXT NOT NULL,
    adults         INTEGER NOT NULL DEFAULT 1,
    children       INTEGER NOT NULL DEFAULT 0,
    notes          TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting', 'booked', 'cancelled')),
    reservation_id INTEGER REFERENCES reservations(id) ON DELETE SET NULL,
    source         TEXT NOT NULL DEFAULT 'desk',          -- desk | online
    alerted_at     TEXT,                                  -- when the desk was told a room came free
    created_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (check_out > check_in)
);
CREATE INDEX idx_waitlist_status ON waitlist(status, check_in);

-- dates on which the website must not sell (all room types, or one)
CREATE TABLE stop_sells (
    id           INTEGER PRIMARY KEY,
    room_type_id INTEGER REFERENCES room_types(id) ON DELETE CASCADE,
    start_date   TEXT NOT NULL,
    end_date     TEXT NOT NULL,
    reason       TEXT NOT NULL DEFAULT '',
    created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (end_date >= start_date)
);

-- rooms of a type that are never sold online, so the desk always has some in hand
ALTER TABLE room_types ADD COLUMN online_hold_back INTEGER NOT NULL DEFAULT 0;
"""
