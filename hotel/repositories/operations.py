"""Hotel operations: housekeeping, maintenance, guest requests, lost & found, reviews."""
from .base import BaseRepository, QueryBuilder


class HousekeepingTaskRepository(BaseRepository):
    table = "housekeeping_tasks"
    columns = ("room_id", "kind", "priority", "status", "assigned_to", "notes", "due_date", "created_by", "started_at",
               "completed_at", "inspected_by")
    select_sql = (
        "SELECT t.*, r.number AS room_number, r.floor, r.status AS room_status, rt.name AS room_type,"
        " u.full_name AS assigned_name, ins.full_name AS inspected_by_name,"
        " (SELECT 1 FROM reservations x WHERE x.room_id = r.id AND x.status = 'checked_in') AS occupied"
        " FROM housekeeping_tasks t JOIN rooms r ON r.id = t.room_id JOIN room_types rt ON rt.id = r.type_id"
        " LEFT JOIN users u ON u.id = t.assigned_to LEFT JOIN users ins ON ins.id = t.inspected_by"
    )
    default_order = ("CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,"
                     " t.due_date, r.floor, r.number")
    entity_label = "Task"

    def search(self, statuses=None, assigned_to=None, unassigned_or_mine=None, due_date=None, room_id=None,
               limit=500) -> list:
        qb = QueryBuilder(self.select_sql)
        if statuses:
            qb.add(f"t.status IN ({','.join('?' for _ in statuses)})", *statuses)
        qb.add_if(assigned_to, "t.assigned_to = ?", assigned_to)
        qb.add_if(unassigned_or_mine, "(t.assigned_to IS NULL OR t.assigned_to = ?)", unassigned_or_mine)
        qb.add_if(due_date, "t.due_date <= ?", due_date)
        qb.add_if(room_id, "t.room_id = ?", room_id)
        return self.fetch_all(qb.sql(self.default_order, limit), qb.args)

    def open_for_room(self, room_id: int, kind: str = None):
        sql, args = "SELECT * FROM housekeeping_tasks WHERE room_id=? AND status IN ('open','in_progress')", [room_id]
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        return self.fetch_one(sql, args)

    def productivity(self, date_from, date_to) -> list:
        return self.fetch_all(
            "SELECT u.full_name AS name, COUNT(*) AS done,"
            " ROUND(AVG((julianday(t.completed_at) - julianday(t.started_at)) * 1440), 0) AS avg_minutes"
            " FROM housekeeping_tasks t JOIN users u ON u.id = t.assigned_to"
            " WHERE t.status IN ('done','inspected') AND date(t.completed_at) BETWEEN ? AND ?"
            " GROUP BY u.id ORDER BY done DESC", (date_from, date_to))


class RosterRepository(BaseRepository):
    table = "roster_shifts"
    columns = ("user_id", "work_date", "start_time", "end_time", "note", "created_by")
    select_sql = "SELECT t.*, u.full_name AS user_name, u.role AS user_role FROM roster_shifts t JOIN users u ON u.id = t.user_id"
    default_order = "t.work_date, t.start_time, u.full_name"
    entity_label = "Shift"

    def between(self, start: str, end: str, user_id: int = None) -> list:
        """Shifts on dates start..end inclusive."""
        qb = QueryBuilder(self.select_sql)
        qb.add("t.work_date BETWEEN ? AND ?", start, end)
        qb.add_if(user_id, "t.user_id = ?", user_id)
        return self.fetch_all(qb.sql(self.default_order), qb.args)


class AttendanceRepository(BaseRepository):
    table = "attendance"
    columns = ("user_id", "clock_in", "clock_out", "note", "edited_by")
    select_sql = "SELECT t.*, u.full_name AS user_name, u.role AS user_role FROM attendance t JOIN users u ON u.id = t.user_id"
    default_order = "t.clock_in DESC"
    entity_label = "Attendance record"

    def open_for(self, user_id: int):
        return self.fetch_one(self.select_sql + " WHERE t.user_id = ? AND t.clock_out IS NULL ORDER BY t.id DESC", (user_id,))

    def between(self, start: str, end: str, user_id: int = None) -> list:
        """Records that started on dates start..end inclusive."""
        qb = QueryBuilder(self.select_sql)
        qb.add("date(t.clock_in) BETWEEN ? AND ?", start, end)
        qb.add_if(user_id, "t.user_id = ?", user_id)
        return self.fetch_all(qb.sql(self.default_order, 2000), qb.args)


class AlertRepository(BaseRepository):
    """In-app alerts for staff (the bell in the portals)."""
    table = "staff_alerts"
    columns = ("user_id", "permission", "title", "body", "link", "actor_id")

    def _visible(self, user_id: int, permissions) -> tuple:
        perms = sorted(permissions)
        marks = ",".join("?" for _ in perms) or "''"
        # alerts for me, or for a permission I hold; never my own actions, never older than my account
        where = (f"(a.user_id = ? OR (a.user_id IS NULL AND a.permission IN ({marks})))"
                 " AND (a.actor_id IS NULL OR a.actor_id <> ?)"
                 " AND a.created_at >= (SELECT created_at FROM users WHERE id = ?)")
        return where, [user_id, *perms, user_id, user_id]

    def recent(self, user_id: int, permissions, limit: int = 30) -> list:
        where, args = self._visible(user_id, permissions)
        return self.fetch_all(
            "SELECT a.id, a.title, a.body, a.link, a.created_at, (r.user_id IS NOT NULL) AS read FROM staff_alerts a"
            f" LEFT JOIN staff_alert_reads r ON r.alert_id = a.id AND r.user_id = ? WHERE {where} ORDER BY a.id DESC LIMIT ?",
            [user_id, *args, limit])

    def unread_count(self, user_id: int, permissions) -> int:
        where, args = self._visible(user_id, permissions)
        return self.scalar(
            f"SELECT COUNT(*) FROM staff_alerts a WHERE {where}"
            " AND NOT EXISTS (SELECT 1 FROM staff_alert_reads r WHERE r.alert_id = a.id AND r.user_id = ?)", [*args, user_id], 0)

    def mark_read(self, user_id: int, permissions, alert_id: int = None) -> None:
        where, args = self._visible(user_id, permissions)
        sql = f"INSERT OR IGNORE INTO staff_alert_reads(alert_id, user_id) SELECT a.id, ? FROM staff_alerts a WHERE {where}"
        if alert_id:
            sql += " AND a.id = ?"
            args = [*args, alert_id]
        self.execute(sql, [user_id, *args])

    def purge(self, before: str) -> None:
        self.execute("DELETE FROM staff_alerts WHERE created_at < ?", (before,))


