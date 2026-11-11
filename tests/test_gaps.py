"""Tests for rate plans, guests changing their own bookings, paged lists, e-mail language, arrival reminders
and the scheduled stay-over tasks."""
import datetime as dt
import sqlite3

from support import AppTestCase, d  # first: puts the project on sys.path

from hotel.infrastructure.mailer import to_html  # noqa: E402


def outbox(app, to=None):
    db = sqlite3.connect(app.config.db_path)
    db.row_factory = sqlite3.Row
    sql = "SELECT * FROM email_outbox" + (" WHERE to_address=?" if to else "") + " ORDER BY id"
    rows = [dict(r) for r in db.execute(sql, (to,) if to else ())]
    db.close()
    return rows


class RatePlanTests(AppTestCase):
    def test_meal_supplement_and_discount_pricing(self):
        admin = self.client("admin")
        plans = {p["name"]: p for p in admin.ok("GET", "/api/rate-plans")}
        bb, saver = plans["Bed & breakfast"], plans["Non-refundable saver"]
        tid = admin.ok("GET", "/api/room-types")[1]["id"]
        ci, co = d(300), d(302)                                    # far from any season, promo or weekend surprise
        q = f"/api/quote?room_type_id={tid}&check_in={ci}&check_out={co}"
        base = admin.ok("GET", q)
        with_bb = admin.ok("GET", q + f"&rate_plan_id={bb['id']}&adults=2&children=1")
        self.assertAlmostEqual(with_bb["total"], base["total"] + 2 * (2 * 350 + 175), places=2)
        self.assertEqual(with_bb["rate_plan"]["meal_plan"], "breakfast")
        cheaper = admin.ok("GET", q + f"&rate_plan_id={saver['id']}")
        self.assertAlmostEqual(cheaper["total"], round(sum(round(n["rate"] * 0.9, 2) for n in base["nightly"]), 2), places=2)
        self.assertFalse(cheaper["rate_plan"]["refundable"])

    def test_booking_keeps_a_copy_of_the_plan(self):
        admin = self.client("admin")
        plan = admin.ok("POST", "/api/rate-plans", {"name": "Half board test", "meal_plan": "half_board", "per_adult": 600})
        res = self.book(admin, 310, 312, rate_plan_id=plan["id"], adults=1)
        self.assertEqual((res["rate_plan_name"], res["meal_plan"], res["refundable"]), ("Half board test", "half_board", 1))
        without = self.book(admin, 310, 312, room={"id": res["room_id"] + 1})
        self.assertAlmostEqual(res["rate"], without["rate"] + 600, places=2)
        # a second adult is priced in when the party changes
        room = admin.ok("GET", f"/api/rooms")
        capacity = next(r["capacity"] for r in room if r["id"] == res["room_id"])
        if capacity >= 2:
            bigger = admin.ok("PUT", f"/api/reservations/{res['id']}", {"adults": 2})
            self.assertAlmostEqual(bigger["rate"], res["rate"] + 600, places=2)
        # editing or deleting the plan later does not touch the booking
        admin.ok("PUT", f"/api/rate-plans/{plan['id']}", {"name": "Half board test", "meal_plan": "half_board", "per_adult": 900})
        admin.ok("DELETE", f"/api/rate-plans/{plan['id']}")
        after = admin.ok("GET", f"/api/reservations/{res['id']}")
        self.assertEqual((after["rate_plan_name"], after["meal_plan"], after["rate_plan_id"]), ("Half board test", "half_board", None))

    def test_management_rules(self):
        admin = self.client("admin")
        self.assertEqual(admin.req("POST", "/api/rate-plans", {"name": "Bed & breakfast"})[0], 409)       # duplicate name
        self.assertEqual(admin.req("POST", "/api/rate-plans", {"name": "X", "meal_plan": "all_inclusive"})[0], 400)
        self.assertEqual(admin.req("POST", "/api/rate-plans", {"name": "X", "per_adult": -5})[0], 400)
        self.assertEqual(self.client("frontdesk").req("POST", "/api/rate-plans", {"name": "Y"})[0], 403)
        self.client("frontdesk").ok("GET", "/api/rate-plans")                                               # can pick one
        hidden = admin.ok("POST", "/api/rate-plans", {"name": "Desk only", "online": False})
        off = admin.ok("POST", "/api/rate-plans", {"name": "Retired", "active": False})
        self.assertNotIn("Retired", [p["name"] for p in admin.ok("GET", "/api/rate-plans")])
        self.assertIn("Retired", [p["name"] for p in admin.ok("GET", "/api/rate-plans?all=1")])
        self.assertEqual(self.book_status(admin, off["id"]), 400)
        guest = self.client("amelia.hart@example.com")
        offers = guest.ok("POST", "/api/public/search", {"check_in": d(320), "check_out": d(322)})["offers"]
        names = [p["name"] for p in offers[0]["plans"]]
        self.assertIn("Bed & breakfast", names)
        self.assertNotIn("Desk only", names)
        self.assertEqual(guest.req("POST", "/api/portal/reservations", {
            "room_type_id": offers[0]["id"], "check_in": d(320), "check_out": d(322), "rate_plan_id": hidden["id"]})[0], 400)

    def book_status(self, c, plan_id):
        room = self.free_room(c, d(330), d(331))
        return c.req("POST", "/api/reservations", {"guest": {"first_name": "A", "last_name": "B"}, "room_id": room["id"],
                                                   "check_in": d(330), "check_out": d(331), "rate_plan_id": plan_id})[0]

    def test_non_refundable_bookings_cannot_be_cancelled_or_changed_online(self):
        guest = self.client("amelia.hart@example.com")
        offer = guest.ok("POST", "/api/public/search", {"check_in": d(340), "check_out": d(342), "adults": 2})["offers"][0]
        saver = next(p for p in offer["plans"] if not p["refundable"])
        self.assertLess(saver["quote"]["total"], offer["quote"]["total"])
        res = guest.ok("POST", "/api/portal/reservations", {"room_type_id": offer["id"], "check_in": d(340), "check_out": d(342),
                                                            "adults": 2, "rate_plan_id": saver["id"]})
        self.assertEqual((res["refundable"], res["can_cancel"], res["can_change"]), (0, False, False))
        self.assertAlmostEqual(res["rate"], saver["quote"]["average_rate"], places=2)
        status, err = guest.req("POST", f"/api/portal/reservations/{res['id']}/cancel")
        self.assertEqual(status, 409)
        self.assertIn("non-refundable", err["error"])
        self.assertEqual(guest.req("POST", f"/api/portal/reservations/{res['id']}/change",
                                   {"check_in": d(341), "check_out": d(343), "adults": 2})[0], 409)
        self.client("frontdesk").ok("POST", f"/api/reservations/{res['id']}/cancel")        # the desk still can


