"""Guest-facing (client) features. Every method is scoped to the signed-in guest's own records."""
from ..core.clock import add_days, nights, today_iso
from ..core.errors import Conflict, NotFound, PermissionDenied, ValidationError
from ..core.permissions import Perm
from ..core.validation import Date, Int, Phone, Schema, Str
from .admin import PrivacyService
from .base import Service
from .billing import BillingService, InvoiceService
from .front_office import PricingService
from .kitchen import MenuService, OrderService
from .operations import GuestRequestService, ReviewService
from .reservations import ReservationService


class SearchSchema(Schema):
    check_in = Date(required=True)
    check_out = Date(required=True)
    adults = Int(min_value=1, max_value=10, default=2)
    children = Int(min_value=0, max_value=10, default=0)
    promo_code = Str(max_len=30, upper=True)


class ChangeSchema(Schema):
    check_in = Date(required=True)
    check_out = Date(required=True)
    adults = Int(min_value=1, max_value=10, default=1)
    children = Int(min_value=0, max_value=10, default=0)
    room_type_id = Int("Room type", nullable=True, default=None)


STAY_FIELDS = ("id", "code", "check_in", "check_out", "nights", "room_type", "room_type_id", "status", "adults", "children",
               "rate", "special_requests", "rate_plan_name", "meal_plan", "refundable")


class ProfileSchema(Schema):
    first_name = Str(required=True, max_len=80)
    last_name = Str(required=True, max_len=80)
    phone = Phone()
    address = Str(max_len=300)
    nationality = Str(max_len=60)
    language = Str(choices=("", "en", "ar"))


class PublicService(Service):
    """Unauthenticated website features."""

    def room_types(self) -> list:
        photos = self.repos.room_photos.ids_by_type()
        return [{k: t[k] for k in ("id", "name", "description", "base_rate", "capacity", "bed_type", "size_sqm", "amenities")}
                | {"photos": photos.get(t["id"], [])}
                for t in self.repos.room_types.all() if t["active"]]

    def search(self, data: dict) -> dict:
        v = SearchSchema.validate(data)
        self.check_online_stay(v["check_in"], v["check_out"])
        free = self.repos.rooms.available(v["check_in"], v["check_out"], v["adults"] + v["children"])
        counts = {}
        for room in free:
            counts[room["type_id"]] = counts.get(room["type_id"], 0) + 1
        pricing = self.use(PricingService)
        plans = pricing.rate_plans(online=True)
        pax = {"adults": v["adults"], "children": v["children"]}
        offers = []
        for t in self.room_types():
            if t["id"] not in counts:
                continue
            try:
                q = pricing.quote(t["id"], v["check_in"], v["check_out"], v["promo_code"], online=True, **pax)
            except ValidationError as e:
                if e.field == "promo_code":
                    raise
                continue
            # Other ways to book the same room: with meals, or a cheaper rate that cannot be cancelled.
            options = [{k: p[k] for k in ("id", "name", "name_ar", "description", "meal_plan", "refundable")}
                       | {"quote": pricing.quote(t["id"], v["check_in"], v["check_out"], v["promo_code"], online=True,
                                                 rate_plan=p, **pax)} for p in plans]
            offers.append({**t, "rooms_left": min(counts[t["id"]], 5), "quote": q, "plans": options})
        return {"check_in": v["check_in"], "check_out": v["check_out"], "offers": offers}

    def check_online_stay(self, check_in: str, check_out: str) -> None:
        """The limits every online booking (new or changed) must respect."""
        s = self.settings()
        if s.get("online_booking_enabled") != "1":
            raise Conflict("Online booking is currently unavailable. Please contact the hotel.")
        v = {"check_in": check_in, "check_out": check_out}
        if v["check_in"] < today_iso():
            raise ValidationError("Arrival date cannot be in the past", field="check_in")
        if v["check_out"] <= v["check_in"]:
            raise ValidationError("Departure must be after arrival", field="check_out")
        if nights(v["check_in"], v["check_out"]) > int(s.get("max_online_nights") or 30):
            raise ValidationError(f"Online bookings are limited to {s.get('max_online_nights')} nights")
        if v["check_in"] > add_days(today_iso(), 540):
            raise ValidationError("Bookings open up to 18 months ahead")


