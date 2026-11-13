"""Billing: folios with Egyptian taxes, charges, payments, cashier shifts, city ledger, tax invoices."""
import datetime as dt
import json

from ..core.clock import money, now_str
from ..core.errors import Conflict, ValidationError
from ..core.permissions import Perm
from ..core.validation import Email, Int, Money, Number, Schema, Str
from .base import Service

PAYMENT_METHODS = ("cash", "card", "bank_transfer", "other")


def second_currency_rate(settings: dict) -> float:
    """How many units of the hotel's currency one unit of the second currency is worth; 0 when there is none."""
    try:
        rate = float(settings.get("exchange_rate") or 0)
    except ValueError:
        rate = 0.0
    return rate if (settings.get("second_currency") or "").strip() and rate > 0 else 0.0
OPEN_FOLIO = ("booked", "checked_in")


class ChargeSchema(Schema):
    item_id = Int("Item", nullable=True, default=None)
    description = Str(max_len=200)
    category = Str(max_len=60, default="Service")
    quantity = Number(min_value=0.01, max_value=10000, places=3, default=1)
    unit_price = Number("Unit price", min_value=-1_000_000, max_value=1_000_000, places=2, nullable=True, default=None)


class PaymentSchema(Schema):
    amount = Number(required=True, min_value=-10_000_000, max_value=10_000_000, places=2)
    method = Str(required=True, choices=PAYMENT_METHODS)
    reference = Str(max_len=120)
    currency = Str(max_len=8, upper=True)        # empty or the hotel's own currency: amount is in it


class CompanySchema(Schema):
    name = Str(required=True, max_len=120)
    tax_number = Str("Tax registration number", max_len=40)
    contact = Str(max_len=120)
    email = Email()
    phone = Str(max_len=40)
    address = Str(max_len=300)
    discount_pct = Number("Corporate discount %", min_value=0, max_value=100, places=2, default=0)
    credit_limit = Money(default=0)


class TaxCalculator:
    """Egyptian hotel billing: service charge on the subtotal, then VAT on (subtotal + service)."""

    def __init__(self, settings: dict):
        f = lambda k: float(settings.get(k) or 0)  # noqa: E731
        self.service_rate, self.vat_rate, self.city_rate = f("service_charge_rate"), f("vat_rate"), f("city_tax_rate")

    def compute(self, subtotal: float) -> dict:
        service = money(subtotal * self.service_rate / 100)
        vat = money((subtotal + service) * self.vat_rate / 100)
        city = money(subtotal * self.city_rate / 100)
        return {"service_charge_rate": self.service_rate, "service_charge": service, "vat_rate": self.vat_rate,
                "vat": vat, "city_tax_rate": self.city_rate, "city_tax": city,
                "total": money(subtotal + service + vat + city)}


