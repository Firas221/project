"""Administration: users, role permissions, settings, audit log, sessions, privacy (Egypt PDPL 151/2020)."""
import json

from ..core.clock import now_str
from ..core.errors import Conflict, PermissionDenied, ValidationError
from ..core.permissions import ALL_PERMISSIONS, PERMISSION_CATALOG, Perm, Role
from ..core.security import PasswordPolicy, Tokens
from ..core.validation import Bool, Email, Number, Schema, Str, Time
from .base import Service
from .notifications import NotificationService


class UserSchema(Schema):
    full_name = Str(required=True, max_len=120)
    email = Email()
    role = Str(required=True, choices=Role.EMPLOYEES)
    active = Bool(default=True)


class NewUserSchema(UserSchema):
    username = Str(required=True, min_len=3, max_len=60, pattern=r"[A-Za-z0-9_.\-]+")
    password = Str(max_len=128)


class SettingsSchema(Schema):
    hotel_name = Str(max_len=120, required=True)
    hotel_name_ar = Str(max_len=120)
    tagline = Str(max_len=200)
    address = Str(max_len=300)
    phone = Str(max_len=60)
    email = Email()
    currency = Str(max_len=8, required=True)
    service_charge_rate = Number(min_value=0, max_value=30)
    vat_rate = Number(min_value=0, max_value=30)
    city_tax_rate = Number(min_value=0, max_value=20)
    tax_registration_number = Str(max_len=40)
    commercial_register = Str(max_len=40)
    tourism_license = Str(max_len=40)
    check_in_time = Time()
    check_out_time = Time()
    require_id_at_checkin = Bool()
    cash_requires_shift = Bool()
    weekend_days = Str(max_len=20, pattern=r"(\s*[0-6]\s*,?)*")
    weekend_adjust_pct = Number(min_value=-50, max_value=200)
    online_booking_enabled = Bool()
    free_cancellation_days = Number(min_value=0, max_value=60, integer=True)
    max_online_nights = Number(min_value=1, max_value=365, integer=True)
    require_2fa_for_admins = Bool()
    require_email_verification = Bool()
    auto_night_audit = Bool()
    night_audit_time = Time()


