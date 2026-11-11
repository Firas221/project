"""Guest profiles."""
from .base import BaseRepository, QueryBuilder, page_of


class GuestDocumentRepository(BaseRepository):
    """Scans of ID documents. The image bytes are only read when one document is opened."""
    table = "guest_documents"
    columns = ("guest_id", "kind", "content_type", "data", "uploaded_by")
    select_sql = ("SELECT t.id, t.guest_id, t.kind, t.content_type, length(t.data) AS size, t.created_at,"
                  " u.full_name AS uploaded_by_name FROM guest_documents t LEFT JOIN users u ON u.id = t.uploaded_by")
    default_order = "t.id"
    entity_label = "Document"

    def for_guest(self, guest_id: int) -> list:
        return self.fetch_all(self.select_sql + " WHERE t.guest_id = ? ORDER BY t.id", (guest_id,))

    def content(self, doc_id: int):
        row = self.conn.execute("SELECT guest_id, content_type, data FROM guest_documents WHERE id = ?", (doc_id,)).fetchone()
        return (row["guest_id"], row["content_type"], bytes(row["data"])) if row else None


class GuestRepository(BaseRepository):
    table = "guests"
    columns = ("first_name", "last_name", "email", "phone", "address", "nationality", "id_type", "id_number",
               "date_of_birth", "gender", "vip", "notes", "marketing_consent", "privacy_accepted_at", "anonymized_at", "language")
    select_sql = (
        "SELECT t.*, (SELECT COUNT(*) FROM reservations r WHERE r.guest_id = t.id AND r.status IN ('checked_in','checked_out')) AS stays,"
        " (SELECT MAX(r.check_in) FROM reservations r WHERE r.guest_id = t.id) AS last_stay,"
        " (SELECT u.id FROM users u WHERE u.guest_id = t.id) AS user_id"
        " FROM guests t"
    )
    default_order = "t.last_name, t.first_name"
    entity_label = "Guest"

    def search(self, q: str = None, limit: int = 500, page=None, per_page=None):
        qb = QueryBuilder(self.select_sql)
        if q:
            like = f"%{q}%"
            qb.add("(t.first_name || ' ' || t.last_name LIKE ? OR t.email LIKE ? OR t.phone LIKE ? OR t.id_number LIKE ?)",
                   like, like, like, like)
        if page is not None:
            return page_of(self, qb, self.default_order, page, per_page)
        return self.fetch_all(qb.sql(self.default_order, limit), qb.args)
