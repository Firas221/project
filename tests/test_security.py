"""Security tests: authentication, sessions, CSRF, RBAC, object-level access, 2FA, resets, hardening."""
import re
import sqlite3

from support import AppTestCase, Client, d  # first: puts the project on sys.path

from hotel.core.security import Tokens  # noqa: E402
from hotel.core.totp import TOTP  # noqa: E402


class AuthenticationTests(AppTestCase):
    def test_requires_sign_in(self):
        c = self.client()
        for path in ("/api/dashboard", "/api/reservations", "/api/users", "/api/portal/reservations", "/api/auth/me"):
            self.assertEqual(c.req("GET", path)[0], 401, path)

    def test_generic_errors_and_lockout(self):
        c = self.client()
        s1, e1 = c.req("POST", "/api/auth/login", {"username": "nobody", "password": "Whatever123"})
        s2, e2 = c.req("POST", "/api/auth/login", {"username": "maid2", "password": "Wrong-pass-1"})
        self.assertEqual((s1, s2), (401, 401))
        self.assertEqual(e1["error"], e2["error"])  # no user enumeration
        for _ in range(4):
            c.req("POST", "/api/auth/login", {"username": "maid2", "password": "Wrong-pass-1"})
        status, err = c.req("POST", "/api/auth/login", {"username": "maid2", "password": "MaidPass123"})
        self.assertEqual(status, 401)
        self.assertIn("locked", err["error"])
        admin = self.client("admin")
        uid = next(u["id"] for u in admin.ok("GET", "/api/users") if u["username"] == "maid2")
        admin.ok("POST", f"/api/users/{uid}/unlock")
        self.client("maid2")

    def test_session_cookie_and_storage(self):
        c = self.client("frontdesk")
        cookie = c.last_headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        token = c.cookie.split("=", 1)[1]
        db = sqlite3.connect(self.app.config.db_path)
        rows = [r[0] for r in db.execute("SELECT token_hash FROM sessions")]
        db.close()
        self.assertNotIn(token, rows)                 # never stored in plain text
        self.assertIn(Tokens.digest(token), rows)

    def test_logout_invalidates_session(self):
        c = self.client("frontdesk")
        old = c.cookie
        c.ok("POST", "/api/auth/logout")
        c.cookie = old
        self.assertEqual(c.req("GET", "/api/auth/me")[0], 401)

    def test_security_headers(self):
        c = self.client()
        c.req("GET", "/")
        h = {k.lower(): v for k, v in c.last_headers.items()}
        self.assertIn("default-src 'self'", h["content-security-policy"])
        self.assertIn("frame-ancestors 'none'", h["content-security-policy"])
        self.assertEqual(h["x-frame-options"], "DENY")
        self.assertEqual(h["x-content-type-options"], "nosniff")

    def test_forced_password_change_for_new_users(self):
        admin = self.client("admin")
        r = admin.ok("POST", "/api/users", {"username": "newcook", "full_name": "New Cook", "role": "chef"})
        temp = r["temporary_password"]
        c = self.client()
        user = c.login("newcook", temp)
        self.assertTrue(user["must_change_password"])
        self.assertEqual(c.req("GET", "/api/kitchen/orders")[0], 403)
        self.assertEqual(c.req("POST", "/api/auth/password", {"current_password": temp, "new_password": "weak"})[0], 400)
        c.ok("POST", "/api/auth/password", {"current_password": temp, "new_password": "Kitchen-Hero-42"})
        c2 = self.client()
        c2.login("newcook", "Kitchen-Hero-42")
        c2.ok("GET", "/api/kitchen/orders")

    def test_deactivation_revokes_access(self):
        admin = self.client("admin")
        r = admin.ok("POST", "/api/users", {"username": "temp.staff", "full_name": "Temp", "role": "staff", "password": "Temp-Staff-77"})
        uid = r["user"]["id"]
        c = self.client()
        c.login("temp.staff", "Temp-Staff-77")
        c.ok("POST", "/api/auth/password", {"current_password": "Temp-Staff-77", "new_password": "Temp-Staff-88"})
        c.ok("GET", "/api/dashboard")
        admin.ok("PUT", f"/api/users/{uid}", {"full_name": "Temp", "role": "staff", "active": False})
        self.assertEqual(c.req("GET", "/api/dashboard")[0], 401)

    def test_last_admin_protected(self):
        admin = self.client("admin")
        me = admin.ok("GET", "/api/auth/me")["user"]
        self.assertEqual(admin.req("PUT", f"/api/users/{me['id']}", {"full_name": "A", "role": "staff"})[0], 400)


