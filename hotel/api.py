"""JSON API: routing, validation and all business logic."""
import csv
import datetime as dt
import io
import re
import secrets
import string
import threading
import time

from .auth import hash_password, verify_password

SESSION_HOURS = 12
ACTIVE_STATUSES = ("booked", "checked_in")
PAYMENT_METHODS = ("cash", "card", "bank_transfer", "other")
ROOM_STATUSES = ("clean", "dirty", "maintenance")
SOURCES = ("walk-in", "direct", "phone", "email", "booking.com", "expedia", "airbnb", "corporate", "other")


# --------------------------------------------------------------------------- infrastructure

class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Raw:
    """A non-JSON response (CSV export)."""

    def __init__(self, body: str, content_type: str, filename: str = None):
        self.body = body
        self.content_type = content_type
        self.filename = filename


class Ctx:
    def __init__(self, db, user, body, query, params):
        self.db = db
        self.user = user
        self.body = body if isinstance(body, dict) else {}
        self.query = query
        self.params = params
        self.cookies = []

    def log(self, action, details=""):
        self.db.execute(
            "INSERT INTO activity(user_id, action, details) VALUES (?,?,?)",
            (self.user["id"] if self.user else None, action, details),
        )


ROUTES = []


def route(method, pattern, role=None, auth=True):
    def deco(fn):
        ROUTES.append((method, re.compile("^/api" + pattern + "$"), fn, role, auth))
        return fn

    return deco


def find_route(method, path):
    path_matched = False
    for m, rx, fn, role, auth in ROUTES:
        match = rx.match(path)
        if match:
            path_matched = True
            if m == method:
                return fn, role, auth, {k: int(v) if v.isdigit() else v for k, v in match.groupdict().items()}
    if path_matched:
        raise ApiError(405, "Method not allowed")
    raise ApiError(404, "Not found")


def user_from_token(db, token):
    if not token:
        return None
    row = db.execute(
        "SELECT u.id, u.username, u.full_name, u.role, u.active FROM sessions s JOIN users u ON u.id = s.user_id"
        " WHERE s.token = ? AND s.expires_at > ?",
        (token, now_str()),
    ).fetchone()
    if not row or not row["active"]:
        return None
    return dict(row)


# --------------------------------------------------------------------------- helpers

def now_str():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return dt.date.today()


def money(x):
    return round(float(x or 0) + 0.0, 2)


def rows(cursor):
    return [dict(r) for r in cursor.fetchall()]


def one(db, sql, args=(), not_found="Not found"):
    r = db.execute(sql, args).fetchone()
    if r is None:
        raise ApiError(404, not_found)
    return dict(r)


def s(body, key, label=None, required=False, max_len=500, default=""):
    v = body.get(key, None)
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise ApiError(400, f"{label or key} is required")
        return default
    if not isinstance(v, (str, int, float)):
        raise ApiError(400, f"{label or key} is invalid")
    v = str(v).strip()
    if len(v) > max_len:
        raise ApiError(400, f"{label or key} is too long (max {max_len})")
    return v


def num(body, key, label=None, required=False, default=0, minimum=None, maximum=None, integer=False):
    v = body.get(key, None)
    if v is None or v == "":
        if required:
            raise ApiError(400, f"{label or key} is required")
        return default
    try:
        if isinstance(v, bool):
            raise ValueError
        v = float(v)
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError
        if integer:
            if v != int(v):
                raise ValueError
            v = int(v)
    except (TypeError, ValueError):
        raise ApiError(400, f"{label or key} must be a {'whole ' if integer else ''}number")
    if minimum is not None and v < minimum:
        raise ApiError(400, f"{label or key} must be at least {minimum}")
    if maximum is not None and v > maximum:
        raise ApiError(400, f"{label or key} must be at most {maximum}")
    return v


def flag(body, key, default=False):
    v = body.get(key, default)
    if isinstance(v, str):
        return 1 if v.lower() in ("1", "true", "yes", "on") else 0
    return 1 if v else 0


def parse_date(value, label="date"):
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise ApiError(400, f"{label} must be a valid date (YYYY-MM-DD)")


def get_settings(db):
    return {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM settings")}


def tax_rate(db):
    try:
        return float(get_settings(db).get("tax_rate", "0"))
    except ValueError:
        return 0.0


def new_code(db):
    alphabet = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"
    while True:
        code = "R" + "".join(secrets.choice(alphabet) for _ in range(6))
        if not db.execute("SELECT 1 FROM reservations WHERE code=?", (code,)).fetchone():
            return code


def nights_between(ci, co):
    return (dt.date.fromisoformat(co) - dt.date.fromisoformat(ci)).days


def room_conflict(db, room_id, check_in, check_out, exclude_id=None):
    sql = (
        "SELECT code FROM reservations WHERE room_id=? AND status IN ('booked','checked_in')"
        " AND check_in < ? AND check_out > ?"
    )
    args = [room_id, check_out, check_in]
    if exclude_id:
        sql += " AND id <> ?"
        args.append(exclude_id)
    r = db.execute(sql, args).fetchone()
    return r["code"] if r else None


def folio(db, res):
    charges = rows(db.execute(
        "SELECT c.*, u.full_name AS created_by_name FROM charges c LEFT JOIN users u ON u.id=c.created_by"
        " WHERE reservation_id=? ORDER BY c.created_at, c.id", (res["id"],)))
    payments = rows(db.execute(
        "SELECT p.*, u.full_name AS created_by_name FROM payments p LEFT JOIN users u ON u.id=p.created_by"
        " WHERE reservation_id=? ORDER BY p.created_at, p.id", (res["id"],)))
    nights = nights_between(res["check_in"], res["check_out"])
    room_total = 0.0 if res["status"] in ("cancelled", "no_show") else money(nights * res["rate"])
    extras = money(sum(c["amount"] for c in charges))
    subtotal = money(room_total + extras)
    rate = tax_rate(db)
    tax = money(subtotal * rate / 100)
    total = money(subtotal + tax)
    paid = money(sum(p["amount"] for p in payments))
    return {
        "nights": nights,
        "room_total": room_total,
        "extras_total": extras,
        "subtotal": subtotal,
        "tax_rate": rate,
        "tax": tax,
        "total": total,
        "paid": paid,
        "balance": money(total - paid),
        "charges": charges,
        "payments": payments,
    }


RES_SELECT = (
    "SELECT r.*, g.first_name || ' ' || g.last_name AS guest_name, g.email AS guest_email, g.phone AS guest_phone,"
    " g.vip AS guest_vip, rm.number AS room_number, rt.name AS room_type, rt.id AS room_type_id"
    " FROM reservations r JOIN guests g ON g.id=r.guest_id JOIN rooms rm ON rm.id=r.room_id"
    " JOIN room_types rt ON rt.id=rm.type_id"
)


def load_reservation(db, rid):
    res = one(db, RES_SELECT + " WHERE r.id=?", (rid,), "Reservation not found")
    res["nights"] = nights_between(res["check_in"], res["check_out"])
    return res


# --------------------------------------------------------------------------- auth & session

_failed = {}
_failed_lock = threading.Lock()
MAX_FAILS, LOCK_SECONDS = 5, 60


@route("POST", "/login", auth=False)
def login(ctx):
    username = s(ctx.body, "username", "Username", required=True, max_len=80)
    password = ctx.body.get("password") or ""
    key = username.lower()
    with _failed_lock:
        fails, until = _failed.get(key, (0, 0))
        if until > time.time():
            raise ApiError(429, f"Too many failed attempts. Try again in {int(until - time.time()) + 1}s")
    u = ctx.db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not u or not u["active"] or not verify_password(str(password), u["password_hash"]):
        with _failed_lock:
            fails += 1
            _failed[key] = (0, time.time() + LOCK_SECONDS) if fails >= MAX_FAILS else (fails, 0)
        raise ApiError(401, "Invalid username or password")
    with _failed_lock:
        _failed.pop(key, None)
    token = secrets.token_urlsafe(32)
    expires = (dt.datetime.now() + dt.timedelta(hours=SESSION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    ctx.db.execute("DELETE FROM sessions WHERE expires_at < ?", (now_str(),))
    ctx.db.execute("INSERT INTO sessions(token, user_id, expires_at) VALUES (?,?,?)", (token, u["id"], expires))
    ctx.cookies.append(
        f"session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_HOURS * 3600}"
    )
    ctx.user = dict(u)
    ctx.log("login", u["username"])
    return {"id": u["id"], "username": u["username"], "full_name": u["full_name"], "role": u["role"]}


@route("POST", "/logout", auth=False)
def logout(ctx):
    token = getattr(ctx, "token", None)
    if token:
        ctx.db.execute("DELETE FROM sessions WHERE token=?", (token,))
    ctx.cookies.append("session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
    return {"ok": True}


@route("GET", "/me")
def me(ctx):
    u = ctx.user
    return {"id": u["id"], "username": u["username"], "full_name": u["full_name"], "role": u["role"],
            "settings": get_settings(ctx.db)}


@route("POST", "/me/password")
def change_password(ctx):
    current = str(ctx.body.get("current_password") or "")
    new = str(ctx.body.get("new_password") or "")
    row = ctx.db.execute("SELECT password_hash FROM users WHERE id=?", (ctx.user["id"],)).fetchone()
    if not verify_password(current, row["password_hash"]):
        raise ApiError(400, "Current password is incorrect")
    if len(new) < 6:
        raise ApiError(400, "New password must be at least 6 characters")
    ctx.db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new), ctx.user["id"]))
    ctx.log("password_change", ctx.user["username"])
    return {"ok": True}


# --------------------------------------------------------------------------- settings & users

@route("GET", "/settings")
def settings_get(ctx):
    return get_settings(ctx.db)


@route("PUT", "/settings", role="admin")
def settings_put(ctx):
    allowed = ("hotel_name", "address", "phone", "email", "currency", "tax_rate", "check_in_time", "check_out_time")
    for k in allowed:
        if k in ctx.body:
            if k == "tax_rate":
                v = str(num(ctx.body, k, "Tax rate", minimum=0, maximum=100))
            else:
                v = s(ctx.body, k, k.replace("_", " ").capitalize(), max_len=200)
                if k in ("hotel_name", "currency") and not v:
                    raise ApiError(400, f"{k.replace('_', ' ').capitalize()} cannot be empty")
            ctx.db.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                           (k, v))
    ctx.log("settings_update")
    return get_settings(ctx.db)


