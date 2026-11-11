"""Tests for deleting users, scans of guest ID documents and the in-app alerts for staff."""
import base64
import sqlite3

from support import PASSWORDS, AppTestCase, d  # first: puts the project on sys.path

from hotel.db.seed import DEMO_PASSWORDS  # noqa: E402
from test_features import png  # noqa: E402

PASSWORDS.update({u: DEMO_PASSWORDS[u] for u in ("manager", "accountant", "supervisor", "tech", "store")})
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


class DeleteUserTests(AppTestCase):
    def test_delete_and_its_rules(self):
        admin = self.client("admin")
        made = admin.ok("POST", "/api/users", {"username": "temp.user", "full_name": "Temp User", "role": "staff"})
        temp = self.client()
        temp.login("temp.user", made["temporary_password"])
        uid = made["user"]["id"]
        self.assertEqual(self.client("manager").req("DELETE", f"/api/users/{uid}")[0], 403)
        admin.ok("DELETE", f"/api/users/{uid}")
        self.assertEqual(temp.req("GET", "/api/auth/me")[0], 401)                       # signed out at once
        self.assertEqual(self.client().req("POST", "/api/auth/login", {"username": "temp.user", "password": made["temporary_password"]})[0], 401)
        self.assertNotIn("temp.user", [u["username"] for u in admin.ok("GET", "/api/users")])
        self.assertTrue(any(a["action"] == "user_delete" and "temp.user" in a["details"] for a in admin.ok("GET", "/api/audit")))
        self.assertEqual(admin.req("DELETE", f"/api/users/{uid}")[0], 404)
        me = next(u for u in admin.ok("GET", "/api/users") if u["username"] == "admin")
        self.assertEqual(admin.req("DELETE", f"/api/users/{me['id']}")[0], 400)         # not yourself
        guest = next(u for u in admin.ok("GET", "/api/users?role=guest"))
        self.assertEqual(admin.req("DELETE", f"/api/users/{guest['id']}")[0], 400)      # guests: erase from the profile

    def test_work_stays_and_money_records_block_deletion(self):
        admin = self.client("admin")
        made = admin.ok("POST", "/api/users", {"username": "busy.clerk", "full_name": "Busy Clerk", "role": "staff",
                                               "password": "Busy-Clerk-2026"})
        clerk = self.client()
        clerk.login("busy.clerk", "Busy-Clerk-2026")
        clerk.ok("POST", "/api/auth/password", {"current_password": "Busy-Clerk-2026", "new_password": "Busy-Clerk-2027"})
        res = self.book(clerk, 80, 82)
        clerk.ok("POST", "/api/cashier/open", {"opening_float": 100})
        status, err = admin.req("DELETE", f"/api/users/{made['user']['id']}")
        self.assertEqual(status, 409)
        self.assertIn("cashier shifts", err["error"])
        # without money records the account goes, and the booking they made stays
        db = sqlite3.connect(self.app.config.db_path)
        db.execute("DELETE FROM cashier_shifts WHERE user_id=?", (made["user"]["id"],))
        db.commit()
        db.close()
        admin.ok("DELETE", f"/api/users/{made['user']['id']}")
        self.assertEqual(admin.ok("GET", f"/api/reservations/{res['id']}")["code"], res["code"])


