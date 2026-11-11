"""Migration 4: rate plans, guest language, pre-arrival reminders."""

MIGRATION_4 = """
-- ------------------------------------------------------------ rate plans (meal plans, non-refundable rates)
CREATE TABLE rate_plans (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name_ar     TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    meal_plan   TEXT NOT NULL DEFAULT 'room_only'
                CHECK (meal_plan IN ('room_only', 'breakfast', 'half_board', 'full_board')),
    adjust_pct  REAL NOT NULL DEFAULT 0,              -- applied to the room rate, e.g. -10 for a non-refundable rate
    per_adult   REAL NOT NULL DEFAULT 0 CHECK (per_adult >= 0),   -- added per adult per night (meals)
    per_child   REAL NOT NULL DEFAULT 0 CHECK (per_child >= 0),
    refundable  INTEGER NOT NULL DEFAULT 1,           -- 0: the guest cannot cancel or change it online
    online      INTEGER NOT NULL DEFAULT 1,           -- offered on the booking website
    active      INTEGER NOT NULL DEFAULT 1,
    position    INTEGER NOT NULL DEFAULT 0
);

-- the plan is copied onto the reservation, so later edits to a plan never change an existing booking
ALTER TABLE reservations ADD COLUMN rate_plan_id INTEGER REFERENCES rate_plans(id) ON DELETE SET NULL;
ALTER TABLE reservations ADD COLUMN rate_plan_name TEXT NOT NULL DEFAULT '';
ALTER TABLE reservations ADD COLUMN meal_plan TEXT NOT NULL DEFAULT 'room_only';
ALTER TABLE reservations ADD COLUMN refundable INTEGER NOT NULL DEFAULT 1;

-- ------------------------------------------------------------ pre-arrival reminder e-mails
ALTER TABLE reservations ADD COLUMN reminder_sent_at TEXT;

-- ------------------------------------------------------------ language for e-mails ('' = English)
ALTER TABLE guests ADD COLUMN language TEXT NOT NULL DEFAULT '';
"""
