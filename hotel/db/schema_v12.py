"""Migration 12: banquet, conference and event bookings."""

MIGRATION_12 = """
CREATE TABLE venues (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    capacity    INTEGER NOT NULL DEFAULT 50 CHECK (capacity > 0),
    hourly_rate REAL NOT NULL DEFAULT 0 CHECK (hourly_rate >= 0),
    day_rate    REAL NOT NULL DEFAULT 0 CHECK (day_rate >= 0),
    description TEXT NOT NULL DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE events (
    id                  INTEGER PRIMARY KEY,
    code                TEXT NOT NULL UNIQUE,
    venue_id            INTEGER NOT NULL REFERENCES venues(id),
    title               TEXT NOT NULL,
    organizer_name      TEXT NOT NULL,
    organizer_phone     TEXT NOT NULL DEFAULT '',
    organizer_email     TEXT NOT NULL DEFAULT '',
    company_id          INTEGER REFERENCES companies(id),
    event_date          TEXT NOT NULL,
    start_time          TEXT NOT NULL,
    end_time            TEXT NOT NULL,
    attendees           INTEGER NOT NULL DEFAULT 1 CHECK (attendees > 0),
    setup               TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'inquiry' CHECK (status IN ('inquiry', 'confirmed', 'completed', 'cancelled')),
    venue_charge        REAL NOT NULL DEFAULT 0,
    catering_per_person REAL NOT NULL DEFAULT 0,
    extras              REAL NOT NULL DEFAULT 0,
    extras_note         TEXT NOT NULL DEFAULT '',
    notes               TEXT NOT NULL DEFAULT '',
    -- frozen when the event is completed, with a numbered tax invoice
    invoice_number      TEXT UNIQUE,
    subtotal            REAL NOT NULL DEFAULT 0,
    service_charge      REAL NOT NULL DEFAULT 0,
    vat                 REAL NOT NULL DEFAULT 0,
    city_tax            REAL NOT NULL DEFAULT 0,
    total               REAL NOT NULL DEFAULT 0,
    completed_at        TEXT,
    created_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_events_date ON events(event_date, venue_id);

CREATE TABLE event_payments (
    id         INTEGER PRIMARY KEY,
    event_id   INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    amount     REAL NOT NULL,
    method     TEXT NOT NULL,
    reference  TEXT NOT NULL DEFAULT '',
    shift_id   INTEGER REFERENCES cashier_shifts(id) ON DELETE SET NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_event_payments ON event_payments(event_id);
"""
