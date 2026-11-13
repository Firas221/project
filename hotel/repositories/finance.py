"""Commercial & finance: companies (city ledger), pricing, cashier shifts, invoices, night audit."""
from .base import BaseRepository, QueryBuilder, page_of


class CompanyRepository(BaseRepository):
    table = "companies"
    columns = ("name", "tax_number", "contact", "email", "phone", "address", "discount_pct", "credit_limit", "active")
    select_sql = ("SELECT t.*, ROUND(COALESCE((SELECT SUM(amount) FROM ledger_entries l WHERE l.company_id = t.id), 0), 2)"
                  " AS balance FROM companies t")
    default_order = "t.name"
    entity_label = "Company"


class LedgerRepository(BaseRepository):
    """Accounts receivable. Positive amounts are owed by the company, payments are negative."""
    table = "ledger_entries"
    columns = ("company_id", "reservation_id", "kind", "amount", "reference", "created_by")
    select_sql = ("SELECT t.*, r.code AS reservation_code, u.full_name AS created_by_name FROM ledger_entries t"
                  " LEFT JOIN reservations r ON r.id = t.reservation_id LEFT JOIN users u ON u.id = t.created_by")
    default_order = "t.id DESC"

    def balance(self, company_id: int) -> float:
        return self.scalar("SELECT COALESCE(SUM(amount),0) FROM ledger_entries WHERE company_id=?", (company_id,), 0)


class SeasonRepository(BaseRepository):
    table = "rate_seasons"
    columns = ("name", "room_type_id", "start_date", "end_date", "adjust_pct", "min_nights", "active")
    select_sql = ("SELECT t.*, rt.name AS room_type_name FROM rate_seasons t"
                  " LEFT JOIN room_types rt ON rt.id = t.room_type_id")
    default_order = "t.start_date"
    entity_label = "Season"

    def covering(self, day: str, room_type_id: int) -> list:
        return self.fetch_all(
            "SELECT * FROM rate_seasons WHERE active=1 AND start_date <= ? AND end_date >= ?"
            " AND (room_type_id IS NULL OR room_type_id = ?) ORDER BY room_type_id IS NULL", (day, day, room_type_id))


class RatePlanRepository(BaseRepository):
    table = "rate_plans"
    columns = ("name", "name_ar", "description", "meal_plan", "adjust_pct", "per_adult", "per_child", "refundable",
               "online", "active", "position")
    default_order = "t.position, t.id"
    entity_label = "Rate plan"

    def offered(self, online: bool) -> list:
        sql = self._select() + " WHERE t.active = 1" + (" AND t.online = 1" if online else "")
        return self.fetch_all(f"{sql} ORDER BY {self.default_order}")


class VenueRepository(BaseRepository):
    table = "venues"
    columns = ("name", "capacity", "hourly_rate", "day_rate", "description", "active")
    default_order = "t.name"
    entity_label = "Venue"