@route("GET", "/users", role="admin")
def users_list(ctx):
    return rows(ctx.db.execute("SELECT id, username, full_name, role, active, created_at FROM users ORDER BY username"))


def _user_fields(ctx, creating):
    full_name = s(ctx.body, "full_name", "Full name", required=True, max_len=120)
    role = s(ctx.body, "role", "Role", required=True)
    if role not in ("admin", "staff"):
        raise ApiError(400, "Role must be admin or staff")
    return full_name, role


@route("POST", "/users", role="admin")
def users_create(ctx):
    username = s(ctx.body, "username", "Username", required=True, max_len=60)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,60}", username):
        raise ApiError(400, "Username must be 3+ characters: letters, digits, . _ -")
    full_name, role = _user_fields(ctx, True)
    password = str(ctx.body.get("password") or "")
    if len(password) < 6:
        raise ApiError(400, "Password must be at least 6 characters")
    if ctx.db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise ApiError(409, "Username already exists")
    cur = ctx.db.execute("INSERT INTO users(username, full_name, role, password_hash) VALUES (?,?,?,?)",
                         (username, full_name, role, hash_password(password)))
    ctx.log("user_create", username)
    return one(ctx.db, "SELECT id, username, full_name, role, active, created_at FROM users WHERE id=?", (cur.lastrowid,))


@route("PUT", "/users/(?P<id>\\d+)", role="admin")
def users_update(ctx):
    uid = ctx.params["id"]
    user = one(ctx.db, "SELECT * FROM users WHERE id=?", (uid,), "User not found")
    full_name, role = _user_fields(ctx, False)
    active = flag(ctx.body, "active", True)
    if uid == ctx.user["id"] and (role != "admin" or not active):
        raise ApiError(400, "You cannot demote or deactivate your own account")
    if user["role"] == "admin" and (role != "admin" or not active):
        others = ctx.db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id<>?", (uid,)).fetchone()[0]
        if others == 0:
            raise ApiError(400, "At least one active admin is required")
    ctx.db.execute("UPDATE users SET full_name=?, role=?, active=? WHERE id=?", (full_name, role, active, uid))
    password = str(ctx.body.get("password") or "")
    if password:
        if len(password) < 6:
            raise ApiError(400, "Password must be at least 6 characters")
        ctx.db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), uid))
    if not active:
        ctx.db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    ctx.log("user_update", user["username"])
    return one(ctx.db, "SELECT id, username, full_name, role, active, created_at FROM users WHERE id=?", (uid,))


@route("GET", "/activity", role="admin")
def activity(ctx):
    limit = int(num(ctx.query, "limit", default=200, minimum=1, maximum=1000, integer=True))
    return rows(ctx.db.execute(
        "SELECT a.*, u.full_name AS user_name FROM activity a LEFT JOIN users u ON u.id=a.user_id"
        " ORDER BY a.id DESC LIMIT ?", (limit,)))


# --------------------------------------------------------------------------- room types & rooms

def _room_type_fields(ctx):
    return (
        s(ctx.body, "name", "Name", required=True, max_len=80),
        s(ctx.body, "description", max_len=500),
        money(num(ctx.body, "base_rate", "Base rate", required=True, minimum=0)),
        num(ctx.body, "capacity", "Capacity", required=True, minimum=1, maximum=20, integer=True),
        s(ctx.body, "amenities", max_len=500),
    )


@route("GET", "/room-types")
def room_types_list(ctx):
    return rows(ctx.db.execute(
        "SELECT t.*, (SELECT COUNT(*) FROM rooms r WHERE r.type_id=t.id) AS room_count FROM room_types t ORDER BY base_rate"))


@route("POST", "/room-types", role="admin")
def room_types_create(ctx):
    f = _room_type_fields(ctx)
    if ctx.db.execute("SELECT 1 FROM room_types WHERE name=?", (f[0],)).fetchone():
        raise ApiError(409, "A room type with this name already exists")
    cur = ctx.db.execute("INSERT INTO room_types(name, description, base_rate, capacity, amenities) VALUES (?,?,?,?,?)", f)
    ctx.log("room_type_create", f[0])
    return one(ctx.db, "SELECT * FROM room_types WHERE id=?", (cur.lastrowid,))


@route("PUT", "/room-types/(?P<id>\\d+)", role="admin")
def room_types_update(ctx):
    tid = ctx.params["id"]
    one(ctx.db, "SELECT id FROM room_types WHERE id=?", (tid,), "Room type not found")
    f = _room_type_fields(ctx)
    if ctx.db.execute("SELECT 1 FROM room_types WHERE name=? AND id<>?", (f[0], tid)).fetchone():
        raise ApiError(409, "A room type with this name already exists")
    ctx.db.execute("UPDATE room_types SET name=?, description=?, base_rate=?, capacity=?, amenities=? WHERE id=?", f + (tid,))
    ctx.log("room_type_update", f[0])
    return one(ctx.db, "SELECT * FROM room_types WHERE id=?", (tid,))


@route("DELETE", "/room-types/(?P<id>\\d+)", role="admin")
def room_types_delete(ctx):
    tid = ctx.params["id"]
    t = one(ctx.db, "SELECT * FROM room_types WHERE id=?", (tid,), "Room type not found")
    if ctx.db.execute("SELECT 1 FROM rooms WHERE type_id=?", (tid,)).fetchone():
        raise ApiError(409, "Cannot delete: rooms still use this type")
    ctx.db.execute("DELETE FROM room_types WHERE id=?", (tid,))
    ctx.log("room_type_delete", t["name"])
    return {"ok": True}


