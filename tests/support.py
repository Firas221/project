"""Test harness: runs the real application (HTTP server + SQLite) on a temporary database."""
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

from hotel.app import HotelApp  # noqa: E402
from hotel.config import Config  # noqa: E402

TODAY = dt.date.today()
PASSWORDS = {"admin": "AdminPass123", "frontdesk": "FrontDesk123", "chef": "ChefPass123", "maid": "MaidPass123",
             "maid2": "MaidPass123", "amelia.hart@example.com": "GuestPass123", "manager": "ManagerPass123",
             "accountant": "AccountPass123", "supervisor": "SuperPass123", "tech": "TechPass123", "store": "StorePass123"}


def d(offset: int) -> str:
    return (TODAY + dt.timedelta(days=offset)).isoformat()


class Client:
    """A browser-like client: keeps the session cookie and sends the CSRF header."""

    def __init__(self, port: int):
        self.port, self.cookie, self.csrf = port, None, None

    def req(self, method, path, body=None, headers=None, csrf=True, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        h = dict(headers or {})
        data = raw
        if body is not None:
            data = json.dumps(body)
            h.setdefault("Content-Type", "application/json")
        if self.cookie:
            h["Cookie"] = self.cookie
        if csrf and self.csrf and method != "GET":
            h["X-CSRF-Token"] = self.csrf
        conn.request(method, path, data, h)
        r = conn.getresponse()
        payload = r.read()
        set_cookie = r.getheader("Set-Cookie")
        if set_cookie:
            value = set_cookie.split(";")[0]
            self.cookie = None if value.endswith("=") else value
        self.last_headers = dict(r.getheaders())
        conn.close()
        ctype = r.getheader("Content-Type") or ""
        if "json" in ctype:
            payload = json.loads(payload or b"null")
        else:
            payload = payload.decode("utf-8-sig", "replace")
        return r.status, payload

    def ok(self, method, path, body=None):
        status, data = self.req(method, path, body)
        assert status in (200, 201), f"{method} {path} -> {status}: {data}"
        return data

    def login(self, username, password=None):
        status, data = self.req("POST", "/api/auth/login", {"username": username, "password": password or PASSWORDS[username]})
        assert status == 200, f"login {username} -> {status}: {data}"
        self.csrf = data["csrf_token"]
        return data["user"]


class AppTestCase(unittest.TestCase):
    """Starts one server per test class with fresh demo data."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cfg = Config.from_env(db_path=os.path.join(cls.tmp, "test.db"), port=0, pbkdf2_iterations=2000,
                              backup_dir=os.path.join(cls.tmp, "backups"), api_limit_per_minute=100000,
                              login_ip_limit_per_minute=1000, public_limit_per_minute=10000)
        cls.app = HotelApp(cfg)
        cls.app.initialize()
        cls.server = cls.app.make_server()
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.app.limiter.reset()

    def client(self, user=None) -> Client:
        c = Client(self.port)
        if user:
            c.login(user)
        return c

    # ---------------------------------------------------------------- domain helpers
    def free_room(self, c, ci, co, guests=1):
        rooms = c.ok("GET", f"/api/availability?check_in={ci}&check_out={co}&guests={guests}")
        self.assertTrue(rooms, "expected a free room")
        return rooms[0]

    def book(self, c, ci_off=10, co_off=12, **extra):
        ci, co = d(ci_off), d(co_off)
        room = extra.pop("room", None) or self.free_room(c, ci, co)
        body = {"guest": {"first_name": "Test", "last_name": "Guest", "nationality": "German", "id_number": "X123"},
                "room_id": room["id"], "check_in": ci, "check_out": co, "adults": 1}
        body.update(extra)
        return c.ok("POST", "/api/reservations", body)

    def check_in_today(self, c, nights=2, **extra):
        res = self.book(c, 0, nights, **extra)
        c.ok("POST", f"/api/rooms/{res['room_id']}/status", {"status": "clean"})
        return c.ok("POST", f"/api/reservations/{res['id']}/checkin")
