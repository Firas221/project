"""Tests for staff rosters and attendance."""
import sqlite3

from support import AppTestCase, d  # first: puts the project on sys.path

from hotel.services.roster import shift_hours, worked_hours  # noqa: E402


class RosterTests(AppTestCase):
    def _user(self, c, username):
        return next(u for u in c.ok("GET", "/api/roster")["staff"] if u["full_name"] == username)

    def test_hours(self):
        self.assertEqual(shift_hours("08:00", "16:00"), 8)
        self.assertEqual(shift_hours("22:00", "06:00"), 8)          # past midnight
        self.assertEqual(shift_hours("09:30", "13:00"), 3.5)
        self.assertEqual(worked_hours("2026-01-01 08:00:00", "2026-01-01 16:30:00"), 8.5)
        self.assertEqual(worked_hours("2026-01-01 22:00:00", "2026-01-02 06:00:00"), 8)
        self.assertEqual(worked_hours("2026-01-01 08:00:00", None), 0)

    def test_manager_plans_a_week_and_staff_see_their_own_shifts(self):
        manager, maid, chef = self.client("manager"), self.client("maid"), self.client("chef")
        rosa = self._user(manager, "Rosa Delgado")
        shift = manager.ok("POST", "/api/roster", {"user_id": rosa["id"], "work_date": d(1), "start_time": "08:00", "end_time": "16:00", "note": "Floor 2"})
        manager.ok("POST", "/api/roster", {"user_id": rosa["id"], "work_date": d(2), "start_time": "22:00", "end_time": "06:00"})
        week = manager.ok("GET", f"/api/roster?from={d(1)}&days=7")
        mine = [s for s in week["shifts"] if s["user_id"] == rosa["id"]]
        self.assertEqual([(s["work_date"], s["hours"]) for s in mine], [(d(1), 8), (d(2), 8)])
        self.assertEqual(next(t for t in week["attendance"]["totals"] if t["user_id"] == rosa["id"])["planned_hours"], 16)
        # Rosa sees them, is told about them, and nobody else's
        seen = maid.ok("GET", "/api/roster/mine")
        self.assertEqual([(s["work_date"], s["start_time"], s["note"]) for s in seen["shifts"]], [(d(1), "08:00", "Floor 2"), (d(2), "22:00", "")])
        self.assertEqual(maid.ok("GET", "/api/alerts")["items"][0]["title"], "You have a new shift")
        self.assertEqual(chef.ok("GET", "/api/roster/mine")["shifts"], [])
        # change and remove
        manager.ok("PUT", f"/api/roster/{shift['id']}", {"user_id": rosa["id"], "work_date": d(1), "start_time": "10:00", "end_time": "18:00"})
        self.assertEqual(maid.ok("GET", "/api/roster/mine")["shifts"][0]["start_time"], "10:00")
        manager.ok("DELETE", f"/api/roster/{shift['id']}")
        self.assertEqual(len(maid.ok("GET", "/api/roster/mine")["shifts"]), 1)
        self.assertEqual(maid.ok("GET", "/api/alerts")["items"][0]["title"], "A shift of yours was removed")

    def test_rules_and_access(self):
        manager = self.client("manager")
        rosa = self._user(manager, "Rosa Delgado")
        ok = {"user_id": rosa["id"], "work_date": d(3), "start_time": "08:00", "end_time": "16:00"}
        self.assertEqual(manager.req("POST", "/api/roster", {**ok, "end_time": "08:00"})[0], 400)        # no length
        self.assertEqual(manager.req("POST", "/api/roster", {**ok, "start_time": "25:00"})[0], 400)
        self.assertEqual(manager.req("POST", "/api/roster", {**ok, "user_id": 99999})[0], 400)
        guest = next(u for u in self.client("admin").ok("GET", "/api/users?role=guest"))
        self.assertEqual(manager.req("POST", "/api/roster", {**ok, "user_id": guest["id"]})[0], 400)      # guests are not staff
        for who in ("frontdesk", "supervisor", "accountant", "maid"):
            c = self.client(who)
            self.assertEqual(c.req("GET", "/api/roster")[0], 403, who)
            self.assertEqual(c.req("POST", "/api/roster", ok)[0], 403, who)
            self.assertEqual(c.req("GET", "/api/roster/mine")[0], 200, who)                               # everyone has their own
        self.assertEqual(self.client("amelia.hart@example.com").req("GET", "/api/roster/mine")[0], 403)
        self.client("admin").ok("GET", "/api/roster")

    def test_copy_last_week(self):
        manager = self.client("manager")
        rosa, marco = self._user(manager, "Rosa Delgado"), self._user(manager, "Marco Bellini")
        manager.ok("POST", "/api/roster", {"user_id": rosa["id"], "work_date": d(20), "start_time": "08:00", "end_time": "16:00"})
        manager.ok("POST", "/api/roster", {"user_id": marco["id"], "work_date": d(22), "start_time": "12:00", "end_time": "20:00"})
        manager.ok("POST", "/api/roster", {"user_id": rosa["id"], "work_date": d(27), "start_time": "08:00", "end_time": "16:00"})   # already there
        self.assertEqual(manager.ok("POST", "/api/roster/copy-week", {"from": d(20), "to": d(27)})["copied"], 1)
        next_week = manager.ok("GET", f"/api/roster?from={d(27)}&days=7")["shifts"]
        self.assertEqual(sorted((s["user_name"], s["work_date"]) for s in next_week), [("Marco Bellini", d(29)), ("Rosa Delgado", d(27))])
        self.assertEqual(manager.ok("POST", "/api/roster/copy-week", {"from": d(20), "to": d(27)})["copied"], 0)   # nothing twice
        self.assertEqual(manager.req("POST", "/api/roster/copy-week", {"from": d(20), "to": d(20)})[0], 400)