ROOM_SELECT = """
SELECT r.*, t.name AS type_name, t.base_rate, t.capacity,
  (SELECT res.id FROM reservations res WHERE res.room_id=r.id AND res.status='checked_in' LIMIT 1) AS current_reservation_id,
  (SELECT g.first_name || ' ' || g.last_name FROM reservations res JOIN guests g ON g.id=res.guest_id
     WHERE res.room_id=r.id AND res.status='checked_in' LIMIT 1) AS current_guest,
  (SELECT res.check_out FROM reservations res WHERE res.room_id=r.id AND res.status='checked_in' LIMIT 1) AS current_check_out,
  (SELECT res.id FROM reservations res WHERE res.room_id=r.id AND res.status='booked' AND res.check_in<=:today
     ORDER BY res.check_in LIMIT 1) AS arriving_reservation_id
FROM rooms r JOIN room_types t ON t.id=r.type_id
"""


def _decorate_room(r):
    r["occupied"] = bool(r["current_reservation_id"])
    return r


@route("GET", "/rooms")
def rooms_list(ctx):
    rs = rows(ctx.db.execute(ROOM_SELECT + " ORDER BY r.floor, r.number", {"today": today().isoformat()}))
    return [_decorate_room(r) for r in rs]


def _room_fields(ctx):
    number = s(ctx.body, "number", "Room number", required=True, max_len=20)
    floor = num(ctx.body, "floor", "Floor", default=1, minimum=-5, maximum=200, integer=True)
    type_id = num(ctx.body, "type_id", "Room type", required=True, integer=True)
    one(ctx.db, "SELECT id FROM room_types WHERE id=?", (type_id,), "Room type not found")
    status = s(ctx.body, "status", default="clean")
    if status not in ROOM_STATUSES:
        raise ApiError(400, "Invalid room status")
    return number, floor, type_id, status, s(ctx.body, "notes", max_len=500)


@route("POST", "/rooms", role="admin")
def rooms_create(ctx):
    f = _room_fields(ctx)
    if ctx.db.execute("SELECT 1 FROM rooms WHERE number=?", (f[0],)).fetchone():
        raise ApiError(409, "Room number already exists")
    cur = ctx.db.execute("INSERT INTO rooms(number, floor, type_id, status, notes) VALUES (?,?,?,?,?)", f)
    ctx.log("room_create", f[0])
    return _decorate_room(one(ctx.db, ROOM_SELECT + " WHERE r.id=:id", {"id": cur.lastrowid, "today": today().isoformat()}))


@route("PUT", "/rooms/(?P<id>\\d+)", role="admin")
def rooms_update(ctx):
    rid = ctx.params["id"]
    one(ctx.db, "SELECT id FROM rooms WHERE id=?", (rid,), "Room not found")
    f = _room_fields(ctx)
    if ctx.db.execute("SELECT 1 FROM rooms WHERE number=? AND id<>?", (f[0], rid)).fetchone():
        raise ApiError(409, "Room number already exists")
    ctx.db.execute("UPDATE rooms SET number=?, floor=?, type_id=?, status=?, notes=? WHERE id=?", f + (rid,))
    ctx.log("room_update", f[0])
    return _decorate_room(one(ctx.db, ROOM_SELECT + " WHERE r.id=:id", {"id": rid, "today": today().isoformat()}))


@route("DELETE", "/rooms/(?P<id>\\d+)", role="admin")
def rooms_delete(ctx):
    rid = ctx.params["id"]
    r = one(ctx.db, "SELECT * FROM rooms WHERE id=?", (rid,), "Room not found")
    if ctx.db.execute("SELECT 1 FROM reservations WHERE room_id=?", (rid,)).fetchone():
        raise ApiError(409, "Cannot delete a room with reservation history. Set it to maintenance instead.")
    ctx.db.execute("DELETE FROM rooms WHERE id=?", (rid,))
    ctx.log("room_delete", r["number"])
    return {"ok": True}


@route("POST", "/rooms/(?P<id>\\d+)/status")
def rooms_status(ctx):
    rid = ctx.params["id"]
    r = one(ctx.db, "SELECT * FROM rooms WHERE id=?", (rid,), "Room not found")
    status = s(ctx.body, "status", "Status", required=True)
    if status not in ROOM_STATUSES:
        raise ApiError(400, "Invalid room status")
    notes = ctx.body.get("notes")
    if notes is not None:
        ctx.db.execute("UPDATE rooms SET status=?, notes=? WHERE id=?", (status, s(ctx.body, "notes", max_len=500), rid))
    else:
        ctx.db.execute("UPDATE rooms SET status=? WHERE id=?", (status, rid))
    ctx.log("room_status", f"{r['number']}: {r['status']} -> {status}")
    return _decorate_room(one(ctx.db, ROOM_SELECT + " WHERE r.id=:id", {"id": rid, "today": today().isoformat()}))


@route("GET", "/availability")
def availability(ctx):
    ci = parse_date(ctx.query.get("check_in"), "Check-in")
    co = parse_date(ctx.query.get("check_out"), "Check-out")
    if co <= ci:
        raise ApiError(400, "Check-out must be after check-in")
    if (co - ci).days > 365:
        raise ApiError(400, "Stay cannot exceed 365 nights")
    guests = int(num(ctx.query, "guests", default=1, minimum=1, integer=True))
    sql = (
        "SELECT r.id, r.number, r.floor, r.status, t.id AS type_id, t.name AS type_name, t.base_rate, t.capacity"
        " FROM rooms r JOIN room_types t ON t.id=r.type_id"
        " WHERE r.status <> 'maintenance' AND t.capacity >= ?"
        " AND NOT EXISTS (SELECT 1 FROM reservations x WHERE x.room_id=r.id AND x.status IN ('booked','checked_in')"
        "   AND x.check_in < ? AND x.check_out > ?"
    )
    args = [guests, co.isoformat(), ci.isoformat()]
    exclude = ctx.query.get("exclude")
    if exclude and str(exclude).isdigit():
        sql += " AND x.id <> ?"
        args.append(int(exclude))
    sql += ")"
    if ctx.query.get("type_id"):
        sql += " AND t.id = ?"
        args.append(int(num(ctx.query, "type_id", integer=True)))
    sql += " ORDER BY t.base_rate, r.number"
    result = rows(ctx.db.execute(sql, args))
    nights = (co - ci).days
    for r in result:
        r["nights"] = nights
        r["estimated_total"] = money(r["base_rate"] * nights)
    return result


@route("GET", "/calendar")
def calendar(ctx):
    start = parse_date(ctx.query.get("start") or today().isoformat(), "Start")
    days = int(num(ctx.query, "days", default=14, minimum=1, maximum=62, integer=True))
    end = start + dt.timedelta(days=days)
    rooms = rows(ctx.db.execute(
        "SELECT r.id, r.number, r.floor, r.status, t.name AS type_name FROM rooms r JOIN room_types t ON t.id=r.type_id"
        " ORDER BY r.floor, r.number"))
    res = rows(ctx.db.execute(
        RES_SELECT + " WHERE r.status IN ('booked','checked_in','checked_out') AND r.check_in < ? AND r.check_out > ?",
        (end.isoformat(), start.isoformat())))
    return {"start": start.isoformat(), "days": days, "rooms": rooms, "reservations": res}


# --------------------------------------------------------------------------- guests

def _guest_fields(ctx):
    email = s(ctx.body, "email", "Email", max_len=160)
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ApiError(400, "Email address is invalid")
    return (
        s(ctx.body, "first_name", "First name", required=True, max_len=80),
        s(ctx.body, "last_name", "Last name", required=True, max_len=80),
        email,
        s(ctx.body, "phone", "Phone", max_len=40),
        s(ctx.body, "address", "Address", max_len=300),
        s(ctx.body, "id_number", "ID / passport", max_len=60),
        flag(ctx.body, "vip"),
        s(ctx.body, "notes", "Notes", max_len=2000),
    )


GUEST_SELECT = (
    "SELECT g.*, (SELECT COUNT(*) FROM reservations r WHERE r.guest_id=g.id AND r.status NOT IN ('cancelled')) AS stays,"
    " (SELECT MAX(check_in) FROM reservations r WHERE r.guest_id=g.id) AS last_stay FROM guests g"
)


@route("GET", "/guests")
def guests_list(ctx):
    q = (ctx.query.get("q") or "").strip()
    sql, args = GUEST_SELECT, []
    if q:
        like = f"%{q}%"
        sql += (" WHERE g.first_name || ' ' || g.last_name LIKE ? OR g.email LIKE ? OR g.phone LIKE ?"
                " OR g.id_number LIKE ?")
        args = [like] * 4
    sql += " ORDER BY g.last_name, g.first_name LIMIT 500"
    return rows(ctx.db.execute(sql, args))


