"""Administration: users, roles, settings, audit, reports, night audit, backups, exports."""
import csv
import io
import logging
import re

from ...core.clock import today_iso
from ...core.errors import NotFound, PermissionDenied, ValidationError
from ...core.permissions import Perm
from ...http.messages import Download
from ...services import (AlertService, AuditService, GuestService, InventoryService, NightAuditService, ReportService,
                         ReservationService, RoleService, SettingsService, UserAdminService)
from ..router import Controller, delete, get, post, put


log = logging.getLogger("hotel.admin")


def to_csv(name: str, header: list, rows: list) -> Download:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([_csv_safe(r.get(h)) for h in header])
    return Download(buf.getvalue(), "text/csv; charset=utf-8", f"{name}-{today_iso()}.csv")


def _csv_safe(v):
    """Neutralise spreadsheet formula injection (=, +, -, @ at the start of text)."""
    if v is None:
        return ""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") and not re.fullmatch(r"-?\d+(\.\d+)?", v):
        return "'" + v
    return v


class UserController(Controller):
    @get("/users", perm=Perm.USERS_MANAGE)
    def list(self):
        return self.svc(UserAdminService).list(self.q("role"), self.q("q"))

    @post("/users", perm=Perm.USERS_MANAGE)
    def create(self):
        return self.svc(UserAdminService).create(self.body)

    @put("/users/{user_id}", perm=Perm.USERS_MANAGE)
    def update(self, user_id):
        return self.svc(UserAdminService).update(user_id, self.body)

    @delete("/users/{user_id}", perm=Perm.USERS_MANAGE)
    def delete(self, user_id):
        self.svc(UserAdminService).delete(user_id)

    @post("/users/{user_id}/reset-password", perm=Perm.USERS_MANAGE)
    def reset_password(self, user_id):
        return self.svc(UserAdminService).reset_password(user_id)

    @post("/users/{user_id}/unlock", perm=Perm.USERS_MANAGE)
    def unlock(self, user_id):
        return self.svc(UserAdminService).unlock(user_id)

    @post("/users/{user_id}/revoke-sessions", perm=Perm.USERS_MANAGE)
    def revoke(self, user_id):
        self.svc(UserAdminService).revoke_sessions(user_id)

    @post("/users/{user_id}/reset-2fa", perm=Perm.USERS_MANAGE)
    def reset_2fa(self, user_id):
        self.svc(UserAdminService).reset_2fa(user_id)

    @get("/sessions", perm=Perm.USERS_MANAGE)
    def sessions(self):
        return self.svc(UserAdminService).active_sessions()


class AlertController(Controller):
    @get("/alerts")
    def recent(self):
        return self.svc(AlertService).recent()

    @post("/alerts/read")
    def read(self):
        alert_id = self.body.get("id")
        return self.svc(AlertService).mark_read(int(alert_id) if str(alert_id or "").isdigit() else None)


class RoleController(Controller):
    @get("/roles", perm=Perm.ROLES_MANAGE)
    def matrix(self):
        return self.svc(RoleService).matrix()

    @put("/roles/{role}", perm=Perm.ROLES_MANAGE)
    def update(self, role):
        return self.svc(RoleService).set_permissions(role, self.body.get("permissions"))


class SettingsController(Controller):
    @get("/settings", audience="user")
    def read(self):
        svc = self.svc(SettingsService)
        return svc.all() if self.req.user.can(Perm.SETTINGS_MANAGE) else svc.public()

    @put("/settings", perm=Perm.SETTINGS_MANAGE)
    def update(self):
        return self.svc(SettingsService).update(self.body)


class AuditController(Controller):
    @get("/audit", perm=Perm.AUDIT_VIEW)
    def list(self):
        return self.svc(AuditService).search(q=self.q("q"), action=self.q("action"), date_from=self.q("from"),
                                             date_to=self.q("to"), **self.paging())

    @get("/outbox", perm=Perm.AUDIT_VIEW)
    def outbox(self):
        return self.svc(AuditService).outbox()


