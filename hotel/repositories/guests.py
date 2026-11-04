"""Guest profiles."""
from .base import BaseRepository, QueryBuilder


class GuestRepository(BaseRepository):
    table = "guests"
    columns = ("first_name", "last_name", "email", "phone", "address", "nationality", "id_number", "vip", "notes")
    select_sql = (
        "SELECT t.*, (SELECT COUNT(*) FROM reservations r WHERE r.guest_id = t.id AND r.status IN ('checked_in','checked_out')) AS stays,"
        " (SELECT MAX(r.check_in) FROM reservations r WHERE r.guest_id = t.id) AS last_stay,"
        " (SELECT u.id FROM users u WHERE u.guest_id = t.id) AS user_id"
        " FROM guests t"
    )
    default_order = "t.last_name, t.first_name"
    entity_label = "Guest"

    def search(self, q: str = None, limit: int = 500) -> list:
        qb = QueryBuilder(self.select_sql)
        if q:
            like = f"%{q}%"
            qb.add("(t.first_name || ' ' || t.last_name LIKE ? OR t.email LIKE ? OR t.phone LIKE ? OR t.id_number LIKE ?)",
                   like, like, like, like)
        return self.fetch_all(qb.sql(self.default_order, limit), qb.args)