@route("POST", "/guests")
def guests_create(ctx):
    f = _guest_fields(ctx)
    cur = ctx.db.execute(
        "INSERT INTO guests(first_name, last_name, email, phone, address, id_number, vip, notes) VALUES (?,?,?,?,?,?,?,?)", f)
    ctx.log("guest_create", f"{f[0]} {f[1]}")
    return one(ctx.db, GUEST_SELECT + " WHERE g.id=?", (cur.lastrowid,))


@route("GET", "/guests/(?P<id>\\d+)")
def guests_get(ctx):
    g = one(ctx.db, GUEST_SELECT + " WHERE g.id=?", (ctx.params["id"],), "Guest not found")
    g["reservations"] = rows(ctx.db.execute(RES_SELECT + " WHERE r.guest_id=? ORDER BY r.check_in DESC", (g["id"],)))
    for r in g["reservations"]:
        r["total"] = folio(ctx.db, r)["total"]
    g["lifetime_value"] = money(sum(r["total"] for r in g["reservations"] if r["status"] not in ("cancelled",)))
    return g


@route("PUT", "/guests/(?P<id>\\d+)")
def guests_update(ctx):
    gid = ctx.params["id"]
    one(ctx.db, "SELECT id FROM guests WHERE id=?", (gid,), "Guest not found")
    f = _guest_fields(ctx)
    ctx.db.execute(
        "UPDATE guests SET first_name=?, last_name=?, email=?, phone=?, address=?, id_number=?, vip=?, notes=? WHERE id=?",
        f + (gid,))
    ctx.log("guest_update", f"{f[0]} {f[1]}")
    return one(ctx.db, GUEST_SELECT + " WHERE g.id=?", (gid,))


@route("DELETE", "/guests/(?P<id>\\d+)")
def guests_delete(ctx):
    gid = ctx.params["id"]
    g = one(ctx.db, "SELECT * FROM guests WHERE id=?", (gid,), "Guest not found")
    if ctx.db.execute("SELECT 1 FROM reservations WHERE guest_id=?", (gid,)).fetchone():
        raise ApiError(409, "Cannot delete a guest with reservations")
    ctx.db.execute("DELETE FROM guests WHERE id=?", (gid,))
    ctx.log("guest_delete", f"{g['first_name']} {g['last_name']}")
    return {"ok": True}


# --------------------------------------------------------------------------- reservations

@route("GET", "/reservations")
def reservations_list(ctx):
    where, args = [], []
    status = ctx.query.get("status")
    if status:
        if status == "active":
            where.append("r.status IN ('booked','checked_in')")
        else:
            where.append("r.status = ?")
            args.append(status)
    q = (ctx.query.get("q") or "").strip()
    if q:
        where.append("(r.code LIKE ? OR g.first_name || ' ' || g.last_name LIKE ? OR rm.number LIKE ? OR g.email LIKE ?)")
        args += [f"%{q}%"] * 4
    if ctx.query.get("from"):
        where.append("r.check_out > ?")
        args.append(parse_date(ctx.query["from"]).isoformat())
    if ctx.query.get("to"):
        where.append("r.check_in <= ?")
        args.append(parse_date(ctx.query["to"]).isoformat())
    if ctx.query.get("arriving"):
        where.append("r.check_in = ? AND r.status='booked'")
        args.append(parse_date(ctx.query["arriving"]).isoformat())
    if ctx.query.get("departing"):
        where.append("r.check_out = ? AND r.status='checked_in'")
        args.append(parse_date(ctx.query["departing"]).isoformat())
    sql = RES_SELECT + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY r.check_in DESC, r.id DESC LIMIT 1000"
    result = rows(ctx.db.execute(sql, args))
    for r in result:
        f = folio(ctx.db, r)
        r["nights"], r["total"], r["balance"] = f["nights"], f["total"], f["balance"]
    return result


def _validate_stay(ctx, res=None):
    """Returns validated (room_id, check_in, check_out, adults, children)."""
    base = res or {}
    ci = parse_date(ctx.body.get("check_in", base.get("check_in")), "Check-in")
    co = parse_date(ctx.body.get("check_out", base.get("check_out")), "Check-out")
    if co <= ci:
        raise ApiError(400, "Check-out must be after check-in")
    if (co - ci).days > 365:
        raise ApiError(400, "Stay cannot exceed 365 nights")
    room_id = num(ctx.body, "room_id", "Room", required=res is None, default=base.get("room_id"), integer=True)
    adults = num(ctx.body, "adults", "Adults", default=base.get("adults", 1), minimum=1, maximum=20, integer=True)
    children = num(ctx.body, "children", "Children", default=base.get("children", 0), minimum=0, maximum=20, integer=True)
    room = one(ctx.db, "SELECT r.*, t.capacity, t.base_rate FROM rooms r JOIN room_types t ON t.id=r.type_id WHERE r.id=?",
               (room_id,), "Room not found")
    if adults + children > room["capacity"]:
        raise ApiError(400, f"Room {room['number']} holds at most {room['capacity']} guests")
    if room["status"] == "maintenance" and (res is None or room_id != res["room_id"]):
        raise ApiError(409, f"Room {room['number']} is under maintenance")
    conflict = room_conflict(ctx.db, room_id, ci.isoformat(), co.isoformat(), res["id"] if res else None)
    if conflict:
        raise ApiError(409, f"Room {room['number']} is already booked for these dates (reservation {conflict})")
    return room, ci.isoformat(), co.isoformat(), adults, children


@route("POST", "/reservations")
def reservations_create(ctx):
    guest_id = ctx.body.get("guest_id")
    if not guest_id and isinstance(ctx.body.get("guest"), dict):
        sub = Ctx(ctx.db, ctx.user, ctx.body["guest"], {}, {})
        guest_id = guests_create(sub)["id"]
    if not guest_id:
        raise ApiError(400, "Guest is required")
    guest_id = num({"g": guest_id}, "g", "Guest", integer=True)
    one(ctx.db, "SELECT id FROM guests WHERE id=?", (guest_id,), "Guest not found")
    room, ci, co, adults, children = _validate_stay(ctx)
    if dt.date.fromisoformat(ci) < today() - dt.timedelta(days=1) and not flag(ctx.body, "allow_past"):
        raise ApiError(400, "Check-in date is in the past")
    rate = money(num(ctx.body, "rate", "Rate", default=room["base_rate"], minimum=0))
    source = s(ctx.body, "source", default="walk-in")
    if source not in SOURCES:
        raise ApiError(400, "Invalid booking source")
    code = new_code(ctx.db)
    cur = ctx.db.execute(
        "INSERT INTO reservations(code, guest_id, room_id, check_in, check_out, adults, children, rate, source, notes,"
        " created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (code, guest_id, room["id"], ci, co, adults, children, rate, source, s(ctx.body, "notes", max_len=2000),
         ctx.user["id"]))
    ctx.log("reservation_create", f"{code} room {room['number']} {ci}→{co}")
    deposit = num(ctx.body, "deposit", "Deposit", default=0, minimum=0)
    if deposit:
        method = s(ctx.body, "deposit_method", default="card")
        if method not in PAYMENT_METHODS:
            raise ApiError(400, "Invalid payment method")
        ctx.db.execute("INSERT INTO payments(reservation_id, amount, method, reference, created_by) VALUES (?,?,?,?,?)",
                       (cur.lastrowid, money(deposit), method, "Deposit", ctx.user["id"]))
    return reservation_detail_data(ctx.db, cur.lastrowid)


def reservation_detail_data(db, rid):
    res = load_reservation(db, rid)
    res["folio"] = folio(db, res)
    res["guest"] = one(db, "SELECT * FROM guests WHERE id=?", (res["guest_id"],))
    return res


@route("GET", "/reservations/(?P<id>\\d+)")
def reservations_get(ctx):
    return reservation_detail_data(ctx.db, ctx.params["id"])