class CsrfAndTransportTests(AppTestCase):
    def test_csrf_token_required(self):
        c = self.client("frontdesk")
        body = {"first_name": "Csrf", "last_name": "Test"}
        self.assertEqual(c.req("POST", "/api/guests", body, csrf=False)[0], 403)
        self.assertEqual(c.req("POST", "/api/guests", body, headers={"X-CSRF-Token": "forged"}, csrf=False)[0], 403)
        self.assertEqual(c.req("POST", "/api/guests", body)[0], 200)

    def test_cross_origin_blocked(self):
        c = self.client("frontdesk")
        status, _ = c.req("POST", "/api/guests", {"first_name": "X", "last_name": "Y"}, headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)

    def test_body_limits_and_types(self):
        c = self.client("frontdesk")
        self.assertEqual(c.req("POST", "/api/guests", raw="first_name=x", headers={"Content-Type": "application/x-www-form-urlencoded"})[0], 415)
        self.assertEqual(c.req("POST", "/api/guests", raw="{bad json", headers={"Content-Type": "application/json"})[0], 400)
        self.assertEqual(c.req("POST", "/api/guests", raw="x" * 400_000, headers={"Content-Type": "application/json"})[0], 413)

    def test_static_traversal_blocked(self):
        c = self.client()
        for path in ("/../hotel/app.py", "/%2e%2e/hotel/app.py", "/css/../../run.py"):
            self.assertEqual(c.req("GET", path)[0], 404, path)

    def test_sql_injection_is_inert(self):
        c = self.client("frontdesk")
        rows = c.ok("GET", "/api/guests?q=%27%20OR%201%3D1%20--")
        self.assertEqual(rows, [])
        self.assertTrue(c.ok("GET", "/api/guests"))

    def test_rate_limiting(self):
        c = self.client()
        self.app.config.login_ip_limit_per_minute = 3
        try:
            codes = [c.req("POST", "/api/auth/login", {"username": "x", "password": "y"})[0] for _ in range(5)]
            self.assertIn(429, codes)
        finally:
            self.app.config.login_ip_limit_per_minute = 1000