class GuestChangeTests(AppTestCase):
    serial = 0

    def _guest(self):
        """A brand-new guest account (each one may hold only a few active online bookings)."""
        GuestChangeTests.serial += 1
        email = f"changer{GuestChangeTests.serial}@example.com"
        c = self.client()
        r = c.ok("POST", "/api/auth/register", {"first_name": "Chan", "last_name": "Ger", "email": email,
                                                "password": "Changer-Pass-2026", "accept_privacy": True})
        c.csrf, c.email = r["csrf_token"], email
        return c

    def _book(self, guest, ci, co, **extra):
        offer = guest.ok("POST", "/api/public/search", {"check_in": d(ci), "check_out": d(co), "adults": 2})["offers"][0]
        return guest.ok("POST", "/api/portal/reservations", {"room_type_id": offer["id"], "check_in": d(ci), "check_out": d(co),
                                                             "adults": 2, **extra})

    def test_preview_then_change_dates(self):
        guest = self._guest()
        res = self._book(guest, 200, 202)
        self.assertTrue(res["can_change"])
        new = {"check_in": d(205), "check_out": d(208), "adults": 2}
        preview = guest.ok("POST", f"/api/portal/reservations/{res['id']}/change", {**new, "preview": True})["preview"]
        self.assertEqual(preview["nights"], 3)
        self.assertEqual(guest.ok("GET", f"/api/portal/reservations/{res['id']}")["check_in"], d(200))   # nothing saved yet
        changed = guest.ok("POST", f"/api/portal/reservations/{res['id']}/change", new)
        self.assertEqual((changed["check_in"], changed["check_out"], changed["nights"]), (d(205), d(208), 3))
        self.assertAlmostEqual(changed["folio"]["total"], preview["total"], places=2)
        self.assertEqual(outbox(self.app, guest.email)[-1]["subject"], f"Your booking {res['code']} was changed")
        entry = next(a for a in self.client("admin").ok("GET", "/api/audit") if a["action"] == "reservation_change_online")
        self.assertIn(res["code"], entry["details"])

    def test_room_is_swapped_when_the_current_one_is_taken(self):
        guest, desk = self._guest(), self.client("frontdesk")
        res = self._book(guest, 220, 222)
        before = desk.ok("GET", f"/api/reservations/{res['id']}")
        # someone else takes the same room right after
        self.book(desk, 222, 224, room={"id": before["room_id"]})
        changed = guest.ok("POST", f"/api/portal/reservations/{res['id']}/change", {"check_in": d(221), "check_out": d(223), "adults": 2})
        after = desk.ok("GET", f"/api/reservations/{changed['id']}")
        self.assertNotEqual(after["room_id"], before["room_id"])
        self.assertEqual(after["room_type"], before["room_type"])

    def test_change_room_type_and_rules(self):
        guest = self._guest()
        res = self._book(guest, 240, 242)
        types = guest.ok("GET", "/api/public/info")["room_types"]
        other = next(t for t in types if t["id"] != res["room_type_id"] and t["capacity"] >= 2)
        changed = guest.ok("POST", f"/api/portal/reservations/{res['id']}/change",
                           {"check_in": d(240), "check_out": d(242), "adults": 2, "room_type_id": other["id"]})
        self.assertEqual(changed["room_type"], other["name"])
        url = f"/api/portal/reservations/{res['id']}/change"
        self.assertEqual(guest.req("POST", url, {"check_in": d(-2), "check_out": d(1)})[0], 400)          # in the past
        self.assertEqual(guest.req("POST", url, {"check_in": d(240), "check_out": d(240)})[0], 400)       # no nights
        self.assertEqual(guest.req("POST", url, {"check_in": d(240), "check_out": d(242), "adults": 9})[0], 409)   # no room that big
        self.assertEqual(guest.req("POST", url, {"check_in": d(240), "check_out": d(340)})[0], 400)       # over the online limit

    def test_too_close_to_arrival_or_someone_elses_booking(self):
        guest = self._guest()
        soon = self._book(guest, 1, 3)                 # inside the 2-day free-cancellation window
        self.assertFalse(soon["can_change"])
        self.assertEqual(guest.req("POST", f"/api/portal/reservations/{soon['id']}/change",
                                   {"check_in": d(10), "check_out": d(12)})[0], 409)
        other = self.book(self.client("frontdesk"), 250, 252)
        self.assertEqual(guest.req("POST", f"/api/portal/reservations/{other['id']}/change",
                                   {"check_in": d(251), "check_out": d(253)})[0], 404)


