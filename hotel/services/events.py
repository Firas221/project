"""Banquet, conference and event bookings.

An event books a venue for part of a day. It starts as an inquiry, is confirmed (the venue is then held: no
other confirmed event may overlap), and is completed after it has taken place, which issues a numbered tax
invoice. Its price is the venue charge, catering per person and any extras, plus service charge and VAT.
"""
import datetime as dt

from ..core.clock import money, now_str, today_iso
from ..core.errors import Conflict, ValidationError
from ..core.permissions import Perm
from ..core.validation import Bool, Date, Email, Int, Money, Number, Phone, Schema, Str, Time
from .base import Service
from .billing import PAYMENT_METHODS, TaxCalculator

SETUPS = ("", "theatre", "classroom", "banquet", "boardroom", "cocktail", "u_shape")


class VenueSchema(Schema):
    name = Str(required=True, max_len=80)
    capacity = Int(required=True, min_value=1, max_value=10000)
    hourly_rate = Money("Hourly rate", default=0)
    day_rate = Money("Day rate", default=0)
    description = Str(max_len=300)
    active = Bool(default=True)


class EventSchema(Schema):
    venue_id = Int("Venue", required=True)
    title = Str(required=True, max_len=160)
    organizer_name = Str("Organizer", required=True, max_len=120)
    organizer_phone = Phone()
    organizer_email = Email()
    company_id = Int("Company", nullable=True, default=None)
    event_date = Date("Date", required=True)
    start_time = Time(required=True)
    end_time = Time(required=True)
    attendees = Int(required=True, min_value=1, max_value=10000)
    setup = Str(choices=SETUPS)
    venue_charge = Money("Venue charge", nullable=True, default=None)     # empty: worked out from the venue's rates
    catering_per_person = Money("Catering per person", default=0)
    extras = Money(default=0)
    extras_note = Str(max_len=200)
    notes = Str(max_len=2000, multiline=True)


class PaymentSchema(Schema):
    amount = Number(required=True, min_value=-10_000_000, max_value=10_000_000, places=2)
    method = Str(required=True, choices=PAYMENT_METHODS)
    reference = Str(max_len=120)


def hours_between(start: str, end: str) -> float:
    return round((int(end[:2]) * 60 + int(end[3:]) - int(start[:2]) * 60 - int(start[3:])) / 60, 2)