class AuthorizationTests(AppTestCase):
    MATRIX = [
        # (user, method, path, expected)
        ("frontdesk", "GET", "/api/users", 403), ("frontdesk", "GET", "/api/roles", 403), ("frontdesk", "PUT", "/api/settings", 403),
        ("frontdesk", "GET", "/api/audit", 403), ("frontdesk", "GET", "/api/reservations", 200), ("frontdesk", "GET", "/api/portal/profile", 403),
        ("chef", "GET", "/api/reservations", 403), ("chef", "GET", "/api/guests", 403), ("chef", "GET", "/api/kitchen/orders", 200),
        ("chef", "GET", "/api/menu", 200), ("chef", "GET", "/api/reports/summary", 403),
        ("maid", "GET", "/api/reservations", 403), ("maid", "GET", "/api/guests", 403), ("maid", "GET", "/api/kitchen/orders", 403),
        ("maid", "GET", "/api/housekeeping/tasks", 200), ("maid", "GET", "/api/items", 403), ("maid", "GET", "/api/items/requestable", 200),
        ("amelia.hart@example.com", "GET", "/api/dashboard", 403), ("amelia.hart@example.com", "GET", "/api/guests", 403),
        ("amelia.hart@example.com", "GET", "/api/portal/reservations", 200), ("admin", "GET", "/api/portal/reservations", 403),
        ("admin", "GET", "/api/audit", 200), ("admin", "GET", "/api/kitchen/orders", 200),
    ]

    def test_role_matrix(self):
        clients = {}
        for user, method, path, expected in self.MATRIX:
            c = clients.setdefault(user, self.client(user))
            self.assertEqual(c.req(method, path, {} if method != "GET" else None)[0], expected, f"{user} {method} {path}")

    def test_guest_cannot_touch_other_guests(self):
        g = self.client("amelia.hart@example.com")
        mine = {r["id"] for r in g.ok("GET", "/api/portal/reservations")}
        staff = self.client("frontdesk")
        others = [r["id"] for r in staff.ok("GET", "/api/reservations?status=") if r["id"] not in mine]
        for rid in others[:5]:
            self.assertEqual(g.req("GET", f"/api/portal/reservations/{rid}")[0], 404)
            self.assertEqual(g.req("POST", f"/api/portal/reservations/{rid}/cancel")[0], 404)
            self.assertEqual(g.req("POST", f"/api/portal/reservations/{rid}/orders", {"lines": [{"menu_item_id": 1}]})[0], 404)

    def test_housekeeper_limited_to_own_tasks(self):
        maid2 = self.client("maid2")
        maid = self.client("maid")
        rosa_tasks = [t for t in maid.ok("GET", "/api/housekeeping/tasks?mine=1") if t["assigned_to"]]
        self.assertTrue(rosa_tasks)
        status, _ = maid2.req("POST", f"/api/housekeeping/tasks/{rosa_tasks[0]['id']}/start")
        self.assertEqual(status, 403)
        visible = {t["id"] for t in maid2.ok("GET", "/api/housekeeping/tasks?mine=1")}
        self.assertNotIn(rosa_tasks[0]["id"], visible)

    def test_admin_can_change_role_permissions(self):
        admin = self.client("admin")
        chef = self.client("chef")
        matrix = admin.ok("GET", "/api/roles")
        chef_perms = next(r for r in matrix["roles"] if r["name"] == "chef")["permissions"]
        admin.ok("PUT", "/api/roles/chef", {"permissions": [p for p in chef_perms if p != "menu.manage"]})
        self.assertEqual(chef.req("POST", "/api/menu", {"name": "Koshary", "price": 120})[0], 403)
        admin.ok("PUT", "/api/roles/chef", {"permissions": chef_perms})
        self.assertEqual(chef.req("POST", "/api/menu", {"name": "Koshary", "price": 120})[0], 200)
        self.assertEqual(admin.req("PUT", "/api/roles/admin", {"permissions": []})[0], 400)
        self.assertEqual(admin.req("PUT", "/api/roles/chef", {"permissions": ["root.everything"]})[0], 400)