class PagingTests(AppTestCase):
    def test_pages_and_totals(self):
        admin = self.client("admin")
        for i in range(7):
            admin.ok("POST", "/api/guests", {"first_name": "Paged", "last_name": f"Guest{i:02d}"})
        self.assertIsInstance(admin.ok("GET", "/api/guests?q=Paged"), list)                  # no page asked: plain list
        first = admin.ok("GET", "/api/guests?q=Paged&page=1&per_page=3")
        self.assertEqual((first["total"], first["pages"], first["page"], len(first["items"])), (7, 3, 1, 3))
        last = admin.ok("GET", "/api/guests?q=Paged&page=3&per_page=3")
        self.assertEqual([g["last_name"] for g in last["items"]], ["Guest06"])
        seen = [g["id"] for p in (1, 2, 3) for g in admin.ok("GET", f"/api/guests?q=Paged&page={p}&per_page=3")["items"]]
        self.assertEqual(len(set(seen)), 7)                                                  # no row twice, none missing
        self.assertEqual(admin.ok("GET", "/api/guests?q=Paged&page=99&per_page=3")["page"], 3)   # past the end: last page
        self.assertEqual(admin.ok("GET", "/api/guests?q=Paged&page=x")["page"], 1)
        self.assertEqual(admin.ok("GET", "/api/guests?page=1&per_page=100000")["per_page"], 200)

    def test_every_long_list_can_be_paged(self):
        admin = self.client("admin")
        res = admin.ok("GET", "/api/reservations?page=1&per_page=4")
        self.assertEqual(len(res["items"]), 4)
        self.assertIn("balance", res["items"][0])                 # totals are still worked out for the rows shown
        self.assertGreater(res["total"], 4)
        for path in ("/api/audit", "/api/movements", "/api/invoices"):
            page = admin.ok("GET", f"{path}?page=1&per_page=2")
            self.assertLessEqual(len(page["items"]), 2, path)
            self.assertGreaterEqual(page["total"], len(page["items"]), path)
        self.assertGreater(res["pages"], 1)

    def test_exports_are_not_cut_short(self):
        admin = self.client("admin")
        db = sqlite3.connect(self.app.config.db_path)
        db.executemany("INSERT INTO guests(first_name, last_name) VALUES ('Bulk', ?)", [(f"G{i}",) for i in range(620)])
        db.commit()
        db.close()
        csv = admin.req("GET", "/api/export/guests?q=Bulk")[1]
        self.assertEqual(len(csv.strip().splitlines()), 621)       # header + every row (the screen list stops at 500)