@route("PUT", "/reservations/(?P<id>\\d+)")
def reservations_update(ctx):
    res = load_reservation(ctx.db, ctx.params["id"])
    if res["status"] in ("checked_out", "cancelled", "no_show"):
        raise ApiError(409, f"Cannot modify a reservation that is {res['status'].replace('_', ' ')}")
    if res["status"] == "checked_in":
        if "check_in" in ctx.body and ctx.body["check_in"] != res["check_in"]:
            raise ApiError(409, "Check-in date cannot change after the guest has checked in")
        if "room_id" in ctx.body and num(ctx.body, "room_id", "Room", integer=True) != res["room_id"]:
            raise ApiError(409, "Use 'Move room' to change the room of an in-house guest")
    room, ci, co, adults, children = _validate_stay(ctx, res)
    if res["status"] == "checked_in" and dt.date.fromisoformat(co) < today():
        raise ApiError(400, "Check-out cannot be in the past for an in-house guest")
    rate = money(num(ctx.body, "rate", "Rate", default=res["rate"], minimum=0))
    source = s(ctx.body, "source", default=res["source"])
    if source not in SOURCES:
        raise ApiError(400, "Invalid booking source")
    notes = s(ctx.body, "notes", max_len=2000) if "notes" in ctx.body else res["notes"]
    ctx.db.execute(
        "UPDATE reservations SET room_id=?, check_in=?, check_out=?, adults=?, children=?, rate=?, source=?, notes=?"
        " WHERE id=?", (room["id"], ci, co, adults, children, rate, source, notes, res["id"]))
    ctx.log("reservation_update", f"{res['code']} room {room['number']} {ci}→{co}")
    return reservation_detail_data(ctx.db, res["id"])


@route("POST", "/reservations/(?P<id>\\d+)/move")
def reservations_move(ctx):
    res = load_reservation(ctx.db, ctx.params["id"])
    if res["status"] not in ACTIVE_STATUSES:
        raise ApiError(409, "Only active reservations can be moved")
    new_room_id = num(ctx.body, "room_id", "Room", required=True, integer=True)
    if new_room_id == res["room_id"]:
        raise ApiError(400, "Guest is already in this room")
    room = one(ctx.db, "SELECT r.*, t.capacity FROM rooms r JOIN room_types t ON t.id=r.type_id WHERE r.id=?",
               (new_room_id,), "Room not found")
    if room["status"] == "maintenance":
        raise ApiError(409, f"Room {room['number']} is under maintenance")
    if res["adults"] + res["children"] > room["capacity"]:
        raise ApiError(400, f"Room {room['number']} holds at most {room['capacity']} guests")
    conflict = room_conflict(ctx.db, new_room_id, res["check_in"], res["check_out"], res["id"])
    if conflict:
        raise ApiError(409, f"Room {room['number']} is already booked for these dates (reservation {conflict})")
    ctx.db.execute("UPDATE reservations SET room_id=? WHERE id=?", (new_room_id, res["id"]))
    if res["status"] == "checked_in":
        ctx.db.execute("UPDATE rooms SET status='dirty' WHERE id=?", (res["room_id"],))
    if "rate" in ctx.body:
        ctx.db.execute("UPDATE reservations SET rate=? WHERE id=?",
                       (money(num(ctx.body, "rate", "Rate", minimum=0)), res["id"]))
    ctx.log("reservation_move", f"{res['code']}: {res['room_number']} -> {room['number']}")
    return reservation_detail_data(ctx.db, res["id"])


@route("POST", "/reservations/(?P<id>\\d+)/checkin")
def reservations_checkin(ctx):
    res = load_reservation(ctx.db, ctx.params["id"])
    if res["status"] != "booked":
        raise ApiError(409, f"Cannot check in: reservation is {res['status'].replace('_', ' ')}")
    t = today().isoformat()
    if res["check_in"] > t:
        raise ApiError(409, f"Arrival date is {res['check_in']}. Edit the reservation dates to check in early.")
    if res["check_out"] <= t:
        raise ApiError(409, "The stay has already ended. Mark as no-show or edit the dates.")
    room = one(ctx.db, "SELECT * FROM rooms WHERE id=?", (res["room_id"],))
    if room["status"] == "maintenance":
        raise ApiError(409, f"Room {room['number']} is under maintenance. Move the guest to another room.")
    if room["status"] == "dirty" and not flag(ctx.body, "force"):
        raise ApiError(409, f"Room {room['number']} is not cleaned yet")
    occupant = ctx.db.execute("SELECT code FROM reservations WHERE room_id=? AND status='checked_in'",
                              (room["id"],)).fetchone()
    if occupant:
        raise ApiError(409, f"Room {room['number']} is still occupied by {occupant['code']}")
    ctx.db.execute("UPDATE reservations SET status='checked_in', checked_in_at=? WHERE id=?", (now_str(), res["id"]))
    ctx.log("check_in", f"{res['code']} room {res['room_number']}")
    return reservation_detail_data(ctx.db, res["id"])


@route("POST", "/reservations/(?P<id>\\d+)/checkout")
def reservations_checkout(ctx):
    res = load_reservation(ctx.db, ctx.params["id"])
    if res["status"] != "checked_in":
        raise ApiError(409, "Only checked-in guests can be checked out")
    t = today()
    # Early departure: shorten the stay so the guest pays only for nights used (at least one).
    if dt.date.fromisoformat(res["check_out"]) > t and flag(ctx.body, "early_departure"):
        new_co = max(t, dt.date.fromisoformat(res["check_in"]) + dt.timedelta(days=1)).isoformat()
        ctx.db.execute("UPDATE reservations SET check_out=? WHERE id=?", (new_co, res["id"]))
        res = load_reservation(ctx.db, res["id"])
    f = folio(ctx.db, res)
    if f["balance"] > 0.004 and not flag(ctx.body, "force"):
        raise ApiError(409, f"Outstanding balance of {f['balance']:.2f} must be settled before check-out")
    ctx.db.execute("UPDATE reservations SET status='checked_out', checked_out_at=? WHERE id=?", (now_str(), res["id"]))
    ctx.db.execute("UPDATE rooms SET status='dirty' WHERE id=?", (res["room_id"],))
    ctx.log("check_out", f"{res['code']} room {res['room_number']}")
    return reservation_detail_data(ctx.db, res["id"])


@route("POST", "/reservations/(?P<id>\\d+)/cancel")
def reservations_cancel(ctx):
    res = load_reservation(ctx.db, ctx.params["id"])
    if res["status"] != "booked":
        raise ApiError(409, "Only reservations that are not yet checked in can be cancelled")
    fee = money(num(ctx.body, "fee", "Cancellation fee", default=0, minimum=0))
    if fee:
        ctx.db.execute("INSERT INTO charges(reservation_id, description, category, quantity, unit_price, amount, created_by)"
                       " VALUES (?, 'Cancellation fee', 'Fee', 1, ?, ?, ?)", (res["id"], fee, fee, ctx.user["id"]))
    reason = s(ctx.body, "reason", max_len=500)
    notes = (res["notes"] + "\n" if res["notes"] else "") + f"Cancelled: {reason}" if reason else res["notes"]
    ctx.db.execute("UPDATE reservations SET status='cancelled', notes=? WHERE id=?", (notes, res["id"]))
    ctx.log("reservation_cancel", res["code"])
    return reservation_detail_data(ctx.db, res["id"])


@route("POST", "/reservations/(?P<id>\\d+)/noshow")
def reservations_noshow(ctx):
    res = load_reservation(ctx.db, ctx.params["id"])
    if res["status"] != "booked":
        raise ApiError(409, "Only booked reservations can be marked as no-show")
    if res["check_in"] > today().isoformat():
        raise ApiError(409, "Cannot mark a future arrival as no-show")
    fee = money(num(ctx.body, "fee", "No-show fee", default=0, minimum=0))
    if fee:
        ctx.db.execute("INSERT INTO charges(reservation_id, description, category, quantity, unit_price, amount, created_by)"
                       " VALUES (?, 'No-show fee', 'Fee', 1, ?, ?, ?)", (res["id"], fee, fee, ctx.user["id"]))
    ctx.db.execute("UPDATE reservations SET status='no_show' WHERE id=?", (res["id"],))
    ctx.log("reservation_noshow", res["code"])
    return reservation_detail_data(ctx.db, res["id"])


