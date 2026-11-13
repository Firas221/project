"""Tests for the restaurant point of sale."""
from support import AppTestCase, d  # first: puts the project on sys.path


def stock(c, sku):
    return next(i for i in c.ok("GET", "/api/items") if i["sku"] == sku)


class RestaurantTests(AppTestCase):
    def _table(self, c, name):
        return next(t for t in c.ok("GET", "/api/restaurant/tables") if t["name"] == name)

    def _dish(self, c, name):
        return next(m for m in c.ok("GET", "/api/restaurant/menu") if m["name"] == name)

    def test_a_table_from_order_to_receipt(self):
        waiter, chef = self.client("waiter"), self.client("chef")
        table = self._table(waiter, "Table 3")
        check = waiter.ok("POST", "/api/restaurant/checks", {"table_id": table["id"], "covers": 2})
        self.assertEqual((check["status"], check["table_name"], check["total"]), ("open", "Table 3", 0))
        self.assertEqual(waiter.req("POST", "/api/restaurant/checks", {"table_id": table["id"]})[0], 409)      # one check per table
        burger, cola_price = self._dish(waiter, "Classic Burger & Fries"), None
        patties = stock(chef, "KT-BEEF")["quantity"]
        check = waiter.ok("POST", f"/api/restaurant/checks/{check['id']}/lines",
                          {"lines": [{"menu_item_id": burger["id"], "quantity": 2, "notes": "one without onions"}]})
        self.assertEqual(stock(chef, "KT-BEEF")["quantity"], patties - 2)                                    # ingredients leave the stock
        subtotal = 2 * burger["price"]
        service = round(subtotal * 0.12, 2)
        vat = round((subtotal + service) * 0.14, 2)
        self.assertEqual((check["subtotal"], check["service_charge"], check["vat"]), (subtotal, service, vat))
        self.assertAlmostEqual(check["total"], subtotal + service + vat, places=2)

        # the kitchen sees the ticket, marks it ready, and the waiter is told
        self.assertEqual(chef.ok("GET", "/api/alerts")["items"][0]["title"], "New restaurant order")
        ticket = next(t for t in chef.ok("GET", "/api/restaurant/tickets") if t["check_id"] == check["id"])
        self.assertEqual((ticket["table_name"], ticket["quantity"], ticket["notes"]), ("Table 3", 2, "one without onions"))
        self.assertEqual(waiter.req("POST", f"/api/restaurant/tickets/{ticket['id']}/ready")[0], 403)          # the cook does that
        chef.ok("POST", f"/api/restaurant/tickets/{ticket['id']}/ready")
        self.assertEqual(chef.req("POST", f"/api/restaurant/tickets/{ticket['id']}/ready")[0], 409)
        self.assertNotIn(check["id"], [t["check_id"] for t in chef.ok("GET", "/api/restaurant/tickets")])
        alert = waiter.ok("GET", "/api/alerts")["items"][0]
        self.assertEqual((alert["title"], alert["link"]), ("A dish is ready", f"#/restaurant/check/{check['id']}"))

        # payment issues a numbered receipt
        self.assertEqual(waiter.req("POST", f"/api/restaurant/checks/{check['id']}/pay", {"method": "bitcoin"})[0], 400)
        paid = waiter.ok("POST", f"/api/restaurant/checks/{check['id']}/pay", {"method": "card"})
        self.assertEqual(paid["status"], "paid")
        self.assertRegex(paid["receipt_number"], r"^RCP-\d{4}-000001$")
        receipt = waiter.ok("GET", f"/api/restaurant/checks/{check['id']}/receipt")
        self.assertEqual((receipt["total"], receipt["hotel"]["hotel_name"]), (paid["total"], "Nile Harbor Hotel"))
        self.assertEqual(waiter.req("POST", f"/api/restaurant/checks/{check['id']}/lines", {"lines": [{"menu_item_id": burger["id"]}]})[0], 409)
        # the table is free again
        again = waiter.ok("POST", "/api/restaurant/checks", {"table_id": table["id"]})
        self.assertEqual(waiter.req("POST", f"/api/restaurant/checks/{again['id']}/pay", {"method": "card"})[0], 409)   # nothing on it
        self.assertIsNone(cola_price)

    def test_charge_to_the_room_of_a_guest_who_is_staying(self):
        waiter, desk = self.client("waiter"), self.client("frontdesk")
        stay = self.check_in_today(desk, nights=2)
        rooms = waiter.ok("GET", "/api/restaurant/in-house")
        self.assertIn(stay["id"], [r["reservation_id"] for r in rooms])
        self.assertEqual(set(rooms[0]), {"reservation_id", "room_number", "guest_name"})                      # nothing more about the guest
        check = waiter.ok("POST", "/api/restaurant/checks", {"table_id": self._table(waiter, "Table 4")["id"]})
        dish = self._dish(waiter, "Caesar Salad")
        waiter.ok("POST", f"/api/restaurant/checks/{check['id']}/lines", {"lines": [{"menu_item_id": dish["id"], "quantity": 3}]})
        before = desk.ok("GET", f"/api/reservations/{stay['id']}")["folio"]
        booked = self.book(desk, 50, 52)
        self.assertEqual(waiter.req("POST", f"/api/restaurant/checks/{check['id']}/charge", {"reservation_id": booked["id"]})[0], 409)   # not staying yet
        charged = waiter.ok("POST", f"/api/restaurant/checks/{check['id']}/charge", {"reservation_id": stay["id"]})
        self.assertEqual((charged["status"], charged["receipt_number"]), ("charged", None))                   # the room invoice is the tax document
        after = desk.ok("GET", f"/api/reservations/{stay['id']}")["folio"]
        self.assertAlmostEqual(after["subtotal"], before["subtotal"] + 3 * dish["price"], places=2)           # taxes are added on the folio
        line = after["charges"][-1]
        self.assertEqual((line["category"], line["description"]), ("Food & Beverage", f"Restaurant {check['code']} (Table 4)"))

    def test_removing_dishes_and_voiding_a_check(self):
        waiter, manager, chef = self.client("waiter"), self.client("manager"), self.client("chef")
        check = waiter.ok("POST", "/api/restaurant/checks", {"customer_name": "Takeaway for Hany"})
        self.assertEqual(check["table_name"], "Takeaway")
        dish = self._dish(waiter, "Espresso")
        check = waiter.ok("POST", f"/api/restaurant/checks/{check['id']}/lines", {"lines": [{"menu_item_id": dish["id"], "quantity": 1},
                                                                                           {"menu_item_id": dish["id"], "quantity": 2}]})
        first, second = check["lines"]
        check = waiter.ok("DELETE", f"/api/restaurant/checks/{check['id']}/lines/{first['id']}")               # still in the kitchen: the waiter may
        self.assertEqual(check["subtotal"], 2 * dish["price"])
        chef.ok("POST", f"/api/restaurant/tickets/{second['id']}/ready")
        self.assertEqual(waiter.req("DELETE", f"/api/restaurant/checks/{check['id']}/lines/{second['id']}")[0], 403)   # made: a manager decides
        self.assertEqual(waiter.req("POST", f"/api/restaurant/checks/{check['id']}/void", {"reason": "walked out"})[0], 403)
        self.assertEqual(manager.req("POST", f"/api/restaurant/checks/{check['id']}/void", {})[0], 400)        # a reason is needed
        voided = manager.ok("POST", f"/api/restaurant/checks/{check['id']}/void", {"reason": "Guest walked out"})
        self.assertEqual(voided["status"], "void")
        self.assertEqual(manager.req("GET", f"/api/restaurant/checks/{check['id']}/receipt")[0], 409)
        self.assertTrue(any(a["action"] == "check_void" for a in manager.ok("GET", "/api/audit")))

    def test_unavailable_dishes_and_stock(self):
        waiter, chef = self.client("waiter"), self.client("chef")
        check = waiter.ok("POST", "/api/restaurant/checks", {"table_id": self._table(waiter, "Table 5")["id"]})
        salmon = next(m for m in chef.ok("GET", "/api/menu") if m["name"] == "Grilled Salmon")
        chef.ok("POST", f"/api/menu/{salmon['id']}/availability", {"available": False})
        self.assertNotIn("Grilled Salmon", [m["name"] for m in waiter.ok("GET", "/api/restaurant/menu")])
        self.assertEqual(waiter.req("POST", f"/api/restaurant/checks/{check['id']}/lines", {"lines": [{"menu_item_id": salmon["id"]}]})[0], 400)
        chef.ok("POST", f"/api/menu/{salmon['id']}/availability", {"available": True})
        status, err = waiter.req("POST", f"/api/restaurant/checks/{check['id']}/lines", {"lines": [{"menu_item_id": salmon["id"], "quantity": 99}]})
        self.assertEqual(status, 409)                                                                         # the kitchen has not got that many
        self.assertIn("Insufficient stock", err["error"])
        self.assertEqual(waiter.ok("GET", f"/api/restaurant/checks/{check['id']}")["lines"], [])              # and nothing was added

    def test_cash_goes_through_the_cashier_shift_and_sales_reach_the_reports(self):
        waiter, manager = self.client("waiter"), self.client("manager")
        check = waiter.ok("POST", "/api/restaurant/checks", {"table_id": self._table(waiter, "Table 6")["id"], "covers": 4})
        dish = self._dish(waiter, "Fresh Orange Juice")
        check = waiter.ok("POST", f"/api/restaurant/checks/{check['id']}/lines", {"lines": [{"menu_item_id": dish["id"], "quantity": 4}]})
        self.assertEqual(waiter.req("POST", f"/api/restaurant/checks/{check['id']}/pay", {"method": "cash"})[0], 409)   # no till open
        waiter.ok("POST", "/api/cashier/open", {"opening_float": 500})                                       # the waiter runs their own till
        paid = waiter.ok("POST", f"/api/restaurant/checks/{check['id']}/pay", {"method": "cash"})
        shift = waiter.ok("GET", "/api/cashier/shifts")["current"]
        self.assertEqual((shift["restaurant_cash"], shift["restaurant_taken"]), (paid["total"], paid["total"]))
        closed = waiter.ok("POST", "/api/cashier/close", {"counted_cash": 500 + paid["total"]})
        # ... but a till does not let a waiter touch room bills
        booked = self.book(self.client("frontdesk"), 55, 57)
        self.assertEqual(waiter.req("POST", f"/api/reservations/{booked['id']}/payments", {"amount": 10, "method": "card"})[0], 403)
        self.assertEqual(self.client("maid").req("POST", "/api/cashier/open", {"opening_float": 1})[0], 403)
        self.assertEqual(closed["variance"], 0)
        summary = manager.ok("GET", "/api/reports/summary")["restaurant"]
        self.assertGreaterEqual(summary["checks"], 1)
        self.assertGreaterEqual(summary["covers"], 4)
        tax = manager.ok("GET", f"/api/reports/tax?from={d(0)}&to={d(0)}")
        self.assertIn(paid["receipt_number"], [r["receipt_number"] for r in tax["restaurant"]["receipts"]])
        self.assertAlmostEqual(tax["grand_totals"]["vat"], tax["totals"]["vat"] + tax["restaurant"]["vat"], places=2)

    def test_tables_setup_and_who_may_do_what(self):
        manager, waiter = self.client("manager"), self.client("waiter")
        made = manager.ok("POST", "/api/restaurant/tables", {"name": "Bar 1", "seats": 2, "area": "Bar"})
        self.assertEqual(manager.req("POST", "/api/restaurant/tables", {"name": "bar 1"})[0], 409)
        self.assertEqual(waiter.req("POST", "/api/restaurant/tables", {"name": "Bar 2"})[0], 403)
        check = waiter.ok("POST", "/api/restaurant/checks", {"table_id": made["id"]})
        self.assertEqual(manager.req("DELETE", f"/api/restaurant/tables/{made['id']}")[0], 409)               # someone is sitting there
        manager.ok("POST", f"/api/restaurant/checks/{check['id']}/void", {"reason": "Opened by mistake"})
        manager.ok("PUT", f"/api/restaurant/tables/{made['id']}", {"name": "Bar 1", "seats": 2, "area": "Bar", "active": False})
        self.assertNotIn("Bar 1", [t["name"] for t in waiter.ok("GET", "/api/restaurant/floor")["tables"]])
        self.assertEqual(waiter.req("POST", "/api/restaurant/checks", {"table_id": made["id"]})[0], 400)
        manager.ok("DELETE", f"/api/restaurant/tables/{made['id']}")
        for who in ("frontdesk", "maid", "accountant", "amelia.hart@example.com"):
            self.assertEqual(self.client(who).req("GET", "/api/restaurant/floor")[0], 403, who)
        self.assertEqual(self.client("chef").req("GET", "/api/restaurant/tickets")[0], 200)
        self.assertEqual(self.client("maid").req("GET", "/api/restaurant/tickets")[0], 403)
        user = waiter.ok("GET", "/api/auth/me")["user"]
        self.assertEqual((user["role"], user["portal"]), ("waiter", "/restaurant"))