class UserAdminService(Service):
    def list(self, role=None, q=None):
        self.require(Perm.USERS_MANAGE)
        return self.repos.users.search(role=role, q=q)

    def create(self, data: dict) -> dict:
        self.require(Perm.USERS_MANAGE)
        v = NewUserSchema.validate(data)
        if self.repos.users.exists(username=v["username"]):
            raise Conflict("Username already exists")
        temporary = not v["password"]
        password = v["password"] or Tokens.temporary_password()
        PasswordPolicy.validate(password, username=v["username"])
        uid = self.repos.users.insert(username=v["username"], full_name=v["full_name"], email=v["email"], role=v["role"],
                                      active=int(v["active"]), password_hash=self.ctx.app.hasher.hash(password),
                                      must_change_password=1)
        self.audit("user_create", "user", uid, f"{v['username']} as {v['role']}")
        user = self.repos.users.get(uid)
        return {"user": user, "temporary_password": password if temporary else None}

    def update(self, user_id: int, data: dict) -> dict:
        self.require(Perm.USERS_MANAGE)
        user = self.repos.users.require(user_id, "User")
        if user["role"] == Role.GUEST:
            raise ValidationError("Guest accounts are managed from the guest profile")
        v = UserSchema.validate(data)
        demoting = user["role"] == Role.ADMIN and (v["role"] != Role.ADMIN or not v["active"])
        if user_id == self.actor_id and demoting:
            raise ValidationError("You cannot demote or deactivate your own account")
        if demoting and self.repos.users.count_active_admins(exclude_id=user_id) == 0:
            raise ValidationError("At least one active administrator is required")
        self.repos.users.update(user_id, full_name=v["full_name"], email=v["email"], role=v["role"],
                                active=int(v["active"]))
        if not v["active"] or v["role"] != user["role"]:
            self.repos.sessions.delete_for_user(user_id)  # permissions changed -> force re-login
        self.audit("user_update", "user", user_id, f"{user['username']}: role={v['role']} active={v['active']}")
        return self.repos.users.get(user_id)

    def reset_password(self, user_id: int) -> dict:
        self.require(Perm.USERS_MANAGE)
        user = self.repos.users.require(user_id, "User")
        if user["role"] == Role.ADMIN and user_id != self.actor_id and not self.actor.is_admin:
            raise PermissionDenied()
        password = Tokens.temporary_password()
        self.repos.users.update(user_id, password_hash=self.ctx.app.hasher.hash(password), must_change_password=1,
                                failed_attempts=0, locked_until=None)
        self.repos.sessions.delete_for_user(user_id)
        self.audit("user_password_reset", "user", user_id, user["username"])
        return {"temporary_password": password}

    def unlock(self, user_id: int) -> dict:
        self.require(Perm.USERS_MANAGE)
        user = self.repos.users.require(user_id, "User")
        self.repos.users.update(user_id, failed_attempts=0, locked_until=None)
        self.audit("user_unlock", "user", user_id, user["username"])
        return self.repos.users.get(user_id)

    def revoke_sessions(self, user_id: int) -> None:
        self.require(Perm.USERS_MANAGE)
        user = self.repos.users.require(user_id, "User")
        self.repos.sessions.delete_for_user(user_id, except_id=self.actor.session_id if user_id == self.actor_id else None)
        self.audit("sessions_revoked", "user", user_id, user["username"])

    def reset_2fa(self, user_id: int) -> None:
        self.require(Perm.USERS_MANAGE)
        if not self.actor.is_admin:
            raise PermissionDenied()
        self.repos.users.update(user_id, totp_enabled=0, totp_secret=None, totp_last_step=0)
        self.audit("2fa_reset", "user", user_id)

    def active_sessions(self) -> list:
        self.require(Perm.USERS_MANAGE)
        return self.repos.sessions.active_list()

    def staff_by_role(self, role: str) -> list:
        return [{"id": u["id"], "full_name": u["full_name"]} for u in self.repos.users.active_by_role(role)]


class RoleService(Service):
    def matrix(self) -> dict:
        self.require(Perm.ROLES_MANAGE)
        roles = []
        for role in Role.ALL:
            perms = sorted(ALL_PERMISSIONS) if role == Role.ADMIN else sorted(self.repos.roles.permissions_of(role))
            roles.append({"name": role, "label": Role.LABELS[role], "editable": role in Role.EDITABLE,
                          "permissions": perms, "users": self.repos.users.count(role=role)})
        catalog = [{"permission": p, "group": g, "description": d} for p, g, d in PERMISSION_CATALOG]
        return {"roles": roles, "catalog": catalog}

    def set_permissions(self, role: str, permissions) -> dict:
        self.require(Perm.ROLES_MANAGE)
        if role not in Role.EDITABLE:
            raise ValidationError("This role's permissions cannot be changed")
        if not isinstance(permissions, list) or any(p not in ALL_PERMISSIONS for p in permissions):
            raise ValidationError("Unknown permission in list")
        before = self.repos.roles.permissions_of(role)
        self.repos.roles.set_permissions(role, permissions)
        added, removed = set(permissions) - before, before - set(permissions)
        self.audit("role_permissions", "role", None,
                   f"{role}: +{','.join(sorted(added)) or '-'} / -{','.join(sorted(removed)) or '-'}")
        return self.matrix()


class SettingsService(Service):
    PUBLIC_KEYS = ("hotel_name", "hotel_name_ar", "tagline", "address", "phone", "email", "currency",
                   "service_charge_rate", "vat_rate", "city_tax_rate", "check_in_time", "check_out_time",
                   "online_booking_enabled", "free_cancellation_days", "max_online_nights", "tax_registration_number")

    def public(self) -> dict:
        s = self.settings()
        return {k: s.get(k, "") for k in self.PUBLIC_KEYS}

    def all(self) -> dict:
        return self.settings()

    def update(self, data: dict) -> dict:
        self.require(Perm.SETTINGS_MANAGE)
        v = SettingsSchema.validate(data, partial=True)
        changed = []
        for k, value in v.items():
            if isinstance(value, bool):
                value = "1" if value else "0"
            elif isinstance(value, float):
                value = f"{value:g}"
            self.repos.settings.put(k, str(value))
            changed.append(k)
        self.audit("settings_update", "settings", None, ", ".join(changed))
        return self.settings()


