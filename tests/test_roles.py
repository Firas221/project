"""Tests for the manager, accountant, housekeeping supervisor, maintenance technician and storekeeper roles."""
import sqlite3

from support import PASSWORDS, AppTestCase, d  # first: puts the project on sys.path

from hotel.core.permissions import ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS, Perm, Role  # noqa: E402
from hotel.db.seed import DEMO_PASSWORDS, Bootstrapper  # noqa: E402

PASSWORDS.update({u: DEMO_PASSWORDS[u] for u in ("manager", "accountant", "supervisor", "tech", "store")})


class RoleDefinitionTests(AppTestCase):
    def test_every_role_is_complete(self):
        for role in Role.ALL:
            self.assertIn(role, Role.LABELS)
            self.assertIn(role, Role.PORTALS)
        for role in Role.EDITABLE:
            self.assertTrue(DEFAULT_ROLE_PERMISSIONS[role] <= ALL_PERMISSIONS, role)
            for admin_only in (Perm.USERS_MANAGE, Perm.ROLES_MANAGE, Perm.SETTINGS_MANAGE):
                self.assertNotIn(admin_only, DEFAULT_ROLE_PERMISSIONS[role], role)

    def test_each_demo_account_lands_on_its_portal(self):
        expected = {"manager": ("manager", "/manager"), "accountant": ("accountant", "/finance"),
                    "supervisor": ("supervisor", "/housekeeping"), "tech": ("maintenance", "/maintenance"),
                    "store": ("storekeeper", "/store")}
        for username, (role, portal) in expected.items():
            user = self.client().login(username)
            self.assertEqual((user["role"], user["portal"]), (role, portal))
            self.assertEqual(sorted(user["permissions"]), sorted(DEFAULT_ROLE_PERMISSIONS[role]))

    def test_existing_hotels_get_the_new_roles_at_the_next_start(self):
        db = sqlite3.connect(self.app.config.db_path)
        db.execute("DELETE FROM role_permissions WHERE role IN ('manager', 'storekeeper')")
        db.execute("UPDATE role_permissions SET permission='x.custom' WHERE role='chef' AND permission='menu.manage'")
        db.commit()
        db.close()
        with self.app.db.unit_of_work(write=True) as conn:
            Bootstrapper(conn, self.app.hasher).run(False)
        db = sqlite3.connect(self.app.config.db_path)
        perms = lambda role: {r[0] for r in db.execute("SELECT permission FROM role_permissions WHERE role=?", (role,))}  # noqa: E731
        self.assertEqual(perms("manager"), set(DEFAULT_ROLE_PERMISSIONS["manager"]))
        self.assertEqual(perms("storekeeper"), set(DEFAULT_ROLE_PERMISSIONS["storekeeper"]))
        self.assertIn("x.custom", perms("chef"))          # roles the hotel already tuned are left alone
        db.execute("UPDATE role_permissions SET permission='menu.manage' WHERE permission='x.custom'")
        db.commit()
        db.close()

    def test_admin_can_create_users_in_the_new_roles_and_tune_them(self):
        admin = self.client("admin")
        for role in ("manager", "accountant", "supervisor", "maintenance", "storekeeper"):
            made = admin.ok("POST", "/api/users", {"username": f"new.{role}", "full_name": "New Person", "role": role})
            self.assertEqual(made["user"]["role"], role)
        self.assertEqual(admin.req("POST", "/api/users", {"username": "x.y", "full_name": "X", "role": "owner"})[0], 400)
        matrix = {r["name"]: r for r in admin.ok("GET", "/api/roles")["roles"]}
        self.assertTrue(all(matrix[r]["editable"] for r in Role.EDITABLE))
        self.assertFalse(matrix["admin"]["editable"])
        # take a permission away from accountants and give it back
        keep = [p for p in matrix["accountant"]["permissions"] if p != "billing.void"]
        admin.ok("PUT", "/api/roles/accountant", {"permissions": keep})
        self.assertEqual(self.client("accountant").req("POST", "/api/companies", {"name": "Blocked Co"})[0], 403)
        admin.ok("PUT", "/api/roles/accountant", {"permissions": matrix["accountant"]["permissions"]})
        self.client("accountant").ok("POST", "/api/companies", {"name": "Allowed Co"})