def _record_movement(db, user_id, item, kind, change, reason="", reservation_id=None, unit_cost=None):
    new_qty = round(item["quantity"] + change, 4)
    if new_qty < 0:
        raise ApiError(409, f"Insufficient stock for {item['name']}: {item['quantity']:g} {item['unit']} available")
    db.execute("UPDATE items SET quantity=? WHERE id=?", (new_qty, item["id"]))
    db.execute(
        "INSERT INTO stock_movements(item_id, kind, change, balance_after, unit_cost, reason, reservation_id, created_by)"
        " VALUES (?,?,?,?,?,?,?,?)", (item["id"], kind, change, new_qty, unit_cost, reason, reservation_id, user_id))
    return new_qty


@route("POST", "/reservations/(?P<id>\\d+)/charges")
def charges_add(ctx):
    res = load_reservation(ctx.db, ctx.params["id"])
    if res["status"] not in ("booked", "checked_in"):
        raise ApiError(409, "Charges can only be posted to active reservations")
    qty = num(ctx.body, "quantity", "Quantity", default=1, minimum=0.01, maximum=10000)
    item_id = ctx.body.get("item_id")
    if item_id:
        item = one(ctx.db, "SELECT * FROM items WHERE id=?", (int(num(ctx.body, "item_id", integer=True)),),
                   "Item not found")
        if not item["active"] or not item["chargeable"]:
            raise ApiError(400, f"{item['name']} cannot be charged to guests")
        unit_price = money(num(ctx.body, "unit_price", "Unit price", default=item["price"], minimum=0))
        description = s(ctx.body, "description", max_len=200) or item["name"]
        category = item["category"]
        _record_movement(ctx.db, ctx.user["id"], item, "sale", -qty, f"Charged to {res['code']}", res["id"])
    else:
        item = None
        description = s(ctx.body, "description", "Description", required=True, max_len=200)
        category = s(ctx.body, "category", default="Service", max_len=60)
        unit_price = money(num(ctx.body, "unit_price", "Unit price", required=True, minimum=-100000, maximum=100000))
    amount = money(qty * unit_price)
    ctx.db.execute(
        "INSERT INTO charges(reservation_id, item_id, description, category, quantity, unit_price, amount, created_by)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (res["id"], item["id"] if item else None, description, category, qty, unit_price, amount, ctx.user["id"]))
    ctx.log("charge_add", f"{res['code']}: {description} x{qty:g} = {amount:.2f}")
    return reservation_detail_data(ctx.db, res["id"])


@route("DELETE", "/reservations/(?P<id>\\d+)/charges/(?P<cid>\\d+)")
def charges_delete(ctx):
    res = load_reservation(ctx.db, ctx.params["id"])
    if res["status"] not in ("booked", "checked_in"):
        raise ApiError(409, "Cannot change the folio of a closed reservation")
    c = one(ctx.db, "SELECT * FROM charges WHERE id=? AND reservation_id=?", (ctx.params["cid"], res["id"]),
            "Charge not found")
    if c["item_id"]:
        item = ctx.db.execute("SELECT * FROM items WHERE id=?", (c["item_id"],)).fetchone()
        if item:
            _record_movement(ctx.db, ctx.user["id"], dict(item), "return", c["quantity"],
                             f"Charge voided on {res['code']}", res["id"])
    ctx.db.execute("DELETE FROM charges WHERE id=?", (c["id"],))
    ctx.log("charge_void", f"{res['code']}: {c['description']} {c['amount']:.2f}")
    return reservation_detail_data(ctx.db, res["id"])


@route("POST", "/reservations/(?P<id>\\d+)/payments")
def payments_add(ctx):
    res = load_reservation(ctx.db, ctx.params["id"])
    if res["status"] == "checked_out":
        raise ApiError(409, "Reservation is closed")
    amount = money(num(ctx.body, "amount", "Amount", required=True, minimum=-1000000, maximum=1000000))
    if amount == 0:
        raise ApiError(400, "Amount cannot be zero")
    method = s(ctx.body, "method", "Method", required=True)
    if method not in PAYMENT_METHODS:
        raise ApiError(400, "Invalid payment method")
    if amount < 0:
        paid = folio(ctx.db, res)["paid"]
        if -amount > paid + 0.004:
            raise ApiError(400, "Refund cannot exceed the amount paid")
    ctx.db.execute("INSERT INTO payments(reservation_id, amount, method, reference, created_by) VALUES (?,?,?,?,?)",
                   (res["id"], amount, method, s(ctx.body, "reference", max_len=120), ctx.user["id"]))
    ctx.log("payment" if amount > 0 else "refund", f"{res['code']}: {amount:.2f} {method}")
    return reservation_detail_data(ctx.db, res["id"])


@route("DELETE", "/reservations/(?P<id>\\d+)/payments/(?P<pid>\\d+)", role="admin")
def payments_delete(ctx):
    res = load_reservation(ctx.db, ctx.params["id"])
    p = one(ctx.db, "SELECT * FROM payments WHERE id=? AND reservation_id=?", (ctx.params["pid"], res["id"]),
            "Payment not found")
    if res["status"] == "checked_out":
        raise ApiError(409, "Reservation is closed")
    ctx.db.execute("DELETE FROM payments WHERE id=?", (p["id"],))
    ctx.log("payment_void", f"{res['code']}: {p['amount']:.2f}")
    return reservation_detail_data(ctx.db, res["id"])


# --------------------------------------------------------------------------- inventory

ITEM_SELECT = (
    "SELECT i.*, s.name AS supplier_name, (i.quantity <= i.reorder_level) AS low_stock,"
    " ROUND(i.quantity * i.cost, 2) AS stock_value FROM items i LEFT JOIN suppliers s ON s.id=i.supplier_id"
)


@route("GET", "/items")
def items_list(ctx):
    where, args = [], []
    if not flag(ctx.query, "include_inactive"):
        where.append("i.active=1")
    if ctx.query.get("category"):
        where.append("i.category=?")
        args.append(ctx.query["category"])
    if flag(ctx.query, "low"):
        where.append("i.quantity <= i.reorder_level")
    if flag(ctx.query, "chargeable"):
        where.append("i.chargeable=1")
    q = (ctx.query.get("q") or "").strip()
    if q:
        where.append("(i.name LIKE ? OR i.sku LIKE ?)")
        args += [f"%{q}%"] * 2
    sql = ITEM_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY i.category, i.name"
    return rows(ctx.db.execute(sql, args))


def _item_fields(ctx):
    supplier_id = ctx.body.get("supplier_id") or None
    if supplier_id:
        supplier_id = num(ctx.body, "supplier_id", integer=True)
        one(ctx.db, "SELECT id FROM suppliers WHERE id=?", (supplier_id,), "Supplier not found")
    return (
        s(ctx.body, "sku", "SKU", required=True, max_len=40).upper(),
        s(ctx.body, "name", "Name", required=True, max_len=120),
        s(ctx.body, "category", "Category", default="General", max_len=60),
        s(ctx.body, "unit", "Unit", default="pcs", max_len=20),
        num(ctx.body, "reorder_level", "Reorder level", default=0, minimum=0),
        money(num(ctx.body, "cost", "Unit cost", default=0, minimum=0)),
        money(num(ctx.body, "price", "Sale price", default=0, minimum=0)),
        flag(ctx.body, "chargeable"),
        supplier_id,
        flag(ctx.body, "active", True),
    )


@route("POST", "/items")
def items_create(ctx):
    f = _item_fields(ctx)
    if ctx.db.execute("SELECT 1 FROM items WHERE sku=?", (f[0],)).fetchone():
        raise ApiError(409, "SKU already exists")
    cur = ctx.db.execute(
        "INSERT INTO items(sku, name, category, unit, reorder_level, cost, price, chargeable, supplier_id, active)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)", f)
    qty = num(ctx.body, "quantity", "Opening quantity", default=0, minimum=0)
    if qty:
        item = one(ctx.db, "SELECT * FROM items WHERE id=?", (cur.lastrowid,))
        _record_movement(ctx.db, ctx.user["id"], item, "receive", qty, "Opening stock", unit_cost=f[5])
    ctx.log("item_create", f"{f[0]} {f[1]}")
    return one(ctx.db, ITEM_SELECT + " WHERE i.id=?", (cur.lastrowid,))


@route("GET", "/items/(?P<id>\\d+)")
def items_get(ctx):
    item = one(ctx.db, ITEM_SELECT + " WHERE i.id=?", (ctx.params["id"],), "Item not found")
    item["movements"] = rows(ctx.db.execute(
        "SELECT m.*, u.full_name AS user_name, r.code AS reservation_code FROM stock_movements m"
        " LEFT JOIN users u ON u.id=m.created_by LEFT JOIN reservations r ON r.id=m.reservation_id"
        " WHERE m.item_id=? ORDER BY m.id DESC LIMIT 200", (item["id"],)))
    return item


@route("PUT", "/items/(?P<id>\\d+)")
def items_update(ctx):
    iid = ctx.params["id"]
    one(ctx.db, "SELECT id FROM items WHERE id=?", (iid,), "Item not found")
    f = _item_fields(ctx)
    if ctx.db.execute("SELECT 1 FROM items WHERE sku=? AND id<>?", (f[0], iid)).fetchone():
        raise ApiError(409, "SKU already exists")
    ctx.db.execute(
        "UPDATE items SET sku=?, name=?, category=?, unit=?, reorder_level=?, cost=?, price=?, chargeable=?,"
        " supplier_id=?, active=? WHERE id=?", f + (iid,))
    ctx.log("item_update", f"{f[0]} {f[1]}")
    return one(ctx.db, ITEM_SELECT + " WHERE i.id=?", (iid,))


@route("DELETE", "/items/(?P<id>\\d+)", role="admin")
def items_delete(ctx):
    iid = ctx.params["id"]
    item = one(ctx.db, "SELECT * FROM items WHERE id=?", (iid,), "Item not found")
    if ctx.db.execute("SELECT 1 FROM charges WHERE item_id=?", (iid,)).fetchone():
        ctx.db.execute("UPDATE items SET active=0 WHERE id=?", (iid,))
        ctx.log("item_deactivate", item["sku"])
        return {"ok": True, "deactivated": True}
    ctx.db.execute("DELETE FROM items WHERE id=?", (iid,))
    ctx.log("item_delete", item["sku"])
    return {"ok": True, "deactivated": False}


@route("POST", "/items/(?P<id>\\d+)/movements")
def items_move(ctx):
    item = one(ctx.db, "SELECT * FROM items WHERE id=?", (ctx.params["id"],), "Item not found")
    kind = s(ctx.body, "kind", "Movement type", required=True)
    reason = s(ctx.body, "reason", max_len=300)
    if kind == "receive":
        qty = num(ctx.body, "quantity", "Quantity", required=True, minimum=0.0001, maximum=1e7)
        unit_cost = num(ctx.body, "unit_cost", "Unit cost", default=None, minimum=0)
        if unit_cost is not None:
            # weighted average cost
            total_qty = item["quantity"] + qty
            avg = (item["quantity"] * item["cost"] + qty * unit_cost) / total_qty if total_qty else unit_cost
            ctx.db.execute("UPDATE items SET cost=? WHERE id=?", (money(avg), item["id"]))
        _record_movement(ctx.db, ctx.user["id"], item, "receive", qty, reason or "Stock received", unit_cost=unit_cost)
    elif kind == "issue":
        qty = num(ctx.body, "quantity", "Quantity", required=True, minimum=0.0001, maximum=1e7)
        _record_movement(ctx.db, ctx.user["id"], item, "issue", -qty, reason or "Issued")
    elif kind == "adjust":
        counted = num(ctx.body, "counted", "Counted quantity", required=True, minimum=0, maximum=1e7)
        change = round(counted - item["quantity"], 4)
        if change == 0:
            raise ApiError(400, "Counted quantity equals current stock; nothing to adjust")
        if not reason:
            raise ApiError(400, "A reason is required for stock adjustments")
        _record_movement(ctx.db, ctx.user["id"], item, "adjust", change, reason)
    else:
        raise ApiError(400, "Movement type must be receive, issue or adjust")
    ctx.log("stock_" + kind, f"{item['sku']}")
    return one(ctx.db, ITEM_SELECT + " WHERE i.id=?", (item["id"],))


@route("GET", "/movements")
def movements_list(ctx):
    where, args = [], []
    if ctx.query.get("item_id"):
        where.append("m.item_id=?")
        args.append(int(num(ctx.query, "item_id", integer=True)))
    if ctx.query.get("kind"):
        where.append("m.kind=?")
        args.append(ctx.query["kind"])
    if ctx.query.get("from"):
        where.append("date(m.created_at) >= ?")
        args.append(parse_date(ctx.query["from"]).isoformat())
    if ctx.query.get("to"):
        where.append("date(m.created_at) <= ?")
        args.append(parse_date(ctx.query["to"]).isoformat())
    sql = ("SELECT m.*, i.sku, i.name AS item_name, i.unit, u.full_name AS user_name, r.code AS reservation_code"
           " FROM stock_movements m JOIN items i ON i.id=m.item_id LEFT JOIN users u ON u.id=m.created_by"
           " LEFT JOIN reservations r ON r.id=m.reservation_id")
    sql += (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY m.id DESC LIMIT 500"
    return rows(ctx.db.execute(sql, args))


@route("GET", "/suppliers")
def suppliers_list(ctx):
    return rows(ctx.db.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM items i WHERE i.supplier_id=s.id AND i.active=1) AS item_count"
        " FROM suppliers s ORDER BY name"))


