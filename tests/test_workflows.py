"""End-to-end hotel workflows across departments."""
import os
import sqlite3

from support import AppTestCase, d


def stock(c, sku):
    return next(i for i in c.ok("GET", "/api/items?include_inactive=1") if i["sku"] == sku)


class ReservationTests(AppTestCase):
    def test_no_double_booking_and_back_to_back(self):
        c = self.client("frontdesk")
        res = self.book(c, 30, 33)
        status, err = c.req("POST", "/api/reservations", {"guest_id": res["guest_id"], "room_id": res["room_id"],
                                                          "check_in": d(32), "check_out": d(35)})
        self.assertEqual(status, 409, err)
        c.ok("POST", "/api/reservations", {"guest_id": res["guest_id"], "room_id": res["room_id"], "check_in": d(33), "check_out": d(34)})
        free = {r["id"] for r in c.ok("GET", f"/api/availability?check_in={d(31)}&check_out={d(32)}")}
        self.assertNotIn(res["room_id"], free)

    def test_validation(self):
        c = self.client("frontdesk")
        room = self.free_room(c, d(40), d(41))
        for body in ({"guest_id": 1, "room_id": room["id"], "check_in": d(41), "check_out": d(40)},
                     {"guest_id": 1, "room_id": room["id"], "check_in": "tomorrow", "check_out": d(41)},
                     {"guest_id": 1, "room_id": room["id"], "check_in": d(40), "check_out": d(41), "adults": 9},
                     {"room_id": room["id"], "check_in": d(40), "check_out": d(41)},
                     {"guest_id": 1, "room_id": 99999, "check_in": d(40), "check_out": d(41)},
                     {"guest_id": 1, "room_id": room["id"], "check_in": d(-20), "check_out": d(-18)}):
            self.assertIn(c.req("POST", "/api/reservations", body)[0], (400, 404, 409), body)

    def test_pricing_seasons_weekends_promos_companies(self):
        c = self.client("admin")
        types = c.ok("GET", "/api/room-types")
        deluxe = next(t for t in types if t["name"] == "Deluxe King")
        season = c.ok("POST", "/api/seasons", {"name": "Test peak", "start_date": d(60), "end_date": d(66), "adjust_pct": 50,
                                               "min_nights": 3, "room_type_id": deluxe["id"]})
        q = c.ok("GET", f"/api/quote?room_type_id={deluxe['id']}&check_in={d(60)}&check_out={d(61)}")
        self.assertFalse(q["meets_min_stay"])
        q = c.ok("GET", f"/api/quote?room_type_id={deluxe['id']}&check_in={d(60)}&check_out={d(63)}")
        self.assertTrue(q["meets_min_stay"])
        for night in q["nightly"]:
            self.assertGreaterEqual(night["rate"], deluxe["base_rate"] * 1.5 - 0.01)
        c.ok("POST", "/api/promos", {"code": "nile20", "discount_pct": 20, "valid_from": d(-1), "valid_to": d(90)})
        qp = c.ok("GET", f"/api/quote?room_type_id={deluxe['id']}&check_in={d(70)}&check_out={d(72)}&promo_code=NILE20")
        self.assertAlmostEqual(qp["total"], qp["subtotal"] * 0.8, places=1)
        company = c.ok("GET", "/api/companies")[0]
        qc = c.ok("GET", f"/api/quote?room_type_id={deluxe['id']}&check_in={d(70)}&check_out={d(72)}&company_id={company['id']}")
        self.assertEqual(qc["discount_pct"], company["discount_pct"])
        self.assertEqual(c.req("GET", f"/api/quote?room_type_id={deluxe['id']}&check_in={d(70)}&check_out={d(72)}&promo_code=FAKE")[0], 400)
        c.ok("DELETE", f"/api/seasons/{season['id']}")

    def test_group_booking(self):
        c = self.client("frontdesk")
        rooms = c.ok("GET", f"/api/availability?check_in={d(80)}&check_out={d(82)}")[:3]
        r = c.ok("POST", "/api/reservations/group", {"group_name": "Conference", "guest_id": 1, "check_in": d(80), "check_out": d(82),
                                                     "rooms": [{"room_id": x["id"]} for x in rooms]})
        self.assertEqual(len(r["reservations"]), 3)
        self.assertTrue(all(x["group_code"] == r["group_code"] for x in r["reservations"]))

    def test_cancel_and_noshow_rules(self):
        c = self.client("frontdesk")
        res = c.ok("POST", f"/api/reservations/{self.book(c, 50, 52)['id']}/cancel", {"fee": 500, "reason": "Plans changed"})
        self.assertEqual(res["status"], "cancelled")
        self.assertEqual(res["folio"]["room_total"], 0)
        self.assertAlmostEqual(res["folio"]["total"], round(500 * 1.12 * 1.14, 2))
        future = self.book(c, 54, 57)
        self.assertEqual(c.req("POST", f"/api/reservations/{future['id']}/noshow")[0], 409)
        self.assertEqual(c.req("POST", f"/api/reservations/{future['id']}/checkin")[0], 409)