class GuestDocumentTests(AppTestCase):
    def _upload(self, c, guest_id, raw, kind="passport"):
        return c.req("POST", f"/api/guests/{guest_id}/documents", {"kind": kind, "data": base64.b64encode(raw).decode()})

    def test_upload_view_delete(self):
        desk = self.client("frontdesk")
        g = desk.ok("POST", "/api/guests", {"first_name": "Doc", "last_name": "Holder"})
        status, doc = self._upload(desk, g["id"], png(20, 20))
        self.assertEqual(status, 201)
        self.assertEqual(self._upload(desk, g["id"], PDF, "national_id")[0], 201)
        listed = desk.ok("GET", f"/api/guests/{g['id']}")["documents"]
        self.assertEqual([(x["kind"], x["content_type"]) for x in listed], [("passport", "image/png"), ("national_id", "application/pdf")])
        status, _ = desk.req("GET", f"/api/guests/{g['id']}/documents/{doc['id']}")
        self.assertEqual(status, 200)
        headers = {k.lower(): v for k, v in desk.last_headers.items()}
        self.assertEqual(headers["content-type"], "image/png")
        self.assertEqual(headers["cache-control"], "no-store")                           # private: never cached
        desk.req("GET", f"/api/guests/{g['id']}/documents/{listed[1]['id']}")
        self.assertIn("attachment", {k.lower(): v for k, v in desk.last_headers.items()}["content-disposition"])
        admin = self.client("admin")
        self.assertTrue(any(a["action"] == "guest_document_view" for a in admin.ok("GET", "/api/audit")))
        desk.ok("DELETE", f"/api/guests/{g['id']}/documents/{doc['id']}")
        self.assertEqual(desk.req("GET", f"/api/guests/{g['id']}/documents/{doc['id']}")[0], 404)

    def test_who_can_and_what_is_refused(self):
        desk = self.client("frontdesk")
        g = desk.ok("POST", "/api/guests", {"first_name": "Private", "last_name": "Person"})
        other = desk.ok("POST", "/api/guests", {"first_name": "Other", "last_name": "Person"})
        doc = self._upload(desk, g["id"], png())[1]
        self.assertEqual(self.client().req("GET", f"/api/guests/{g['id']}/documents/{doc['id']}")[0], 401)
        for who in ("chef", "maid", "store", "tech", "amelia.hart@example.com"):
            self.assertEqual(self.client(who).req("GET", f"/api/guests/{g['id']}/documents/{doc['id']}")[0], 403, who)
        acc = self.client("accountant")                                                    # may view guests, not change them
        self.assertEqual(acc.req("GET", f"/api/guests/{g['id']}/documents/{doc['id']}")[0], 200)
        self.assertEqual(self._upload(acc, g["id"], png())[0], 403)
        self.assertEqual(acc.req("DELETE", f"/api/guests/{g['id']}/documents/{doc['id']}")[0], 403)
        # a document is only reachable through its own guest
        self.assertEqual(desk.req("GET", f"/api/guests/{other['id']}/documents/{doc['id']}")[0], 404)
        self.assertEqual(desk.req("DELETE", f"/api/guests/{other['id']}/documents/{doc['id']}")[0], 404)
        self.assertEqual(self._upload(desk, g["id"], b"<html><script>alert(1)</script>")[0], 400)
        self.assertEqual(self._upload(desk, g["id"], png(), "selfie")[0], 400)
        self.assertEqual(self._upload(desk, g["id"], png() + b"\x00" * 1_600_000)[0], 400)
        for _ in range(5):
            self.assertEqual(self._upload(desk, g["id"], png())[0], 201)
        self.assertEqual(self._upload(desk, g["id"], png())[0], 409)                       # six per guest

    def test_erasing_a_guest_destroys_the_scans(self):
        desk, admin = self.client("frontdesk"), self.client("admin")
        g = desk.ok("POST", "/api/guests", {"first_name": "Forget", "last_name": "Me"})
        doc = self._upload(desk, g["id"], png())[1]
        self.assertEqual(len(admin.ok("GET", f"/api/guests/{g['id']}/export")["id_documents"]), 1)
        admin.ok("POST", f"/api/guests/{g['id']}/erase")
        self.assertEqual(desk.req("GET", f"/api/guests/{g['id']}/documents/{doc['id']}")[0], 404)
        db = sqlite3.connect(self.app.config.db_path)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM guest_documents WHERE guest_id=?", (g["id"],)).fetchone()[0], 0)
        db.close()
        self.assertEqual(self._upload(desk, g["id"], png())[0], 409)