class AttendanceTests(AppTestCase):
    def test_clock_in_and_out(self):
        chef = self.client("chef")
        self.assertIsNone(chef.ok("GET", "/api/roster/mine")["open"])
        self.assertEqual(chef.req("POST", "/api/attendance/clock-out")[0], 409)
        started = chef.ok("POST", "/api/attendance/clock-in")
        self.assertIsNotNone(started["open"])
        self.assertEqual(chef.req("POST", "/api/attendance/clock-in")[0], 409)       # not twice
        manager = self.client("manager")
        totals = manager.ok("GET", f"/api/roster?from={d(0)}&days=1")["attendance"]["totals"]
        self.assertTrue(next(t for t in totals if t["full_name"] == "Marco Bellini")["on_the_clock"])
        ended = chef.ok("POST", "/api/attendance/clock-out")
        self.assertIsNone(ended["open"])
        self.assertEqual(len(ended["attendance"]), 1)
        self.assertIsNotNone(ended["attendance"][0]["clock_out"])
        self.assertEqual(self.client("amelia.hart@example.com").req("POST", "/api/attendance/clock-in")[0], 403)

    def test_manager_corrects_a_forgotten_clock_out_and_sees_worked_against_planned(self):
        manager, maid = self.client("manager"), self.client("maid")
        rosa = next(u for u in manager.ok("GET", "/api/roster")["staff"] if u["full_name"] == "Rosa Delgado")
        manager.ok("POST", "/api/roster", {"user_id": rosa["id"], "work_date": d(0), "start_time": "08:00", "end_time": "16:00"})
        maid.ok("POST", "/api/attendance/clock-in")
        records = manager.ok("GET", f"/api/roster?from={d(0)}&days=1")["attendance"]["records"]
        record = next(r for r in records if r["user_id"] == rosa["id"])
        url = f"/api/attendance/{record['id']}"
        self.assertEqual(maid.req("PUT", url, {"clock_in": f"{d(0)}T08:00", "clock_out": f"{d(0)}T14:30"})[0], 403)   # not your own record
        self.assertEqual(manager.req("PUT", url, {"clock_in": f"{d(0)}T08:00", "clock_out": f"{d(0)}T07:00"})[0], 400)
        self.assertEqual(manager.req("PUT", url, {"clock_in": f"{d(-3)}T08:00", "clock_out": f"{d(0)}T07:00"})[0], 400)   # over 24 h
        self.assertEqual(manager.req("PUT", url, {"clock_in": "yesterday", "clock_out": ""})[0], 400)
        fixed = manager.ok("PUT", url, {"clock_in": f"{d(0)}T08:00", "clock_out": f"{d(0)}T14:30"})
        self.assertEqual((fixed["clock_in"], fixed["clock_out"]), (f"{d(0)} 08:00:00", f"{d(0)} 14:30:00"))
        total = next(t for t in manager.ok("GET", f"/api/roster?from={d(0)}&days=1")["attendance"]["totals"] if t["user_id"] == rosa["id"])
        self.assertEqual((total["planned_hours"], total["worked_hours"], total["on_the_clock"]), (8, 6.5, False))
        self.assertIsNone(maid.ok("GET", "/api/roster/mine")["open"])
        self.assertTrue(any(a["action"] == "attendance_correct" for a in manager.ok("GET", "/api/audit")))
        self.assertEqual(manager.req("PUT", "/api/attendance/99999", {"clock_in": f"{d(0)}T08:00"})[0], 404)

    def test_deleting_a_user_removes_their_shifts_and_clock_records(self):
        admin = self.client("admin")
        made = admin.ok("POST", "/api/users", {"username": "short.stay", "full_name": "Short Stay", "role": "chef", "password": "Short-Stay-2026"})
        admin.ok("POST", "/api/roster", {"user_id": made["user"]["id"], "work_date": d(5), "start_time": "08:00", "end_time": "12:00"})
        admin.ok("DELETE", f"/api/users/{made['user']['id']}")
        db = sqlite3.connect(self.app.config.db_path)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM roster_shifts WHERE user_id=?", (made["user"]["id"],)).fetchone()[0], 0)
        db.close()