class StayLifecycleTests(AppTestCase):
    def test_full_stay_with_egyptian_taxes(self):
        c = self.client("frontdesk")
        guest = c.ok("POST", "/api/guests", {"first_name": "No", "last_name": "Papers"})
        room = self.free_room(c, d(0), d(2))
        res = c.ok("POST", "/api/reservations", {"guest_id": guest["id"], "room_id": room["id"], "check_in": d(0), "check_out": d(2),
                                                 "deposit": 1000, "deposit_method": "card"})
        c.ok("POST", f"/api/rooms/{room['id']}/status", {"status": "clean"})
        status, err = c.req("POST", f"/api/reservations/{res['id']}/checkin")
        self.assertEqual(status, 400)                    # nationality + ID required (Egyptian guest registration)
        self.assertIn("registration", err["error"])
        c.ok("PUT", f"/api/guests/{guest['id']}", {"first_name": "No", "last_name": "Papers", "nationality": "Jordanian", "id_number": "J998877"})
        c.ok("POST", f"/api/reservations/{res['id']}/checkin")

        water = stock(c, "MB-WATER")
        res = c.ok("POST", f"/api/reservations/{res['id']}/charges", {"item_id": water["id"], "quantity": 3})
        self.assertEqual(stock(c, "MB-WATER")["quantity"], water["quantity"] - 3)
        res = c.ok("POST", f"/api/reservations/{res['id']}/charges", {"description": "Laundry", "unit_price": 150, "quantity": 2})
        f = res["folio"]
        subtotal = round(res["rate"] * 2 + 3 * water["price"] + 300, 2)
        self.assertAlmostEqual(f["subtotal"], subtotal, places=2)
        self.assertAlmostEqual(f["service_charge"], round(subtotal * 0.12, 2), places=2)
        self.assertAlmostEqual(f["vat"], round((subtotal + f["service_charge"]) * 0.14, 2), places=2)
        self.assertAlmostEqual(f["balance"], round(f["total"] - 1000, 2), places=2)

        # staff cannot void (supervisor permission); admin can
        charge = next(x for x in f["charges"] if x["item_id"])
        self.assertEqual(c.req("DELETE", f"/api/reservations/{res['id']}/charges/{charge['id']}")[0], 403)
        self.client("admin").ok("DELETE", f"/api/reservations/{res['id']}/charges/{charge['id']}")
        self.assertEqual(stock(c, "MB-WATER")["quantity"], water["quantity"])

        # cash needs an open cashier shift
        bal = c.ok("GET", f"/api/reservations/{res['id']}")["folio"]["balance"]
        self.assertEqual(c.req("POST", f"/api/reservations/{res['id']}/payments", {"amount": 100, "method": "cash"})[0], 409)
        c.ok("POST", "/api/cashier/open", {"opening_float": 2000})
        c.ok("POST", f"/api/reservations/{res['id']}/payments", {"amount": 100, "method": "cash"})
        self.assertEqual(c.req("POST", f"/api/reservations/{res['id']}/checkout")[0], 409)   # balance outstanding
        c.ok("POST", f"/api/reservations/{res['id']}/payments", {"amount": round(bal - 100, 2), "method": "card"})
        out = c.ok("POST", f"/api/reservations/{res['id']}/checkout")
        self.assertEqual(out["status"], "checked_out")
        self.assertTrue(out["invoice"]["number"].startswith("INV-"))
        inv = c.ok("GET", f"/api/invoices/{out['invoice']['id']}")
        self.assertAlmostEqual(inv["total"], out["folio"]["total"])
        self.assertEqual(inv["data"]["totals"]["vat_rate"], 14.0)
        closed = c.ok("POST", "/api/cashier/close", {"counted_cash": 2100})
        self.assertEqual(closed["variance"], 0)
        # room handed to housekeeping
        room_now = next(r for r in c.ok("GET", "/api/rooms") if r["id"] == room["id"])
        self.assertEqual(room_now["status"], "dirty")
        tasks = c.ok("GET", "/api/housekeeping/tasks")
        self.assertTrue(any(t["room_id"] == room["id"] and t["kind"] == "checkout_clean" for t in tasks))
        self.assertEqual(c.req("POST", f"/api/reservations/{res['id']}/payments", {"amount": 1, "method": "card"})[0], 409)

    def test_corporate_city_ledger(self):
        c = self.client("frontdesk")
        company = c.ok("GET", "/api/companies")[0]
        res = self.check_in_today(c, 1, company_id=company["id"], bill_to_company=True)
        before = self.client("admin").ok("GET", f"/api/companies/{company['id']}")["balance"]
        out = c.ok("POST", f"/api/reservations/{res['id']}/checkout")
        self.assertEqual(out["folio"]["balance"], 0)
        after = self.client("admin").ok("GET", f"/api/companies/{company['id']}")["balance"]
        self.assertAlmostEqual(after - before, out["folio"]["total"], places=2)
        self.assertEqual(out["invoice"]["bill_to"], company["name"])

    def test_early_departure(self):
        c = self.client("frontdesk")
        res = self.check_in_today(c, 4)
        self.assertEqual(res["folio"]["nights"], 4)
        # Leaving on the day of arrival still bills the minimum of one night; pay that and check out early.
        one_night = round(res["rate"] * 1.12 * 1.14, 2)
        c.ok("POST", f"/api/reservations/{res['id']}/payments", {"amount": one_night, "method": "card"})
        out = c.ok("POST", f"/api/reservations/{res['id']}/checkout", {"early_departure": True})
        self.assertEqual(out["folio"]["nights"], 1)
        self.assertEqual(out["check_out"], d(1))
        self.assertAlmostEqual(out["folio"]["balance"], 0, places=2)


