"""Tests for banquet, conference and event bookings."""
import sqlite3

from support import AppTestCase, d  # first: puts the project on sys.path


class EventTests(AppTestCase):
    def _venue(self, c, name):
        return next(v for v in c.ok("GET", "/api/venues") if v["name"] == name)

    def _body(self, venue, day, **extra):
        return {"venue_id": venue["id"], "title": "Sales kick-off", "organizer_name": "Nadia Organizer", "organizer_phone": "+20 100 111 2222",
                "event_date": d(day), "start_time": "09:00", "end_time": "13:00", "attendees": 20, **extra}

    def test_price_is_venue_plus_catering_plus_extras_with_taxes(self):
        desk = self.client("frontdesk")
        room = self._venue(desk, "Lotus Meeting Room")                       # 900 an hour, 6,000 a day, holds 24
        e = desk.ok("POST", "/api/events", self._body(room, 10, catering_per_person=250, extras=400, extras_note="Projector"))
        self.assertEqual((e["status"], e["hours"], e["venue_charge"], e["catering_total"]), ("inquiry", 4, 3600, 5000))
        subtotal = 3600 + 5000 + 400
        service = round(subtotal * 0.12, 2)
        self.assertEqual((e["subtotal"], e["service_charge"], e["vat"]), (subtotal, service, round((subtotal + service) * 0.14, 2)))
        self.assertAlmostEqual(e["total"], subtotal + service + e["vat"], places=2)
        self.assertEqual(e["balance"], e["total"])
        # a long day is capped at the day rate; a typed charge wins over both
        long_day = desk.ok("POST", "/api/events", self._body(room, 11, start_time="08:00", end_time="20:00"))
        self.assertEqual(long_day["venue_charge"], 6000)
        fixed = desk.ok("PUT", f"/api/events/{long_day['id']}", self._body(room, 11, start_time="08:00", end_time="20:00", venue_charge=4500))
        self.assertEqual(fixed["venue_charge"], 4500)

    def test_a_confirmed_event_holds_the_venue(self):
        desk = self.client("frontdesk")
        hall = self._venue(desk, "Nile Ballroom")
        first = desk.ok("POST", "/api/events", self._body(hall, 20, title="Wedding", start_time="18:00", end_time="23:00", attendees=200))
        second = desk.ok("POST", "/api/events", self._body(hall, 20, title="Gala dinner", start_time="20:00", end_time="23:30", attendees=150))
        desk.ok("POST", f"/api/events/{first['id']}/status", {"status": "confirmed"})          # two inquiries may overlap ...
        status, err = desk.req("POST", f"/api/events/{second['id']}/status", {"status": "confirmed"})
        self.assertEqual(status, 409)                                                           # ... but only one is confirmed
        self.assertIn(first["code"], err["error"])
        # the same hall earlier that day, or another day, is fine
        lunch = desk.ok("POST", "/api/events", self._body(hall, 20, title="Lunch", start_time="12:00", end_time="18:00", attendees=80))
        desk.ok("POST", f"/api/events/{lunch['id']}/status", {"status": "confirmed"})
        # a confirmed event cannot be moved onto another confirmed one
        self.assertEqual(desk.req("PUT", f"/api/events/{lunch['id']}", self._body(hall, 20, title="Lunch", start_time="12:00", end_time="19:00", attendees=80))[0], 409)
        # cancelling frees the hall
        desk.ok("POST", f"/api/events/{first['id']}/status", {"status": "cancelled"})
        desk.ok("POST", f"/api/events/{second['id']}/status", {"status": "confirmed"})

    def test_validation(self):
        desk = self.client("frontdesk")
        room = self._venue(desk, "Lotus Meeting Room")
        self.assertEqual(desk.req("POST", "/api/events", self._body(room, 5, attendees=25))[0], 400)                    # holds 24
        self.assertEqual(desk.req("POST", "/api/events", self._body(room, 5, start_time="14:00", end_time="09:00"))[0], 400)
        self.assertEqual(desk.req("POST", "/api/events", self._body(room, -1))[0], 400)                                 # in the past
        self.assertEqual(desk.req("POST", "/api/events", self._body(room, 5, title=""))[0], 400)
        self.assertEqual(desk.req("POST", "/api/events", self._body({"id": 9999}, 5))[0], 404)
        e = desk.ok("POST", "/api/events", self._body(room, 5))
        self.assertEqual(desk.req("POST", f"/api/events/{e['id']}/status", {"status": "completed"})[0], 409)            # not confirmed yet
        self.assertEqual(desk.req("POST", f"/api/events/{e['id']}/status", {"status": "postponed"})[0], 400)

    def _past(self, event_id, days=1):
        """Moves an event into the past, as if the day has come and gone."""
        db = sqlite3.connect(self.app.config.db_path)
        db.execute("UPDATE events SET event_date=? WHERE id=?", (d(-days), event_id))
        db.commit()
        db.close()

    def test_deposit_then_complete_issues_a_numbered_invoice(self):
        desk, manager = self.client("frontdesk"), self.client("manager")
        room = self._venue(desk, "Lotus Meeting Room")
        e = desk.ok("POST", "/api/events", self._body(room, 30, catering_per_person=100))
        desk.ok("POST", f"/api/events/{e['id']}/status", {"status": "confirmed"})
        e = desk.ok("POST", f"/api/events/{e['id']}/payments", {"amount": 2000, "method": "card", "reference": "Deposit"})
        self.assertEqual((e["paid"], e["balance"]), (2000, round(e["total"] - 2000, 2)))
        self.assertEqual(desk.req("POST", f"/api/events/{e['id']}/payments", {"amount": -500, "method": "card"})[0], 400)   # refunds: supervisors
        self.assertEqual(desk.req("POST", f"/api/events/{e['id']}/status", {"status": "cancelled"})[0], 409)                # money must go back first
        self.assertEqual(desk.req("POST", f"/api/events/{e['id']}/status", {"status": "completed"})[0], 409)                # has not happened yet
        self._past(e["id"])
        status, err = desk.req("POST", f"/api/events/{e['id']}/status", {"status": "completed"})
        self.assertEqual(status, 409)
        self.assertIn("Outstanding balance", err["error"])
        desk.ok("POST", f"/api/events/{e['id']}/payments", {"amount": e["balance"], "method": "bank_transfer"})
        done = desk.ok("POST", f"/api/events/{e['id']}/status", {"status": "completed"})
        self.assertEqual((done["status"], done["balance"]), ("completed", 0))
        self.assertRegex(done["invoice_number"], r"^EVT-\d{4}-\d{6}$")
        self.assertEqual(desk.req("PUT", f"/api/events/{e['id']}", self._body(room, 30))[0], 409)                           # frozen
        self.assertEqual(desk.req("POST", f"/api/events/{e['id']}/payments", {"amount": 1, "method": "card"})[0], 409)
        # the invoice keeps its figures even if the tax rates change later
        admin = self.client("admin")
        admin.ok("PUT", "/api/settings", {"vat_rate": 20})
        self.assertEqual(desk.ok("GET", f"/api/events/{e['id']}")["vat"], done["vat"])
        admin.ok("PUT", "/api/settings", {"vat_rate": 14})
        # it is in the VAT report and the summary
        tax = manager.ok("GET", f"/api/reports/tax?from={d(0)}&to={d(0)}")
        self.assertIn(done["invoice_number"], [i["invoice_number"] for i in tax["events"]["invoices"]])
        self.assertAlmostEqual(tax["grand_totals"]["total"], tax["totals"]["total"] + tax["restaurant"]["total"] + tax["events"]["total"], places=2)
        self.assertGreaterEqual(manager.ok("GET", "/api/reports/summary")["events"]["events"], 1)

    def test_company_event_goes_on_the_city_ledger(self):
        desk, acc = self.client("frontdesk"), self.client("accountant")
        company = acc.ok("POST", "/api/companies", {"name": "Event Corp", "credit_limit": 0})
        hall = self._venue(desk, "Nile Ballroom")
        e = desk.ok("POST", "/api/events", self._body(hall, 40, title="Conference", company_id=company["id"], attendees=100))
        desk.ok("POST", f"/api/events/{e['id']}/status", {"status": "confirmed"})
        self._past(e["id"])
        done = desk.ok("POST", f"/api/events/{e['id']}/status", {"status": "completed"})
        self.assertEqual((done["balance"], done["payments"][-1]["reference"]), (0, "City ledger: Event Corp"))
        ledger = acc.ok("GET", f"/api/companies/{company['id']}")["ledger"]
        self.assertEqual((ledger[0]["amount"], ledger[0]["reference"]), (done["total"], f"Event {e['code']}"))

    def test_cash_deposit_needs_a_shift_and_counts_in_the_drawer(self):
        desk = self.client("frontdesk")
        room = self._venue(desk, "Lotus Meeting Room")
        e = desk.ok("POST", "/api/events", self._body(room, 50))
        self.assertEqual(desk.req("POST", f"/api/events/{e['id']}/payments", {"amount": 500, "method": "cash"})[0], 409)
        desk.ok("POST", "/api/cashier/open", {"opening_float": 100})
        desk.ok("POST", f"/api/events/{e['id']}/payments", {"amount": 500, "method": "cash"})
        self.assertEqual(desk.ok("GET", "/api/cashier/shifts")["current"]["events_cash"], 500)
        self.assertEqual(desk.ok("POST", "/api/cashier/close", {"counted_cash": 600})["variance"], 0)

    def test_venues_and_access(self):
        desk, manager = self.client("frontdesk"), self.client("manager")
        v = manager.ok("POST", "/api/venues", {"name": "Garden", "capacity": 80, "hourly_rate": 1500})
        self.assertEqual(manager.req("POST", "/api/venues", {"name": "garden", "capacity": 10})[0], 409)
        self.assertEqual(manager.req("POST", "/api/venues", {"name": "Tiny", "capacity": 0})[0], 400)
        e = desk.ok("POST", "/api/events", self._body(v, 60))
        self.assertEqual(manager.req("DELETE", f"/api/venues/{v['id']}")[0], 409)                    # has an event
        manager.ok("PUT", f"/api/venues/{v['id']}", {"name": "Garden", "capacity": 80, "hourly_rate": 1500, "active": False})
        self.assertEqual(desk.req("POST", "/api/events", self._body(v, 61))[0], 400)                 # switched off: no new events
        desk.ok("PUT", f"/api/events/{e['id']}", self._body(v, 60, attendees=30))                    # the existing one can still be edited
        acc = self.client("accountant")
        self.assertEqual(acc.req("GET", "/api/events")[0], 200)                                      # may look
        self.assertEqual(acc.req("POST", "/api/events", self._body(v, 62))[0], 403)
        for who in ("chef", "maid", "waiter", "amelia.hart@example.com"):
            self.assertEqual(self.client(who).req("GET", "/api/events")[0], 403, who)
        empty = manager.ok("POST", "/api/venues", {"name": "Unused", "capacity": 5})
        manager.ok("DELETE", f"/api/venues/{empty['id']}")
