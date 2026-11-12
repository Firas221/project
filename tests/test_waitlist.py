"""Tests for the waiting list, stop-sell dates and rooms held back from the website."""
from support import AppTestCase, d  # first: puts the project on sys.path


class WaitlistTests(AppTestCase):
    def _fill_type(self, c, type_id, ci, co):
        """Books every room of a type for the dates; returns the reservations."""
        made = []
        for room in c.ok("GET", f"/api/availability?check_in={ci}&check_out={co}&guests=1&type_id={type_id}"):
            made.append(self.book(c, room=room, check_in=ci, check_out=co))
        return made

    def test_desk_is_alerted_when_a_room_frees_up_and_books_from_the_list(self):
        desk = self.client("frontdesk")
        suite = next(t for t in desk.ok("GET", "/api/room-types") if t["name"] == "Presidential Suite")
        ci, co = d(500), d(503)
        taken = self._fill_type(desk, suite["id"], ci, co)
        self.assertTrue(taken)
        entry = desk.ok("POST", "/api/waitlist", {"name": "Wael Waiting", "phone": "+20 100 000 0000", "room_type_id": suite["id"],
                                                  "check_in": d(501), "check_out": d(502), "adults": 2})
        listed = next(w for w in desk.ok("GET", "/api/waitlist") if w["id"] == entry["id"])
        self.assertEqual((listed["rooms_free"], listed["room_type"], listed["status"]), (0, "Presidential Suite", "waiting"))

        manager = self.client("manager")
        before = manager.ok("GET", "/api/alerts")["unread"]
        desk.ok("POST", f"/api/reservations/{taken[0]['id']}/cancel")
        alerts = manager.ok("GET", "/api/alerts")
        self.assertEqual(alerts["unread"], before + 1)
        self.assertEqual((alerts["items"][0]["title"], alerts["items"][0]["link"]), ("A room is free for the waiting list", "#/waitlist"))
        self.assertIn("Wael Waiting", alerts["items"][0]["body"])
        self.assertEqual(next(w for w in desk.ok("GET", "/api/waitlist") if w["id"] == entry["id"])["rooms_free"], 1)
        # told once only, even if more rooms free up
        desk.ok("POST", f"/api/reservations/{taken[1]['id']}/cancel")
        self.assertEqual(manager.ok("GET", "/api/alerts")["unread"], before + 1)

        res = self.book(desk, 501, 502, room={"id": taken[0]["room_id"]})
        closed = desk.ok("POST", f"/api/waitlist/{entry['id']}/close", {"status": "booked", "reservation_id": res["id"]})
        self.assertEqual((closed["status"], closed["reservation_code"]), ("booked", res["code"]))
        self.assertNotIn(entry["id"], [w["id"] for w in desk.ok("GET", "/api/waitlist")])
        self.assertIn(entry["id"], [w["id"] for w in desk.ok("GET", "/api/waitlist?status=booked")])
        self.assertEqual(desk.req("POST", f"/api/waitlist/{entry['id']}/close", {"status": "cancelled"})[0], 409)

    def test_rules_and_access(self):
        desk = self.client("frontdesk")
        ok = {"name": "A B", "phone": "123", "check_in": d(30), "check_out": d(31)}
        self.assertEqual(desk.req("POST", "/api/waitlist", {**ok, "check_out": d(30)})[0], 400)
        self.assertEqual(desk.req("POST", "/api/waitlist", {**ok, "check_in": d(-2), "check_out": d(-1)})[0], 400)
        self.assertEqual(desk.req("POST", "/api/waitlist", {**ok, "phone": ""})[0], 400)                # no way to reach them
        self.assertEqual(desk.req("POST", "/api/waitlist", {**ok, "name": ""})[0], 400)
        self.assertEqual(desk.req("POST", "/api/waitlist", {**ok, "room_type_id": 9999})[0], 404)
        guest = desk.ok("POST", "/api/guests", {"first_name": "Known", "last_name": "Guest", "email": "known@example.com"})
        entry = desk.ok("POST", "/api/waitlist", {"guest_id": guest["id"], "check_in": d(30), "check_out": d(31)})
        self.assertEqual((entry["name"], entry["email"]), ("Known Guest", "known@example.com"))       # filled from the profile
        self.assertEqual(desk.req("POST", f"/api/waitlist/{entry['id']}/close", {"status": "nonsense"})[0], 400)
        desk.ok("POST", f"/api/waitlist/{entry['id']}/close", {"status": "cancelled"})
        self.assertEqual(self.client("accountant").req("GET", "/api/waitlist")[0], 200)                # may look
        self.assertEqual(self.client("accountant").req("POST", "/api/waitlist", ok)[0], 403)
        self.assertEqual(self.client("chef").req("GET", "/api/waitlist")[0], 403)

    def test_guest_joins_and_leaves_online(self):
        guest, other = self.client("amelia.hart@example.com"), self.client()
        r = other.ok("POST", "/api/auth/register", {"first_name": "Other", "last_name": "Guest", "email": "other.wl@example.com",
                                                    "password": "Other-Guest-2026", "accept_privacy": True})
        other.csrf = r["csrf_token"]
        entry = guest.ok("POST", "/api/portal/waitlist", {"check_in": d(60), "check_out": d(62), "adults": 2})
        self.assertEqual(entry["status"], "waiting")
        self.assertEqual([w["id"] for w in guest.ok("GET", "/api/portal/waitlist")], [entry["id"]])
        self.assertEqual(other.ok("GET", "/api/portal/waitlist"), [])
        self.assertEqual(other.req("DELETE", f"/api/portal/waitlist/{entry['id']}")[0], 404)           # not theirs
        desk = self.client("frontdesk")
        mine = next(w for w in desk.ok("GET", "/api/waitlist") if w["id"] == entry["id"])
        self.assertEqual((mine["name"], mine["source"], mine["email"]), ("Amelia Hart", "online", "amelia.hart@example.com"))
        self.assertEqual(desk.ok("GET", "/api/alerts")["items"][0]["title"], "A guest joined the waiting list")
        guest.ok("DELETE", f"/api/portal/waitlist/{entry['id']}")
        self.assertEqual(guest.ok("GET", "/api/portal/waitlist"), [])
        for n in range(5):
            guest.ok("POST", "/api/portal/waitlist", {"check_in": d(70 + n), "check_out": d(71 + n)})
        self.assertEqual(guest.req("POST", "/api/portal/waitlist", {"check_in": d(80), "check_out": d(81)})[0], 409)