class EventRepository(BaseRepository):
    table = "events"
    columns = ("code", "venue_id", "title", "organizer_name", "organizer_phone", "organizer_email", "company_id", "event_date",
               "start_time", "end_time", "attendees", "setup", "status", "venue_charge", "catering_per_person", "extras",
               "extras_note", "notes", "invoice_number", "subtotal", "service_charge", "vat", "city_tax", "total", "completed_at",
               "created_by")
    select_sql = ("SELECT t.*, v.name AS venue_name, v.capacity AS venue_capacity, c.name AS company_name,"
                  " ROUND(COALESCE((SELECT SUM(amount) FROM event_payments p WHERE p.event_id = t.id), 0), 2) AS paid"
                  " FROM events t JOIN venues v ON v.id = t.venue_id LEFT JOIN companies c ON c.id = t.company_id")
    default_order = "t.event_date, t.start_time"
    entity_label = "Event"

    def search(self, status=None, date_from=None, date_to=None, venue_id=None) -> list:
        qb = QueryBuilder(self.select_sql)
        if status == "active":
            qb.add("t.status IN ('inquiry', 'confirmed')")
        else:
            qb.add_if(status, "t.status = ?", status)
        qb.add_if(date_from, "t.event_date >= ?", date_from)
        qb.add_if(date_to, "t.event_date <= ?", date_to)
        qb.add_if(venue_id, "t.venue_id = ?", venue_id)
        return self.fetch_all(qb.sql(self.default_order, 1000), qb.args)

    def clash(self, venue_id: int, day: str, start: str, end: str, exclude_id: int = None):
        """The code of a confirmed event that uses the venue at an overlapping time on that day, if any."""
        sql = ("SELECT code FROM events WHERE venue_id = ? AND event_date = ? AND status = 'confirmed'"
               " AND start_time < ? AND end_time > ?")
        args = [venue_id, day, end, start]
        if exclude_id:
            sql += " AND id <> ?"
            args.append(exclude_id)
        return self.scalar(sql, args)

    def next_number(self, year: int) -> str:
        prefix = f"EVT-{year}-"
        last = self.scalar("SELECT invoice_number FROM events WHERE invoice_number LIKE ? ORDER BY invoice_number DESC LIMIT 1",
                           (prefix + "%",))
        return f"{prefix}{(int(last.rsplit('-', 1)[1]) + 1 if last else 1):06d}"

    def payments(self, event_id: int) -> list:
        return self.fetch_all("SELECT p.*, u.full_name AS created_by_name FROM event_payments p LEFT JOIN users u ON u.id = p.created_by"
                              " WHERE p.event_id = ? ORDER BY p.id", (event_id,))

    def add_payment(self, event_id, amount, method, reference, shift_id, created_by) -> None:
        self.execute("INSERT INTO event_payments(event_id, amount, method, reference, shift_id, created_by) VALUES (?,?,?,?,?,?)",
                     (event_id, amount, method, reference, shift_id, created_by))

    def completed_between(self, start: str, end: str) -> list:
        return self.fetch_all(self.select_sql + " WHERE t.status = 'completed' AND date(t.completed_at) BETWEEN ? AND ?"
                              " ORDER BY t.id DESC", (start, end))


class PromoRepository(BaseRepository):
    table = "promo_codes"
    columns = ("code", "description", "discount_pct", "valid_from", "valid_to", "max_uses", "used_count", "online_only",
               "active")
    default_order = "t.valid_to DESC"
    entity_label = "Promo code"

    def by_code(self, code: str):
        return self.fetch_one("SELECT * FROM promo_codes WHERE code = ?", (code,))

    def increment_use(self, promo_id: int) -> None:
        self.execute("UPDATE promo_codes SET used_count = used_count + 1 WHERE id=?", (promo_id,))


class ShiftRepository(BaseRepository):
    table = "cashier_shifts"
    columns = ("user_id", "closed_at", "opening_float", "expected_cash", "counted_cash", "variance", "notes")
    select_sql = (
        "SELECT t.*, u.full_name AS user_name,"
        " ROUND(COALESCE((SELECT SUM(amount) FROM payments p WHERE p.shift_id = t.id AND p.method='cash' AND p.currency=''),0),2) AS cash_taken,"
        " ROUND(COALESCE((SELECT SUM(foreign_amount) FROM payments p WHERE p.shift_id = t.id AND p.method='cash' AND p.currency<>''),0),2) AS foreign_cash_taken,"
        " (SELECT MAX(currency) FROM payments p WHERE p.shift_id = t.id AND p.method='cash' AND p.currency<>'') AS foreign_currency,"
        " ROUND(COALESCE((SELECT SUM(amount) FROM payments p WHERE p.shift_id = t.id),0),2) AS total_taken,"
        " (SELECT COUNT(*) FROM payments p WHERE p.shift_id = t.id) AS payment_count,"
        " ROUND(COALESCE((SELECT SUM(total) FROM restaurant_checks k WHERE k.shift_id = t.id AND k.status='paid' AND k.paid_method='cash'),0),2) AS restaurant_cash,"
        " ROUND(COALESCE((SELECT SUM(total) FROM restaurant_checks k WHERE k.shift_id = t.id AND k.status='paid'),0),2) AS restaurant_taken,"
        " ROUND(COALESCE((SELECT SUM(amount) FROM event_payments e WHERE e.shift_id = t.id AND e.method='cash'),0),2) AS events_cash"
        " FROM cashier_shifts t JOIN users u ON u.id = t.user_id"
    )
    default_order = "t.id DESC"
    entity_label = "Shift"

    def open_for(self, user_id: int):
        return self.fetch_one(self.select_sql + " WHERE t.user_id=? AND t.closed_at IS NULL", (user_id,))

    def recent(self, limit=100) -> list:
        return self.fetch_all(self.select_sql + " ORDER BY t.id DESC LIMIT ?", (limit,))

    def payments(self, shift_id: int) -> list:
        return self.fetch_all(
            "SELECT p.*, r.code AS reservation_code FROM payments p JOIN reservations r ON r.id=p.reservation_id"
            " WHERE p.shift_id=? ORDER BY p.id", (shift_id,))


