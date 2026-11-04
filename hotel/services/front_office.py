"""Front office: guests, rooms & room types, pricing."""
import datetime as dt

from ..core.clock import date_range, money, nights, now_str, today_iso
from ..core.errors import Conflict, ValidationError
from ..core.permissions import Perm
from ..core.validation import Bool, Date, Email, Int, Money, Number, Phone, Schema, Str
from .base import Service

ID_TYPES = ("passport", "national_id", "driving_license", "other")


class GuestSchema(Schema):
    first_name = Str(required=True, max_len=80)
    last_name = Str(required=True, max_len=80)
    email = Email()
    phone = Phone()
    address = Str(max_len=300)
    nationality = Str(max_len=60)
    id_type = Str(choices=ID_TYPES, default="passport")
    id_number = Str("ID / passport number", max_len=40)
    date_of_birth = Date(nullable=True, default="")
    gender = Str(choices=("", "male", "female"))
    vip = Bool()
    notes = Str(max_len=2000, multiline=True)
    marketing_consent = Bool()


class RoomTypeSchema(Schema):
    name = Str(required=True, max_len=80)
    description = Str(max_len=500)
    base_rate = Money("Base rate", required=True)
    capacity = Int(required=True, min_value=1, max_value=20)
    bed_type = Str(max_len=40)
    size_sqm = Int("Size", min_value=0, max_value=2000, default=0)
    amenities = Str(max_len=500)
    active = Bool(default=True)


class RoomSchema(Schema):
    number = Str("Room number", required=True, max_len=20)
    floor = Int(min_value=-5, max_value=200, default=1)
    type_id = Int("Room type", required=True)
    status = Str(choices=("clean", "dirty", "inspected", "maintenance"), default="clean")
    notes = Str(max_len=500)


class SeasonSchema(Schema):
    name = Str(required=True, max_len=80)
    room_type_id = Int("Room type", nullable=True, default=None)
    start_date = Date(required=True)
    end_date = Date(required=True)
    adjust_pct = Number("Rate adjustment %", min_value=-90, max_value=500, places=2, default=0)
    min_nights = Int("Minimum stay", min_value=1, max_value=60, default=1)
    active = Bool(default=True)


class PromoSchema(Schema):
    code = Str(required=True, max_len=30, pattern=r"[A-Za-z0-9_\-]+", upper=True)
    description = Str(max_len=200)
    discount_pct = Number("Discount %", required=True, min_value=0.5, max_value=100, places=2)
    valid_from = Date(required=True)
    valid_to = Date(required=True)
    max_uses = Int(min_value=0, max_value=100000, default=0)
    online_only = Bool()
    active = Bool(default=True)


class GuestService(Service):
    def search(self, q=None):
        self.require(Perm.GUESTS_VIEW)
        return self.repos.guests.search(q)

    def get(self, guest_id: int) -> dict:
        self.require(Perm.GUESTS_VIEW)
        g = self.repos.guests.require(guest_id, "Guest")
        billing = self.use(BillingServiceProxy)
        g["reservations"] = self.repos.reservations.search(guest_id=guest_id)
        for r in g["reservations"]:
            r["total"] = billing.folio(r)["total"]
        g["lifetime_value"] = money(sum(r["total"] for r in g["reservations"] if r["status"] != "cancelled"))
        return g

    def create(self, data: dict) -> dict:
        self.require(Perm.GUESTS_MANAGE)
        v = GuestSchema.validate(data)
        v["vip"], v["marketing_consent"] = int(v["vip"]), int(v["marketing_consent"])
        gid = self.repos.guests.insert(**v)
        self.audit("guest_create", "guest", gid, f"{v['first_name']} {v['last_name']}")
        return self.repos.guests.get(gid)

    def update(self, guest_id: int, data: dict) -> dict:
        self.require(Perm.GUESTS_MANAGE)
        g = self.repos.guests.require(guest_id, "Guest")
        if g["anonymized_at"]:
            raise Conflict("This guest's personal data was erased and cannot be edited")
        v = GuestSchema.validate(data)
        v["vip"], v["marketing_consent"] = int(v["vip"]), int(v["marketing_consent"])
        self.repos.guests.update(guest_id, **v)
        self.audit("guest_update", "guest", guest_id, f"{v['first_name']} {v['last_name']}")
        return self.repos.guests.get(guest_id)

    def delete(self, guest_id: int) -> None:
        self.require(Perm.GUESTS_MANAGE)
        g = self.repos.guests.require(guest_id, "Guest")
        if self.repos.reservations.exists(guest_id=guest_id) or g["user_id"]:
            raise Conflict("Guests with reservations or an online account cannot be deleted; use 'Erase personal data'")
        self.repos.guests.delete(guest_id)
        self.audit("guest_delete", "guest", guest_id, f"{g['first_name']} {g['last_name']}")

    def registration_report(self, day: str, foreign_only: bool = True) -> list:
        """Daily guest register for the authorities (arrivals and in-house guests)."""
        self.require(Perm.GUESTS_VIEW)
        rows = self.repos.reservations.fetch_all(
            "SELECT r.code, r.check_in, r.check_out, r.status, rm.number AS room_number, g.first_name, g.last_name,"
            " g.nationality, g.id_type, g.id_number, g.date_of_birth, g.gender, g.address, r.adults, r.children"
            " FROM reservations r JOIN guests g ON g.id=r.guest_id JOIN rooms rm ON rm.id=r.room_id"
            " WHERE r.status IN ('checked_in','checked_out') AND r.check_in <= ? AND r.check_out >= ?"
            " ORDER BY rm.number", (day, day))
        if foreign_only:
            rows = [r for r in rows if (r["nationality"] or "").strip().lower() not in ("egyptian", "egypt")]
        return rows


