"""Reservation lifecycle: booked → checked_in → checked_out (or cancelled / no_show)."""
import secrets

from ..core.clock import add_days, money, nights, now_str, today_iso
from ..core.errors import Conflict, ValidationError
from ..core.permissions import Perm
from ..core.validation import Bool, Date, Int, ListOf, Money, Schema, Str
from .base import Service
from .billing import PAYMENT_METHODS, BillingService, InvoiceService
from .front_office import GuestService, PricingService
from .notifications import NotificationService

SOURCES = ("walk-in", "direct", "phone", "email", "online", "booking.com", "expedia", "airbnb", "corporate", "travel_agent",
           "other")
MAX_NIGHTS = 365


class StaySchema(Schema):
    check_in = Date(required=True)
    check_out = Date(required=True)
    adults = Int(min_value=1, max_value=20, default=1)
    children = Int(min_value=0, max_value=20, default=0)
    infants = Int(min_value=0, max_value=6, default=0)


class ReservationSchema(StaySchema):
    guest_id = Int("Guest", nullable=True, default=None)
    room_id = Int("Room", nullable=True, default=None)
    room_type_id = Int("Room type", nullable=True, default=None)
    rate = Money("Nightly rate", nullable=True, default=None)
    extra_beds = Int("Extra beds", min_value=0, max_value=4, nullable=True, default=None)   # empty = as many as needed
    source = Str(choices=SOURCES, default="walk-in")
    promo_code = Str(max_len=30, upper=True)
    rate_plan_id = Int("Rate plan", nullable=True, default=None)
    company_id = Int("Company", nullable=True, default=None)
    bill_to_company = Bool()
    special_requests = Str(max_len=1000, multiline=True)
    notes = Str(max_len=2000, multiline=True)
    deposit = Money(default=0)
    deposit_method = Str(choices=PAYMENT_METHODS, default="card")
    allow_past = Bool()


class UpdateSchema(Schema):
    check_in = Date()
    check_out = Date()
    adults = Int(min_value=1, max_value=20)
    children = Int(min_value=0, max_value=20)
    infants = Int(min_value=0, max_value=6)
    extra_beds = Int("Extra beds", min_value=0, max_value=4, nullable=True)
    rate = Money("Nightly rate")
    rate_plan_id = Int("Rate plan", nullable=True)
    source = Str(choices=SOURCES)
    company_id = Int("Company", nullable=True)
    bill_to_company = Bool()
    special_requests = Str(max_len=1000, multiline=True)
    notes = Str(max_len=2000, multiline=True)


class GroupRoomSchema(Schema):
    room_id = Int("Room", required=True)
    adults = Int(min_value=1, max_value=20, default=1)
    children = Int(min_value=0, max_value=20, default=0)


class GroupSchema(StaySchema):
    group_name = Str(required=True, max_len=120)
    guest_id = Int("Lead guest", required=True)
    rooms = ListOf(GroupRoomSchema, min_items=2, max_items=60)
    company_id = Int("Company", nullable=True, default=None)
    bill_to_company = Bool()
    source = Str(choices=SOURCES, default="direct")
    notes = Str(max_len=2000, multiline=True)