class AccountRecoveryAnd2FATests(AppTestCase):
    def _outbox_token(self, email):
        db = sqlite3.connect(self.app.config.db_path)
        body = db.execute("SELECT body FROM email_outbox WHERE to_address=? ORDER BY id DESC LIMIT 1", (email,)).fetchone()[0]
        db.close()
        return re.search(r"#reset=([A-Za-z0-9_\-]+)", body).group(1)

    def test_password_reset_flow(self):
        anon = self.client()
        r = anon.ok("POST", "/api/auth/forgot", {"identifier": "rosa.delgado@nileharbor.example"})
        unknown = anon.ok("POST", "/api/auth/forgot", {"identifier": "nobody@example.com"})
        self.assertEqual(r["message"], unknown["message"])  # same answer either way
        token = self._outbox_token("rosa.delgado@nileharbor.example")
        self.assertEqual(anon.req("POST", "/api/auth/reset", {"token": "bogus", "new_password": "Brand-New-55"})[0], 400)
        anon.ok("POST", "/api/auth/reset", {"token": token, "new_password": "Brand-New-55"})
        self.assertEqual(anon.req("POST", "/api/auth/reset", {"token": token, "new_password": "Again-New-66"})[0], 400)  # single use
        self.client().login("maid", "Brand-New-55")
        admin = self.client("admin")
        self.assertTrue(all("#reset=" not in m["body"] for m in admin.ok("GET", "/api/outbox")))

    def test_two_factor_login(self):
        c = self.client("chef")
        setup = c.ok("POST", "/api/auth/2fa/setup")
        self.assertEqual(c.req("POST", "/api/auth/2fa/confirm", {"code": "000000"})[0], 400)
        c.ok("POST", "/api/auth/2fa/confirm", {"code": TOTP.code_at(setup["secret"])})
        anon = self.client()
        status, r = anon.req("POST", "/api/auth/login", {"username": "chef", "password": "ChefPass123"})
        self.assertTrue(r["two_factor_required"])
        self.assertIsNone(anon.cookie)  # no session before the second factor
        self.assertEqual(anon.req("POST", "/api/auth/2fa", {"challenge": r["challenge"], "code": "123456"})[0], 401)
        # the code used to enable 2FA is already consumed; wait-free: use the next step's code
        import time
        code = TOTP.code_at(setup["secret"], time.time() + 30)
        anon.ok("POST", "/api/auth/2fa", {"challenge": r["challenge"], "code": code})
        anon.ok("GET", "/api/kitchen/orders")
        self.assertEqual(Client(self.port).req("POST", "/api/auth/2fa", {"challenge": r["challenge"], "code": code})[0], 401)

    def test_guest_registration(self):
        anon = self.client()
        bad = anon.req("POST", "/api/auth/register", {"first_name": "Mona", "last_name": "Zaki", "email": "mona@example.com",
                                                      "password": "Mona-Pass-2026"})
        self.assertEqual(bad[0], 400)  # privacy notice not accepted
        r = anon.ok("POST", "/api/auth/register", {"first_name": "Mona", "last_name": "Zaki", "email": "mona@example.com",
                                                   "password": "Mona-Pass-2026", "accept_privacy": True})
        self.assertEqual(r["user"]["role"], "guest")
        anon.ok("GET", "/api/portal/profile")
        self.assertEqual(self.client().req("POST", "/api/auth/register", {"first_name": "M", "last_name": "Z", "email": "mona@example.com",
                                                                          "password": "Mona-Pass-2027", "accept_privacy": True})[0], 409)

    def test_privacy_export_and_erasure(self):
        anon = self.client()
        anon.ok("POST", "/api/auth/register", {"first_name": "Erase", "last_name": "Me", "email": "erase.me@example.com",
                                               "password": "Erase-Me-2026", "accept_privacy": True})
        anon.csrf = anon.ok("GET", "/api/auth/me")["csrf_token"]
        data = anon.req("GET", "/api/portal/privacy/export")[1]
        self.assertIn("erase.me@example.com", str(data))
        self.assertEqual(anon.req("DELETE", "/api/portal/account", {"password": "wrong"})[0], 400)
        anon.ok("DELETE", "/api/portal/account", {"password": "Erase-Me-2026"})
        self.assertEqual(anon.req("GET", "/api/portal/profile")[0], 401)
        admin = self.client("admin")
        self.assertFalse(admin.ok("GET", "/api/guests?q=erase.me"))
        self.assertEqual(self.client().req("POST", "/api/auth/login", {"username": "erase.me@example.com", "password": "Erase-Me-2026"})[0], 401)


class AuditTrailTests(AppTestCase):
    def test_actions_are_audited_with_ip(self):
        c = self.client("frontdesk")
        c.ok("POST", "/api/guests", {"first_name": "Audit", "last_name": "Trail"})
        rows = self.client("admin").ok("GET", "/api/audit?q=Audit%20Trail")
        self.assertTrue(any(r["action"] == "guest_create" and r["username"] == "frontdesk" and r["ip"] for r in rows))
        _ = d