class BillingServiceProxy(Service):
    """Late-bound access to billing to avoid a circular import."""

    def folio(self, res):
        from .billing import BillingService
        return self.use(BillingService).folio(res)


class RoomService(Service):
    def types(self, include_inactive=True):
        rows = self.repos.room_types.all()
        return rows if include_inactive else [t for t in rows if t["active"]]

    def save_type(self, data: dict, type_id: int = None) -> dict:
        self.require(Perm.ROOMS_MANAGE)
        v = RoomTypeSchema.validate(data)
        v["active"] = int(v["active"])
        if self.repos.room_types.exists(name=v["name"], exclude_id=type_id):
            raise Conflict("A room type with this name already exists")
        if type_id:
            self.repos.room_types.require(type_id)
            self.repos.room_types.update(type_id, **v)
        else:
            type_id = self.repos.room_types.insert(**v)
        self.audit("room_type_save", "room_type", type_id, f"{v['name']} @ {v['base_rate']}")
        return self.repos.room_types.get(type_id)

    def delete_type(self, type_id: int) -> None:
        self.require(Perm.ROOMS_MANAGE)
        t = self.repos.room_types.require(type_id)
        if self.repos.rooms.exists(type_id=type_id):
            raise Conflict("Rooms still use this type")
        self.repos.room_types.delete(type_id)
        self.audit("room_type_delete", "room_type", type_id, t["name"])

    def rooms(self, **filters):
        return self.repos.rooms.search(**filters)

    def save_room(self, data: dict, room_id: int = None) -> dict:
        self.require(Perm.ROOMS_MANAGE)
        v = RoomSchema.validate(data)
        self.repos.room_types.require(v["type_id"])
        if self.repos.rooms.exists(number=v["number"], exclude_id=room_id):
            raise Conflict("Room number already exists")
        if room_id:
            self.repos.rooms.require(room_id)
            self.repos.rooms.update(room_id, **v)
        else:
            room_id = self.repos.rooms.insert(**v)
        self.audit("room_save", "room", room_id, v["number"])
        return self.repos.rooms.get(room_id)

    def delete_room(self, room_id: int) -> None:
        self.require(Perm.ROOMS_MANAGE)
        r = self.repos.rooms.require(room_id)
        if self.repos.reservations.exists(room_id=room_id):
            raise Conflict("Rooms with reservation history cannot be deleted; put the room out of order instead")
        self.repos.rooms.delete(room_id)
        self.audit("room_delete", "room", room_id, r["number"])

    def set_status(self, room_id: int, status: str, notes: str = None) -> dict:
        self.require(Perm.ROOMS_STATUS)
        if status not in ("clean", "dirty", "inspected", "maintenance"):
            raise ValidationError("Invalid room status")
        r = self.repos.rooms.require(room_id)
        if status == "maintenance" and not self.actor.can(Perm.MAINTENANCE_MANAGE):
            raise ValidationError("Report a maintenance ticket to take a room out of order")
        self.repos.rooms.set_status(room_id, status, None if notes is None else str(notes)[:500])
        self.audit("room_status", "room", room_id, f"{r['number']}: {r['status']} -> {status}")
        return self.repos.rooms.get(room_id)

    def calendar(self, start: str, days: int) -> dict:
        self.require(Perm.RESERVATIONS_VIEW)
        end = (dt.date.fromisoformat(start) + dt.timedelta(days=days)).isoformat()
        return {"start": start, "days": days, "rooms": self.repos.rooms.search(),
                "reservations": self.repos.reservations.overlapping(start, end)}


