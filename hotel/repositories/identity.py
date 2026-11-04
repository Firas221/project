"""Users, roles, sessions, settings and the audit log."""
from ..core.clock import now_str
from .base import BaseRepository, QueryBuilder

USER_PUBLIC_COLUMNS = (
    "t.id, t.username, t.email, t.full_name, t.role, t.active, t.guest_id, t.failed_attempts, t.locked_until,"
    " t.must_change_password, t.password_changed_at, t.last_login_at, t.created_at, t.totp_enabled"
)


class RoleRepository(BaseRepository):
    table = "roles"
    columns = ("name", "label", "description")

    def all_roles(self) -> list:
        return self.fetch_all("SELECT * FROM roles ORDER BY rowid")

    def permissions_of(self, role: str) -> set:
        return {r["permission"] for r in self.fetch_all("SELECT permission FROM role_permissions WHERE role=?", (role,))}

    def set_permissions(self, role: str, permissions) -> None:
        self.execute("DELETE FROM role_permissions WHERE role=?", (role,))
        for p in sorted(set(permissions)):
            self.execute("INSERT INTO role_permissions(role, permission) VALUES (?, ?)", (role, p))

    def ensure(self, name: str, label: str, description: str = "") -> None:
        self.execute("INSERT OR IGNORE INTO roles(name, label, description) VALUES (?,?,?)", (name, label, description))


class UserRepository(BaseRepository):
    table = "users"
    columns = ("username", "email", "full_name", "role", "password_hash", "active", "guest_id", "failed_attempts",
               "locked_until", "must_change_password", "password_changed_at", "last_login_at", "totp_secret", "totp_enabled",
               "totp_last_step")
    select_sql = f"SELECT {USER_PUBLIC_COLUMNS} FROM users t"
    default_order = "t.role, t.username"
    entity_label = "User"

    def get_with_secret(self, username: str):
        """Includes the password hash — only for the authentication service."""
        return self.fetch_one("SELECT * FROM users WHERE username = ?", (username,))

    def password_hash(self, user_id: int) -> str:
        return self.scalar("SELECT password_hash FROM users WHERE id=?", (user_id,))

    def search(self, role: str = None, q: str = None) -> list:
        qb = QueryBuilder(self.select_sql)
        qb.add_if(role, "t.role = ?", role)
        qb.add_if(q, "(t.username LIKE ? OR t.full_name LIKE ? OR t.email LIKE ?)", *[f"%{q}%"] * 3)
        return self.fetch_all(qb.sql(self.default_order), qb.args)

    def active_by_role(self, role: str) -> list:
        return self.fetch_all(self.select_sql + " WHERE t.role=? AND t.active=1 ORDER BY t.full_name", (role,))

    def count_active_admins(self, exclude_id: int = None) -> int:
        sql, args = "SELECT COUNT(*) FROM users WHERE role='admin' AND active=1", []
        if exclude_id:
            sql += " AND id<>?"
            args.append(exclude_id)
        return self.scalar(sql, args, 0)


class SessionRepository(BaseRepository):
    table = "sessions"
    columns = ("token_hash", "csrf_token", "user_id", "ip", "user_agent", "last_seen_at", "expires_at")

    def find_valid(self, token_hash: str, idle_cutoff: str):
        return self.fetch_one(
            "SELECT s.*, u.username, u.full_name, u.role, u.active, u.guest_id, u.must_change_password"
            " FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = ? AND s.expires_at > ? AND s.last_seen_at > ?",
            (token_hash, now_str(), idle_cutoff),
        )

    def touch(self, session_id: int) -> None:
        self.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (now_str(), session_id))

    def delete_for_user(self, user_id: int, except_id: int = None) -> None:
        if except_id:
            self.execute("DELETE FROM sessions WHERE user_id=? AND id<>?", (user_id, except_id))
        else:
            self.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def delete_by_hash(self, token_hash: str) -> None:
        self.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))

    def purge_expired(self, idle_cutoff: str) -> None:
        self.execute("DELETE FROM sessions WHERE expires_at <= ? OR last_seen_at <= ?", (now_str(), idle_cutoff))

    def for_user(self, user_id: int) -> list:
        return self.fetch_all(
            "SELECT id, ip, user_agent, created_at, last_seen_at, expires_at FROM sessions WHERE user_id=?"
            " ORDER BY last_seen_at DESC", (user_id,))

    def active_list(self) -> list:
        return self.fetch_all(
            "SELECT s.id, s.user_id, u.username, u.full_name, u.role, s.ip, s.user_agent, s.created_at, s.last_seen_at"
            " FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.expires_at > ? ORDER BY s.last_seen_at DESC",
            (now_str(),))


class AuditRepository(BaseRepository):
    table = "audit_log"
    columns = ("user_id", "username", "action", "entity", "entity_id", "details", "ip")
    default_order = "t.id DESC"

    def search(self, q: str = None, user_id: int = None, action: str = None, date_from: str = None,
               date_to: str = None, limit: int = 300) -> list:
        qb = QueryBuilder("SELECT t.* FROM audit_log t")
        qb.add_if(q, "(t.details LIKE ? OR t.action LIKE ? OR t.username LIKE ?)", *[f"%{q}%"] * 3)
        qb.add_if(user_id, "t.user_id = ?", user_id)
        qb.add_if(action, "t.action LIKE ?", f"{action}%")
        qb.add_if(date_from, "date(t.created_at) >= ?", date_from)
        qb.add_if(date_to, "date(t.created_at) <= ?", date_to)
        return self.fetch_all(qb.sql("t.id DESC", limit), qb.args)


class SettingsRepository(BaseRepository):
    table = "settings"
    columns = ("key", "value")

    def as_dict(self) -> dict:
        return {r["key"]: r["value"] for r in self.fetch_all("SELECT key, value FROM settings")}

    def put(self, key: str, value: str) -> None:
        self.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, value))

    def put_default(self, key: str, value: str) -> None:
        self.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