class AlertTests(AppTestCase):
    def titles(self, c, unread_only=False):
        return [a["title"] for a in c.ok("GET", "/api/alerts")["items"] if not (unread_only and a["read"])]

    def test_guest_actions_reach_the_right_staff(self):
        desk, chef, maid = self.client("frontdesk"), self.client("chef"), self.client("maid")
        before = desk.ok("GET", "/api/alerts")["unread"]
        guest = self.client("amelia.hart@example.com")
        stay = next(r for r in guest.ok("GET", "/api/portal/reservations") if r["status"] == "checked_in")
        guest.ok("POST", f"/api/portal/reservations/{stay['id']}/requests", {"kind": "amenity", "message": "Two more pillows"})
        dish = guest.ok("GET", "/api/portal/menu")[0]
        guest.ok("POST", f"/api/portal/reservations/{stay['id']}/orders", {"lines": [{"menu_item_id": dish["id"], "quantity": 2}]})
        offer = guest.ok("POST", "/api/public/search", {"check_in": d(90), "check_out": d(92)})["offers"][0]
        booked = guest.ok("POST", "/api/portal/reservations", {"room_type_id": offer["id"], "check_in": d(90), "check_out": d(92)})
        guest.ok("POST", f"/api/portal/reservations/{booked['id']}/cancel")

        seen = desk.ok("GET", "/api/alerts")
        self.assertEqual(seen["unread"], before + 3)
        self.assertEqual(self.titles(desk)[:3], ["A guest cancelled their booking", "New online booking", "New guest request"])
        request = next(a for a in seen["items"] if a["title"] == "New guest request")
        self.assertIn("Two more pillows", request["body"])
        self.assertEqual(request["link"], "#/requests")
        self.assertEqual(self.titles(chef)[0], "New room-service order")            # the kitchen, not the front desk
        self.assertNotIn("New room-service order", self.titles(desk))
        self.assertNotIn("New guest request", self.titles(chef))
        for title in ("New guest request", "New online booking", "New room-service order"):
            self.assertNotIn(title, self.titles(maid))
        self.assertEqual(guest.req("GET", "/api/alerts")[0], 403)                   # staff only

    def test_assignments_go_to_one_person_and_nobody_is_told_of_their_own_action(self):
        desk, sup, tech = self.client("frontdesk"), self.client("supervisor"), self.client("tech")
        maid, maid2 = self.client("maid"), self.client("maid2")
        rosa = next(s for s in sup.ok("GET", "/api/housekeeping/staff") if s["full_name"] == "Rosa Delgado")
        room = sup.ok("GET", "/api/rooms")[-1]
        sup.ok("POST", "/api/housekeeping/tasks", {"room_id": room["id"], "kind": "deep_clean", "assigned_to": rosa["id"]})
        self.assertEqual(self.titles(maid), ["A room was assigned to you"])
        self.assertEqual(self.titles(maid2), [])
        ticket = desk.ok("POST", "/api/maintenance", {"location": "Roof", "title": "Loose tile"})
        self.assertIn("New maintenance ticket", self.titles(tech))
        self.assertNotIn("New maintenance ticket", self.titles(desk))                # desk raised it
        me = desk.ok("GET", "/api/maintenance/staff")[0]
        desk.ok("PUT", f"/api/maintenance/{ticket['id']}", {"assigned_to": me["id"]})
        self.assertEqual(self.titles(tech)[0], "A ticket was assigned to you")
        chef = self.client("chef")
        item = chef.ok("GET", "/api/items/requestable")[0]
        chef.ok("POST", "/api/stock-requests", {"lines": [{"item_id": item["id"], "quantity": 1}]})
        self.assertEqual(self.titles(self.client("store"))[0], "New supply request")

    def test_reading(self):
        desk = self.client("frontdesk")
        guest = self.client("amelia.hart@example.com")
        stay = next(r for r in guest.ok("GET", "/api/portal/reservations") if r["status"] == "checked_in")
        for message in ("First", "Second", "Third"):
            guest.ok("POST", f"/api/portal/reservations/{stay['id']}/requests", {"kind": "other", "message": message})
        start = desk.ok("GET", "/api/alerts")
        one = start["items"][0]
        after = desk.ok("POST", "/api/alerts/read", {"id": one["id"]})
        self.assertEqual(after["unread"], start["unread"] - 1)
        self.assertTrue(next(a for a in after["items"] if a["id"] == one["id"])["read"])
        # each person has their own read marks
        self.assertEqual(self.client("manager").ok("GET", "/api/alerts")["unread"] >= 3, True)
        self.assertEqual(desk.ok("POST", "/api/alerts/read")["unread"], 0)
        # an alert the user cannot see cannot be marked by guessing its number
        chef = self.client("chef")
        chef.ok("POST", "/api/alerts/read", {"id": one["id"]})
        db = sqlite3.connect(self.app.config.db_path)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM staff_alert_reads r JOIN users u ON u.id=r.user_id WHERE u.username='chef'").fetchone()[0], 0)
        db.close()

    def test_new_staff_do_not_inherit_old_alerts_and_old_ones_are_purged(self):
        admin = self.client("admin")
        guest = self.client("amelia.hart@example.com")
        stay = next(r for r in guest.ok("GET", "/api/portal/reservations") if r["status"] == "checked_in")
        guest.ok("POST", f"/api/portal/reservations/{stay['id']}/requests", {"kind": "other", "message": "Before you joined"})
        db = sqlite3.connect(self.app.config.db_path)
        db.execute("UPDATE staff_alerts SET created_at = datetime('now', 'localtime', '-2 days')")
        db.commit()
        made = admin.ok("POST", "/api/users", {"username": "new.desk", "full_name": "New Desk", "role": "staff", "password": "New-Desk-2026"})
        new = self.client()
        new.login("new.desk", "New-Desk-2026")
        new.ok("POST", "/api/auth/password", {"current_password": "New-Desk-2026", "new_password": "New-Desk-2027"})
        self.assertEqual(new.ok("GET", "/api/alerts")["items"], [])
        db.execute("UPDATE staff_alerts SET created_at = datetime('now', 'localtime', '-40 days')")
        db.commit()
        self.app._alerts_purged_on = None
        self.app.purge_old_alerts()
        self.assertEqual(db.execute("SELECT COUNT(*) FROM staff_alerts").fetchone()[0], 0)
        db.close()
        self.assertTrue(made["user"]["id"])