class BillingService(Service):
    def folio(self, res: dict) -> dict:
        charges = self.repos.charges.for_reservation(res["id"])
        payments = self.repos.payments.for_reservation(res["id"])
        n = int(res.get("nights") or (dt.date.fromisoformat(res["check_out"]) - dt.date.fromisoformat(res["check_in"])).days)
        room_total = 0.0 if res["status"] in ("cancelled", "no_show") else money(n * res["rate"])
        extras = money(sum(c["amount"] for c in charges))
        subtotal = money(room_total + extras)
        taxes = TaxCalculator(self.settings()).compute(subtotal)
        paid = money(sum(p["amount"] for p in payments))
        return {"nights": n, "room_total": room_total, "extras_total": extras, "subtotal": subtotal, **taxes,
                "paid": paid, "balance": money(taxes["total"] - paid), "charges": charges, "payments": payments}

    def _open_reservation(self, reservation_id: int) -> dict:
        res = self.repos.reservations.require(reservation_id, "Reservation")
        if res["status"] not in OPEN_FOLIO:
            raise Conflict("This folio is closed")
        return res

    def add_charge(self, reservation_id: int, data: dict, *, order_id: int = None) -> None:
        self.require(Perm.BILLING_CHARGE)
        res = self._open_reservation(reservation_id)
        v = ChargeSchema.validate(data)
        if v["item_id"]:
            from .inventory import InventoryService
            item = self.repos.items.require(v["item_id"], "Item")
            if not item["active"] or not item["chargeable"]:
                raise ValidationError(f"{item['name']} cannot be charged to guests")
            unit_price = item["price"] if v["unit_price"] is None else v["unit_price"]
            if unit_price < 0:
                raise ValidationError("Unit price cannot be negative for items")
            description, category = v["description"] or item["name"], item["category"]
            self.use(InventoryService).move(item, "sale", -v["quantity"], f"Charged to {res['code']}",
                                            reservation_id=res["id"])
        else:
            if not v["description"]:
                raise ValidationError("Description is required", field="description")
            if v["unit_price"] is None:
                raise ValidationError("Unit price is required", field="unit_price")
            if v["unit_price"] < 0 and not self.actor.can(Perm.BILLING_VOID):
                raise ValidationError("Only supervisors can post discounts (negative charges)")
            item, unit_price, description, category = None, v["unit_price"], v["description"], v["category"]
        amount = money(v["quantity"] * unit_price)
        self.repos.charges.insert(reservation_id=res["id"], item_id=item["id"] if item else None, order_id=order_id,
                                  description=description, category=category, quantity=v["quantity"],
                                  unit_price=unit_price, amount=amount, created_by=self.actor_id)
        self.audit("charge_add", "reservation", res["id"], f"{res['code']}: {description} x{v['quantity']:g} = {amount:.2f}")

    def post_system_charge(self, res: dict, description: str, category: str, amount: float, order_id: int = None):
        """Charges posted by the system itself (orders, fees) — no permission check."""
        self.repos.charges.insert(reservation_id=res["id"], order_id=order_id, description=description,
                                  category=category, quantity=1, unit_price=amount, amount=money(amount),
                                  created_by=self.actor_id)

    def void_charge(self, reservation_id: int, charge_id: int) -> None:
        self.require(Perm.BILLING_VOID)
        res = self._open_reservation(reservation_id)
        c = self.repos.charges.first_by(id=charge_id, reservation_id=res["id"])
        if not c:
            raise ValidationError("Charge not found on this folio")
        if c["item_id"]:
            from .inventory import InventoryService
            item = self.repos.items.get(c["item_id"])
            if item:
                self.use(InventoryService).move(item, "return", c["quantity"], f"Charge voided on {res['code']}",
                                                reservation_id=res["id"])
        if c["category"] == "Loyalty":
            from .loyalty import LoyaltyService
            self.use(LoyaltyService).redemption_voided(res, c)
        self.repos.charges.delete(c["id"])
        self.audit("charge_void", "reservation", res["id"], f"{res['code']}: {c['description']} {c['amount']:.2f}")

    def transfer_charge(self, reservation_id: int, charge_id: int, target_code: str) -> None:
        """Split billing: move a charge to another open folio (e.g. a group master)."""
        self.require(Perm.BILLING_CHARGE)
        res = self._open_reservation(reservation_id)
        target = self.repos.reservations.first_by(code=(target_code or "").strip().upper())
        if not target or target["status"] not in OPEN_FOLIO or target["id"] == res["id"]:
            raise ValidationError("Target reservation must be another open folio")
        c = self.repos.charges.first_by(id=charge_id, reservation_id=res["id"])
        if not c:
            raise ValidationError("Charge not found on this folio")
        if c["category"] == "Loyalty":
            raise ValidationError("Redeemed points stay on the guest's own bill")
        self.repos.charges.update(c["id"], reservation_id=target["id"])
        self.audit("charge_transfer", "reservation", res["id"], f"{c['description']} {res['code']} -> {target['code']}")

    def add_payment(self, reservation_id: int, data: dict) -> None:
        self.require(Perm.BILLING_PAYMENT)
        res = self.repos.reservations.require(reservation_id, "Reservation")
        if res["status"] == "checked_out":
            raise Conflict("This folio is closed")
        v = PaymentSchema.validate(data)
        if v["amount"] == 0:
            raise ValidationError("Amount cannot be zero")
        foreign = {"currency": "", "fx_rate": 0, "foreign_amount": 0}
        s = self.settings()
        if v["currency"] and v["currency"] != (s.get("currency") or "").upper():
            # paid in the second currency: book it in the hotel's currency at today's rate, remember both
            rate = second_currency_rate(s)
            if v["currency"] != (s.get("second_currency") or "").upper() or not rate:
                raise ValidationError(f"Payments in {v['currency']} are not accepted", field="currency")
            foreign = {"currency": v["currency"], "fx_rate": rate, "foreign_amount": v["amount"]}
            v["amount"] = money(v["amount"] * rate)
        if v["amount"] < 0:
            if not self.actor.can(Perm.BILLING_VOID):
                raise ValidationError("Only supervisors can issue refunds")
            if -v["amount"] > self.folio(res)["paid"] + 0.004:
                raise ValidationError("Refund cannot exceed the amount paid")
        shift = self.repos.shifts.open_for(self.actor_id)
        if v["method"] == "cash" and not shift and self.settings().get("cash_requires_shift") == "1":
            raise Conflict("Open a cashier shift before taking cash")
        self.repos.payments.insert(reservation_id=res["id"], amount=v["amount"], method=v["method"],
                                   reference=v["reference"], created_by=self.actor_id, shift_id=shift["id"] if shift else None,
                                   **foreign)
        paid_as = f" ({foreign['foreign_amount']:.2f} {foreign['currency']} @ {foreign['fx_rate']:g})" if foreign["currency"] else ""
        self.audit("payment" if v["amount"] > 0 else "refund", "reservation", res["id"],
                   f"{res['code']}: {v['amount']:.2f} {v['method']}{paid_as}")

    def void_payment(self, reservation_id: int, payment_id: int) -> None:
        self.require(Perm.BILLING_VOID)
        res = self.repos.reservations.require(reservation_id, "Reservation")
        if res["status"] == "checked_out":
            raise Conflict("This folio is closed")
        p = self.repos.payments.first_by(id=payment_id, reservation_id=res["id"])
        if not p:
            raise ValidationError("Payment not found on this folio")
        shift = self.repos.shifts.get(p["shift_id"]) if p["shift_id"] else None
        if shift and shift["closed_at"]:
            raise Conflict("The payment belongs to a closed cashier shift; record a refund instead")
        self.repos.payments.delete(p["id"])
        self.audit("payment_void", "reservation", res["id"], f"{res['code']}: {p['amount']:.2f}")

    def settle_to_company(self, res: dict, balance: float) -> None:
        """Moves an outstanding folio balance to the company's accounts receivable (city ledger)."""
        company = self.repos.companies.require(res["company_id"], "Company")
        if company["credit_limit"] and self.repos.ledger.balance(company["id"]) + balance > company["credit_limit"] + 0.004:
            raise Conflict(f"{company['name']} would exceed its credit limit")
        self.repos.ledger.insert(company_id=company["id"], reservation_id=res["id"], kind="invoice", amount=balance,
                                 reference=res["code"], created_by=self.actor_id)
        self.repos.payments.insert(reservation_id=res["id"], amount=balance, method="other",
                                   reference=f"City ledger: {company['name']}", created_by=self.actor_id)
        self.audit("city_ledger_transfer", "company", company["id"], f"{res['code']} {balance:.2f}")