class MaintenanceRepository(BaseRepository):
    table = "maintenance_tickets"
    columns = ("code", "room_id", "location", "title", "description", "priority", "status", "out_of_order",
               "reported_by", "assigned_to", "resolution", "resolved_at")
    select_sql = (
        "SELECT t.*, r.number AS room_number, rep.full_name AS reported_by_name, a.full_name AS assigned_name"
        " FROM maintenance_tickets t LEFT JOIN rooms r ON r.id = t.room_id"
        " LEFT JOIN users rep ON rep.id = t.reported_by LEFT JOIN users a ON a.id = t.assigned_to"
    )
    default_order = ("CASE t.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END,"
                     " CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, t.id DESC")
    entity_label = "Ticket"

    def search(self, status=None, reported_by=None, room_id=None, limit=500) -> list:
        qb = QueryBuilder(self.select_sql)
        if status == "active":
            qb.add("t.status IN ('open','in_progress')")
        else:
            qb.add_if(status, "t.status = ?", status)
        qb.add_if(reported_by, "t.reported_by = ?", reported_by)
        qb.add_if(room_id, "t.room_id = ?", room_id)
        return self.fetch_all(qb.sql(self.default_order, limit), qb.args)

    def other_out_of_order(self, room_id: int, exclude_id: int) -> bool:
        return self.scalar(
            "SELECT 1 FROM maintenance_tickets WHERE room_id=? AND id<>? AND out_of_order=1 AND status IN ('open','in_progress')",
            (room_id, exclude_id)) is not None


class GuestRequestRepository(BaseRepository):
    table = "guest_requests"
    columns = ("reservation_id", "kind", "message", "status", "response", "handled_by", "updated_at")
    select_sql = (
        "SELECT t.*, r.code AS reservation_code, r.guest_id, rm.number AS room_number,"
        " g.first_name || ' ' || g.last_name AS guest_name, h.full_name AS handled_by_name"
        " FROM guest_requests t JOIN reservations r ON r.id = t.reservation_id JOIN rooms rm ON rm.id = r.room_id"
        " JOIN guests g ON g.id = r.guest_id LEFT JOIN users h ON h.id = t.handled_by"
    )
    default_order = "t.id DESC"
    entity_label = "Request"

    def search(self, status=None, guest_id=None, limit=300) -> list:
        qb = QueryBuilder(self.select_sql)
        if status == "active":
            qb.add("t.status IN ('open','in_progress')")
        else:
            qb.add_if(status, "t.status = ?", status)
        qb.add_if(guest_id, "r.guest_id = ?", guest_id)
        return self.fetch_all(qb.sql(self.default_order, limit), qb.args)


class LostFoundRepository(BaseRepository):
    table = "lost_found"
    columns = ("room_id", "location", "description", "status", "found_by", "guest_id", "notes", "closed_at")
    select_sql = (
        "SELECT t.*, r.number AS room_number, u.full_name AS found_by_name,"
        " g.first_name || ' ' || g.last_name AS guest_name FROM lost_found t LEFT JOIN rooms r ON r.id = t.room_id"
        " LEFT JOIN users u ON u.id = t.found_by LEFT JOIN guests g ON g.id = t.guest_id"
    )
    default_order = "t.id DESC"
    entity_label = "Lost & found item"

    def search(self, status=None, found_by=None) -> list:
        qb = QueryBuilder(self.select_sql)
        qb.add_if(status, "t.status = ?", status)
        qb.add_if(found_by, "t.found_by = ?", found_by)
        return self.fetch_all(qb.sql(self.default_order), qb.args)


class ReviewRepository(BaseRepository):
    table = "reviews"
    columns = ("reservation_id", "rating", "comment", "published", "reply")
    select_sql = (
        "SELECT t.*, r.code AS reservation_code, r.guest_id, g.first_name AS guest_first_name,"
        " g.first_name || ' ' || g.last_name AS guest_name, rt.name AS room_type"
        " FROM reviews t JOIN reservations r ON r.id = t.reservation_id JOIN guests g ON g.id = r.guest_id"
        " JOIN rooms rm ON rm.id = r.room_id JOIN room_types rt ON rt.id = rm.type_id"
    )
    default_order = "t.id DESC"
    entity_label = "Review"

    def published(self, limit=12) -> list:
        return self.fetch_all(self.select_sql + " WHERE t.published=1 ORDER BY t.id DESC LIMIT ?", (limit,))

    def average(self) -> dict:
        return self.fetch_one("SELECT ROUND(AVG(rating),2) AS average, COUNT(*) AS count FROM reviews")
