"""Migration 2: commercial & compliance features (Egypt), security hardening."""

MIGRATION_2 = """
-- ------------------------------------------------------------ guests: compliance (Egypt)
ALTER TABLE guests ADD COLUMN id_type TEXT NOT NULL DEFAULT 'passport';
ALTER TABLE guests ADD COLUMN date_of_birth TEXT NOT NULL DEFAULT '';
ALTER TABLE guests ADD COLUMN gender TEXT NOT NULL DEFAULT '';
ALTER TABLE guests ADD COLUMN marketing_consent INTEGER NOT NULL DEFAULT 0;
ALTER TABLE guests ADD COLUMN privacy_accepted_at TEXT;
ALTER TABLE guests ADD COLUMN anonymized_at TEXT;

-- ------------------------------------------------------------ users: 2FA
ALTER TABLE users ADD COLUMN totp_secret TEXT;
ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN totp_last_step INTEGER NOT NULL DEFAULT 0;

CREATE TABLE password_resets (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE login_challenges (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    attempts   INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT NOT NULL
);

CREATE TABLE email_outbox (
    id         INTEGER PRIMARY KEY,
    to_address TEXT NOT NULL,
    subject    TEXT NOT NULL,
    body       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'failed', 'logged')),
    attempts   INTEGER NOT NULL DEFAULT 0,
    error      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    sent_at    TEXT
);

-- ------------------------------------------------------------ corporate accounts (city ledger) & groups
CREATE TABLE companies (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    tax_number    TEXT NOT NULL DEFAULT '',
    contact       TEXT NOT NULL DEFAULT '',
    email         TEXT NOT NULL DEFAULT '',
    phone         TEXT NOT NULL DEFAULT '',
    address       TEXT NOT NULL DEFAULT '',
    discount_pct  REAL NOT NULL DEFAULT 0 CHECK (discount_pct BETWEEN 0 AND 100),
    credit_limit  REAL NOT NULL DEFAULT 0 CHECK (credit_limit >= 0),
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE ledger_entries (
    id             INTEGER PRIMARY KEY,
    company_id     INTEGER NOT NULL REFERENCES companies(id),
    reservation_id INTEGER REFERENCES reservations(id) ON DELETE SET NULL,
    kind           TEXT NOT NULL CHECK (kind IN ('invoice', 'payment', 'adjustment')),
    amount         REAL NOT NULL,
    reference      TEXT NOT NULL DEFAULT '',
    created_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_ledger_company ON ledger_entries(company_id);

ALTER TABLE reservations ADD COLUMN company_id INTEGER REFERENCES companies(id);
ALTER TABLE reservations ADD COLUMN bill_to_company INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reservations ADD COLUMN group_code TEXT NOT NULL DEFAULT '';
ALTER TABLE reservations ADD COLUMN group_name TEXT NOT NULL DEFAULT '';
ALTER TABLE reservations ADD COLUMN promo_code TEXT NOT NULL DEFAULT '';
ALTER TABLE reservations ADD COLUMN rate_note TEXT NOT NULL DEFAULT '';
CREATE INDEX idx_res_group ON reservations(group_code);

-- ------------------------------------------------------------ pricing
CREATE TABLE rate_seasons (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    room_type_id INTEGER REFERENCES room_types(id) ON DELETE CASCADE,
    start_date   TEXT NOT NULL,
    end_date     TEXT NOT NULL,
    adjust_pct   REAL NOT NULL DEFAULT 0 CHECK (adjust_pct BETWEEN -90 AND 500),
    min_nights   INTEGER NOT NULL DEFAULT 1 CHECK (min_nights >= 1),
    active       INTEGER NOT NULL DEFAULT 1,
    CHECK (end_date >= start_date)
);

CREATE TABLE promo_codes (
    id           INTEGER PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description  TEXT NOT NULL DEFAULT '',
    discount_pct REAL NOT NULL CHECK (discount_pct > 0 AND discount_pct <= 100),
    valid_from   TEXT NOT NULL,
    valid_to     TEXT NOT NULL,
    max_uses     INTEGER NOT NULL DEFAULT 0,
    used_count   INTEGER NOT NULL DEFAULT 0,
    online_only  INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1
);

-- ------------------------------------------------------------ cashiering & invoices
CREATE TABLE cashier_shifts (
    id             INTEGER PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    opened_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    closed_at      TEXT,
    opening_float  REAL NOT NULL DEFAULT 0,
    expected_cash  REAL,
    counted_cash   REAL,
    variance       REAL,
    notes          TEXT NOT NULL DEFAULT ''
);
ALTER TABLE payments ADD COLUMN shift_id INTEGER REFERENCES cashier_shifts(id);

CREATE TABLE invoices (
    id             INTEGER PRIMARY KEY,
    number         TEXT NOT NULL UNIQUE,
    reservation_id INTEGER NOT NULL REFERENCES reservations(id),
    bill_to        TEXT NOT NULL,
    bill_to_tax_no TEXT NOT NULL DEFAULT '',
    subtotal       REAL NOT NULL,
    service_charge REAL NOT NULL,
    vat            REAL NOT NULL,
    city_tax       REAL NOT NULL DEFAULT 0,
    total          REAL NOT NULL,
    snapshot       TEXT NOT NULL,
    issued_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    issued_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ------------------------------------------------------------ night audit
CREATE TABLE audit_days (
    business_date  TEXT PRIMARY KEY,
    rooms_total    INTEGER NOT NULL,
    rooms_sold     INTEGER NOT NULL,
    room_revenue   REAL NOT NULL,
    other_revenue  REAL NOT NULL,
    payments       REAL NOT NULL,
    arrivals       INTEGER NOT NULL,
    departures     INTEGER NOT NULL,
    no_shows       INTEGER NOT NULL,
    notes          TEXT NOT NULL DEFAULT '',
    closed_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    closed_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""
