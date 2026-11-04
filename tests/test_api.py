"""End-to-end tests: start the real HTTP server on a temp DB and exercise the API."""
import datetime as dt
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hotel import api  # noqa: E402
from hotel.server import make_server  # noqa: E402

TODAY = dt.date.today()


def d(offset):
    return (TODAY + dt.timedelta(days=offset)).isoformat()


class Client:
    def __init__(self, port):
        self.port = port
        self.cookie = None

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {}
        data = None
        if body is not None:
            data = json.dumps(body)
            headers["Content-Type"] = "application/json"
        if self.cookie:
            headers["Cookie"] = self.cookie
        conn.request(method, path, data, headers)
        r = conn.getresponse()
        raw = r.read()
        sc = r.getheader("Set-Cookie")
        if sc:
            self.cookie = sc.split(";")[0]
        conn.close()
        ctype = r.getheader("Content-Type") or ""
        return r.status, (json.loads(raw) if "json" in ctype else raw.decode("utf-8-sig"))

    def ok(self, method, path, body=None):
        status, data = self.req(method, path, body)
        assert status in (200, 201), f"{method} {path} -> {status}: {data}"
        return data

    def login(self, user="admin", pw="admin123"):
        return self.ok("POST", "/api/login", {"username": user, "password": pw})


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.server = make_server(os.path.join(cls.tmp, "test.db"), port=0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        api._failed.clear()
        self.c = Client(self.port)
        self.c.login()

    # ---------------------------------------------------------------- helpers
    def free_room(self, ci, co, guests=1):
        rooms = self.c.ok("GET", f"/api/availability?check_in={ci}&check_out={co}&guests={guests}")
        self.assertTrue(rooms, "expected an available room")
        return rooms[0]

    def book(self, ci_off=10, co_off=12, **extra):
        ci, co = d(ci_off), d(co_off)
        room = extra.pop("room", None) or self.free_room(ci, co)
        body = {"guest": {"first_name": "Test", "last_name": "Guest"}, "room_id": room["id"],
                "check_in": ci, "check_out": co, "adults": 1}
        body.update(extra)
        return self.c.ok("POST", "/api/reservations", body)

    # ---------------------------------------------------------------- auth
    def test_auth_required_and_bad_login(self):
        anon = Client(self.port)
        self.assertEqual(anon.req("GET", "/api/dashboard")[0], 401)
        self.assertEqual(anon.req("POST", "/api/login", {"username": "admin", "password": "nope"})[0], 401)
        self.assertEqual(anon.req("GET", "/api/nope")[0], 404)

    def test_login_lockout(self):
        anon = Client(self.port)
        for _ in range(5):
            anon.req("POST", "/api/login", {"username": "frontdesk", "password": "x"})
        self.assertEqual(anon.req("POST", "/api/login", {"username": "frontdesk", "password": "front123"})[0], 429)

    def test_staff_cannot_use_admin_endpoints(self):
        staff = Client(self.port)
        staff.login("frontdesk", "front123")
        self.assertEqual(staff.req("GET", "/api/users")[0], 403)
        self.assertEqual(staff.req("PUT", "/api/settings", {"tax_rate": 5})[0], 403)
        self.assertEqual(staff.req("GET", "/api/rooms")[0], 200)

    def test_logout(self):
        self.c.ok("POST", "/api/logout")
        self.assertEqual(self.c.req("GET", "/api/me")[0], 401)

    # ---------------------------------------------------------------- reservations
    def test_create_and_prevent_double_booking(self):
        res = self.book(20, 23)
        self.assertEqual(res["status"], "booked")
        self.assertEqual(res["folio"]["nights"], 3)
        # overlapping booking in the same room is rejected
        status, err = self.c.req("POST", "/api/reservations", {
            "guest_id": res["guest_id"], "room_id": res["room_id"], "check_in": d(22), "check_out": d(25)})
        self.assertEqual(status, 409, err)
        # back-to-back booking is allowed (check-out day == next check-in day)
        self.c.ok("POST", "/api/reservations", {
            "guest_id": res["guest_id"], "room_id": res["room_id"], "check_in": d(23), "check_out": d(24)})
        # availability excludes the room
        avail = self.c.ok("GET", f"/api/availability?check_in={d(21)}&check_out={d(22)}")
        self.assertNotIn(res["room_id"], [r["id"] for r in avail])

    def test_validation(self):
        room = self.free_room(d(30), d(31))
        bad = [
            {"guest_id": 1, "room_id": room["id"], "check_in": d(31), "check_out": d(30)},
            {"guest_id": 1, "room_id": room["id"], "check_in": "nope", "check_out": d(30)},
            {"guest_id": 1, "room_id": room["id"], "check_in": d(30), "check_out": d(31), "adults": 9},
            {"room_id": room["id"], "check_in": d(30), "check_out": d(31)},
            {"guest_id": 1, "room_id": 99999, "check_in": d(30), "check_out": d(31)},
        ]
        for body in bad:
            status, _ = self.c.req("POST", "/api/reservations", body)
            self.assertIn(status, (400, 404), body)

    def test_full_stay_lifecycle_with_inventory(self):
        res = self.book(0, 2, deposit=50, deposit_method="cash")
        rid = res["id"]
        self.c.ok("POST", f"/api/rooms/{res['room_id']}/status", {"status": "clean"})
        res = self.c.ok("POST", f"/api/reservations/{rid}/checkin")
        self.assertEqual(res["status"], "checked_in")

        items = self.c.ok("GET", "/api/items?chargeable=1")
        water = next(i for i in items if i["sku"] == "MB-WATER")
        res = self.c.ok("POST", f"/api/reservations/{rid}/charges", {"item_id": water["id"], "quantity": 3})
        after = self.c.ok("GET", f"/api/items/{water['id']}")
        self.assertEqual(after["quantity"], water["quantity"] - 3)
        self.assertEqual(after["movements"][0]["kind"], "sale")

        res = self.c.ok("POST", f"/api/reservations/{rid}/charges",
                        {"description": "Laundry", "unit_price": 12.5, "quantity": 2})
        f = res["folio"]
        expected_sub = round(res["rate"] * 2 + 3 * water["price"] + 25, 2)
        self.assertAlmostEqual(f["subtotal"], expected_sub, places=2)
        self.assertAlmostEqual(f["total"], round(expected_sub * 1.1, 2), places=2)
        self.assertAlmostEqual(f["balance"], round(f["total"] - 50, 2), places=2)

        # void the water charge -> stock restored
        charge = next(c for c in f["charges"] if c["item_id"] == water["id"])
        self.c.ok("DELETE", f"/api/reservations/{rid}/charges/{charge['id']}")
        self.assertEqual(self.c.ok("GET", f"/api/items/{water['id']}")["quantity"], water["quantity"])

        # cannot check out with balance
        self.assertEqual(self.c.req("POST", f"/api/reservations/{rid}/checkout")[0], 409)
        bal = self.c.ok("GET", f"/api/reservations/{rid}")["folio"]["balance"]
        self.c.ok("POST", f"/api/reservations/{rid}/payments", {"amount": bal, "method": "card"})
        res = self.c.ok("POST", f"/api/reservations/{rid}/checkout")
        self.assertEqual(res["status"], "checked_out")
        self.assertEqual(res["folio"]["balance"], 0)
        room = next(r for r in self.c.ok("GET", "/api/rooms") if r["id"] == res["room_id"])
        self.assertEqual(room["status"], "dirty")
        # closed folio is read-only
        self.assertEqual(self.c.req("POST", f"/api/reservations/{rid}/payments", {"amount": 1, "method": "cash"})[0], 409)

    def test_checkin_rules(self):
        future = self.book(15, 16)
        self.assertEqual(self.c.req("POST", f"/api/reservations/{future['id']}/checkin")[0], 409)
        today = self.book(0, 1)
        self.c.ok("POST", f"/api/rooms/{today['room_id']}/status", {"status": "dirty"})
        self.assertEqual(self.c.req("POST", f"/api/reservations/{today['id']}/checkin")[0], 409)
        self.c.ok("POST", f"/api/reservations/{today['id']}/checkin", {"force": True})

    def test_cancel_and_noshow(self):
        res = self.book(40, 42)
        res = self.c.ok("POST", f"/api/reservations/{res['id']}/cancel", {"fee": 30, "reason": "Plans changed"})
        self.assertEqual(res["status"], "cancelled")
        self.assertEqual(res["folio"]["room_total"], 0)
        self.assertAlmostEqual(res["folio"]["total"], 33.0)
        # the room is free again
        avail = self.c.ok("GET", f"/api/availability?check_in={d(40)}&check_out={d(42)}")
        self.assertIn(res["room_id"], [r["id"] for r in avail])
        self.assertEqual(self.c.req("POST", f"/api/reservations/{res['id']}/checkin")[0], 409)
        future = self.book(44, 45)
        self.assertEqual(self.c.req("POST", f"/api/reservations/{future['id']}/noshow")[0], 409)

    def test_modify_and_move(self):
        res = self.book(50, 52)
        upd = self.c.ok("PUT", f"/api/reservations/{res['id']}", {"check_out": d(54), "rate": 99})
        self.assertEqual(upd["folio"]["nights"], 4)
        self.assertEqual(upd["folio"]["room_total"], 396)
        other = [r for r in self.c.ok("GET", f"/api/availability?check_in={d(50)}&check_out={d(54)}")
                 if r["id"] != res["room_id"]][0]
        moved = self.c.ok("POST", f"/api/reservations/{res['id']}/move", {"room_id": other["id"]})
        self.assertEqual(moved["room_id"], other["id"])

    def test_early_departure(self):
        res = self.book(0, 4)
        self.c.ok("POST", f"/api/rooms/{res['room_id']}/status", {"status": "clean"})
        self.c.ok("POST", f"/api/reservations/{res['id']}/checkin")
        res = self.c.ok("POST", f"/api/reservations/{res['id']}/checkout", {"early_departure": True, "force": True})
        self.assertEqual(res["folio"]["nights"], 1)

    # ---------------------------------------------------------------- inventory
    def test_inventory_movements(self):
        item = self.c.ok("POST", "/api/items", {"sku": "t-1", "name": "Test Item", "quantity": 10, "cost": 2,
                                                 "reorder_level": 5})
        self.assertEqual(item["sku"], "T-1")
        item = self.c.ok("POST", f"/api/items/{item['id']}/movements", {"kind": "receive", "quantity": 10, "unit_cost": 4})
        self.assertEqual(item["quantity"], 20)
        self.assertEqual(item["cost"], 3)  # weighted average
        item = self.c.ok("POST", f"/api/items/{item['id']}/movements", {"kind": "issue", "quantity": 16})
        self.assertEqual(item["quantity"], 4)
        self.assertEqual(item["low_stock"], 1)
        self.assertEqual(self.c.req("POST", f"/api/items/{item['id']}/movements", {"kind": "issue", "quantity": 5})[0], 409)
        self.assertEqual(self.c.req("POST", f"/api/items/{item['id']}/movements", {"kind": "adjust", "counted": 7})[0], 400)
        item = self.c.ok("POST", f"/api/items/{item['id']}/movements",
                         {"kind": "adjust", "counted": 7, "reason": "Stock count"})
        self.assertEqual(item["quantity"], 7)
        moves = self.c.ok("GET", f"/api/movements?item_id={item['id']}")
        self.assertEqual([m["kind"] for m in moves], ["adjust", "issue", "receive", "receive"])
        self.assertEqual(self.c.req("POST", "/api/items", {"sku": "T-1", "name": "dup"})[0], 409)
        # non-chargeable items cannot be posted to a folio
        res = self.book(60, 61)
        self.assertEqual(self.c.req("POST", f"/api/reservations/{res['id']}/charges", {"item_id": item["id"]})[0], 400)

    # ---------------------------------------------------------------- misc
    def test_dashboard_reports_exports(self):
        dash = self.c.ok("GET", "/api/dashboard")
        self.assertGreater(dash["rooms"]["total"], 0)
        rep = self.c.ok("GET", f"/api/reports/summary?from={d(-14)}&to={d(0)}")
        self.assertEqual(len(rep["daily"]), 15)
        self.assertGreater(rep["totals"]["room_revenue"], 0)
        for name in ("reservations", "guests", "items", "movements", "daily_report"):
            status, body = self.c.req("GET", f"/api/export/{name}.csv")
            self.assertEqual(status, 200)
            self.assertGreater(len(body.splitlines()), 1)
        cal = self.c.ok("GET", f"/api/calendar?start={d(-3)}&days=14")
        self.assertTrue(cal["reservations"])

    def test_guest_crud_and_users(self):
        g = self.c.ok("POST", "/api/guests", {"first_name": "Zed", "last_name": "Lane", "email": "zed@example.com"})
        self.assertEqual(self.c.req("POST", "/api/guests", {"first_name": "X", "last_name": "Y", "email": "bad"})[0], 400)
        self.assertEqual(len(self.c.ok("GET", "/api/guests?q=Zed%20Lane")), 1)
        self.c.ok("PUT", f"/api/guests/{g['id']}", dict(g, phone="123"))
        self.c.ok("DELETE", f"/api/guests/{g['id']}")
        u = self.c.ok("POST", "/api/users", {"username": "temp.user", "full_name": "Temp", "role": "staff",
                                             "password": "secret1"})
        Client(self.port).login("temp.user", "secret1")
        self.c.ok("PUT", f"/api/users/{u['id']}", {"full_name": "Temp", "role": "staff", "active": False})
        self.assertEqual(Client(self.port).req("POST", "/api/login", {"username": "temp.user", "password": "secret1"})[0], 401)
        me = self.c.ok("GET", "/api/me")
        self.assertEqual(self.c.req("PUT", f"/api/users/{me['id']}", {"full_name": "A", "role": "staff"})[0], 400)

    def test_rooms_admin(self):
        types = self.c.ok("GET", "/api/room-types")
        room = self.c.ok("POST", "/api/rooms", {"number": "999", "floor": 9, "type_id": types[0]["id"]})
        self.assertEqual(self.c.req("POST", "/api/rooms", {"number": "999", "type_id": types[0]["id"]})[0], 409)
        self.c.ok("POST", f"/api/rooms/{room['id']}/status", {"status": "maintenance"})
        avail = self.c.ok("GET", f"/api/availability?check_in={d(70)}&check_out={d(71)}")
        self.assertNotIn(room["id"], [r["id"] for r in avail])
        self.c.ok("DELETE", f"/api/rooms/{room['id']}")
        self.assertEqual(self.c.req("DELETE", f"/api/room-types/{types[0]['id']}")[0], 409)

    def test_static_gui_served(self):
        status, body = Client(self.port).req("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("<html", body)
        self.assertEqual(Client(self.port).req("GET", "/../hotel/db.py")[0], 404)


if __name__ == "__main__":
    unittest.main()