class KitchenTests(AppTestCase):
    def test_guest_order_to_folio_with_ingredient_deduction(self):
        staff = self.client("frontdesk")
        guest = self.client("amelia.hart@example.com")
        res = next(r for r in guest.ok("GET", "/api/portal/reservations") if r["status"] == "checked_in")
        menu = guest.ok("GET", "/api/portal/menu")
        burger = next(m for m in menu if "Burger" in m["name"])
        order = guest.ok("POST", f"/api/portal/reservations/{res['id']}/orders", {"lines": [{"menu_item_id": burger["id"], "quantity": 2}]})
        chef = self.client("chef")
        oid = next(o["id"] for o in chef.ok("GET", "/api/kitchen/orders") if o["code"] == order["code"])
        beef = stock(staff, "KT-BEEF")["quantity"]
        chef.ok("POST", f"/api/kitchen/orders/{oid}/status", {"status": "preparing"})
        self.assertEqual(stock(staff, "KT-BEEF")["quantity"], beef - 2)
        self.assertEqual(staff.req("POST", f"/api/reservations/{res['id']}/checkout")[0], 409)   # open order blocks checkout
        self.assertEqual(chef.req("POST", f"/api/kitchen/orders/{oid}/status", {"status": "delivered"})[0], 409)  # must be ready first
        chef.ok("POST", f"/api/kitchen/orders/{oid}/status", {"status": "ready"})
        staff.ok("POST", f"/api/kitchen/orders/{oid}/status", {"status": "delivered"})
        folio = staff.ok("GET", f"/api/reservations/{res['id']}")["folio"]
        self.assertTrue(any(ch["description"] == f"Room service {order['code']}" and ch["amount"] == burger["price"] * 2 for ch in folio["charges"]))

    def test_menu_management_and_availability(self):
        chef = self.client("chef")
        eggs = stock(self.client("admin"), "KT-EGGS")
        m = chef.ok("POST", "/api/menu", {"name": "Shakshuka", "price": 220, "category": "Breakfast",
                                          "ingredients": [{"item_id": eggs["id"], "quantity": 3}]})
        self.assertEqual(m["ingredients"][0]["quantity"], 3)
        chef.ok("POST", f"/api/menu/{m['id']}/availability", {"available": False})
        guest = self.client("amelia.hart@example.com")
        self.assertNotIn("Shakshuka", [x["name"] for x in guest.ok("GET", "/api/portal/menu")])