class EmailLanguageTests(AppTestCase):
    def test_guest_gets_mail_in_their_language(self):
        c = self.client()
        r = c.ok("POST", "/api/auth/register", {"first_name": "Laila", "last_name": "Nabil", "email": "laila@example.com",
                                                "password": "Laila-Pass-2026", "accept_privacy": True, "language": "ar"})
        c.csrf = r["csrf_token"]
        self.assertEqual(outbox(self.app, "laila@example.com")[-1]["subject"], "أكّد بريدك الإلكتروني")
        offer = c.ok("POST", "/api/public/search", {"check_in": d(150), "check_out": d(152), "adults": 1})["offers"][0]
        bb = next(p for p in offer["plans"] if p["meal_plan"] == "breakfast")
        res = c.ok("POST", "/api/portal/reservations", {"room_type_id": offer["id"], "check_in": d(150), "check_out": d(152),
                                                        "adults": 1, "rate_plan_id": bb["id"]})
        mail = outbox(self.app, "laila@example.com")[-1]
        self.assertEqual(mail["subject"], f"تأكيد الحجز {res['code']}")
        self.assertIn("شامل الإفطار", mail["body"])
        self.assertIn("فندق نايل هاربور", mail["body"])                      # the hotel's Arabic name in the signature
        # switching the site to English switches the e-mails
        c.ok("POST", "/api/portal/language", {"language": "en"})
        self.assertEqual(c.ok("GET", "/api/portal/profile")["language"], "en")
        c.ok("POST", f"/api/portal/reservations/{res['id']}/cancel")
        self.assertEqual(outbox(self.app, "laila@example.com")[-1]["subject"], f"Booking cancelled — {res['code']}")
        self.assertEqual(c.req("POST", "/api/portal/language", {"language": "fr"})[0], 400)

    def test_staff_can_set_a_guests_language_and_default_is_english(self):
        desk = self.client("frontdesk")
        res = self.book(desk, 160, 162, guest={"first_name": "Omar", "last_name": "Adel", "email": "omar.adel@example.com",
                                               "language": "ar"})
        self.assertIn("تأكيد الحجز", outbox(self.app, "omar.adel@example.com")[-1]["subject"])
        self.book(desk, 163, 165, guest={"first_name": "Eve", "last_name": "Stone", "email": "eve.stone@example.com"})
        self.assertIn("Booking confirmation", outbox(self.app, "eve.stone@example.com")[-1]["subject"])
        self.assertIn("free of charge", outbox(self.app, "eve.stone@example.com")[-1]["body"])
        self.assertTrue(res["code"])

    def test_html_version(self):
        html = to_html("مرحبًا <b>\nhttps://hotel.example/login#verify=abc")
        self.assertIn('dir="rtl"', html)
        self.assertIn("&lt;b&gt;", html)                                       # text is escaped, never trusted as HTML
        self.assertIn('<a href="https://hotel.example/login#verify=abc">', html)
        self.assertIn('dir="ltr"', to_html("Hello"))