class ReportController(Controller):
    @get("/reports/summary", perm=Perm.REPORTS_VIEW)
    def summary(self):
        return self.svc(ReportService).summary(self.q("from"), self.q("to"))

    @get("/reports/tax", perm=Perm.REPORTS_VIEW)
    def tax(self):
        return self.svc(ReportService).tax_report(self.q("from"), self.q("to"))

    @get("/night-audit", perm=Perm.REPORTS_VIEW)
    def night_audit(self):
        return self.svc(NightAuditService).preview()

    @post("/night-audit/close", perm=Perm.NIGHT_AUDIT_CLOSE)
    def close_day(self):
        return self.svc(NightAuditService).close_day(bool(self.body.get("mark_no_shows", True)), self.body.get("notes", ""))

    @get("/backups", perm=Perm.SETTINGS_MANAGE)
    def backups(self):
        return self.req.ctx.app.backups.list()

    @post("/backups", perm=Perm.SETTINGS_MANAGE)
    def backup_now(self):
        result = self.req.ctx.app.backups.run()
        self.req.ctx.service(AuditService).audit("backup_manual", "backup", None, result["file"])
        return result

    @post("/backups/restore", perm=Perm.SETTINGS_MANAGE)
    def restore(self):
        """Replaces all current data with a backup. Needs the administrator's password again."""
        ctx = self.req.ctx
        if not self.req.user.is_admin:
            raise PermissionDenied("Only an administrator can restore a backup")
        if not ctx.app.hasher.verify(str(self.body.get("password") or ""), ctx.repos.users.password_hash(self.req.user.id)):
            raise ValidationError("Password is incorrect", field="password")
        try:
            path = ctx.app.backups.resolve(self.body.get("file"))
        except ValueError as e:
            raise NotFound(str(e))
        who = self.req.user.username
        ctx.conn.execute("COMMIT")  # release this request's write lock so the restore can replace the database
        try:
            result = ctx.app.restore_backup(path)
        except ValueError as e:
            raise ValidationError(str(e))
        log.warning("Backup %s restored by %s from %s", result["restored"], who, self.req.ip)
        return result


EXPORT_ROWS = 100_000   # exports hold everything in the period, not just the first screenful


class ExportController(Controller):
    EXPORTS = {
        "reservations": (Perm.RESERVATIONS_VIEW, ["code", "guest_name", "guest_email", "room_number", "room_type",
                                                   "check_in", "check_out", "nights", "adults", "children", "rate",
                                                   "status", "source", "company_name", "total", "balance", "created_at"]),
        "guests": (Perm.GUESTS_VIEW, ["id", "first_name", "last_name", "email", "phone", "nationality", "id_type",
                                      "id_number", "vip", "stays", "last_stay"]),
        "items": (Perm.INVENTORY_VIEW, ["sku", "name", "category", "department", "unit", "quantity", "reorder_level",
                                        "cost", "price", "stock_value", "supplier_name"]),
        "movements": (Perm.INVENTORY_VIEW, ["created_at", "sku", "item_name", "kind", "change", "balance_after",
                                            "unit_cost", "reason", "reference", "reservation_code", "user_name"]),
        "daily": (Perm.REPORTS_VIEW, ["date", "occupied", "occupancy", "room_revenue", "adr", "revpar"]),
        "tax": (Perm.REPORTS_VIEW, ["number", "issued_at", "reservation_code", "bill_to", "bill_to_tax_no", "subtotal",
                                    "service_charge", "vat", "city_tax", "total"]),
        "guest_register": (Perm.GUESTS_VIEW, ["room_number", "first_name", "last_name", "nationality", "id_type",
                                              "id_number", "date_of_birth", "gender", "check_in", "check_out",
                                              "adults", "children", "address", "code"]),
        "audit": (Perm.AUDIT_VIEW, ["created_at", "username", "action", "entity", "entity_id", "details", "ip"]),
    }

    @get("/export/{name}")
    def export(self, name):
        if name not in self.EXPORTS:
            raise NotFound("Unknown export")
        perm, header = self.EXPORTS[name]
        if not self.req.user.can(perm):
            raise PermissionDenied()
        frm, to = self.q("from"), self.q("to")
        rows = {
            "reservations": lambda: self.svc(ReservationService).search(status=self.q("status"), q=self.q("q"),
                                                                        date_from=frm, date_to=to, limit=EXPORT_ROWS),
            "guests": lambda: self.svc(GuestService).search(self.q("q"), limit=EXPORT_ROWS),
            "items": lambda: self.svc(InventoryService).search(),
            "movements": lambda: self.svc(InventoryService).movements(date_from=frm, date_to=to, limit=EXPORT_ROWS),
            "daily": lambda: self.svc(ReportService).summary(frm, to)["daily"],
            "tax": lambda: self.svc(ReportService).tax_report(frm, to)["invoices"],
            "guest_register": lambda: self.svc(GuestService).registration_report(self.q("date") or today_iso(),
                                                                                 foreign_only=not self.flag("all")),
            "audit": lambda: self.svc(AuditService).search(date_from=frm, date_to=to, limit=EXPORT_ROWS),
        }[name]()
        return to_csv(name, header, rows)
