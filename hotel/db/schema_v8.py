"""Migration 8: guest loyalty points."""

MIGRATION_8 = """
ALTER TABLE guests ADD COLUMN loyalty_points INTEGER NOT NULL DEFAULT 0;

-- every change to a guest's points: earned at check-out, redeemed against a bill, adjusted by a manager
CREATE TABLE loyalty_ledger (
    id             INTEGER PRIMARY KEY,
    guest_id       INTEGER NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    reservation_id INTEGER REFERENCES reservations(id) ON DELETE SET NULL,
    charge_id      INTEGER,                         -- the folio line of a redemption (so voiding it returns the points)
    points         INTEGER NOT NULL,                -- positive = earned or added, negative = redeemed or removed
    reason         TEXT NOT NULL DEFAULT '',
    created_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_loyalty_guest ON loyalty_ledger(guest_id, id);
"""