class ReservationService(Service):
    # ------------------------------------------------------------ queries
    def search(self, **filters):
        self.require(Perm.RESERVATIONS_VIEW)
        billing = self.use(BillingService)
        found = self.repos.reservations.search(**filters)
        for r in (found["items"] if isinstance(found, dict) else found):
            f = billing.folio(r)
            r["total"], r["balance"] = f["total"], f["balance"]
        return found

    def detail(self, reservation_id: int) -> dict:
        res = self.repos.reservations.require(reservation_id, "Reservation")
        res["folio"] = self.use(BillingService).folio(res)
        res["guest"] = self.repos.guests.get(res["guest_id"])
        res["invoice"] = self.repos.invoices.first_by(reservation_id=res["id"])
        res["orders"] = self.repos.orders.search(reservation_id=res["id"])
        res["requests"] = self.repos.guest_requests.fetch_all(
            self.repos.guest_requests.select_sql + " WHERE t.reservation_id=? ORDER BY t.id DESC", (res["id"],))
        res["group"] = self.repos.reservations.group_members(res["group_code"]) if res["group_code"] else []
        return res

    def availability(self, check_in, check_out, guests=1, type_id=None, exclude=None):
        self.require(Perm.RESERVATIONS_VIEW)
        self._check_dates(check_in, check_out)
        return self.repos.rooms.available(check_in, check_out, guests, type_id, exclude)

    # ------------------------------------------------------------ validation helpers
    def _check_dates(self, ci: str, co: str) -> None:
        if co <= ci:
            raise ValidationError("Check-out must be after check-in", field="check_out")
        if nights(ci, co) > MAX_NIGHTS:
            raise ValidationError(f"Stay cannot exceed {MAX_NIGHTS} nights")

    def _check_room(self, room_id, ci, co, adults, children, exclude_id=None, allow_maintenance=False) -> dict:
        room = self.repos.rooms.require(room_id, "Room")
        if adults + children > room["capacity"] + room["max_extra_beds"]:
            raise ValidationError(f"Room {room['number']} holds at most {room['capacity'] + room['max_extra_beds']} guests")
        if room["status"] == "maintenance" and not allow_maintenance:
            raise Conflict(f"Room {room['number']} is out of order")
        conflict = self.repos.reservations.conflict(room_id, ci, co, exclude_id)
        if conflict:
            raise Conflict(f"Room {room['number']} is already booked for these dates ({conflict})")
        return room

    @staticmethod
    def _plan_fields(plan) -> dict:
        """What a reservation remembers about its rate plan (a copy, so editing the plan later changes nothing)."""
        if not plan:
            return {"rate_plan_id": None, "rate_plan_name": "", "meal_plan": "room_only", "refundable": 1}
        return {"rate_plan_id": plan["id"], "rate_plan_name": plan["name"], "meal_plan": plan["meal_plan"],
                "refundable": int(plan["refundable"])}

    def _plan_of(self, res: dict):
        return self.repos.rate_plans.get(res["rate_plan_id"]) if res.get("rate_plan_id") else None

    def _resolve_guest(self, data: dict) -> int:
        if data.get("guest_id"):
            self.repos.guests.require(data["guest_id"], "Guest")
            return int(data["guest_id"])
        if isinstance(data.get("guest"), dict):
            return self.use(GuestService).create(data["guest"])["id"]
        raise ValidationError("Guest is required", field="guest_id")

    # ------------------------------------------------------------ create
    def create(self, data: dict, *, online: bool = False) -> dict:
        if not online:
            self.require(Perm.RESERVATIONS_MANAGE)
        v = ReservationSchema.validate(data)
        guest_id = self._resolve_guest({**data, "guest_id": v["guest_id"]})
        self._check_dates(v["check_in"], v["check_out"])
        if v["check_in"] < add_days(today_iso(), -1) and not (v["allow_past"] and not online):
            raise ValidationError("Check-in date is in the past", field="check_in")
        if not v["room_id"]:
            if not v["room_type_id"]:
                raise ValidationError("Choose a room or room type", field="room_id")
            free = self.repos.rooms.available(v["check_in"], v["check_out"], v["adults"] + v["children"], v["room_type_id"])
            if not free:
                raise Conflict("No rooms of this type are available for these dates")
            clean = [r for r in free if r["status"] in ("clean", "inspected")]
            v["room_id"] = (clean or free)[0]["id"]
        room = self._check_room(v["room_id"], v["check_in"], v["check_out"], v["adults"], v["children"])
        if v["company_id"]:
            self.repos.companies.require(v["company_id"], "Company")
        pricing = self.use(PricingService)
        plan = pricing.plan(v["rate_plan_id"], online)
        beds = pricing.extra_beds_needed(room, v["adults"], v["children"], None if online else v["extra_beds"])
        quote = pricing.quote(room["type_id"], v["check_in"], v["check_out"], v["promo_code"], v["company_id"],
                              online=online, rate_plan=plan, adults=v["adults"], children=v["children"], extra_beds=beds)
        if not quote["meets_min_stay"] and (online or v["rate"] is None):
            raise ValidationError(f"A minimum stay of {quote['min_nights']} nights applies to these dates")
        rate, rate_note = quote["average_rate"], quote["discount_label"]
        if v["rate"] is not None and not online:
            if v["rate"] != rate:
                rate_note = "Manual rate"
            rate = v["rate"]
        if v["promo_code"]:
            self.repos.promos.increment_use(self.repos.promos.by_code(v["promo_code"])["id"])
        code = self.new_code("R", self.repos.reservations)
        rid = self.repos.reservations.insert(
            code=code, guest_id=guest_id, room_id=room["id"], check_in=v["check_in"], check_out=v["check_out"],
            adults=v["adults"], children=v["children"], infants=v["infants"], extra_beds=beds, rate=rate,
            source="online" if online else v["source"],
            promo_code=v["promo_code"], company_id=v["company_id"], bill_to_company=int(v["bill_to_company"] and bool(v["company_id"])),
            rate_note=rate_note, special_requests=v["special_requests"], notes="" if online else v["notes"],
            created_by=self.actor_id, **self._plan_fields(plan))
        self.audit("reservation_create", "reservation", rid, f"{code} room {room['number']} {v['check_in']}→{v['check_out']}")
        if online:
            self.alert("New online booking", f"{code} · {v['check_in']} → {v['check_out']}", f"#/reservations/{rid}",
                       permission=Perm.RESERVATIONS_MANAGE)
        if v["deposit"] and not online:
            self.use(BillingService).add_payment(rid, {"amount": v["deposit"], "method": v["deposit_method"],
                                                       "reference": "Deposit"})
        res = self.repos.reservations.get(rid)
        guest = self.repos.guests.get(guest_id)
        if guest["email"]:
            self.use(NotificationService).booking_confirmation(res, guest["email"])
        return self.detail(rid)

    def create_group(self, data: dict) -> dict:
        self.require(Perm.RESERVATIONS_MANAGE)
        v = GroupSchema.validate(data)
        self._check_dates(v["check_in"], v["check_out"])
        self.repos.guests.require(v["guest_id"], "Guest")
        ids = [r["room_id"] for r in v["rooms"]]
        if len(set(ids)) != len(ids):
            raise ValidationError("A room is listed twice")
        group_code = "G" + secrets.token_hex(3).upper()
        created = []
        for line in v["rooms"]:
            res = self.create({"guest_id": v["guest_id"], "room_id": line["room_id"], "check_in": v["check_in"],
                               "check_out": v["check_out"], "adults": line["adults"], "children": line["children"],
                               "source": v["source"], "company_id": v["company_id"],
                               "bill_to_company": v["bill_to_company"], "notes": v["notes"]})
            self.repos.reservations.update(res["id"], group_code=group_code, group_name=v["group_name"])
            created.append(res["code"])
        self.audit("group_create", "reservation", None, f"{group_code} {v['group_name']}: {', '.join(created)}")
        return {"group_code": group_code, "reservations": self.repos.reservations.group_members(group_code)}

    # ------------------------------------------------------------ modify
    def update(self, reservation_id: int, data: dict, *, online: bool = False) -> dict:
        if not online:
            self.require(Perm.RESERVATIONS_MANAGE)
        res = self.repos.reservations.require(reservation_id, "Reservation")
        if res["status"] not in ("booked", "checked_in"):
            raise Conflict(f"A {res['status'].replace('_', ' ')} reservation cannot be changed")
        v = UpdateSchema.validate(data, partial=True)
        ci, co = v.get("check_in", res["check_in"]), v.get("check_out", res["check_out"])
        if res["status"] == "checked_in":
            if ci != res["check_in"]:
                raise Conflict("Arrival date cannot change after check-in")
            if co < today_iso():
                raise ValidationError("Departure cannot be in the past for an in-house guest")
        self._check_dates(ci, co)
        adults, children = v.get("adults", res["adults"]), v.get("children", res["children"])
        room = self._check_room(res["room_id"], ci, co, adults, children, exclude_id=res["id"], allow_maintenance=True)
        pricing = self.use(PricingService)
        # extra beds: what the desk typed; otherwise keep the current number if it still fits, else what is needed
        asked = v["extra_beds"] if "extra_beds" in v else None
        if asked is None and res["extra_beds"] >= max(0, adults + children - room["capacity"]) and "adults" not in v and "children" not in v:
            asked = res["extra_beds"]
        beds = pricing.extra_beds_needed(room, adults, children, asked)
        fields = {"check_in": ci, "check_out": co, "adults": adults, "children": children, "extra_beds": beds,
                  "infants": v.get("infants", res["infants"])}
        for k in ("source", "special_requests", "notes"):
            if k in v:
                fields[k] = v[k]
        if "company_id" in v:
            if v["company_id"]:
                self.repos.companies.require(v["company_id"], "Company")
            fields["company_id"] = v["company_id"]
        if "bill_to_company" in v:
            fields["bill_to_company"] = int(v["bill_to_company"] and bool(fields.get("company_id", res["company_id"])))
        plan, plan_changed = self._plan_of(res), False
        if "rate_plan_id" in v and v["rate_plan_id"] != res["rate_plan_id"]:
            plan, plan_changed = pricing.plan(v["rate_plan_id"]), True
            fields.update(self._plan_fields(plan))
        stay_changed = (ci, co) != (res["check_in"], res["check_out"])
        pax_changed = (plan is not None and (adults, children) != (res["adults"], res["children"])) or beds != res["extra_beds"]
        if "rate" in v:
            fields["rate"], fields["rate_note"] = v["rate"], "Manual rate"
        elif plan_changed or ((stay_changed or pax_changed) and res["rate_note"] != "Manual rate"):
            q = pricing.quote(res["room_type_id"], ci, co, res["promo_code"], fields.get("company_id", res["company_id"]),
                              rate_plan=plan, adults=adults, children=children, extra_beds=beds)
            fields["rate"] = q["average_rate"]
            if plan_changed:
                fields["rate_note"] = q["discount_label"]
        if ci != res["check_in"]:
            fields["reminder_sent_at"] = None   # a new arrival date gets its own reminder
        self.repos.reservations.update(res["id"], **fields)
        self.audit("reservation_update", "reservation", res["id"], f"{res['code']} {ci}→{co}")
        if (ci, co) != (res["check_in"], res["check_out"]):
            self._room_freed(res["check_in"], res["check_out"])
        return self.detail(res["id"])

    def move(self, reservation_id: int, room_id: int, keep_rate: bool = True) -> dict:
        self.require(Perm.RESERVATIONS_MANAGE)
        res = self.repos.reservations.require(reservation_id, "Reservation")
        if res["status"] not in ("booked", "checked_in"):
            raise Conflict("Only active reservations can be moved")
        if room_id == res["room_id"]:
            raise ValidationError("The guest is already in this room")
        room = self._check_room(room_id, res["check_in"], res["check_out"], res["adults"], res["children"],
                                exclude_id=res["id"])
        pricing = self.use(PricingService)
        beds = pricing.extra_beds_needed(room, res["adults"], res["children"])
        fields = {"room_id": room_id, "extra_beds": beds}
        if not keep_rate:
            fields["rate"] = pricing.quote(
                room["type_id"], res["check_in"], res["check_out"], res["promo_code"], res["company_id"],
                rate_plan=self._plan_of(res), adults=res["adults"], children=res["children"], extra_beds=beds)["average_rate"]
        self.repos.reservations.update(res["id"], **fields)
        if res["status"] == "checked_in":
            self.repos.rooms.set_status(res["room_id"], "dirty")
            self._ensure_task(res["room_id"], "checkout_clean", "high", "Guest moved to another room")
        self.audit("reservation_move", "reservation", res["id"], f"{res['code']}: {res['room_number']} -> {room['number']}")
        return self.detail(res["id"])

    def change_online(self, res: dict, check_in: str, check_out: str, adults: int, children: int, room_type_id: int,
                      preview: bool = False, infants: int = None) -> dict:
        """A guest changes their own booking: new dates, guests or room type. Keeps the room when it is free,
        otherwise takes another of that type, and re-prices at today's rates with the booking's own rate plan."""
        self._check_dates(check_in, check_out)
        rt = self.repos.room_types.require(room_type_id, "Room type")
        if not rt["active"]:
            raise ValidationError("This room type is not available", field="room_type_id")
        room_id = None
        if room_type_id == res["room_type_id"]:
            current = self.repos.rooms.require(res["room_id"])
            if (adults + children <= current["capacity"] + current["max_extra_beds"] and current["status"] != "maintenance"
                    and not self.repos.reservations.conflict(res["room_id"], check_in, check_out, res["id"])):
                room_id = res["room_id"]
        if room_id is None:
            free = self.repos.rooms.available(check_in, check_out, adults + children, room_type_id, res["id"])
            if not free:
                raise Conflict("No rooms of this type are available for these dates")
            room_id = ([r for r in free if r["status"] in ("clean", "inspected")] or free)[0]["id"]
        pricing, plan, promo = self.use(PricingService), self._plan_of(res), res["promo_code"]
        beds = pricing.extra_beds_needed(rt, adults, children)
        infants = res["infants"] if infants is None else infants
        args = dict(company_id=res["company_id"], online=True, rate_plan=plan, adults=adults, children=children,
                    extra_beds=beds)
        try:
            quote = pricing.quote(room_type_id, check_in, check_out, promo, **args)
        except ValidationError as e:
            if e.field != "promo_code":
                raise
            promo, quote = "", pricing.quote(room_type_id, check_in, check_out, "", **args)   # the promo has run out
        if not quote["meets_min_stay"]:
            raise ValidationError(f"A minimum stay of {quote['min_nights']} nights applies to these dates")
        if preview:
            from .billing import TaxCalculator
            taxes = TaxCalculator(self.settings()).compute(quote["total"])
            return {"check_in": check_in, "check_out": check_out, "nights": quote["nights"], "room_type": rt["name"],
                    "adults": adults, "children": children, "infants": infants, "extra_beds": beds,
                    "rate": quote["average_rate"], "subtotal": quote["total"],
                    "total": taxes["total"], "discount_label": quote["discount_label"],
                    "promo_dropped": bool(res["promo_code"]) and not promo}
        fields = {"check_in": check_in, "check_out": check_out, "adults": adults, "children": children,
                  "infants": infants, "extra_beds": beds, "room_id": room_id, "rate": quote["average_rate"], "rate_note": quote["discount_label"],
                  "promo_code": promo}
        if check_in != res["check_in"]:
            fields["reminder_sent_at"] = None
        self.repos.reservations.update(res["id"], **fields)
        self.audit("reservation_change_online", "reservation", res["id"],
                   f"{res['code']} {res['check_in']}→{res['check_out']} becomes {check_in}→{check_out}, {rt['name']}")
        self.alert("A guest changed their booking", f"{res['code']} · {check_in} → {check_out}", f"#/reservations/{res['id']}",
                   permission=Perm.RESERVATIONS_MANAGE)
        updated = self.repos.reservations.get(res["id"])
        guest = self.repos.guests.get(res["guest_id"])
        if guest["email"]:
            self.use(NotificationService).booking_changed(updated, guest["email"])
        return updated

    # ------------------------------------------------------------ lifecycle
    def check_in(self, reservation_id: int, force_dirty: bool = False) -> dict:
        self.require(Perm.FRONTDESK_CHECKIN)
        res = self.repos.reservations.require(reservation_id, "Reservation")
        today = today_iso()
        if res["status"] != "booked":
            raise Conflict(f"Cannot check in: the reservation is {res['status'].replace('_', ' ')}")
        if res["check_in"] > today:
            raise Conflict(f"Arrival date is {res['check_in']}. Change the dates to check in early.")
        if res["check_out"] <= today:
            raise Conflict("The stay has already ended. Mark it as a no-show or change the dates.")
        guest = self.repos.guests.get(res["guest_id"])
        if self.settings().get("require_id_at_checkin") == "1" and not (guest["id_number"] and guest["nationality"]):
            raise ValidationError("Guest registration is incomplete: record the guest's nationality and ID/passport "
                                  "number before check-in (required for the authorities).")
        room = self.repos.rooms.require(res["room_id"])
        if room["status"] == "maintenance":
            raise Conflict(f"Room {room['number']} is out of order. Move the guest to another room.")
        if room["status"] == "dirty" and not force_dirty:
            raise Conflict(f"Room {room['number']} is not cleaned yet")
        occupant = self.repos.reservations.occupant(room["id"])
        if occupant:
            raise Conflict(f"Room {room['number']} is still occupied ({occupant['code']})")
        self.repos.reservations.update(res["id"], status="checked_in", checked_in_at=now_str())
        self.audit("check_in", "reservation", res["id"], f"{res['code']} room {res['room_number']}")
        return self.detail(res["id"])

    def check_out(self, reservation_id: int, early_departure: bool = False, force: bool = False) -> dict:
        self.require(Perm.FRONTDESK_CHECKIN)
        res = self.repos.reservations.require(reservation_id, "Reservation")
        if res["status"] != "checked_in":
            raise Conflict("Only in-house guests can be checked out")
        if self.repos.orders.open_for_reservation(res["id"]):
            raise Conflict("This guest has room-service orders still open. Deliver or cancel them first.")
        today = today_iso()
        if res["check_out"] > today and early_departure:
            new_co = max(today, add_days(res["check_in"], 1))
            self.repos.reservations.update(res["id"], check_out=new_co)
            res = self.repos.reservations.get(res["id"])
        billing = self.use(BillingService)
        balance = billing.folio(res)["balance"]
        if balance > 0.004:
            if res["bill_to_company"] and res["company_id"]:
                billing.settle_to_company(res, balance)
            elif force:
                self.require(Perm.BILLING_VOID)
            else:
                raise Conflict(f"Outstanding balance of {balance:,.2f} must be settled before check-out")
        self.repos.reservations.update(res["id"], status="checked_out", checked_out_at=now_str())
        self.repos.rooms.set_status(res["room_id"], "dirty")
        self._ensure_task(res["room_id"], "checkout_clean", "high", f"Departure {res['code']}")
        res = self.repos.reservations.get(res["id"])
        invoice = self.use(InvoiceService).issue(res)
        guest = self.repos.guests.get(res["guest_id"])
        if guest["email"]:
            self.use(NotificationService).receipt(res, guest["email"], invoice["number"], invoice["total"])
        self.audit("check_out", "reservation", res["id"], f"{res['code']} invoice {invoice['number']}")
        return self.detail(res["id"])

    def cancel(self, reservation_id: int, fee: float = 0, reason: str = "", *, online: bool = False) -> dict:
        if not online:
            self.require(Perm.RESERVATIONS_MANAGE)
        res = self.repos.reservations.require(reservation_id, "Reservation")
        if res["status"] != "booked":
            raise Conflict("Only reservations that are not checked in can be cancelled")
        fee = money(Money("Fee").clean(fee) if fee not in (None, "") else 0)
        if fee:
            self.use(BillingService).post_system_charge(res, "Cancellation fee", "Fee", fee)
        reason = str(reason or "")[:300]
        notes = (res["notes"] + "\n" if res["notes"] else "") + f"Cancelled: {reason}" if reason else res["notes"]
        self.repos.reservations.update(res["id"], status="cancelled", cancelled_at=now_str(), notes=notes)
        guest = self.repos.guests.get(res["guest_id"])
        if guest["email"]:
            self.use(NotificationService).cancellation(res, guest["email"])
        self.audit("reservation_cancel", "reservation", res["id"], f"{res['code']} {'(online)' if online else ''}")
        self._room_freed(res["check_in"], res["check_out"])
        if online:
            self.alert("A guest cancelled their booking", f"{res['code']} · {res['check_in']} → {res['check_out']}",
                       f"#/reservations/{res['id']}", permission=Perm.RESERVATIONS_MANAGE)
        return self.detail(res["id"])

    def no_show(self, reservation_id: int, fee: float = 0, *, system: bool = False) -> dict:
        if not system:
            self.require(Perm.RESERVATIONS_MANAGE)
        res = self.repos.reservations.require(reservation_id, "Reservation")
        if res["status"] != "booked":
            raise Conflict("Only booked reservations can be marked as no-show")
        if res["check_in"] > today_iso():
            raise Conflict("A future arrival cannot be a no-show")
        fee = money(Money("Fee").clean(fee) if fee not in (None, "") else 0)
        if fee:
            self.use(BillingService).post_system_charge(res, "No-show fee", "Fee", fee)
        self.repos.reservations.update(res["id"], status="no_show")
        self.audit("reservation_noshow", "reservation", res["id"], res["code"])
        self._room_freed(res["check_in"], res["check_out"])
        return self.repos.reservations.get(res["id"])

    def _room_freed(self, check_in: str, check_out: str) -> None:
        from .waitlist import WaitlistService
        self.use(WaitlistService).room_freed(check_in, check_out)

    def _ensure_task(self, room_id: int, kind: str, priority: str, notes: str) -> None:
        if not self.repos.housekeeping.open_for_room(room_id, kind):
            self.repos.housekeeping.insert(room_id=room_id, kind=kind, priority=priority, due_date=today_iso(),
                                           notes=notes, created_by=self.actor_id)
