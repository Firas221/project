"""Migration 11: restaurant point of sale (tables, checks, receipts)."""

MIGRATION_11 = """
CREATE TABLE restaurant_tables (
    id     INTEGER PRIMARY KEY,
    name   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    seats  INTEGER NOT NULL DEFAULT 4 CHECK (seats > 0),
    area   TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1
);

-- a check is one party's bill: opened on a table (or as takeaway), added to, then paid or charged to a room
CREATE TABLE restaurant_checks (
    id             INTEGER PRIMARY KEY,
    code           TEXT NOT NULL UNIQUE,
    table_id       INTEGER REFERENCES restaurant_tables(id) ON DELETE SET NULL,
    table_name     TEXT NOT NULL DEFAULT '',
    covers         INTEGER NOT NULL DEFAULT 1,
    customer_name  TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'paid', 'charged', 'void')),
    reservation_id INTEGER REFERENCES reservations(id) ON DELETE SET NULL,
    subtotal       REAL NOT NULL DEFAULT 0,
    service_charge REAL NOT NULL DEFAULT 0,
    vat            REAL NOT NULL DEFAULT 0,
    city_tax       REAL NOT NULL DEFAULT 0,
    total          REAL NOT NULL DEFAULT 0,
    paid_method    TEXT NOT NULL DEFAULT '',
    receipt_number TEXT UNIQUE,
    shift_id       INTEGER REFERENCES cashier_shifts(id) ON DELETE SET NULL,
    notes          TEXT NOT NULL DEFAULT '',
    opened_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    opened_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    closed_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    closed_at      TEXT
);
CREATE INDEX idx_checks_status ON restaurant_checks(status, table_id);

CREATE TABLE restaurant_check_lines (
    id           INTEGER PRIMARY KEY,
    check_id     INTEGER NOT NULL REFERENCES restaurant_checks(id) ON DELETE CASCADE,
    menu_item_id INTEGER REFERENCES menu_items(id) ON DELETE SET NULL,
    name         TEXT NOT NULL,
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    unit_price   REAL NOT NULL,
    notes        TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('sent', 'ready', 'void')),
    created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_check_lines ON restaurant_check_lines(check_id, status);
"""
