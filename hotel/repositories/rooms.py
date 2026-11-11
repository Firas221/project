"""Room types and rooms."""
from ..core.clock import today_iso
from .base import BaseRepository, QueryBuilder


class RoomTypeRepository(BaseRepository):
    table = "room_types"
    columns = ("name", "description", "base_rate", "capacity", "bed_type", "size_sqm", "amenities", "active", "max_extra_beds",
               "extra_bed_rate")
    select_sql = ("SELECT t.*, (SELECT COUNT(*) FROM rooms r WHERE r.type_id = t.id) AS room_count"
                  " FROM room_types t")
    default_order = "t.base_rate, t.name"
    entity_label = "Room type"


class RoomPhotoRepository(BaseRepository):
    """Photos of a room type. The image bytes are only read when a photo is served."""
    table = "room_photos"
    columns = ("room_type_id", "content_type", "data", "position")
    select_sql = "SELECT t.id, t.room_type_id, t.content_type, t.position, length(t.data) AS size, t.created_at FROM room_photos t"
    default_order = "t.position, t.id"
    entity_label = "Photo"

    def ids_by_type(self) -> dict:
        out = {}
        for r in self.fetch_all("SELECT id, room_type_id FROM room_photos ORDER BY position, id"):
            out.setdefault(r["room_type_id"], []).append(r["id"])
        return out

    def content(self, photo_id: int):
        row = self.conn.execute("SELECT content_type, data FROM room_photos WHERE id = ?", (photo_id,)).fetchone()
        return (row["content_type"], bytes(row["data"])) if row else None

    def first_position(self, room_type_id: int) -> int:
        return self.scalar("SELECT MIN(position) FROM room_photos WHERE room_type_id = ?", (room_type_id,), 0)

    def last_position(self, room_type_id: int) -> int:
        return self.scalar("SELECT MAX(position) FROM room_photos WHERE room_type_id = ?", (room_type_id,), 0)


class RoomRepository(BaseRepository):
    table = "rooms"
    columns = ("number", "floor", "type_id", "status", "notes")
    default_order = "t.floor, t.number"
    entity_label = "Room"

    @property
    def select_sql(self):
        # Occupancy is derived from reservations, never stored, so it cannot drift.
        return """
        SELECT t.*, rt.name AS type_name, rt.base_rate, rt.capacity, rt.max_extra_beds, rt.extra_bed_rate,
          cur.id AS current_reservation_id, cur.check_out AS current_check_out,
          cg.first_name || ' ' || cg.last_name AS current_guest,
          (SELECT a.id FROM reservations a WHERE a.room_id = t.id AND a.status = 'booked' AND a.check_in <= '%s'
             ORDER BY a.check_in LIMIT 1) AS arriving_reservation_id,
          (SELECT COUNT(*) FROM housekeeping_tasks h WHERE h.room_id = t.id AND h.status IN ('open','in_progress')) AS open_tasks
        FROM rooms t
        JOIN room_types rt ON rt.id = t.type_id
        LEFT JOIN reservations cur ON cur.room_id = t.id AND cur.status = 'checked_in'
        LEFT JOIN guests cg ON cg.id = cur.guest_id
        """ % today_iso()

    def search(self, status: str = None, floor: int = None, type_id: int = None) -> list:
        qb = QueryBuilder(self.select_sql)
        qb.add_if(status, "t.status = ?", status)
        qb.add_if(floor, "t.floor = ?", floor)
        qb.add_if(type_id, "t.type_id = ?", type_id)
        rows = self.fetch_all(qb.sql(self.default_order), qb.args)
        for r in rows:
            r["occupied"] = bool(r["current_reservation_id"])
        return rows

    def get(self, id_):
        r = super().get(id_)
        if r:
            r["occupied"] = bool(r["current_reservation_id"])
        return r

    def available(self, check_in: str, check_out: str, guests: int = 1, type_id: int = None,
                  exclude_reservation_id: int = None) -> list:
        """Rooms with no active reservation overlapping [check_in, check_out) and not out of order.
        `guests` counts adults and paying children; a room qualifies if it holds them with its extra beds."""
        sql = (
            "SELECT r.id, r.number, r.floor, r.status, rt.id AS type_id, rt.name AS type_name, rt.base_rate, rt.capacity,"
            " rt.max_extra_beds, rt.extra_bed_rate"
            " FROM rooms r JOIN room_types rt ON rt.id = r.type_id"
            " WHERE r.status <> 'maintenance' AND rt.active = 1 AND rt.capacity + rt.max_extra_beds >= ?"
            " AND NOT EXISTS (SELECT 1 FROM reservations x WHERE x.room_id = r.id"
            "   AND x.status IN ('booked','checked_in') AND x.check_in < ? AND x.check_out > ?"
        )
        args = [guests, check_out, check_in]
        if exclude_reservation_id:
            sql += " AND x.id <> ?"
            args.append(exclude_reservation_id)
        sql += ")"
        if type_id:
            sql += " AND rt.id = ?"
            args.append(type_id)
        return self.fetch_all(sql + " ORDER BY rt.base_rate, r.number", args)

    def set_status(self, room_id: int, status: str, notes: str = None) -> None:
        if notes is None:
            self.update(room_id, status=status)
        else:
            self.update(room_id, status=status, notes=notes)

    def status_counts(self) -> dict:
        return {r["status"]: r["n"] for r in self.fetch_all("SELECT status, COUNT(*) AS n FROM rooms GROUP BY status")}