class InvoiceService(Service):
    def issue(self, res: dict) -> dict:
        """Issues an immutable, sequentially-numbered tax invoice for a closed stay."""
        existing = self.repos.invoices.first_by(reservation_id=res["id"])
        if existing:
            return existing
        f = self.use(BillingService).folio(res)
        s = self.settings()
        company = self.repos.companies.get(res["company_id"]) if res.get("company_id") and res.get("bill_to_company") else None
        guest = self.repos.guests.get(res["guest_id"])
        snapshot = {
            "hotel": {k: s.get(k, "") for k in ("hotel_name", "hotel_name_ar", "address", "phone", "email",
                                                "tax_registration_number", "commercial_register", "currency")},
            "guest": {"name": f"{guest['first_name']} {guest['last_name']}", "address": guest["address"],
                      "nationality": guest["nationality"]},
            "company": {"name": company["name"], "tax_number": company["tax_number"], "address": company["address"]}
            if company else None,
            "stay": {"code": res["code"], "room": res["room_number"], "room_type": res["room_type"],
                     "check_in": res["check_in"], "check_out": res["check_out"], "nights": f["nights"], "rate": res["rate"]},
            "lines": [{"description": f"Accommodation — {res['room_type']}", "quantity": f["nights"],
                       "unit_price": res["rate"], "amount": f["room_total"]}]
            + [{"description": c["description"], "quantity": c["quantity"], "unit_price": c["unit_price"],
                "amount": c["amount"]} for c in f["charges"]],
            "totals": {k: f[k] for k in ("subtotal", "service_charge_rate", "service_charge", "vat_rate", "vat",
                                         "city_tax_rate", "city_tax", "total", "paid", "balance")},
            "payments": [{"date": p["created_at"], "method": p["method"], "reference": p["reference"],
                          "amount": p["amount"]} for p in f["payments"]],
        }
        number = self.repos.invoices.next_number(dt.date.today().year)
        iid = self.repos.invoices.insert(
            number=number, reservation_id=res["id"], bill_to=company["name"] if company else snapshot["guest"]["name"],
            bill_to_tax_no=company["tax_number"] if company else "", subtotal=f["subtotal"],
            service_charge=f["service_charge"], vat=f["vat"], city_tax=f["city_tax"], total=f["total"],
            snapshot=json.dumps(snapshot, ensure_ascii=False), issued_by=self.actor_id)
        self.audit("invoice_issue", "invoice", iid, f"{number} for {res['code']} total {f['total']:.2f}")
        return self.repos.invoices.get(iid)

    def get(self, invoice_id: int) -> dict:
        inv = self.repos.invoices.require(invoice_id, "Invoice")
        inv["data"] = json.loads(inv.pop("snapshot"))
        return inv

    def for_reservation(self, reservation_id: int):
        inv = self.repos.invoices.first_by(reservation_id=reservation_id)
        return self.get(inv["id"]) if inv else None

    def search(self, date_from=None, date_to=None, **paging):
        self.require(Perm.BILLING_VIEW)
        return self.repos.invoices.search(date_from, date_to, **paging)