def _supplier_fields(ctx):
    email = s(ctx.body, "email", "Email", max_len=160)
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ApiError(400, "Email address is invalid")
    return (s(ctx.body, "name", "Name", required=True, max_len=120), s(ctx.body, "contact", max_len=120),
            s(ctx.body, "phone", max_len=40), email)


@route("POST", "/suppliers")
def suppliers_create(ctx):
    f = _supplier_fields(ctx)
    if ctx.db.execute("SELECT 1 FROM suppliers WHERE name=?", (f[0],)).fetchone():
        raise ApiError(409, "Supplier already exists")
    cur = ctx.db.execute("INSERT INTO suppliers(name, contact, phone, email) VALUES (?,?,?,?)", f)
    ctx.log("supplier_create", f[0])
    return one(ctx.db, "SELECT * FROM suppliers WHERE id=?", (cur.lastrowid,))


@route("PUT", "/suppliers/(?P<id>\\d+)")
def suppliers_update(ctx):
    sid = ctx.params["id"]
    one(ctx.db, "SELECT id FROM suppliers WHERE id=?", (sid,), "Supplier not found")
    f = _supplier_fields(ctx)
    if ctx.db.execute("SELECT 1 FROM suppliers WHERE name=? AND id<>?", (f[0], sid)).fetchone():
        raise ApiError(409, "Supplier already exists")
    ctx.db.execute("UPDATE suppliers SET name=?, contact=?, phone=?, email=? WHERE id=?", f + (sid,))
    ctx.log("supplier_update", f[0])
    return one(ctx.db, "SELECT * FROM suppliers WHERE id=?", (sid,))


@route("DELETE", "/suppliers/(?P<id>\\d+)", role="admin")
def suppliers_delete(ctx):
    sid = ctx.params["id"]
    sup = one(ctx.db, "SELECT * FROM suppliers WHERE id=?", (sid,), "Supplier not found")
    ctx.db.execute("DELETE FROM suppliers WHERE id=?", (sid,))
    ctx.log("supplier_delete", sup["name"])
    return {"ok": True}


# --------------------------------------------------------------------------- dashboard & reports