class PricingService(Service):
    """Nightly rates = base rate × season adjustment × weekend uplift, minus promo/corporate discount."""

    def quote(self, room_type_id: int, check_in: str, check_out: str, promo_code: str = "", company_id: int = None,
              online: bool = False) -> dict:
        rt = self.repos.room_types.require(room_type_id, "Room type")
        n = nights(check_in, check_out)
        if n < 1:
            raise ValidationError("Check-out must be after check-in")
        s = self.settings()
        weekend = {int(x) for x in (s.get("weekend_days") or "").replace(" ", "").split(",") if x.isdigit()}
        weekend_pct = float(s.get("weekend_adjust_pct") or 0)
        nightly, min_nights = [], 1
        for day in list(date_range(check_in, check_out))[:-1]:
            rate, label = rt["base_rate"], []
            seasons = self.repos.seasons.covering(day, room_type_id)
            if seasons:
                season = seasons[0]
                rate *= 1 + season["adjust_pct"] / 100
                min_nights = max(min_nights, season["min_nights"])
                label.append(season["name"])
            if dt.date.fromisoformat(day).weekday() in weekend and weekend_pct:
                rate *= 1 + weekend_pct / 100
                label.append("weekend")
            nightly.append({"date": day, "rate": money(rate), "label": ", ".join(label)})
        subtotal = money(sum(x["rate"] for x in nightly))
        discount_pct, discount_label = 0.0, ""
        if promo_code:
            promo = self.validate_promo(promo_code, check_in, online)
            discount_pct, discount_label = promo["discount_pct"], f"Promo {promo['code']}"
        if company_id:
            company = self.repos.companies.require(company_id, "Company")
            if company["discount_pct"] > discount_pct:
                discount_pct, discount_label = company["discount_pct"], f"Corporate rate ({company['name']})"
        discount = money(subtotal * discount_pct / 100)
        total = money(subtotal - discount)
        return {"room_type_id": room_type_id, "room_type": rt["name"], "nights": n, "nightly": nightly,
                "subtotal": subtotal, "discount_pct": discount_pct, "discount": discount, "discount_label": discount_label,
                "total": total, "average_rate": money(total / n), "min_nights": min_nights,
                "meets_min_stay": n >= min_nights}

    def validate_promo(self, code: str, check_in: str, online: bool) -> dict:
        promo = self.repos.promos.by_code(code.strip().upper())
        today = today_iso()
        if (not promo or not promo["active"] or not (promo["valid_from"] <= today <= promo["valid_to"])
                or (promo["max_uses"] and promo["used_count"] >= promo["max_uses"])
                or (promo["online_only"] and not online)):
            raise ValidationError("This promo code is not valid", field="promo_code")
        return promo

    # ---- seasons & promos management
    def seasons(self):
        return self.repos.seasons.all()

    def save_season(self, data, season_id=None):
        self.require(Perm.ROOMS_MANAGE)
        v = SeasonSchema.validate(data)
        if v["end_date"] < v["start_date"]:
            raise ValidationError("End date must be on or after the start date")
        if v["room_type_id"]:
            self.repos.room_types.require(v["room_type_id"])
        v["active"] = int(v["active"])
        if season_id:
            self.repos.seasons.require(season_id)
            self.repos.seasons.update(season_id, **v)
        else:
            season_id = self.repos.seasons.insert(**v)
        self.audit("season_save", "season", season_id, f"{v['name']} {v['adjust_pct']:+g}%")
        return self.repos.seasons.get(season_id)

    def delete_season(self, season_id):
        self.require(Perm.ROOMS_MANAGE)
        self.repos.seasons.require(season_id)
        self.repos.seasons.delete(season_id)
        self.audit("season_delete", "season", season_id)

    def promos(self):
        self.require(Perm.ROOMS_MANAGE)
        return self.repos.promos.all()

    def save_promo(self, data, promo_id=None):
        self.require(Perm.ROOMS_MANAGE)
        v = PromoSchema.validate(data)
        if v["valid_to"] < v["valid_from"]:
            raise ValidationError("'Valid to' must be after 'valid from'")
        if self.repos.promos.exists(code=v["code"], exclude_id=promo_id):
            raise Conflict("Promo code already exists")
        v["online_only"], v["active"] = int(v["online_only"]), int(v["active"])
        if promo_id:
            self.repos.promos.require(promo_id)
            self.repos.promos.update(promo_id, **v)
        else:
            promo_id = self.repos.promos.insert(**v)
        self.audit("promo_save", "promo", promo_id, f"{v['code']} {v['discount_pct']}%")
        return self.repos.promos.get(promo_id)


def stamp():
    return now_str()