class HousekeepingAndMaintenanceTests(AppTestCase):
    def test_clean_inspect_cycle(self):
        maid = self.client("maid")
        task = next(t for t in maid.ok("GET", "/api/housekeeping/tasks?mine=1") if t["assigned_to"] and t["status"] == "open")
        maid.ok("POST", f"/api/housekeeping/tasks/{task['id']}/start")
        maid.ok("POST", f"/api/housekeeping/tasks/{task['id']}/complete", {"notes": "Replaced towels"})
        staff = self.client("frontdesk")
        room = next(r for r in staff.ok("GET", "/api/rooms") if r["id"] == task["room_id"])
        self.assertEqual(room["status"], "clean")
        self.assertEqual(maid.req("POST", f"/api/housekeeping/tasks/{task['id']}/inspect", {"passed": True})[0], 403)
        staff.ok("POST", f"/api/housekeeping/tasks/{task['id']}/inspect", {"passed": False, "notes": "Dust under bed"})
        room = next(r for r in staff.ok("GET", "/api/rooms") if r["id"] == task["room_id"])
        self.assertEqual(room["status"], "dirty")
        maid.ok("POST", f"/api/housekeeping/tasks/{task['id']}/start")
        maid.ok("POST", f"/api/housekeeping/tasks/{task['id']}/complete")
        staff.ok("POST", f"/api/housekeeping/tasks/{task['id']}/inspect", {"passed": True})
        room = next(r for r in staff.ok("GET", "/api/rooms") if r["id"] == task["room_id"])
        self.assertEqual(room["status"], "inspected")

    def test_out_of_order_and_repair(self):
        staff = self.client("frontdesk")
        rooms = staff.ok("GET", "/api/rooms")
        room = next(r for r in rooms if not r["occupied"] and r["status"] != "maintenance")
        maid = self.client("maid")
        t = maid.ok("POST", "/api/maintenance", {"room_id": room["id"], "title": "Broken lamp", "out_of_order": True})
        self.assertFalse(t["out_of_order"])          # housekeepers cannot take rooms out of order
        t = staff.ok("POST", "/api/maintenance", {"room_id": room["id"], "title": "Water leak", "out_of_order": True, "priority": "urgent"})
        free = {r["id"] for r in staff.ok("GET", f"/api/availability?check_in={d(0)}&check_out={d(1)}")}
        self.assertNotIn(room["id"], free)
        staff.ok("PUT", f"/api/maintenance/{t['id']}", {"status": "resolved", "resolution": "Pipe replaced"})
        now = next(r for r in staff.ok("GET", "/api/rooms") if r["id"] == room["id"])
        self.assertEqual(now["status"], "dirty")
        self.assertTrue(any(x["room_id"] == room["id"] and x["kind"] == "deep_clean" for x in staff.ok("GET", "/api/housekeeping/tasks")))

    def test_guest_request_routing(self):
        guest = self.client("amelia.hart@example.com")
        res = next(r for r in guest.ok("GET", "/api/portal/reservations") if r["status"] == "checked_in")
        guest.ok("POST", f"/api/portal/reservations/{res['id']}/requests", {"kind": "maintenance", "message": "Shower is cold"})
        staff = self.client("frontdesk")
        self.assertTrue(any("Shower is cold" in t["title"] for t in staff.ok("GET", "/api/maintenance")))
        req = next(r for r in staff.ok("GET", "/api/requests") if r["message"] == "Shower is cold")
        staff.ok("POST", f"/api/requests/{req['id']}", {"status": "done", "response": "Fixed"})
        detail = guest.ok("GET", f"/api/portal/reservations/{res['id']}")
        self.assertTrue(any(q["response"] == "Fixed" for q in detail["requests"]))


