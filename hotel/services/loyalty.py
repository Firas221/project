"""Guest loyalty: points earned on money spent, redeemed against a later bill."""
from ..core.clock import money
from ..core.errors import Conflict, ValidationError
from ..core.permissions import Perm
from ..core.validation import Int, Str
from .base import Service

# tier name and the points a guest must have earned from stays, highest first
TIERS = (("Platinum", 15000), ("Gold", 5000), ("Silver", 1000), ("Member", 0))
REDEEM_CATEGORY = "Loyalty"


class LoyaltyService(Service):
    def enabled(self) -> bool:
        return self.settings().get("loyalty_enabled", "1") == "1"

    def point_value(self) -> float:
        try:
            return float(self.settings().get("loyalty_point_value") or 0)
        except ValueError:
            return 0.0

    def summary(self, guest_id: int) -> dict:
        g = self.repos.guests.require(guest_id, "Guest")
        earned = self.repos.loyalty.lifetime_earned(guest_id)
        tier = next(name for name, floor in TIERS if earned >= floor)
        higher = [(name, floor) for name, floor in TIERS if floor > earned]
        return {"enabled": self.enabled(), "points": g["loyalty_points"], "value": money(g["loyalty_points"] * self.point_value()),
                "point_value": self.point_value(), "lifetime": earned, "tier": tier,
                "next_tier": {"name": higher[-1][0], "points_needed": higher[-1][1] - earned} if higher else None,
                "history": [{k: h[k] for k in ("points", "reason", "reservation_code", "created_by_name", "created_at")}
                            for h in self.repos.loyalty.history(guest_id)]}

    def _move(self, guest_id: int, points: int, reason: str, reservation_id=None, charge_id=None) -> int:
        g = self.repos.guests.require(guest_id, "Guest")
        balance = g["loyalty_points"] + points
        if balance < 0:
            raise ValidationError(f"The guest has only {g['loyalty_points']} points", field="points")
        self.repos.guests.update(guest_id, loyalty_points=balance)
        self.repos.loyalty.insert(guest_id=guest_id, reservation_id=reservation_id, charge_id=charge_id, points=points,
                                  reason=reason[:200], created_by=self.actor_id)
        return balance

    def earn_for_stay(self, res: dict, subtotal: float) -> int:
        """Called at check-out. Points are earned on what the guest spent before taxes, room and extras alike."""
        guest = self.repos.guests.get(res["guest_id"])
        try:
            per_100 = float(self.settings().get("loyalty_points_per_100") or 0)
        except ValueError:
            per_100 = 0
        points = int(max(0, subtotal) * per_100 / 100)
        if not self.enabled() or not points or not guest or guest["anonymized_at"]:
            return 0
        self._move(guest["id"], points, f"Stay {res['code']}", reservation_id=res["id"])
        return points

    def redeem(self, reservation_id: int, points) -> dict:
        """Takes points off the guest's balance and money off this bill."""
        self.require(Perm.BILLING_CHARGE)
        if not self.enabled():
            raise Conflict("The loyalty programme is switched off")
        res = self.repos.reservations.require(reservation_id, "Reservation")
        if res["status"] not in ("booked", "checked_in"):
            raise Conflict("This folio is closed")
        points = Int("Points", required=True, min_value=1, max_value=10_000_000).clean(points)
        from .billing import BillingService
        billing = self.use(BillingService)
        discount = money(points * self.point_value())
        if discount <= 0:
            raise ValidationError("These points are worth nothing at the current point value", field="points")
        if discount > billing.folio(res)["subtotal"] + 0.004:
            raise ValidationError("The points are worth more than this bill. Redeem fewer points.", field="points")
        self._move(res["guest_id"], -points, f"Redeemed on {res['code']}", reservation_id=res["id"])
        charge_id = self.repos.charges.insert(reservation_id=res["id"], description=f"Loyalty points redeemed ({points} points)",
                                              category=REDEEM_CATEGORY, quantity=1, unit_price=-discount, amount=-discount,
                                              created_by=self.actor_id)
        last = self.repos.loyalty.history(res["guest_id"], 1)[0]
        self.repos.loyalty.update(last["id"], charge_id=charge_id)
        self.audit("loyalty_redeem", "reservation", res["id"], f"{res['code']}: {points} points = {discount:.2f}")
        return self.summary(res["guest_id"])

    def redemption_voided(self, res: dict, charge: dict) -> None:
        """A redemption line was removed from a folio: the guest gets the points back."""
        row = self.repos.loyalty.fetch_one("SELECT * FROM loyalty_ledger WHERE charge_id = ?", (charge["id"],))
        if row:
            self._move(row["guest_id"], -row["points"], f"Redemption on {res['code']} cancelled", reservation_id=res["id"])

    def adjust(self, guest_id: int, points, reason: str) -> dict:
        """A manager adds or removes points by hand (a goodwill gesture, a correction)."""
        self.require(Perm.BILLING_VOID)
        g = self.repos.guests.require(guest_id, "Guest")
        if g["anonymized_at"]:
            raise Conflict("This guest's personal data was erased and cannot be edited")
        points = Int("Points", required=True, min_value=-10_000_000, max_value=10_000_000).clean(points)
        reason = Str("Reason", required=True, max_len=200).clean(reason or "")
        if not points:
            raise ValidationError("Enter a number of points to add or remove", field="points")
        if not reason:
            raise ValidationError("Reason is required", field="reason")
        self._move(guest_id, points, reason)
        self.audit("loyalty_adjust", "guest", guest_id, f"{points:+d}: {reason}")
        return self.summary(guest_id)