class InvoiceRepository(BaseRepository):
    table = "invoices"
    columns = ("number", "reservation_id", "bill_to", "bill_to_tax_no", "subtotal", "service_charge", "vat", "city_tax",
               "total", "snapshot", "issued_by")
    select_sql = ("SELECT t.*, r.code AS reservation_code, u.full_name AS issued_by_name FROM invoices t"
                  " JOIN reservations r ON r.id = t.reservation_id LEFT JOIN users u ON u.id = t.issued_by")
    default_order = "t.id DESC"
    entity_label = "Invoice"

    def next_number(self, year: int) -> str:
        prefix = f"INV-{year}-"
        last = self.scalar("SELECT number FROM invoices WHERE number LIKE ? ORDER BY id DESC LIMIT 1", (prefix + "%",))
        seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
        return f"{prefix}{seq:06d}"

    def search(self, date_from=None, date_to=None, limit=500, page=None, per_page=None):
        qb = QueryBuilder(self.select_sql)
        qb.add_if(date_from, "date(t.issued_at) >= ?", date_from)
        qb.add_if(date_to, "date(t.issued_at) <= ?", date_to)
        if page is not None:
            return page_of(self, qb, "t.id DESC", page, per_page)
        return self.fetch_all(qb.sql("t.id DESC", limit), qb.args)


class AuditDayRepository(BaseRepository):
    table = "audit_days"
    columns = ("business_date", "rooms_total", "rooms_sold", "room_revenue", "other_revenue", "payments", "arrivals",
               "departures", "no_shows", "notes", "closed_by")
    select_sql = "SELECT t.*, u.full_name AS closed_by_name FROM audit_days t LEFT JOIN users u ON u.id = t.closed_by"
    default_order = "t.business_date DESC"

    def get_day(self, business_date: str):
        return self.fetch_one(self.select_sql + " WHERE t.business_date = ?", (business_date,))

    def insert_day(self, **data) -> None:
        self._check_columns(data)
        cols = ", ".join(data)
        self.execute(f"INSERT INTO audit_days ({cols}) VALUES ({', '.join('?' for _ in data)})", data.values())

    def recent(self, limit=60) -> list:
        return self.fetch_all(self.select_sql + " ORDER BY t.business_date DESC LIMIT ?", (limit,))


class PasswordResetRepository(BaseRepository):
    table = "password_resets"
    columns = ("user_id", "token_hash", "expires_at", "used_at")


class EmailVerificationRepository(BaseRepository):
    table = "email_verifications"
    columns = ("user_id", "token_hash", "expires_at", "used_at")


class ChallengeRepository(BaseRepository):
    """Short-lived second-factor login challenges."""
    table = "login_challenges"
    columns = ("user_id", "token_hash", "attempts", "expires_at")


class OutboxRepository(BaseRepository):
    table = "email_outbox"
    columns = ("to_address", "subject", "body", "status", "attempts", "error", "sent_at")
    default_order = "t.id DESC"

    def queued(self, limit=20) -> list:
        return self.fetch_all("SELECT * FROM email_outbox WHERE status='queued' AND attempts < 5 ORDER BY id LIMIT ?",
                              (limit,))

    def recent(self, limit=200) -> list:
        return self.fetch_all("SELECT * FROM email_outbox ORDER BY id DESC LIMIT ?", (limit,))