class GuestPortalService(Service):
    # ------------------------------------------------------------ guards
    def _guest_id(self) -> int:
        if not self.actor or not self.actor.can(Perm.PORTAL_GUEST) or not self.actor.guest_id:
            raise PermissionDenied()
        if self.actor.must_verify_email:
            raise PermissionDenied("Please confirm your e-mail address first. We sent you a link when you registered.")
        return self.actor.guest_id

    def _own_reservation(self, reservation_id: int) -> dict:
        res = self.repos.reservations.get(reservation_id)
        if not res or res["guest_id"] != self._guest_id():
            raise NotFound("Reservation not found")  # never reveal other guests' bookings
        return res

    # ------------------------------------------------------------ profile
    def profile(self) -> dict:
        g = self.repos.guests.require(self._guest_id())
        return {k: g[k] for k in ("first_name", "last_name", "email", "phone", "address", "nationality", "language",
                                  "marketing_consent", "privacy_accepted_at")}

    def set_language(self, language: str) -> None:
        """Remembers the language the guest reads the site in, so their e-mails arrive in it."""
        if language not in ("en", "ar"):
            raise ValidationError("Unknown language", field="language")
        self.repos.guests.update(self._guest_id(), language=language)

    def update_profile(self, data: dict) -> dict:
        gid = self._guest_id()
        v = ProfileSchema.validate(data)
        self.repos.guests.update(gid, **v)
        self.repos.users.update(self.actor.id, full_name=f"{v['first_name']} {v['last_name']}")
        self.audit("guest_profile_update", "guest", gid)
        return self.profile()

    # ------------------------------------------------------------ bookings
    def reservations(self) -> list:
        billing = self.use(BillingService)
        rows = self.repos.reservations.search(guest_id=self._guest_id())
        out = []
        for r in rows:
            f = billing.folio(r)
            out.append({k: r[k] for k in STAY_FIELDS}
                       | {"room_number": r["room_number"] if r["status"] == "checked_in" else None,
                          "total": f["total"], "balance": f["balance"],
                          "can_cancel": self._can_cancel(r), "can_change": self._can_cancel(r), "has_review": self.repos.reviews.exists(reservation_id=r["id"])})
        return out

    def reservation(self, reservation_id: int) -> dict:
        res = self._own_reservation(reservation_id)
        f = self.use(BillingService).folio(res)
        inv = self.repos.invoices.first_by(reservation_id=res["id"])
        return {
            **{k: res[k] for k in STAY_FIELDS},
            "room_number": res["room_number"] if res["status"] == "checked_in" else None,
            "folio": {k: f[k] for k in ("room_total", "subtotal", "service_charge_rate", "service_charge", "vat_rate",
                                        "vat", "city_tax", "total", "paid", "balance", "nights")}
            | {"charges": [{"date": c["created_at"], "description": c["description"], "amount": c["amount"]}
                           for c in f["charges"]],
               "payments": [{"date": p["created_at"], "method": p["method"], "amount": p["amount"]} for p in f["payments"]]},
            "invoice_id": inv["id"] if inv else None,
            "can_cancel": self._can_cancel(res), "can_change": self._can_cancel(res),
            "orders": [{"code": o["code"], "status": o["status"], "total": o["total"], "created_at": o["created_at"]}
                       for o in self.repos.orders.search(reservation_id=res["id"])],
            "requests": [{"kind": q["kind"], "message": q["message"], "status": q["status"], "response": q["response"],
                          "created_at": q["created_at"]} for q in self.repos.guest_requests.fetch_all(
                self.repos.guest_requests.select_sql + " WHERE t.reservation_id=? ORDER BY t.id DESC", (res["id"],))],
        }

    def book(self, data: dict) -> dict:
        gid = self._guest_id()
        if self.settings().get("online_booking_enabled") != "1":
            raise Conflict("Online booking is currently unavailable")
        if self.repos.reservations.active_count_for_guest(gid) >= 5:
            raise Conflict("You have reached the maximum number of active online bookings. Please contact us.")
        v = SearchSchema.validate(data)
        type_id = Int("Room type", required=True).clean(data.get("room_type_id"))
        PublicService(self.ctx).search(v)  # re-validates the online limits
        payload = {"guest_id": gid, "room_type_id": type_id, "check_in": v["check_in"], "check_out": v["check_out"],
                   "adults": v["adults"], "children": v["children"], "promo_code": v["promo_code"],
                   "rate_plan_id": Int("Rate plan").clean(data["rate_plan_id"]) if data.get("rate_plan_id") else None,
                   "special_requests": str(data.get("special_requests") or "")[:1000]}
        res = self.use(ReservationService).create(payload, online=True)
        return self.reservation(res["id"])

    def _can_cancel(self, res: dict) -> bool:
        """Free cancellation (and changes) end a set number of days before arrival; non-refundable rates never allow it."""
        days = int(self.settings().get("free_cancellation_days") or 0)
        return (res["status"] == "booked" and bool(res["refundable"])
                and today_iso() <= add_days(res["check_in"], -days))

    def change(self, reservation_id: int, data: dict, preview: bool = False) -> dict:
        """The guest moves their own booking to other dates, guests or room type, at today's prices."""
        res = self._own_reservation(reservation_id)
        if not self._can_cancel(res):
            raise Conflict("This booking can no longer be changed online. Please contact the hotel.")
        v = ChangeSchema.validate(data)
        PublicService(self.ctx).check_online_stay(v["check_in"], v["check_out"])
        result = self.use(ReservationService).change_online(
            res, v["check_in"], v["check_out"], v["adults"], v["children"], v["room_type_id"] or res["room_type_id"], preview)
        return {"preview": result} if preview else self.reservation(res["id"])

    def cancel(self, reservation_id: int) -> dict:
        res = self._own_reservation(reservation_id)
        if not res["refundable"] and res["status"] == "booked":
            raise Conflict("This booking was made at a non-refundable rate and cannot be cancelled online. "
                           "Please contact the hotel.")
        if not self._can_cancel(res):
            raise Conflict("This booking can no longer be cancelled online. Please contact the hotel.")
        self.use(ReservationService).cancel(res["id"], reason="Cancelled by guest online", online=True)
        return self.reservation(res["id"])

    def invoice(self, reservation_id: int):
        res = self._own_reservation(reservation_id)
        inv = self.use(InvoiceService).for_reservation(res["id"])
        if not inv:
            raise NotFound("No invoice has been issued for this stay yet")
        return inv

    # ------------------------------------------------------------ in-stay services
    def menu(self) -> list:
        self._guest_id()
        return [{k: m[k] for k in ("id", "name", "description", "category", "price", "prep_minutes")}
                for m in self.use(MenuService).list(available_only=True)]

    def order(self, reservation_id: int, data: dict) -> dict:
        res = self._own_reservation(reservation_id)
        order = self.use(OrderService).place({**data, "reservation_id": res["id"]}, by_guest=True)
        return {"code": order["code"], "status": order["status"], "total": order["total"]}

    def request(self, reservation_id: int, kind: str, message: str) -> dict:
        res = self._own_reservation(reservation_id)
        if res["status"] != "checked_in":
            raise Conflict("Requests can be sent during your stay")
        open_count = self.repos.guest_requests.scalar(
            "SELECT COUNT(*) FROM guest_requests WHERE reservation_id=? AND status IN ('open','in_progress')", (res["id"],), 0)
        if open_count >= 10:
            raise Conflict("You have many open requests; please call the front desk")
        self.use(GuestRequestService).create_for_reservation(res, kind, message)
        return self.reservation(res["id"])

    def review(self, reservation_id: int, rating, comment: str) -> dict:
        res = self._own_reservation(reservation_id)
        if res["status"] != "checked_out":
            raise Conflict("You can review a stay after check-out")
        if self.repos.reviews.exists(reservation_id=res["id"]):
            raise Conflict("You already reviewed this stay")
        rating = Int("Rating", min_value=1, max_value=5).clean(rating)
        comment = Str("Comment", max_len=2000, multiline=True).clean(comment or "") if comment else ""
        self.repos.reviews.insert(reservation_id=res["id"], rating=rating, comment=comment)
        self.audit("review_submit", "reservation", res["id"], f"{rating} stars")
        return {"ok": True}

    def public_reviews(self):
        return ReviewService(self.ctx).public()

    # ------------------------------------------------------------ privacy (data-subject rights)
    def export_my_data(self) -> dict:
        return self.use(PrivacyService).export_guest(self._guest_id())

    def delete_my_account(self, password: str) -> None:
        gid = self._guest_id()
        if not self.ctx.app.hasher.verify(password or "", self.repos.users.password_hash(self.actor.id)):
            raise ValidationError("Password is incorrect", field="password")
        self.use(PrivacyService).anonymize_guest(gid)
