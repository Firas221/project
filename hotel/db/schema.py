"""Versioned database schema.

Each entry in ``MIGRATIONS`` is applied once, in order, and recorded in the
``schema_migrations`` table. To change the schema, append a new migration —
never edit one that has already shipped.
"""

MIGRATION_1 = """
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ------------------------------------------------------------ identity & access
CREATE TABLE roles (
    name        TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE role_permissions (
    role       TEXT NOT NULL REFERENCES roles(name) ON DELETE CASCADE,
    permission TEXT NOT NULL,
    PRIMARY KEY (role, permission)
);

CREATE TABLE guests (
    id          INTEGER PRIMARY KEY,
    first_name  TEXT NOT NULL,
    last_name   TEXT NOT NULL,
    email       TEXT NOT NULL DEFAULT '',
    phone       TEXT NOT NULL DEFAULT '',
    address     TEXT NOT NULL DEFAULT '',
    nationality TEXT NOT NULL DEFAULT '',
    id_number   TEXT NOT NULL DEFAULT '',
    vip         INTEGER NOT NULL DEFAULT 0,
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_guests_email ON guests(email);

CREATE TABLE users (
    id                   INTEGER PRIMARY KEY,
    username             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email                TEXT NOT NULL DEFAULT '',
    full_name            TEXT NOT NULL,
    role                 TEXT NOT NULL REFERENCES roles(name),
    password_hash        TEXT NOT NULL,
    active               INTEGER NOT NULL DEFAULT 1,
    guest_id             INTEGER UNIQUE REFERENCES guests(id) ON DELETE SET NULL,
    failed_attempts      INTEGER NOT NULL DEFAULT 0,
    locked_until         TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    password_changed_at  TEXT,
    last_login_at        TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE sessions (
    id           INTEGER PRIMARY KEY,
    token_hash   TEXT NOT NULL UNIQUE,
    csrf_token   TEXT NOT NULL,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ip           TEXT NOT NULL DEFAULT '',
    user_agent   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    expires_at   TEXT NOT NULL
);
CREATE INDEX idx_sessions_user ON sessions(user_id);

CREATE TABLE audit_log (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username   TEXT NOT NULL DEFAULT '',
    action     TEXT NOT NULL,
    entity     TEXT NOT NULL DEFAULT '',
    entity_id  INTEGER,
    details    TEXT NOT NULL DEFAULT '',
    ip         TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_audit_created ON audit_log(created_at);

-- ------------------------------------------------------------ rooms
CREATE TABLE room_types (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '',
    base_rate   REAL NOT NULL CHECK (base_rate >= 0),
    capacity    INTEGER NOT NULL CHECK (capacity > 0),
    bed_type    TEXT NOT NULL DEFAULT '',
    size_sqm    INTEGER NOT NULL DEFAULT 0,
    amenities   TEXT NOT NULL DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE rooms (
    id      INTEGER PRIMARY KEY,
    number  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    floor   INTEGER NOT NULL DEFAULT 1,
    type_id INTEGER NOT NULL REFERENCES room_types(id),
    status  TEXT NOT NULL DEFAULT 'clean' CHECK (status IN ('clean', 'dirty', 'inspected', 'maintenance')),
    notes   TEXT NOT NULL DEFAULT ''
);

-- ------------------------------------------------------------ reservations & billing
CREATE TABLE reservations (
    id               INTEGER PRIMARY KEY,
    code             TEXT NOT NULL UNIQUE,
    guest_id         INTEGER NOT NULL REFERENCES guests(id),
    room_id          INTEGER NOT NULL REFERENCES rooms(id),
    check_in         TEXT NOT NULL,
    check_out        TEXT NOT NULL,
    adults           INTEGER NOT NULL DEFAULT 1 CHECK (adults >= 1),
    children         INTEGER NOT NULL DEFAULT 0 CHECK (children >= 0),
    rate             REAL NOT NULL CHECK (rate >= 0),
    status           TEXT NOT NULL DEFAULT 'booked'
                     CHECK (status IN ('booked', 'checked_in', 'checked_out', 'cancelled', 'no_show')),
    source           TEXT NOT NULL DEFAULT 'walk-in',
    special_requests TEXT NOT NULL DEFAULT '',
    notes            TEXT NOT NULL DEFAULT '',
    created_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    checked_in_at    TEXT,
    checked_out_at   TEXT,
    cancelled_at     TEXT,
    CHECK (check_out > check_in)
);
CREATE INDEX idx_res_room_dates ON reservations(room_id, check_in, check_out);
CREATE INDEX idx_res_status ON reservations(status);
CREATE INDEX idx_res_guest ON reservations(guest_id);

CREATE TABLE charges (
    id             INTEGER PRIMARY KEY,
    reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
    item_id        INTEGER REFERENCES items(id) ON DELETE SET NULL,
    order_id       INTEGER REFERENCES orders(id) ON DELETE SET NULL,
    description    TEXT NOT NULL,
    category       TEXT NOT NULL DEFAULT 'Service',
    quantity       REAL NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price     REAL NOT NULL,
    amount         REAL NOT NULL,
    created_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_charges_res ON charges(reservation_id);

CREATE TABLE payments (
    id             INTEGER PRIMARY KEY,
    reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
    amount         REAL NOT NULL,
    method         TEXT NOT NULL CHECK (method IN ('cash', 'card', 'bank_transfer', 'other')),
    reference      TEXT NOT NULL DEFAULT '',
    created_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_payments_res ON payments(reservation_id);

-- ------------------------------------------------------------ inventory & purchasing
CREATE TABLE suppliers (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    contact TEXT NOT NULL DEFAULT '',
    phone   TEXT NOT NULL DEFAULT '',
    email   TEXT NOT NULL DEFAULT '',
    active  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE items (
    id            INTEGER PRIMARY KEY,
    sku           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name          TEXT NOT NULL,
    category      TEXT NOT NULL DEFAULT 'General',
    department    TEXT NOT NULL DEFAULT 'general'
                  CHECK (department IN ('general', 'housekeeping', 'kitchen', 'minibar', 'maintenance', 'front_office')),
    unit          TEXT NOT NULL DEFAULT 'pcs',
    quantity      REAL NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    reorder_level REAL NOT NULL DEFAULT 0 CHECK (reorder_level >= 0),
    cost          REAL NOT NULL DEFAULT 0 CHECK (cost >= 0),
    price         REAL NOT NULL DEFAULT 0 CHECK (price >= 0),
    chargeable    INTEGER NOT NULL DEFAULT 0,
    supplier_id   INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    active        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE stock_movements (
    id             INTEGER PRIMARY KEY,
    item_id        INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL CHECK (kind IN ('receive', 'issue', 'adjust', 'sale', 'return', 'consume')),
    change         REAL NOT NULL,
    balance_after  REAL NOT NULL,
    unit_cost      REAL,
    reason         TEXT NOT NULL DEFAULT '',
    reference      TEXT NOT NULL DEFAULT '',
    reservation_id INTEGER REFERENCES reservations(id) ON DELETE SET NULL,
    created_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_mov_item ON stock_movements(item_id);

CREATE TABLE purchase_orders (
    id            INTEGER PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    supplier_id   INTEGER NOT NULL REFERENCES suppliers(id),
    status        TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'ordered', 'received', 'cancelled')),
    expected_date TEXT,
    notes         TEXT NOT NULL DEFAULT '',
    created_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    ordered_at    TEXT,
    received_at   TEXT
);

CREATE TABLE purchase_order_lines (
    id        INTEGER PRIMARY KEY,
    po_id     INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    item_id   INTEGER NOT NULL REFERENCES items(id),
    quantity  REAL NOT NULL CHECK (quantity > 0),
    unit_cost REAL NOT NULL CHECK (unit_cost >= 0)
);

CREATE TABLE stock_requests (
    id           INTEGER PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,
    department   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'issued', 'rejected', 'cancelled')),
    notes        TEXT NOT NULL DEFAULT '',
    response     TEXT NOT NULL DEFAULT '',
    requested_by INTEGER NOT NULL REFERENCES users(id),
    handled_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    handled_at   TEXT
);

CREATE TABLE stock_request_lines (
    id         INTEGER PRIMARY KEY,
    request_id INTEGER NOT NULL REFERENCES stock_requests(id) ON DELETE CASCADE,
    item_id    INTEGER NOT NULL REFERENCES items(id),
    quantity   REAL NOT NULL CHECK (quantity > 0)
);

-- ------------------------------------------------------------ kitchen / food & beverage
CREATE TABLE menu_items (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description  TEXT NOT NULL DEFAULT '',
    category     TEXT NOT NULL DEFAULT 'Mains',
    price        REAL NOT NULL CHECK (price >= 0),
    prep_minutes INTEGER NOT NULL DEFAULT 15,
    available    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE menu_ingredients (
    menu_item_id INTEGER NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
    item_id      INTEGER NOT NULL REFERENCES items(id),
    quantity     REAL NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (menu_item_id, item_id)
);

CREATE TABLE orders (
    id             INTEGER PRIMARY KEY,
    code           TEXT NOT NULL UNIQUE,
    reservation_id INTEGER NOT NULL REFERENCES reservations(id),
    status         TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'preparing', 'ready', 'delivered', 'cancelled')),
    notes          TEXT NOT NULL DEFAULT '',
    total          REAL NOT NULL DEFAULT 0,
    placed_via     TEXT NOT NULL DEFAULT 'staff' CHECK (placed_via IN ('staff', 'guest')),
    created_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    delivered_at   TEXT
);
CREATE INDEX idx_orders_status ON orders(status);

CREATE TABLE order_lines (
    id           INTEGER PRIMARY KEY,
    order_id     INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    menu_item_id INTEGER REFERENCES menu_items(id) ON DELETE SET NULL,
    name         TEXT NOT NULL,
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    unit_price   REAL NOT NULL,
    notes        TEXT NOT NULL DEFAULT ''
);

-- ------------------------------------------------------------ housekeeping & maintenance
CREATE TABLE housekeeping_tasks (
    id           INTEGER PRIMARY KEY,
    room_id      INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN ('checkout_clean', 'stayover', 'deep_clean', 'turndown', 'guest_request')),
    priority     TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'done', 'inspected', 'cancelled')),
    assigned_to  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    notes        TEXT NOT NULL DEFAULT '',
    due_date     TEXT NOT NULL,
    created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    started_at   TEXT,
    completed_at TEXT,
    inspected_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX idx_hk_status ON housekeeping_tasks(status, due_date);

CREATE TABLE maintenance_tickets (
    id            INTEGER PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    room_id       INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
    location      TEXT NOT NULL DEFAULT '',
    title         TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    priority      TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    out_of_order  INTEGER NOT NULL DEFAULT 0,
    reported_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    assigned_to   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    resolution    TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    resolved_at   TEXT
);

-- ------------------------------------------------------------ guest services
CREATE TABLE guest_requests (
    id             INTEGER PRIMARY KEY,
    reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL CHECK (kind IN ('housekeeping', 'maintenance', 'amenity', 'wake_up', 'other')),
    message        TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'done', 'cancelled')),
    response       TEXT NOT NULL DEFAULT '',
    handled_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE lost_found (
    id          INTEGER PRIMARY KEY,
    room_id     INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
    location    TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'stored' CHECK (status IN ('stored', 'returned', 'disposed')),
    found_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    guest_id    INTEGER REFERENCES guests(id) ON DELETE SET NULL,
    notes       TEXT NOT NULL DEFAULT '',
    found_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    closed_at   TEXT
);

CREATE TABLE reviews (
    id             INTEGER PRIMARY KEY,
    reservation_id INTEGER NOT NULL UNIQUE REFERENCES reservations(id) ON DELETE CASCADE,
    rating         INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment        TEXT NOT NULL DEFAULT '',
    published      INTEGER NOT NULL DEFAULT 0,
    reply          TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

MIGRATIONS = [
    (1, "initial schema", MIGRATION_1),
]
