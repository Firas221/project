"""Reservations and folio lines (charges, payments)."""
from .base import BaseRepository, QueryBuilder, page_of

ACTIVE = ("booked", "checked_in")


class WaitlistRepository(BaseRepository):
    table = "waitlist"
    columns = ("guest_id", "name", "phone", "email", "room_type_id", "check_in", "check_out", "adults", "children", "notes",
               "status", "reservation_id", "source", "alerted_at", "created_by")
    select_sql = ("SELECT t.*, rt.name AS room_type, r.code AS reservation_code FROM waitlist t"
                  " LEFT JOIN room_types rt ON rt.id = t.room_type_id LEFT JOIN reservations r ON r.id = t.reservation_id")
    default_order = "t.check_in, t.id"
    entity_label = "Waitlist entry"

    def search(self, status: str = "waiting", guest_id: int = None) -> list:
        qb = QueryBuilder(self.select_sql)
        qb.add_if(status, "t.status = ?", status)
        qb.add_if(guest_id, "t.guest_id = ?", guest_id)
        return self.fetch_all(qb.sql(self.default_order, 500), qb.args)

    def waiting_between(self, start: str, end: str) -> list:
        """Entries still waiting whose dates overlap [start, end)."""
        return self.fetch_all(self.select_sql + " WHERE t.status = 'waiting' AND t.check_in < ? AND t.check_out > ?"
                              " ORDER BY t.id", (end, start))


class StopSellRepository(BaseRepository):
    table = "stop_sells"
    columns = ("room_type_id", "start_date", "end_date", "reason", "created_by")
    select_sql = "SELECT t.*, rt.name AS room_type FROM stop_sells t LEFT JOIN room_types rt ON rt.id = t.room_type_id"
    default_order = "t.start_date, t.id"
    entity_label = "Stop-sell"

    def blocked_types(self, check_in: str, check_out: str) -> set:
        """Room types closed to online sale on any night of the stay. None in the set means every type."""
        rows = self.fetch_all("SELECT room_type_id FROM stop_sells WHERE start_date < ? AND end_date >= ?", (check_out, check_in))
        return {r["room_type_id"] for r in rows}