class RoleAccessTests(AppTestCase):
    MATRIX = [
        # manager: runs the hotel, but accounts, permissions, settings and backups stay with the administrator
        ("manager", "GET", "/api/dashboard", 200), ("manager", "GET", "/api/reports/summary", 200), ("manager", "GET", "/api/audit", 200),
        ("manager", "GET", "/api/promos", 200), ("manager", "GET", "/api/purchase-orders", 200), ("manager", "GET", "/api/housekeeping/staff", 200),
        ("manager", "GET", "/api/users", 403), ("manager", "GET", "/api/roles", 403), ("manager", "PUT", "/api/settings", 403),
        ("manager", "GET", "/api/backups", 403), ("manager", "POST", "/api/backups", 403), ("manager", "GET", "/api/portal/reservations", 403),
        # accountant: money and reports; can look at reservations and guests but not change them
        ("accountant", "GET", "/api/invoices", 200), ("accountant", "GET", "/api/reports/tax", 200), ("accountant", "GET", "/api/companies", 200),
        ("accountant", "GET", "/api/cashier/shifts", 200), ("accountant", "GET", "/api/reservations", 200), ("accountant", "GET", "/api/guests", 200),
        ("accountant", "GET", "/api/items", 200), ("accountant", "GET", "/api/night-audit", 200), ("accountant", "POST", "/api/night-audit/close", 403),
        ("accountant", "POST", "/api/reservations", 403), ("accountant", "POST", "/api/guests", 403), ("accountant", "GET", "/api/dashboard", 403),
        ("accountant", "GET", "/api/kitchen/orders", 403), ("accountant", "GET", "/api/users", 403), ("accountant", "GET", "/api/audit", 403),
        # housekeeping supervisor
        ("supervisor", "GET", "/api/housekeeping/tasks", 200), ("supervisor", "GET", "/api/housekeeping/staff", 200),
        ("supervisor", "POST", "/api/housekeeping/generate", 200), ("supervisor", "GET", "/api/lost-found", 200), ("supervisor", "GET", "/api/maintenance", 200),
        ("supervisor", "GET", "/api/reservations", 403), ("supervisor", "GET", "/api/guests", 403), ("supervisor", "GET", "/api/items", 403),
        ("supervisor", "GET", "/api/invoices", 403), ("supervisor", "GET", "/api/maintenance/staff", 403),
        # maintenance technician
        ("tech", "GET", "/api/maintenance", 200), ("tech", "GET", "/api/maintenance/staff", 200), ("tech", "GET", "/api/rooms", 200),
        ("tech", "GET", "/api/items/requestable", 200), ("tech", "GET", "/api/reservations", 403), ("tech", "GET", "/api/guests", 403),
        ("tech", "GET", "/api/housekeeping/staff", 403), ("tech", "GET", "/api/items", 403), ("tech", "GET", "/api/kitchen/orders", 403),
        # storekeeper
        ("store", "GET", "/api/items", 200), ("store", "GET", "/api/movements", 200), ("store", "GET", "/api/purchase-orders", 200),
        ("store", "GET", "/api/suppliers", 200), ("store", "GET", "/api/stock-requests", 200), ("store", "GET", "/api/reservations", 403),
        ("store", "GET", "/api/guests", 403), ("store", "GET", "/api/invoices", 403), ("store", "GET", "/api/reports/summary", 403),
        ("store", "GET", "/api/companies", 403), ("store", "GET", "/api/housekeeping/tasks", 403),
        # roles that existed before keep exactly what they had
        ("frontdesk", "POST", "/api/night-audit/close", 403), ("frontdesk", "GET", "/api/companies", 200), ("chef", "GET", "/api/companies", 403),
        ("maid", "GET", "/api/rooms", 200), ("maid", "GET", "/api/maintenance/staff", 403),
    ]

    def test_matrix(self):
        clients = {}
        for user, method, path, expected in self.MATRIX:
            c = clients.get(user) or clients.setdefault(user, self.client(user))
            self.assertEqual(c.req(method, path, {} if method != "GET" else None)[0], expected, f"{user} {method} {path}")

    def test_manager_does_the_managers_work(self):
        manager = self.client("manager")
        res = self.book(manager, 60, 62)
        manager.ok("POST", f"/api/reservations/{res['id']}/charges", {"description": "Flowers", "unit_price": 200, "quantity": 1})
        charge = manager.ok("GET", f"/api/reservations/{res['id']}")["folio"]["charges"][0]
        manager.ok("DELETE", f"/api/reservations/{res['id']}/charges/{charge['id']}")           # void: not for the front desk
        manager.ok("POST", "/api/promos", {"code": "MGR5", "discount_pct": 5, "valid_from": d(0), "valid_to": d(30)})
        day = manager.ok("POST", "/api/night-audit/close", {"mark_no_shows": False})
        self.assertEqual(day["business_date"], d(1))
        entry = next(a for a in manager.ok("GET", "/api/audit") if a["action"] == "night_audit")
        self.assertEqual(entry["username"], "manager")

    def test_accountant_handles_company_money_but_not_bookings(self):
        acc = self.client("accountant")
        co = acc.ok("POST", "/api/companies", {"name": "Ledger Test Ltd", "discount_pct": 5})
        acc.ok("PUT", f"/api/companies/{co['id']}", {"name": "Ledger Test Ltd", "discount_pct": 7})
        res = self.book(self.client("frontdesk"), 70, 72)
        self.assertEqual(acc.ok("GET", f"/api/reservations/{res['id']}")["code"], res["code"])
        self.assertEqual(acc.req("PUT", f"/api/reservations/{res['id']}", {"adults": 2})[0], 403)
        self.assertEqual(acc.req("POST", f"/api/reservations/{res['id']}/cancel")[0], 403)
        self.assertEqual(acc.req("POST", f"/api/reservations/{res['id']}/checkin")[0], 403)
        self.assertIn("ADR", str(acc.ok("GET", "/api/reports/summary")["totals"].keys()).upper())
        self.assertTrue(acc.req("GET", "/api/export/tax")[0] == 200)

    def test_supervisor_assigns_and_inspects_without_cleaning(self):
        sup, maid = self.client("supervisor"), self.client("maid")
        staff = sup.ok("GET", "/api/housekeeping/staff")
        rosa = next(s for s in staff if s["full_name"] == "Rosa Delgado")
        room = sup.ok("GET", "/api/rooms")[-1]
        task = sup.ok("POST", "/api/housekeeping/tasks", {"room_id": room["id"], "kind": "deep_clean", "assigned_to": rosa["id"]})
        self.assertEqual(task["assigned_to"], rosa["id"])
        maid.ok("POST", f"/api/housekeeping/tasks/{task['id']}/start")
        maid.ok("POST", f"/api/housekeeping/tasks/{task['id']}/complete")
        self.assertEqual(maid.req("POST", f"/api/housekeeping/tasks/{task['id']}/inspect", {"passed": True})[0], 403)
        sup.ok("POST", f"/api/housekeeping/tasks/{task['id']}/inspect", {"passed": True})
        self.assertEqual(next(r for r in sup.ok("GET", "/api/rooms") if r["id"] == room["id"])["status"], "inspected")
        sup.ok("POST", f"/api/rooms/{room['id']}/status", {"status": "dirty"})
        self.assertEqual(sup.req("POST", f"/api/rooms/{room['id']}/status", {"status": "maintenance"})[0], 400)   # needs a ticket

    def test_tickets_are_given_to_technicians(self):
        desk, tech = self.client("frontdesk"), self.client("tech")
        ticket = desk.ok("POST", "/api/maintenance", {"location": "Lobby", "title": "Door closer loose"})
        people = desk.ok("GET", "/api/maintenance/staff")
        self.assertEqual([p["full_name"] for p in people], ["Tarek Aziz"])
        rosa = next(u for u in self.client("admin").ok("GET", "/api/users") if u["username"] == "maid")
        self.assertEqual(desk.req("PUT", f"/api/maintenance/{ticket['id']}", {"assigned_to": rosa["id"]})[0], 400)   # not a technician
        desk.ok("PUT", f"/api/maintenance/{ticket['id']}", {"assigned_to": people[0]["id"]})
        mine = next(t for t in tech.ok("GET", "/api/maintenance") if t["id"] == ticket["id"])
        self.assertEqual(mine["assigned_name"], "Tarek Aziz")
        done = tech.ok("PUT", f"/api/maintenance/{ticket['id']}", {"status": "resolved", "resolution": "Tightened"})
        self.assertEqual(done["status"], "resolved")
        desk.ok("PUT", f"/api/maintenance/{ticket['id']}", {"assigned_to": None})
        # a technician takes a room out of order and asks the store for parts
        room = tech.ok("GET", "/api/rooms")[-2]
        broken = tech.ok("POST", "/api/maintenance", {"room_id": room["id"], "title": "No hot water", "out_of_order": True})
        self.assertTrue(broken["out_of_order"])
        item = tech.ok("GET", "/api/items/requestable")[0]
        req = tech.ok("POST", "/api/stock-requests", {"lines": [{"item_id": item["id"], "quantity": 1}]})
        self.assertEqual(req["department"], "maintenance")

    def test_storekeeper_runs_the_store(self):
        store, chef = self.client("store"), self.client("chef")
        item = store.ok("POST", "/api/items", {"sku": "ST-TEST", "name": "Store test item", "unit": "pcs", "department": "kitchen"})
        store.ok("POST", f"/api/items/{item['id']}/movements", {"kind": "receive", "quantity": 10, "unit_cost": 5})
        req = chef.ok("POST", "/api/stock-requests", {"lines": [{"item_id": item["id"], "quantity": 4}]})
        self.assertEqual(chef.req("POST", f"/api/stock-requests/{req['id']}/decide", {"approve": True})[0], 403)
        store.ok("POST", f"/api/stock-requests/{req['id']}/decide", {"approve": True})
        self.assertEqual(store.ok("GET", f"/api/items/{item['id']}")["quantity"], 6)
        supplier = store.ok("POST", "/api/suppliers", {"name": "Store Test Supplies"})
        self.assertTrue(supplier["id"])