class OnlineSaleControlTests(AppTestCase):
    def _offers(self, c, ci, co, **extra):
        return {o["name"]: o for o in c.ok("POST", "/api/public/search", {"check_in": ci, "check_out": co, **extra})["offers"]}

    def test_stop_sell_hides_dates_from_the_website_only(self):
        admin, guest, desk = self.client("admin"), self.client("amelia.hart@example.com"), self.client("frontdesk")
        king = next(t for t in admin.ok("GET", "/api/room-types") if t["name"] == "Deluxe King")
        self.assertIn("Deluxe King", self._offers(guest, d(300), d(302)))
        stop = admin.ok("POST", "/api/stop-sells", {"room_type_id": king["id"], "start_date": d(301), "end_date": d(305), "reason": "Renovation"})
        self.assertNotIn("Deluxe King", self._offers(guest, d(300), d(302)))            # one night inside is enough
        self.assertIn("Standard Double", self._offers(guest, d(300), d(302)))
        self.assertIn("Deluxe King", self._offers(guest, d(306), d(308)))               # the night after the last one
        self.assertIn("Deluxe King", self._offers(guest, d(299), d(301)))               # leaves on the first closed day
        status, err = guest.req("POST", "/api/portal/reservations", {"room_type_id": king["id"], "check_in": d(300), "check_out": d(302)})
        self.assertEqual(status, 409)                                                   # even when asked for directly
        self.assertIn("not available online", err["error"])
        self.assertTrue(desk.ok("GET", f"/api/availability?check_in={d(300)}&check_out={d(302)}&type_id={king['id']}"))   # the desk still can
        # an existing online booking cannot be moved onto closed dates
        res = guest.ok("POST", "/api/portal/reservations", {"room_type_id": king["id"], "check_in": d(310), "check_out": d(312)})
        self.assertEqual(guest.req("POST", f"/api/portal/reservations/{res['id']}/change", {"check_in": d(303), "check_out": d(304)})[0], 409)
        # every room type at once
        all_stop = admin.ok("POST", "/api/stop-sells", {"start_date": d(320), "end_date": d(320)})
        self.assertEqual(self._offers(guest, d(320), d(321)), {})
        self.assertEqual(len(admin.ok("GET", "/api/stop-sells")), 2)
        admin.ok("DELETE", f"/api/stop-sells/{stop['id']}")
        admin.ok("DELETE", f"/api/stop-sells/{all_stop['id']}")
        self.assertIn("Deluxe King", self._offers(guest, d(300), d(302)))
        self.assertEqual(desk.req("POST", "/api/stop-sells", {"start_date": d(1), "end_date": d(2)})[0], 403)
        self.assertEqual(admin.req("POST", "/api/stop-sells", {"start_date": d(5), "end_date": d(4)})[0], 400)

    def test_rooms_held_back_are_never_sold_online(self):
        admin, guest = self.client("admin"), self.client("amelia.hart@example.com")
        suite = next(t for t in admin.ok("GET", "/api/room-types") if t["name"] == "Presidential Suite")
        ci, co = d(340), d(342)
        total = len(admin.ok("GET", f"/api/availability?check_in={ci}&check_out={co}&type_id={suite['id']}"))
        self.assertEqual(self._offers(guest, ci, co)["Presidential Suite"]["rooms_left"], total)
        body = {k: suite[k] for k in ("name", "base_rate", "capacity", "max_extra_beds", "extra_bed_rate")}
        admin.ok("PUT", f"/api/room-types/{suite['id']}", {**body, "online_hold_back": total - 1})
        self.assertEqual(self._offers(guest, ci, co)["Presidential Suite"]["rooms_left"], 1)
        guest.ok("POST", "/api/portal/reservations", {"room_type_id": suite["id"], "check_in": ci, "check_out": co})
        self.assertNotIn("Presidential Suite", self._offers(guest, ci, co))             # the rest is the desk's
        self.assertEqual(guest.req("POST", "/api/portal/reservations", {"room_type_id": suite["id"], "check_in": ci, "check_out": co})[0], 409)
        self.assertEqual(len(admin.ok("GET", f"/api/availability?check_in={ci}&check_out={co}&type_id={suite['id']}")), total - 1)
        admin.ok("PUT", f"/api/room-types/{suite['id']}", {**body, "online_hold_back": 0})