class EventService(Service):
    # ------------------------------------------------------------ venues
    def venues(self, include_inactive: bool = True) -> list:
        self.require(Perm.EVENTS_VIEW)
        return [v for v in self.repos.venues.all() if include_inactive or v["active"]]

    def save_venue(self, data: dict, venue_id: int = None) -> dict:
        self.require(Perm.EVENTS_MANAGE)
        v = VenueSchema.validate(data)
        v["active"] = int(v["active"])
        if self.repos.venues.exists(name=v["name"], exclude_id=venue_id):
            raise Conflict("A venue with this name already exists")
        if venue_id:
            self.repos.venues.require(venue_id)
            self.repos.venues.update(venue_id, **v)
        else:
            venue_id = self.repos.venues.insert(**v)
        self.audit("venue_save", "venue", venue_id, v["name"])
        return self.repos.venues.get(venue_id)

    def delete_venue(self, venue_id: int) -> None:
        self.require(Perm.EVENTS_MANAGE)
        venue = self.repos.venues.require(venue_id)
        if self.repos.events.exists(venue_id=venue_id):
            raise Conflict("This venue has events on record; switch it off instead of deleting it")
        self.repos.venues.delete(venue_id)
        self.audit("venue_delete", "venue", venue_id, venue["name"])

    # ------------------------------------------------------------ pricing
    @staticmethod
    def venue_price(venue: dict, start: str, end: str) -> float:
        """The hourly rate times the hours, capped at the day rate when the venue has one."""
        by_hour = venue["hourly_rate"] * hours_between(start, end)
        return money(min(by_hour, venue["day_rate"]) if venue["day_rate"] and (by_hour > venue["day_rate"] or not venue["hourly_rate"])
                     else by_hour)

    def _priced(self, event: dict) -> dict:
        """Adds the bill. A completed event shows the figures frozen on its invoice."""
        if event["status"] != "completed":
            catering = money(event["catering_per_person"] * event["attendees"])
            subtotal = money(event["venue_charge"] + catering + event["extras"])
            taxes = TaxCalculator(self.settings()).compute(subtotal)
            event.update(subtotal=subtotal, service_charge=taxes["service_charge"], vat=taxes["vat"], city_tax=taxes["city_tax"],
                         total=taxes["total"])
        event["catering_total"] = money(event["catering_per_person"] * event["attendees"])
        event["balance"] = money(event["total"] - event["paid"])
        event["hours"] = hours_between(event["start_time"], event["end_time"])
        s = self.settings()
        event["service_charge_rate"], event["vat_rate"] = s.get("service_charge_rate"), s.get("vat_rate")
        return event

    # ------------------------------------------------------------ events
    def list(self, status="active", date_from=None, date_to=None) -> list:
        self.require(Perm.EVENTS_VIEW)
        return [self._priced(e) for e in self.repos.events.search(status or None, date_from, date_to)]

    def get(self, event_id: int) -> dict:
        self.require(Perm.EVENTS_VIEW)
        event = self._priced(self.repos.events.require(event_id))
        event["payments"] = self.repos.events.payments(event_id)
        s = self.settings()
        event["hotel"] = {k: s.get(k, "") for k in ("hotel_name", "hotel_name_ar", "address", "phone", "tax_registration_number")}
        return event

    def _checked(self, data: dict, current: dict = None) -> dict:
        v = EventSchema.validate(data)
        venue = self.repos.venues.require(v["venue_id"], "Venue")
        if not venue["active"] and not (current and current["venue_id"] == venue["id"]):
            raise ValidationError("This venue is not in use", field="venue_id")
        if v["end_time"] <= v["start_time"]:
            raise ValidationError("The event must end after it starts, on the same day", field="end_time")
        if v["attendees"] > venue["capacity"]:
            raise ValidationError(f"{venue['name']} holds at most {venue['capacity']} people", field="attendees")
        if v["company_id"]:
            self.repos.companies.require(v["company_id"], "Company")
        if v["venue_charge"] is None:
            v["venue_charge"] = self.venue_price(venue, v["start_time"], v["end_time"])
        return v

    def create(self, data: dict) -> dict:
        self.require(Perm.EVENTS_MANAGE)
        v = self._checked(data)
        if v["event_date"] < today_iso():
            raise ValidationError("The date is in the past", field="event_date")
        eid = self.repos.events.insert(code=self.new_code("EV", self.repos.events, 5), **v, created_by=self.actor_id)
        self.audit("event_create", "event", eid, f"{v['title']} {v['event_date']} {v['start_time']}-{v['end_time']}")
        return self.get(eid)

    def update(self, event_id: int, data: dict) -> dict:
        self.require(Perm.EVENTS_MANAGE)
        event = self.repos.events.require(event_id)
        if event["status"] not in ("inquiry", "confirmed"):
            raise Conflict("A completed or cancelled event cannot be changed")
        v = self._checked(data, event)
        if event["status"] == "confirmed":
            self._no_clash(v["venue_id"], v["event_date"], v["start_time"], v["end_time"], event_id)
        self.repos.events.update(event_id, **v)
        self.audit("event_update", "event", event_id, f"{event['code']} {v['event_date']} {v['start_time']}-{v['end_time']}")
        return self.get(event_id)

    def _no_clash(self, venue_id, day, start, end, exclude_id=None) -> None:
        other = self.repos.events.clash(venue_id, day, start, end, exclude_id)
        if other:
            raise Conflict(f"The venue is already confirmed for another event at that time ({other})")

    def set_status(self, event_id: int, status: str) -> dict:
        self.require(Perm.EVENTS_MANAGE)
        event = self._priced(self.repos.events.require(event_id))
        if status == "confirmed":
            if event["status"] != "inquiry":
                raise Conflict("Only an inquiry can be confirmed")
            self._no_clash(event["venue_id"], event["event_date"], event["start_time"], event["end_time"], event_id)
            self.repos.events.update(event_id, status="confirmed")
        elif status == "cancelled":
            if event["status"] not in ("inquiry", "confirmed"):
                raise Conflict("This event is already closed")
            if event["paid"] > 0.004:
                raise Conflict("Refund the payments before cancelling this event")
            self.repos.events.update(event_id, status="cancelled")
        elif status == "completed":
            if event["status"] != "confirmed":
                raise Conflict("Only a confirmed event can be completed")
            if event["event_date"] > today_iso():
                raise Conflict("The event has not taken place yet")
            if event["balance"] > 0.004:
                self._to_company_ledger(event)
            number = self.repos.events.next_number(dt.date.today().year)
            self.repos.events.update(event_id, status="completed", invoice_number=number, completed_at=now_str(),
                                     **{k: event[k] for k in ("subtotal", "service_charge", "vat", "city_tax", "total")})
            self.audit("event_invoice", "event", event_id, f"{event['code']} {number}: {event['total']:.2f}")
        else:
            raise ValidationError("Invalid status")
        self.audit(f"event_{status}", "event", event_id, event["code"])
        return self.get(event_id)

    def _to_company_ledger(self, event: dict) -> None:
        """An unpaid balance can only be left open on a company's account."""
        if not event["company_id"]:
            raise Conflict(f"Outstanding balance of {event['balance']:,.2f} must be settled before the event is completed")
        company = self.repos.companies.require(event["company_id"], "Company")
        if company["credit_limit"] and self.repos.ledger.balance(company["id"]) + event["balance"] > company["credit_limit"] + 0.004:
            raise Conflict(f"{company['name']} would exceed its credit limit")
        self.repos.ledger.insert(company_id=company["id"], kind="invoice", amount=event["balance"], reference=f"Event {event['code']}",
                                 created_by=self.actor_id)
        self.repos.events.add_payment(event["id"], event["balance"], "other", f"City ledger: {company['name']}", None, self.actor_id)
        self.audit("city_ledger_transfer", "company", company["id"], f"Event {event['code']} {event['balance']:.2f}")

    def add_payment(self, event_id: int, data: dict) -> dict:
        """A deposit or settlement. Negative amounts are refunds."""
        self.require(Perm.EVENTS_MANAGE)
        self.require(Perm.BILLING_PAYMENT)
        event = self._priced(self.repos.events.require(event_id))
        if event["status"] in ("completed", "cancelled"):
            raise Conflict("This event is already closed")
        v = PaymentSchema.validate(data)
        if v["amount"] == 0:
            raise ValidationError("Amount cannot be zero")
        if v["amount"] < 0:
            if not self.actor.can(Perm.BILLING_VOID):
                raise ValidationError("Only supervisors can issue refunds")
            if -v["amount"] > event["paid"] + 0.004:
                raise ValidationError("Refund cannot exceed the amount paid")
        shift = self.repos.shifts.open_for(self.actor_id)
        if v["method"] == "cash" and not shift and self.settings().get("cash_requires_shift") == "1":
            raise Conflict("Open a cashier shift before taking cash")
        self.repos.events.add_payment(event_id, v["amount"], v["method"], v["reference"], shift["id"] if shift else None, self.actor_id)
        self.audit("event_payment" if v["amount"] > 0 else "event_refund", "event", event_id,
                   f"{event['code']}: {v['amount']:.2f} {v['method']}")
        return self.get(event_id)

    # ------------------------------------------------------------ reporting
    def sales(self, start: str, end: str) -> dict:
        done = [self._priced(e) for e in self.repos.events.completed_between(start, end)]
        keys = ("subtotal", "service_charge", "vat", "city_tax", "total")
        return {"events": len(done), **{k: money(sum(e[k] for e in done)) for k in keys},
                "invoices": [{k: e[k] for k in ("id", "invoice_number", "completed_at", "title", "organizer_name", "company_name",
                                                 *keys)} for e in done]}