class CashierService(Service):
    def _may_hold_a_till(self) -> None:
        """Anyone who takes money can run a cashier shift: the front desk, and restaurant staff."""
        if not self.actor.can_any(Perm.BILLING_PAYMENT, Perm.RESTAURANT_SERVE):
            from ..core.errors import PermissionDenied
            raise PermissionDenied()

    def current(self):
        return self.repos.shifts.open_for(self.actor_id)

    def open(self, opening_float: float) -> dict:
        self._may_hold_a_till()
        if self.current():
            raise Conflict("You already have an open shift")
        try:
            opening = money(float(opening_float or 0))
        except (TypeError, ValueError):
            raise ValidationError("Opening float must be a number")
        if opening < 0 or opening > 1_000_000:
            raise ValidationError("Opening float is out of range")
        sid = self.repos.shifts.insert(user_id=self.actor_id, opening_float=opening)
        self.audit("shift_open", "shift", sid, f"float {opening:.2f}")
        return self.repos.shifts.get(sid)

    def close(self, counted_cash, notes: str = "") -> dict:
        self._may_hold_a_till()
        shift = self.current()
        if not shift:
            raise Conflict("You have no open shift")
        try:
            counted = money(float(counted_cash))
        except (TypeError, ValueError):
            raise ValidationError("Counted cash must be a number", field="counted_cash")
        expected = money(shift["opening_float"] + shift["cash_taken"] + shift["restaurant_cash"])
        self.repos.shifts.update(shift["id"], closed_at=now_str(), expected_cash=expected, counted_cash=counted,
                                 variance=money(counted - expected), notes=str(notes or "")[:500])
        self.audit("shift_close", "shift", shift["id"], f"expected {expected:.2f} counted {counted:.2f}")
        return self.detail(shift["id"])

    def detail(self, shift_id: int) -> dict:
        shift = self.repos.shifts.require(shift_id, "Shift")
        if shift["user_id"] != self.actor_id and not self.actor.can(Perm.REPORTS_VIEW):
            from ..core.errors import PermissionDenied
            raise PermissionDenied()
        shift["payments"] = self.repos.shifts.payments(shift_id)
        return shift

    def list(self):
        if self.actor.can(Perm.REPORTS_VIEW):
            return self.repos.shifts.recent()
        return [s for s in self.repos.shifts.recent() if s["user_id"] == self.actor_id]


class CompanyService(Service):
    def list(self):
        self.require(Perm.RESERVATIONS_VIEW)
        return self.repos.companies.all()

    def get(self, company_id: int) -> dict:
        self.require(Perm.BILLING_VIEW)
        c = self.repos.companies.require(company_id, "Company")
        c["ledger"] = self.repos.ledger.find_by(company_id=company_id)
        return c

    def save(self, data: dict, company_id: int = None) -> dict:
        self.require(Perm.BILLING_VOID)
        v = CompanySchema.validate(data)
        if self.repos.companies.exists(name=v["name"], exclude_id=company_id):
            raise Conflict("A company with this name already exists")
        if company_id:
            self.repos.companies.require(company_id)
            self.repos.companies.update(company_id, **v)
        else:
            company_id = self.repos.companies.insert(**v)
        self.audit("company_save", "company", company_id, v["name"])
        return self.get(company_id)

    def record_payment(self, company_id: int, data: dict) -> dict:
        self.require(Perm.BILLING_PAYMENT)
        company = self.repos.companies.require(company_id, "Company")
        v = PaymentSchema.validate(data)
        if v["amount"] <= 0:
            raise ValidationError("Amount must be positive")
        self.repos.ledger.insert(company_id=company_id, kind="payment", amount=-v["amount"],
                                 reference=f"{v['method']} {v['reference']}".strip(), created_by=self.actor_id)
        self.audit("city_ledger_payment", "company", company_id, f"{company['name']} {v['amount']:.2f}")
        return self.get(company_id)