class InventoryTests(AppTestCase):
    def test_supply_request_approval(self):
        chef = self.client("chef")
        admin = self.client("admin")
        flour = admin.ok("POST", "/api/items", {"sku": "KT-FLOUR", "name": "Flour", "department": "kitchen", "unit": "kg", "quantity": 20, "cost": 25})
        req = chef.ok("POST", "/api/stock-requests", {"lines": [{"item_id": flour["id"], "quantity": 5}], "notes": "Bread"})
        self.assertEqual(req["department"], "kitchen")
        self.assertEqual(chef.req("POST", f"/api/stock-requests/{req['id']}/decide", {"approve": True})[0], 403)
        admin.ok("POST", f"/api/stock-requests/{req['id']}/decide", {"approve": True})
        self.assertEqual(stock(admin, "KT-FLOUR")["quantity"], 15)
        big = chef.ok("POST", "/api/stock-requests", {"lines": [{"item_id": flour["id"], "quantity": 999}]})
        self.assertEqual(admin.req("POST", f"/api/stock-requests/{big['id']}/decide", {"approve": True})[0], 409)

    def test_purchase_order_receiving_updates_cost(self):
        admin = self.client("admin")
        item = admin.ok("POST", "/api/items", {"sku": "T-PO", "name": "PO item", "quantity": 10, "cost": 10, "supplier_id": 1})
        po = admin.ok("POST", "/api/purchase-orders", {"supplier_id": 1, "lines": [{"item_id": item["id"], "quantity": 10, "unit_cost": 20}]})
        self.assertEqual(admin.req("POST", f"/api/purchase-orders/{po['id']}/status", {"status": "received"})[0], 409)  # must be ordered first
        admin.ok("POST", f"/api/purchase-orders/{po['id']}/status", {"status": "ordered"})
        admin.ok("POST", f"/api/purchase-orders/{po['id']}/status", {"status": "received"})
        now = stock(admin, "T-PO")
        self.assertEqual(now["quantity"], 20)
        self.assertEqual(now["cost"], 15)   # weighted average
        low = admin.ok("POST", "/api/purchase-orders/from-low-stock", {"supplier_id": 2})
        self.assertTrue(low["lines"])

    def test_stock_never_negative(self):
        admin = self.client("admin")
        item = admin.ok("POST", "/api/items", {"sku": "T-NEG", "name": "Neg", "quantity": 2})
        self.assertEqual(admin.req("POST", f"/api/items/{item['id']}/movements", {"kind": "issue", "quantity": 3})[0], 409)
        self.assertEqual(admin.req("POST", f"/api/items/{item['id']}/movements", {"kind": "adjust", "counted": 1})[0], 400)  # reason required
        admin.ok("POST", f"/api/items/{item['id']}/movements", {"kind": "adjust", "counted": 1, "reason": "Breakage"})