@route("GET", "/dashboard")
def dashboard(ctx):
    db = ctx.db
    t = today().isoformat()
    rooms = rooms_list(ctx)
    total = len(rooms)
    occupied = sum(1 for r in rooms if r["occupied"])
    maintenance = sum(1 for r in rooms if r["status"] == "maintenance")
    dirty = sum(1 for r in rooms if r["status"] == "dirty")
    vacant_clean = sum(1 for r in rooms if not r["occupied"] and r["status"] == "clean")
    sellable = total - maintenance
    arrivals = rows(db.execute(RES_SELECT + " WHERE r.status='booked' AND r.check_in<=? AND r.check_out>?"
                               " ORDER BY r.check_in, rm.number", (t, t)))
    departures = rows(db.execute(RES_SELECT + " WHERE r.status='checked_in' AND r.check_out<=? ORDER BY r.check_out, rm.number", (t,)))
    for r in departures:
        r["balance"] = folio(db, r)["balance"]
    in_house = db.execute("SELECT COALESCE(SUM(adults+children),0) FROM reservations WHERE status='checked_in'").fetchone()[0]
    month_start = today().replace(day=1).isoformat()
    pay_today = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE date(created_at)=?", (t,)).fetchone()[0]
    pay_month = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE date(created_at)>=?", (month_start,)).fetchone()[0]
    low_stock = rows(db.execute(ITEM_SELECT + " WHERE i.active=1 AND i.quantity <= i.reorder_level ORDER BY i.quantity / NULLIF(i.reorder_level,0)"))
    upcoming = rows(db.execute(RES_SELECT + " WHERE r.status='booked' AND r.check_in>? ORDER BY r.check_in LIMIT 8", (t,)))
    recent = rows(db.execute("SELECT a.*, u.full_name AS user_name FROM activity a LEFT JOIN users u ON u.id=a.user_id"
                             " ORDER BY a.id DESC LIMIT 10"))
    return {
        "date": t,
        "rooms": {"total": total, "occupied": occupied, "vacant_clean": vacant_clean, "dirty": dirty,
                  "maintenance": maintenance, "occupancy": round(occupied * 100 / sellable, 1) if sellable else 0},
        "in_house_guests": in_house,
        "arrivals": arrivals,
        "departures": departures,
        "upcoming": upcoming,
        "revenue_today": money(pay_today),
        "revenue_month": money(pay_month),
        "low_stock": low_stock,
        "recent_activity": recent,
    }


def _range(ctx, default_days=30):
    end = parse_date(ctx.query.get("to") or today().isoformat(), "To")
    start = parse_date(ctx.query.get("from") or (end - dt.timedelta(days=default_days - 1)).isoformat(), "From")
    if start > end:
        raise ApiError(400, "'From' must be before 'To'")
    if (end - start).days > 366:
        raise ApiError(400, "Range cannot exceed one year")
    return start, end


@route("GET", "/reports/summary")
def report_summary(ctx):
    db = ctx.db
    start, end = _range(ctx)
    room_count = db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
    stays = rows(db.execute(
        "SELECT check_in, check_out, rate FROM reservations WHERE status IN ('booked','checked_in','checked_out')"
        " AND check_in <= ? AND check_out > ?", (end.isoformat(), start.isoformat())))
    daily = []
    d = start
    while d <= end:
        ds = d.isoformat()
        occ = [x for x in stays if x["check_in"] <= ds < x["check_out"]]
        rev = money(sum(x["rate"] for x in occ))
        daily.append({
            "date": ds, "occupied": len(occ),
            "occupancy": round(len(occ) * 100 / room_count, 1) if room_count else 0,
            "room_revenue": rev,
            "adr": money(rev / len(occ)) if occ else 0,
            "revpar": money(rev / room_count) if room_count else 0,
        })
        d += dt.timedelta(days=1)
    days = len(daily)
    room_nights = sum(x["occupied"] for x in daily)
    room_revenue = money(sum(x["room_revenue"] for x in daily))
    extras = rows(db.execute(
        "SELECT category, ROUND(SUM(amount),2) AS amount, COUNT(*) AS count FROM charges"
        " WHERE date(created_at) BETWEEN ? AND ? GROUP BY category ORDER BY amount DESC",
        (start.isoformat(), end.isoformat())))
    payments = rows(db.execute(
        "SELECT method, ROUND(SUM(amount),2) AS amount, COUNT(*) AS count FROM payments"
        " WHERE date(created_at) BETWEEN ? AND ? GROUP BY method ORDER BY amount DESC",
        (start.isoformat(), end.isoformat())))
    sources = rows(db.execute(
        "SELECT source, COUNT(*) AS count FROM reservations WHERE status<>'cancelled' AND check_in BETWEEN ? AND ?"
        " GROUP BY source ORDER BY count DESC", (start.isoformat(), end.isoformat())))
    status_counts = rows(db.execute(
        "SELECT status, COUNT(*) AS count FROM reservations WHERE check_in BETWEEN ? AND ? GROUP BY status",
        (start.isoformat(), end.isoformat())))
    top_items = rows(db.execute(
        "SELECT i.sku, i.name, SUM(-m.change) AS qty, ROUND(SUM(-m.change * i.price),2) AS revenue"
        " FROM stock_movements m JOIN items i ON i.id=m.item_id WHERE m.kind IN ('sale','return')"
        " AND date(m.created_at) BETWEEN ? AND ? GROUP BY i.id HAVING qty > 0 ORDER BY revenue DESC LIMIT 10",
        (start.isoformat(), end.isoformat())))
    inventory = rows(db.execute(
        "SELECT category, COUNT(*) AS items, ROUND(SUM(quantity*cost),2) AS value,"
        " SUM(quantity <= reorder_level) AS low FROM items WHERE active=1 GROUP BY category ORDER BY value DESC"))
    usage = rows(db.execute(
        "SELECT i.sku, i.name, i.unit, SUM(-m.change) AS qty, ROUND(SUM(-m.change*i.cost),2) AS cost"
        " FROM stock_movements m JOIN items i ON i.id=m.item_id WHERE m.kind='issue'"
        " AND date(m.created_at) BETWEEN ? AND ? GROUP BY i.id ORDER BY cost DESC LIMIT 10",
        (start.isoformat(), end.isoformat())))
    return {
        "from": start.isoformat(), "to": end.isoformat(), "room_count": room_count,
        "totals": {
            "room_nights": room_nights,
            "occupancy": round(room_nights * 100 / (room_count * days), 1) if room_count and days else 0,
            "room_revenue": room_revenue,
            "adr": money(room_revenue / room_nights) if room_nights else 0,
            "revpar": money(room_revenue / (room_count * days)) if room_count and days else 0,
            "extras_revenue": money(sum(e["amount"] for e in extras)),
            "payments": money(sum(p["amount"] for p in payments)),
            "inventory_value": money(sum(i["value"] or 0 for i in inventory)),
        },
        "daily": daily, "extras": extras, "payments": payments, "sources": sources,
        "statuses": status_counts, "top_items": top_items, "inventory": inventory, "usage": usage,
    }


def _csv(name, header, data):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in data:
        w.writerow(["" if r.get(h) is None else _csv_safe(r.get(h)) for h in header])
    return Raw(buf.getvalue(), "text/csv; charset=utf-8", f"{name}-{today().isoformat()}.csv")


def _csv_safe(v):
    # Neutralise spreadsheet formula injection.
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") and not re.fullmatch(r"-?\d+(\.\d+)?", v):
        return "'" + v
    return v


@route("GET", "/export/(?P<name>[a-z_]+)\\.csv")
def export(ctx):
    name = ctx.params["name"]
    if name == "reservations":
        data = reservations_list(ctx)
        header = ["code", "guest_name", "guest_email", "room_number", "room_type", "check_in", "check_out", "nights",
                  "adults", "children", "rate", "status", "source", "total", "balance", "created_at"]
    elif name == "guests":
        data = guests_list(ctx)
        header = ["id", "first_name", "last_name", "email", "phone", "address", "id_number", "vip", "stays", "last_stay"]
    elif name == "items":
        data = items_list(ctx)
        header = ["sku", "name", "category", "unit", "quantity", "reorder_level", "cost", "price", "stock_value",
                  "supplier_name", "chargeable"]
    elif name == "movements":
        data = movements_list(ctx)
        header = ["created_at", "sku", "item_name", "kind", "change", "balance_after", "unit_cost", "reason",
                  "reservation_code", "user_name"]
    elif name == "daily_report":
        data = report_summary(ctx)["daily"]
        header = ["date", "occupied", "occupancy", "room_revenue", "adr", "revpar"]
    else:
        raise ApiError(404, "Unknown export")
    return _csv(name, header, data)
