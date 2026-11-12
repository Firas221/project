"""Tests for guest loyalty points."""
from support import AppTestCase  # first: puts the project on sys.path


class LoyaltyTests(AppTestCase):
    def _stay(self, c, guest=None, nights=1):
        """Checks a guest in today, pays the bill and checks them out. Returns the reservation before check-out."""
        extra = {"guest": guest} if guest else {}
        res = self.check_in_today(c, nights=nights + 1, **extra)
        return res

    def _settle_and_leave(self, c, res):
        folio = c.ok("GET", f"/api/reservations/{res['id']}")["folio"]
        if folio["balance"] > 0.004:
            c.ok("POST", f"/api/reservations/{res['id']}/payments", {"amount": folio["balance"], "method": "card"})
        return c.ok("POST", f"/api/reservations/{res['id']}/checkout", {"early_departure": True})

    def test_points_are_earned_at_check_out_on_spend_before_tax(self):
        desk = self.client("frontdesk")
        res = self._stay(desk, {"first_name": "Loyal", "last_name": "One", "nationality": "German", "id_number": "L1"})
        desk.ok("POST", f"/api/reservations/{res['id']}/charges", {"description": "Laundry", "unit_price": 250, "quantity": 1})
        self.assertEqual(desk.ok("GET", f"/api/guests/{res['guest_id']}")["loyalty"]["points"], 0)       # nothing until they leave
        out = self._settle_and_leave(desk, res)
        subtotal = out["folio"]["subtotal"]
        loyalty = desk.ok("GET", f"/api/guests/{res['guest_id']}")["loyalty"]
        self.assertEqual(loyalty["points"], int(subtotal * 10 / 100))                                    # 10 points per 100
        self.assertAlmostEqual(loyalty["value"], loyalty["points"] * 0.5, places=2)
        self.assertEqual(loyalty["history"][0]["reason"], f"Stay {res['code']}")
        self.assertEqual(loyalty["tier"], "Member")
        self.assertEqual(loyalty["next_tier"]["name"], "Silver")

    def test_redeem_takes_money_off_the_next_bill_and_voiding_returns_the_points(self):
        desk, manager = self.client("frontdesk"), self.client("manager")
        guest = {"first_name": "Loyal", "last_name": "Two", "nationality": "German", "id_number": "L2"}
        first = self._stay(desk, guest)
        self._settle_and_leave(desk, first)
        points = desk.ok("GET", f"/api/guests/{first['guest_id']}")["loyalty"]["points"]
        self.assertGreater(points, 100)

        second = self.book(desk, 20, 22, guest_id=first["guest_id"])
        before = desk.ok("GET", f"/api/reservations/{second['id']}")["folio"]
        self.assertEqual(desk.req("POST", f"/api/reservations/{second['id']}/redeem", {"points": points + 1})[0], 400)   # more than they have
        self.assertEqual(desk.req("POST", f"/api/reservations/{second['id']}/redeem", {"points": 0})[0], 400)
        after_redeem = desk.ok("POST", f"/api/reservations/{second['id']}/redeem", {"points": 100})
        self.assertEqual(after_redeem["points"], points - 100)
        folio = desk.ok("GET", f"/api/reservations/{second['id']}")["folio"]
        self.assertAlmostEqual(folio["subtotal"], before["subtotal"] - 50, places=2)                     # 100 points × 0.5
        self.assertLess(folio["total"], before["total"])                                                # and less tax on it
        line = next(c for c in folio["charges"] if c["category"] == "Loyalty")
        self.assertEqual(line["description"], "Loyalty points redeemed (100 points)")
        # the line cannot be moved to someone else's bill
        other = self.book(desk, 20, 22)
        self.assertEqual(desk.req("POST", f"/api/reservations/{second['id']}/charges/{line['id']}/transfer", {"target_code": other["code"]})[0], 400)
        # voiding it (a manager's permission) gives the points back
        self.assertEqual(desk.req("DELETE", f"/api/reservations/{second['id']}/charges/{line['id']}")[0], 403)
        manager.ok("DELETE", f"/api/reservations/{second['id']}/charges/{line['id']}")
        self.assertEqual(desk.ok("GET", f"/api/guests/{first['guest_id']}")["loyalty"]["points"], points)
        self.assertAlmostEqual(desk.ok("GET", f"/api/reservations/{second['id']}")["folio"]["subtotal"], before["subtotal"], places=2)

    def test_redemption_cannot_exceed_the_bill(self):
        desk, manager = self.client("frontdesk"), self.client("manager")
        res = self.book(desk, 30, 31)
        manager.ok("POST", f"/api/guests/{res['guest_id']}/points", {"points": 1_000_000, "reason": "Test balance"})
        status, err = desk.req("POST", f"/api/reservations/{res['id']}/redeem", {"points": 900_000})
        self.assertEqual(status, 400)
        self.assertIn("worth more than this bill", err["error"])

    def test_manager_adjusts_points_and_tiers_follow_stays_only(self):
        desk, manager = self.client("frontdesk"), self.client("manager")
        g = desk.ok("POST", "/api/guests", {"first_name": "Adjust", "last_name": "Me"})
        url = f"/api/guests/{g['id']}/points"
        self.assertEqual(desk.req("POST", url, {"points": 500, "reason": "x"})[0], 403)                 # not the front desk
        self.assertEqual(manager.req("POST", url, {"points": 500})[0], 400)                             # a reason is needed
        self.assertEqual(manager.req("POST", url, {"points": 0, "reason": "x"})[0], 400)
        self.assertEqual(manager.req("POST", url, {"points": -5, "reason": "x"})[0], 400)               # cannot go below zero
        loyalty = manager.ok("POST", url, {"points": 6000, "reason": "Goodwill after a complaint"})
        self.assertEqual((loyalty["points"], loyalty["value"]), (6000, 3000))
        self.assertEqual(loyalty["tier"], "Member")                                                     # gifts do not buy a tier
        self.assertEqual(manager.ok("POST", url, {"points": -1000, "reason": "Correction"})["points"], 5000)
        self.assertTrue(any(a["action"] == "loyalty_adjust" for a in manager.ok("GET", "/api/audit")))

    def test_guest_sees_their_points_and_switching_the_programme_off(self):
        admin, desk = self.client("admin"), self.client("frontdesk")
        guest = self.client("amelia.hart@example.com")
        mine = guest.ok("GET", "/api/portal/loyalty")
        self.assertTrue(mine["enabled"])
        self.assertEqual(guest.ok("GET", "/api/public/info")["settings"]["loyalty_point_value"], "0.5")
        self.assertNotIn("created_by_name", str(mine["history"]))                                       # no staff names for guests
        admin.ok("PUT", "/api/settings", {"loyalty_enabled": False})
        try:
            res = self._stay(desk, {"first_name": "No", "last_name": "Points", "nationality": "German", "id_number": "N1"})
            self._settle_and_leave(desk, res)
            self.assertEqual(desk.ok("GET", f"/api/guests/{res['guest_id']}")["loyalty"]["points"], 0)
            other = self.book(desk, 10, 12)
            self.assertEqual(desk.req("POST", f"/api/reservations/{other['id']}/redeem", {"points": 1})[0], 409)
            self.assertFalse(guest.ok("GET", "/api/portal/loyalty")["enabled"])
        finally:
            admin.ok("PUT", "/api/settings", {"loyalty_enabled": True})
        self.assertEqual(admin.req("PUT", "/api/settings", {"loyalty_points_per_100": -1})[0], 400)

    def test_erasing_a_guest_clears_their_points(self):
        admin, manager = self.client("admin"), self.client("manager")
        g = admin.ok("POST", "/api/guests", {"first_name": "Gone", "last_name": "Soon"})
        manager.ok("POST", f"/api/guests/{g['id']}/points", {"points": 300, "reason": "Welcome"})
        admin.ok("POST", f"/api/guests/{g['id']}/erase")
        loyalty = admin.ok("GET", f"/api/guests/{g['id']}")["loyalty"]
        self.assertEqual((loyalty["points"], loyalty["history"]), (0, []))
        self.assertEqual(manager.req("POST", f"/api/guests/{g['id']}/points", {"points": 5, "reason": "x"})[0], 409)


class SecondCurrencyTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.client("admin")
        self.admin.ok("PUT", "/api/settings", {"second_currency": "usd", "exchange_rate": 50})

    def test_setting_is_public_and_validated(self):
        s = self.client().ok("GET", "/api/public/info")["settings"]
        self.assertEqual((s["second_currency"], s["exchange_rate"]), ("USD", "50"))
        self.assertEqual(self.admin.req("PUT", "/api/settings", {"second_currency": "U$D"})[0], 400)
        self.assertEqual(self.admin.req("PUT", "/api/settings", {"exchange_rate": -1})[0], 400)

    def test_payment_in_the_second_currency_is_booked_at_the_rate(self):
        desk = self.client("frontdesk")
        res = self.book(desk, 15, 17)
        before = desk.ok("GET", f"/api/reservations/{res['id']}")["folio"]["balance"]
        out = desk.ok("POST", f"/api/reservations/{res['id']}/payments", {"amount": 100, "method": "card", "currency": "USD"})
        paid = out["folio"]["payments"][-1]
        self.assertEqual((paid["amount"], paid["currency"], paid["foreign_amount"], paid["fx_rate"]), (5000, "USD", 100, 50))
        self.assertAlmostEqual(out["folio"]["balance"], before - 5000, places=2)
        # the hotel's own currency, named or not, is taken as is
        desk.ok("POST", f"/api/reservations/{res['id']}/payments", {"amount": 200, "method": "card", "currency": "EGP"})
        desk.ok("POST", f"/api/reservations/{res['id']}/payments", {"amount": 300, "method": "card"})
        last_two = desk.ok("GET", f"/api/reservations/{res['id']}")["folio"]["payments"][-2:]
        self.assertEqual([(p["amount"], p["currency"]) for p in last_two], [(200, ""), (300, "")])
        self.assertEqual(desk.req("POST", f"/api/reservations/{res['id']}/payments", {"amount": 10, "method": "card", "currency": "EUR"})[0], 400)
        # the rate is fixed on the payment: changing it later does not rewrite history
        self.admin.ok("PUT", "/api/settings", {"exchange_rate": 60})
        again = desk.ok("GET", f"/api/reservations/{res['id']}")["folio"]["payments"]
        self.assertEqual((again[0]["amount"], again[0]["fx_rate"]), (5000, 50))
        self.assertTrue(any("100.00 USD @ 50" in a["details"] for a in self.admin.ok("GET", "/api/audit")))

    def test_foreign_cash_is_kept_out_of_the_drawer_count(self):
        desk = self.client("frontdesk")
        res = self.book(desk, 18, 20)
        desk.ok("POST", "/api/cashier/open", {"opening_float": 1000})
        desk.ok("POST", f"/api/reservations/{res['id']}/payments", {"amount": 400, "method": "cash"})
        desk.ok("POST", f"/api/reservations/{res['id']}/payments", {"amount": 20, "method": "cash", "currency": "USD"})
        shift = desk.ok("GET", "/api/cashier/shifts")["current"]
        self.assertEqual((shift["cash_taken"], shift["foreign_cash_taken"], shift["foreign_currency"]), (400, 20, "USD"))
        self.assertEqual(shift["total_taken"], 400 + 20 * 50)
        closed = desk.ok("POST", "/api/cashier/close", {"counted_cash": 1400})
        self.assertEqual((closed["expected_cash"], closed["variance"]), (1400, 0))       # the dollars are not counted as pounds

    def test_without_a_second_currency_foreign_payments_are_refused(self):
        self.admin.ok("PUT", "/api/settings", {"second_currency": "", "exchange_rate": 0})
        desk = self.client("frontdesk")
        res = self.book(desk, 21, 23)
        self.assertEqual(desk.req("POST", f"/api/reservations/{res['id']}/payments", {"amount": 10, "method": "card", "currency": "USD"})[0], 400)