class GuestPortalTests(AppTestCase):
    def test_online_booking_and_cancellation(self):
        guest = self.client("amelia.hart@example.com")
        offers = guest.ok("POST", "/api/public/search", {"check_in": d(100), "check_out": d(103), "adults": 2})["offers"]
        self.assertTrue(offers)
        res = guest.ok("POST", "/api/portal/reservations", {"room_type_id": offers[0]["id"], "check_in": d(100), "check_out": d(103),
                                                            "adults": 2, "promo_code": "WELCOME10"})
        self.assertEqual(res["status"], "booked")
        self.assertIsNone(res["room_number"])        # room numbers are not revealed before arrival
        self.assertTrue(res["can_cancel"])
        cancelled = guest.ok("POST", f"/api/portal/reservations/{res['id']}/cancel")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(guest.req("POST", "/api/public/search", {"check_in": d(-3), "check_out": d(-1)})[0], 400)

    def test_review_after_stay_and_moderation(self):
        guest = self.client("amelia.hart@example.com")
        stays = guest.ok("GET", "/api/portal/reservations")
        done = next(r for r in stays if r["status"] == "checked_out" and not r["has_review"]) if any(
            r["status"] == "checked_out" and not r["has_review"] for r in stays) else None
        active = next(r for r in stays if r["status"] in ("booked", "checked_in"))
        self.assertEqual(guest.req("POST", f"/api/portal/reservations/{active['id']}/review", {"rating": 5})[0], 409)
        if done:
            guest.ok("POST", f"/api/portal/reservations/{done['id']}/review", {"rating": 4, "comment": "Lovely"})


class ReportsAndAdminTests(AppTestCase):
    def test_reports_exports_and_csv_injection(self):
        admin = self.client("admin")
        admin.ok("POST", "/api/guests", {"first_name": "=HYPERLINK(\"http://x\")", "last_name": "Evil"})
        rep = admin.ok("GET", f"/api/reports/summary?from={d(-14)}&to={d(0)}")
        self.assertEqual(len(rep["daily"]), 15)
        self.assertGreater(rep["totals"]["room_revenue"], 0)
        admin.ok("GET", f"/api/reports/tax?from={d(-30)}&to={d(0)}")
        for name in ("reservations", "guests", "items", "movements", "daily", "tax", "guest_register", "audit"):
            status, body = admin.req("GET", f"/api/export/{name}")
            self.assertEqual(status, 200, name)
        _, guests_csv = admin.req("GET", "/api/export/guests")
        self.assertIn("'=HYPERLINK", guests_csv)
        self.assertEqual(self.client("chef").req("GET", "/api/export/guests")[0], 403)

    def test_settings_and_backup(self):
        admin = self.client("admin")
        s = admin.ok("PUT", "/api/settings", {"vat_rate": 14, "service_charge_rate": 12, "tax_registration_number": "123-456-789"})
        self.assertEqual(s["tax_registration_number"], "123-456-789")
        self.assertEqual(admin.req("PUT", "/api/settings", {"vat_rate": 99})[0], 400)
        b = admin.ok("POST", "/api/backups")
        path = os.path.join(self.app.config.backup_dir, b["file"])
        db = sqlite3.connect(path)
        self.assertGreater(db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0], 0)
        db.close()


class NightAuditTests(AppTestCase):
    def test_close_day_marks_no_shows(self):
        admin = self.client("admin")
        preview = admin.ok("GET", "/api/night-audit")
        self.assertTrue(preview["can_close"])
        pending = len(preview["pending_arrivals"])
        self.assertEqual(self.client("frontdesk").req("POST", "/api/night-audit/close", {})[0], 403)
        after = admin.ok("POST", "/api/night-audit/close", {"mark_no_shows": True})
        self.assertEqual(after["history"][0]["no_shows"], pending)
        self.assertEqual(after["business_date"], d(1))
        self.assertFalse(after["can_close"])
        self.assertEqual(admin.req("POST", "/api/night-audit/close", {})[0], 409)