class ArrivalReminderTests(AppTestCase):
    def _at(self, offset):
        return dt.datetime.combine(dt.date.today() + dt.timedelta(days=offset), dt.time(9, 0))

    def test_one_reminder_per_booking_inside_the_window(self):
        desk = self.client("frontdesk")
        early = self.book(desk, 6, 8, guest={"first_name": "Rem", "last_name": "Inder", "email": "rem@example.com"})
        last_minute = self.book(desk, 1, 2, guest={"first_name": "Last", "last_name": "Minute", "email": "last@example.com"})
        self.book(desk, 6, 8, guest={"first_name": "No", "last_name": "Mail"})
        send = self.app.send_arrival_reminders
        mails = lambda who: len(outbox(self.app, who))               # noqa: E731
        send(self._at(0))                                           # 6 days away: too early
        self.assertEqual(mails("rem@example.com"), 1)               # only the confirmation so far
        self.assertEqual(mails("last@example.com"), 1)              # booked inside the window: confirmation is enough
        send(self._at(4))                                           # 2 days before arrival
        mail = outbox(self.app, "rem@example.com")[-1]
        self.assertIn("See you soon", mail["subject"])
        self.assertIn(early["code"], mail["body"])
        self.assertIn("passport", mail["body"])
        send(self._at(4))
        send(self._at(5))
        self.assertEqual(mails("rem@example.com"), 2)               # never twice
        # moving the arrival date earns a fresh reminder
        desk.ok("PUT", f"/api/reservations/{early['id']}", {"check_in": d(20), "check_out": d(22)})
        send(self._at(18))
        self.assertEqual(mails("rem@example.com"), 3)
        self.assertEqual(mails("last@example.com"), 1)
        self.assertTrue(last_minute["code"])

    def test_cancelled_bookings_and_switched_off(self):
        desk, admin = self.client("frontdesk"), self.client("admin")
        res = self.book(desk, 30, 32, guest={"first_name": "Can", "last_name": "Celled", "email": "can@example.com"})
        desk.ok("POST", f"/api/reservations/{res['id']}/cancel")
        self.app.send_arrival_reminders(self._at(28))
        self.assertFalse(any("See you soon" in m["subject"] for m in outbox(self.app, "can@example.com")))
        self.book(desk, 40, 42, guest={"first_name": "Off", "last_name": "Switch", "email": "off@example.com"})
        admin.ok("PUT", "/api/settings", {"arrival_reminder_days": 0})
        self.assertEqual(self.app.send_arrival_reminders(self._at(38)), 0)
        admin.ok("PUT", "/api/settings", {"arrival_reminder_days": 5})
        self.app.send_arrival_reminders(self._at(35))                            # the longer window applies at once
        self.assertTrue(any("See you soon" in m["subject"] for m in outbox(self.app, "off@example.com")))


class ScheduledStayoverTests(AppTestCase):
    def _at(self, clock):
        h, m = map(int, clock.split(":"))
        return dt.datetime.combine(dt.date.today(), dt.time(h, m))

    def test_daily_tasks_for_occupied_rooms(self):
        admin = self.client("admin")
        run = self.app.run_scheduled_stayover_tasks
        self.assertEqual(run(self._at("09:00")), -1)                                    # off by default
        admin.ok("PUT", "/api/settings", {"auto_stayover_tasks": True, "stayover_time": "08:30"})
        self.assertEqual(run(self._at("08:29")), -1)                                    # not yet
        arrived = self.check_in_today(admin, nights=3)                                  # a guest who stays on tomorrow
        staying = [r for r in admin.ok("GET", "/api/reservations?status=checked_in") if r["check_out"] > d(0)]
        open_before = {t["room_id"] for t in admin.ok("GET", "/api/housekeeping/tasks")}
        expected = len([r for r in staying if r["room_id"] not in open_before])
        self.assertNotIn(arrived["room_id"], open_before)
        self.assertEqual(run(self._at("08:30")), expected)
        self.assertIn(arrived["room_id"], {t["room_id"] for t in admin.ok("GET", "/api/housekeeping/tasks")})
        self.assertEqual(run(self._at("12:00")), -1)                                    # once a day
        tasks = [t for t in admin.ok("GET", "/api/housekeeping/tasks") if t["kind"] == "stayover"]
        self.assertGreaterEqual(len(tasks), expected)
        entry = next(a for a in admin.ok("GET", "/api/audit") if a["action"] == "tasks_generate")
        self.assertEqual(entry["username"], "system")