class ReservationRepository(BaseRepository):
    table = "reservations"
    columns = ("code", "guest_id", "room_id", "check_in", "check_out", "adults", "children", "rate", "status", "source",
               "special_requests", "notes", "created_by", "checked_in_at", "checked_out_at", "cancelled_at", "company_id",
               "bill_to_company", "group_code", "group_name", "promo_code", "rate_note", "rate_plan_id", "rate_plan_name",
               "meal_plan", "refundable", "reminder_sent_at", "infants", "extra_beds")
    select_sql = (
        "SELECT t.*, g.first_name || ' ' || g.last_name AS guest_name, g.email AS guest_email, g.phone AS guest_phone,"
        " g.vip AS guest_vip, rm.number AS room_number, rt.name AS room_type, rt.id AS room_type_id,"
        " CAST(julianday(t.check_out) - julianday(t.check_in) AS INTEGER) AS nights, c.name AS company_name"
        " FROM reservations t JOIN guests g ON g.id = t.guest_id JOIN rooms rm ON rm.id = t.room_id"
        " JOIN room_types rt ON rt.id = rm.type_id LEFT JOIN companies c ON c.id = t.company_id"
    )
    default_order = "t.check_in DESC, t.id DESC"
    entity_label = "Reservation"

    def conflict(self, room_id: int, check_in: str, check_out: str, exclude_id: int = None):
        """Returns the code of an overlapping active reservation, if any. Ranges are [check_in, check_out)."""
        sql = ("SELECT code FROM reservations WHERE room_id=? AND status IN ('booked','checked_in')"
               " AND check_in < ? AND check_out > ?")
        args = [room_id, check_out, check_in]
        if exclude_id:
            sql += " AND id <> ?"
            args.append(exclude_id)
        return self.scalar(sql, args)

    def occupant(self, room_id: int):
        return self.fetch_one("SELECT * FROM reservations WHERE room_id=? AND status='checked_in'", (room_id,))

    def search(self, status=None, q=None, date_from=None, date_to=None, guest_id=None, limit=1000, page=None,
               per_page=None):
        qb = QueryBuilder(self.select_sql)
        if status == "active":
            qb.add("t.status IN ('booked','checked_in')")
        else:
            qb.add_if(status, "t.status = ?", status)
        if q:
            like = f"%{q}%"
            qb.add("(t.code LIKE ? OR g.first_name || ' ' || g.last_name LIKE ? OR rm.number LIKE ? OR g.email LIKE ?)",
                   like, like, like, like)
        qb.add_if(date_from, "t.check_out > ?", date_from)
        qb.add_if(date_to, "t.check_in <= ?", date_to)
        qb.add_if(guest_id, "t.guest_id = ?", guest_id)
        if page is not None:
            return page_of(self, qb, self.default_order, page, per_page)
        return self.fetch_all(qb.sql(self.default_order, limit), qb.args)

    def due_for_reminder(self, first_day: str, last_day: str) -> list:
        """Booked arrivals in the window whose guest has an e-mail address and has not been reminded yet."""
        return self.fetch_all(self.select_sql + " WHERE t.status='booked' AND t.reminder_sent_at IS NULL"
                              " AND t.check_in BETWEEN ? AND ? AND g.email <> '' AND g.anonymized_at IS NULL"
                              " ORDER BY t.check_in LIMIT 200", (first_day, last_day))

    def arrivals(self, day: str) -> list:
        return self.fetch_all(self.select_sql + " WHERE t.status='booked' AND t.check_in <= ? AND t.check_out > ?"
                              " ORDER BY t.check_in, rm.number", (day, day))

    def departures(self, day: str) -> list:
        return self.fetch_all(self.select_sql + " WHERE t.status='checked_in' AND t.check_out <= ? ORDER BY t.check_out, rm.number",
                              (day,))

    def in_house(self) -> list:
        return self.fetch_all(self.select_sql + " WHERE t.status='checked_in' ORDER BY rm.number")

    def upcoming(self, after: str, limit: int = 8) -> list:
        return self.fetch_all(self.select_sql + " WHERE t.status='booked' AND t.check_in > ? ORDER BY t.check_in LIMIT ?",
                              (after, limit))

    def overlapping(self, start: str, end: str, statuses=("booked", "checked_in", "checked_out")) -> list:
        marks = ",".join("?" for _ in statuses)
        return self.fetch_all(self.select_sql + f" WHERE t.status IN ({marks}) AND t.check_in < ? AND t.check_out > ?",
                              (*statuses, end, start))

    def active_count_for_guest(self, guest_id: int) -> int:
        return self.scalar("SELECT COUNT(*) FROM reservations WHERE guest_id=? AND status IN ('booked','checked_in')",
                           (guest_id,), 0)

    def in_house_guests_count(self) -> int:
        return self.scalar("SELECT COALESCE(SUM(adults+children),0) FROM reservations WHERE status='checked_in'", (), 0)


    def group_members(self, group_code: str) -> list:
        return self.fetch_all(self.select_sql + " WHERE t.group_code = ? ORDER BY rm.number", (group_code,))


class ChargeRepository(BaseRepository):
    table = "charges"
    columns = ("reservation_id", "item_id", "order_id", "description", "category", "quantity", "unit_price", "amount",
               "created_by")
    select_sql = ("SELECT t.*, u.full_name AS created_by_name FROM charges t LEFT JOIN users u ON u.id = t.created_by")
    default_order = "t.created_at, t.id"
    entity_label = "Charge"

    def for_reservation(self, reservation_id: int) -> list:
        return self.find_by(reservation_id=reservation_id)

    def by_category(self, date_from: str, date_to: str) -> list:
        return self.fetch_all(
            "SELECT category, ROUND(SUM(amount),2) AS amount, COUNT(*) AS count FROM charges"
            " WHERE date(created_at) BETWEEN ? AND ? GROUP BY category ORDER BY amount DESC", (date_from, date_to))


class PaymentRepository(BaseRepository):
    table = "payments"
    columns = ("reservation_id", "amount", "method", "reference", "created_by", "shift_id")
    select_sql = ("SELECT t.*, u.full_name AS created_by_name FROM payments t LEFT JOIN users u ON u.id = t.created_by")
    default_order = "t.created_at, t.id"
    entity_label = "Payment"

    def for_reservation(self, reservation_id: int) -> list:
        return self.find_by(reservation_id=reservation_id)

    def total_between(self, date_from: str, date_to: str) -> float:
        return self.scalar("SELECT COALESCE(SUM(amount),0) FROM payments WHERE date(created_at) BETWEEN ? AND ?",
                           (date_from, date_to), 0)

    def by_method(self, date_from: str, date_to: str) -> list:
        return self.fetch_all(
            "SELECT method, ROUND(SUM(amount),2) AS amount, COUNT(*) AS count FROM payments"
            " WHERE date(created_at) BETWEEN ? AND ? GROUP BY method ORDER BY amount DESC", (date_from, date_to))