class AuditService(Service):
    def search(self, **filters) -> list:
        self.require(Perm.AUDIT_VIEW)
        return self.repos.audit.search(**filters)

    def outbox(self) -> list:
        self.require(Perm.AUDIT_VIEW)
        rows = self.repos.outbox.recent()
        for r in rows:  # never expose one-time links to the browser
            subject = r["subject"].lower()
            if "reset" in subject or "confirm your e-mail" in subject:
                r["body"] = "(hidden: contains a one-time link)"
        return rows


class PrivacyService(Service):
    """Data-subject rights under Egypt's Personal Data Protection Law (151/2020): access & erasure."""

    def export_guest(self, guest_id: int) -> dict:
        g = self.repos.guests.require(guest_id, "Guest")
        reservations = self.repos.reservations.search(guest_id=guest_id)
        data = {
            "exported_at": now_str(),
            "controller": self.settings().get("hotel_name"),
            "profile": {k: g[k] for k in self.repos.guests.columns if k in g},
            "reservations": [{k: r[k] for k in ("code", "check_in", "check_out", "room_type", "status", "rate", "source",
                                                "special_requests")} for r in reservations],
            "charges": [], "payments": [], "requests": [], "reviews": [],
        }
        for r in reservations:
            data["charges"] += [{"reservation": r["code"], "description": c["description"], "amount": c["amount"],
                                 "date": c["created_at"]} for c in self.repos.charges.for_reservation(r["id"])]
            data["payments"] += [{"reservation": r["code"], "amount": p["amount"], "method": p["method"],
                                  "date": p["created_at"]} for p in self.repos.payments.for_reservation(r["id"])]
        data["requests"] = [{"kind": q["kind"], "message": q["message"], "date": q["created_at"]}
                            for q in self.repos.guest_requests.search(guest_id=guest_id)]
        data["reviews"] = [{"rating": v["rating"], "comment": v["comment"]}
                           for v in self.repos.reviews.fetch_all(self.repos.reviews.select_sql + " WHERE r.guest_id=?",
                                                                 (guest_id,))]
        self.audit("privacy_export", "guest", guest_id)
        return data

    def anonymize_guest(self, guest_id: int) -> dict:
        g = self.repos.guests.require(guest_id, "Guest")
        if g["anonymized_at"]:
            raise Conflict("This guest has already been anonymised")
        active = self.repos.reservations.active_count_for_guest(guest_id)
        if active:
            raise Conflict("The guest has active reservations. Complete or cancel them first.")
        # Financial records (invoices, payments) are retained as required by tax law; personal identifiers are erased.
        self.repos.guests.update(guest_id, first_name="Erased", last_name=f"Guest #{guest_id}", email="", phone="",
                                 address="", id_number="", date_of_birth="", notes="", nationality=g["nationality"],
                                 marketing_consent=0, anonymized_at=now_str())
        self.repos.guests.execute("UPDATE guest_requests SET message='(erased)' WHERE reservation_id IN"
                           " (SELECT id FROM reservations WHERE guest_id=?)", (guest_id,))
        self.repos.guests.execute("UPDATE reservations SET special_requests='', notes='' WHERE guest_id=?", (guest_id,))
        user = self.repos.users.first_by(guest_id=guest_id)
        if user:
            self.repos.sessions.delete_for_user(user["id"])
            self.repos.users.update(user["id"], active=0, email="", username=f"erased-{user['id']}-{Tokens.new(4)}",
                                    full_name="Erased guest", guest_id=None)
        self.audit("privacy_erase", "guest", guest_id)
        return self.repos.guests.get(guest_id)

    def notify_staff_welcome(self, user_id: int):
        user = self.repos.users.get(user_id)
        if user and user["email"]:
            self.use(NotificationService).welcome(user)
