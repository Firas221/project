"""Database schema, connection handling and demo seed data."""
import datetime as dt
import os
import sqlite3

from .auth import hash_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name     TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'staff')),
    password_hash TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS room_types (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '',
    base_rate   REAL NOT NULL CHECK (base_rate >= 0),
    capacity    INTEGER NOT NULL CHECK (capacity > 0),
    amenities   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS rooms (
    id      INTEGER PRIMARY KEY,
    number  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    floor   INTEGER NOT NULL DEFAULT 1,
    type_id INTEGER NOT NULL REFERENCES room_types(id),
    status  TEXT NOT NULL DEFAULT 'clean' CHECK (status IN ('clean', 'dirty', 'maintenance')),
    notes   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS guests (
    id         INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name  TEXT NOT NULL,
    email      TEXT NOT NULL DEFAULT '',
    phone      TEXT NOT NULL DEFAULT '',
    address    TEXT NOT NULL DEFAULT '',
    id_number  TEXT NOT NULL DEFAULT '',
    vip        INTEGER NOT NULL DEFAULT 0,
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS reservations (
    id             INTEGER PRIMARY KEY,
    code           TEXT NOT NULL UNIQUE,
    guest_id       INTEGER NOT NULL REFERENCES guests(id),
    room_id        INTEGER NOT NULL REFERENCES rooms(id),
    check_in       TEXT NOT NULL,
    check_out      TEXT NOT NULL,
    adults         INTEGER NOT NULL DEFAULT 1 CHECK (adults >= 1),
    children       INTEGER NOT NULL DEFAULT 0 CHECK (children >= 0),
    rate           REAL NOT NULL CHECK (rate >= 0),
    status         TEXT NOT NULL DEFAULT 'booked'
                   CHECK (status IN ('booked', 'checked_in', 'checked_out', 'cancelled', 'no_show')),
    source         TEXT NOT NULL DEFAULT 'walk-in',
    notes          TEXT NOT NULL DEFAULT '',
    created_by     INTEGER REFERENCES users(id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    checked_in_at  TEXT,
    checked_out_at TEXT,
    CHECK (check_out > check_in)
);
CREATE INDEX IF NOT EXISTS idx_res_room_dates ON reservations(room_id, check_in, check_out);
CREATE INDEX IF NOT EXISTS idx_res_status ON reservations(status);

CREATE TABLE IF NOT EXISTS suppliers (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    contact TEXT NOT NULL DEFAULT '',
    phone   TEXT NOT NULL DEFAULT '',
    email   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY,
    sku           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name          TEXT NOT NULL,
    category      TEXT NOT NULL DEFAULT 'General',
    unit          TEXT NOT NULL DEFAULT 'pcs',
    quantity      REAL NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    reorder_level REAL NOT NULL DEFAULT 0,
    cost          REAL NOT NULL DEFAULT 0 CHECK (cost >= 0),
    price         REAL NOT NULL DEFAULT 0 CHECK (price >= 0),
    chargeable    INTEGER NOT NULL DEFAULT 0,
    supplier_id   INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    active        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS stock_movements (
    id             INTEGER PRIMARY KEY,
    item_id        INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL CHECK (kind IN ('receive', 'issue', 'adjust', 'sale', 'return')),
    change         REAL NOT NULL,
    balance_after  REAL NOT NULL,
    unit_cost      REAL,
    reason         TEXT NOT NULL DEFAULT '',
    reservation_id INTEGER REFERENCES reservations(id) ON DELETE SET NULL,
    created_by     INTEGER REFERENCES users(id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_mov_item ON stock_movements(item_id);

CREATE TABLE IF NOT EXISTS charges (
    id             INTEGER PRIMARY KEY,
    reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
    item_id        INTEGER REFERENCES items(id) ON DELETE SET NULL,
    description    TEXT NOT NULL,
    category       TEXT NOT NULL DEFAULT 'Service',
    quantity       REAL NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price     REAL NOT NULL,
    amount         REAL NOT NULL,
    created_by     INTEGER REFERENCES users(id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS payments (
    id             INTEGER PRIMARY KEY,
    reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
    amount         REAL NOT NULL,
    method         TEXT NOT NULL CHECK (method IN ('cash', 'card', 'bank_transfer', 'other')),
    reference      TEXT NOT NULL DEFAULT '',
    created_by     INTEGER REFERENCES users(id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS activity (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action     TEXT NOT NULL,
    details    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

DEFAULT_SETTINGS = {
    "hotel_name": "Harborview Hotel",
    "address": "1 Harbor Road, Bayside",
    "phone": "+1 555 0100",
    "email": "frontdesk@harborview.example",
    "currency": "$",
    "tax_rate": "10",
    "check_in_time": "14:00",
    "check_out_time": "11:00",
}


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db(path: str, seed: bool = True) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        conn.execute("BEGIN IMMEDIATE")
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        if not conn.execute("SELECT 1 FROM users").fetchone():
            conn.execute(
                "INSERT INTO users(username, full_name, role, password_hash) VALUES (?,?,?,?)",
                ("admin", "Administrator", "admin", hash_password("admin123")),
            )
            if seed:
                _seed_demo(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _seed_demo(conn: sqlite3.Connection) -> None:
    today = dt.date.today()

    def d(offset):
        return (today + dt.timedelta(days=offset)).isoformat()

    conn.execute(
        "INSERT INTO users(username, full_name, role, password_hash) VALUES (?,?,?,?)",
        ("frontdesk", "Front Desk", "staff", hash_password("front123")),
    )

    types = [
        ("Standard Single", "Cozy room with a single bed", 89, 1, "Wi-Fi, TV, Desk"),
        ("Standard Double", "Comfortable room with a queen bed", 119, 2, "Wi-Fi, TV, Mini-bar"),
        ("Deluxe King", "Spacious king room with city view", 159, 2, "Wi-Fi, Smart TV, Mini-bar, Bathtub"),
        ("Family Suite", "Two bedrooms and a living area", 229, 4, "Wi-Fi, 2 TVs, Kitchenette, Mini-bar"),
        ("Presidential Suite", "Top-floor suite with terrace", 450, 4, "Wi-Fi, Terrace, Jacuzzi, Butler service"),
    ]
    for t in types:
        conn.execute(
            "INSERT INTO room_types(name, description, base_rate, capacity, amenities) VALUES (?,?,?,?,?)", t
        )

    rooms = []
    for n in range(1, 9):
        rooms.append((f"1{n:02d}", 1, 1 if n <= 4 else 2))
    for n in range(1, 9):
        rooms.append((f"2{n:02d}", 2, 2 if n <= 3 else 3))
    for n in range(1, 7):
        rooms.append((f"3{n:02d}", 3, 3 if n <= 2 else 4))
    rooms += [("401", 4, 5), ("402", 4, 5)]
    for number, floor, type_id in rooms:
        conn.execute("INSERT INTO rooms(number, floor, type_id) VALUES (?,?,?)", (number, floor, type_id))
    conn.execute("UPDATE rooms SET status='maintenance', notes='AC unit repair' WHERE number='208'")
    conn.execute("UPDATE rooms SET status='dirty' WHERE number IN ('103','204','302')")

    guests = [
        ("Amelia", "Hart", "amelia.hart@example.com", "+1 555 0111", "12 Oak St", "P1234567", 1),
        ("Benjamin", "Okafor", "ben.okafor@example.com", "+1 555 0112", "44 Pine Ave", "P2345678", 0),
        ("Chloe", "Nguyen", "chloe.n@example.com", "+1 555 0113", "9 Elm Rd", "D3456789", 0),
        ("Daniel", "Rossi", "d.rossi@example.com", "+39 555 0114", "Via Roma 3", "P4567890", 0),
        ("Elena", "Petrova", "elena.p@example.com", "+7 555 0115", "Lenina 21", "P5678901", 1),
        ("Farid", "Haddad", "farid.h@example.com", "+961 555 0116", "Hamra St 5", "P6789012", 0),
        ("Grace", "Kim", "grace.kim@example.com", "+82 555 0117", "Gangnam 77", "P7890123", 0),
        ("Hugo", "Martin", "hugo.martin@example.com", "+33 555 0118", "Rue Lepic 8", "P8901234", 0),
        ("Isla", "Brown", "isla.b@example.com", "+44 555 0119", "Baker St 221", "D9012345", 0),
        ("Jonas", "Weber", "jonas.w@example.com", "+49 555 0120", "Hauptstr 10", "P0123456", 0),
    ]
    for g in guests:
        conn.execute(
            "INSERT INTO guests(first_name, last_name, email, phone, address, id_number, vip) VALUES (?,?,?,?,?,?,?)",
            g,
        )

    suppliers = [
        ("FreshServe Foods", "Maria Lopez", "+1 555 0201", "orders@freshserve.example"),
        ("CleanCo Supplies", "Tom Becker", "+1 555 0202", "sales@cleanco.example"),
        ("LinenWorks", "Sara Ali", "+1 555 0203", "hello@linenworks.example"),
    ]
    for s in suppliers:
        conn.execute("INSERT INTO suppliers(name, contact, phone, email) VALUES (?,?,?,?)", s)

    items = [
        ("MB-WATER", "Mineral Water 500ml", "Minibar", "bottle", 120, 40, 0.40, 3.00, 1, 1),
        ("MB-COLA", "Cola 330ml", "Minibar", "can", 80, 30, 0.55, 4.00, 1, 1),
        ("MB-BEER", "Craft Beer 330ml", "Minibar", "bottle", 18, 24, 1.50, 7.00, 1, 1),
        ("MB-CHIPS", "Potato Chips", "Minibar", "bag", 45, 20, 0.70, 4.50, 1, 1),
        ("MB-CHOC", "Dark Chocolate Bar", "Minibar", "bar", 9, 15, 0.90, 5.00, 1, 1),
        ("FB-BRKF", "Breakfast Buffet", "Food & Beverage", "serving", 500, 50, 6.00, 18.00, 1, 1),
        ("AM-SHAMP", "Shampoo 30ml", "Amenities", "bottle", 300, 100, 0.25, 0, 0, 2),
        ("AM-SOAP", "Soap Bar", "Amenities", "bar", 260, 100, 0.20, 0, 0, 2),
        ("AM-TOOTH", "Dental Kit", "Amenities", "kit", 60, 50, 0.45, 2.00, 1, 2),
        ("CL-DETER", "Multi-surface Cleaner 5L", "Cleaning", "can", 6, 4, 12.00, 0, 0, 2),
        ("CL-BAGS", "Trash Bags (roll)", "Cleaning", "roll", 3, 10, 3.50, 0, 0, 2),
        ("LN-TOWEL", "Bath Towel", "Linen", "pcs", 180, 80, 6.50, 0, 0, 3),
        ("LN-SHEET", "Bed Sheet Set (King)", "Linen", "set", 70, 40, 18.00, 0, 0, 3),
        ("LN-ROBE", "Bathrobe", "Linen", "pcs", 25, 10, 22.00, 45.00, 1, 3),
    ]
    for it in items:
        cur = conn.execute(
            "INSERT INTO items(sku, name, category, unit, quantity, reorder_level, cost, price, chargeable, supplier_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            it,
        )
        conn.execute(
            "INSERT INTO stock_movements(item_id, kind, change, balance_after, unit_cost, reason, created_by)"
            " VALUES (?, 'receive', ?, ?, ?, 'Opening stock', 1)",
            (cur.lastrowid, it[4], it[4], it[6]),
        )

    def room_id(number):
        return conn.execute("SELECT id FROM rooms WHERE number=?", (number,)).fetchone()[0]

    def rate_for(number):
        return conn.execute(
            "SELECT t.base_rate FROM rooms r JOIN room_types t ON t.id=r.type_id WHERE r.number=?", (number,)
        ).fetchone()[0]

    # (code, guest, room, check_in offset, check_out offset, adults, children, status, source)
    reservations = [
        ("RHV1001", 1, "301", -2, 2, 2, 0, "checked_in", "direct"),
        ("RHV1002", 2, "105", -1, 1, 2, 0, "checked_in", "booking.com"),
        ("RHV1003", 3, "202", -3, 0, 2, 0, "checked_in", "phone"),
        ("RHV1004", 4, "401", 0, 4, 2, 1, "booked", "direct"),
        ("RHV1005", 5, "203", 0, 3, 2, 0, "booked", "expedia"),
        ("RHV1006", 6, "101", 1, 3, 1, 0, "booked", "walk-in"),
        ("RHV1007", 7, "304", 2, 6, 3, 1, "booked", "direct"),
        ("RHV1008", 8, "106", -6, -2, 2, 0, "checked_out", "booking.com"),
        ("RHV1009", 9, "205", -9, -5, 1, 0, "checked_out", "phone"),
        ("RHV1010", 10, "102", 5, 8, 1, 0, "booked", "direct"),
        ("RHV1011", 1, "206", -12, -10, 2, 0, "checked_out", "direct"),
        ("RHV1012", 4, "107", -4, -1, 2, 0, "cancelled", "expedia"),
    ]
    for code, gid, room, ci, co, ad, ch, status, source in reservations:
        cur = conn.execute(
            "INSERT INTO reservations(code, guest_id, room_id, check_in, check_out, adults, children, rate, status,"
            " source, created_by, checked_in_at, checked_out_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?,?)",
            (
                code, gid, room_id(room), d(ci), d(co), ad, ch, rate_for(room), status, source,
                d(ci) + " 14:20:00" if status in ("checked_in", "checked_out") else None,
                d(co) + " 10:45:00" if status == "checked_out" else None,
                d(min(ci, 0) - 7) + " 09:00:00",
            ),
        )
        rid = cur.lastrowid
        if status == "checked_out":
            nights = co - ci
            room_total = nights * rate_for(room)
            conn.execute(
                "INSERT INTO charges(reservation_id, item_id, description, category, quantity, unit_price, amount,"
                " created_by, created_at) VALUES (?, 6, 'Breakfast Buffet', 'Food & Beverage', 2, 18, 36, 1, ?)",
                (rid, d(ci + 1) + " 08:30:00"),
            )
            total = round((room_total + 36) * 1.10, 2)
            conn.execute(
                "INSERT INTO payments(reservation_id, amount, method, reference, created_by, created_at)"
                " VALUES (?,?,?,?,1,?)",
                (rid, total, "card", "POS-" + code[-4:], d(co) + " 10:40:00"),
            )
        if code == "RHV1001":
            conn.execute(
                "INSERT INTO charges(reservation_id, item_id, description, category, quantity, unit_price, amount,"
                " created_by, created_at) VALUES (?, 3, 'Craft Beer 330ml', 'Minibar', 2, 7, 14, 1, ?)",
                (rid, d(-1) + " 22:10:00"),
            )
            conn.execute(
                "INSERT INTO payments(reservation_id, amount, method, reference, created_by, created_at)"
                " VALUES (?, 200, 'card', 'Deposit', 1, ?)",
                (rid, d(-2) + " 14:25:00"),
            )
    conn.execute("UPDATE rooms SET status='dirty' WHERE number IN ('301','105','202')")
