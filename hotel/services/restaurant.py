"""Restaurant point of sale: tables, checks, kitchen tickets, receipts.

A check is opened on a table (or as takeaway), dishes are added and go to the kitchen, and it is settled either
by payment — which issues a numbered receipt with service charge and VAT — or by charging it to the room of a
guest who is staying, where the taxes are added on the room bill.
"""
import datetime as dt

from ..core.clock import money, now_str
from ..core.errors import Conflict, ValidationError
from ..core.permissions import Perm
from ..core.validation import Bool, Int, ListOf, Schema, Str
from .base import Service
from .billing import PAYMENT_METHODS, BillingService, TaxCalculator
from .inventory import InventoryService


class TableSchema(Schema):
    name = Str(required=True, max_len=40)
    seats = Int(min_value=1, max_value=50, default=4)
    area = Str(max_len=40)
    active = Bool(default=True)


class OpenSchema(Schema):
    table_id = Int("Table", nullable=True, default=None)
    covers = Int("Guests", min_value=1, max_value=50, default=1)
    customer_name = Str(max_len=120)


class LineSchema(Schema):
    menu_item_id = Int("Dish", required=True)
    quantity = Int(min_value=1, max_value=99, default=1)
    notes = Str(max_len=200)


class LinesSchema(Schema):
    lines = ListOf(LineSchema, min_items=1, max_items=60)


class RestaurantService(Service):
    # ------------------------------------------------------------ tables
    def floor(self) -> dict:
        """Every table with its open check, plus open takeaway checks."""
        self.require(Perm.RESTAURANT_SERVE)
        open_checks = [self._totals(c) for c in self.repos.checks.open_checks()]
        by_table = {c["table_id"]: c for c in open_checks if c["table_id"]}
        tables = [{**t, "check": by_table.get(t["id"])} for t in self.repos.restaurant_tables.all()
                  if t["active"] or t["id"] in by_table]
        return {"tables": tables, "takeaway": [c for c in open_checks if not c["table_id"]]}

    def tables(self) -> list:
        self.require(Perm.RESTAURANT_SERVE)
        return self.repos.restaurant_tables.all()

    def save_table(self, data: dict, table_id: int = None) -> dict:
        self.require(Perm.RESTAURANT_MANAGE)
        v = TableSchema.validate(data)
        v["active"] = int(v["active"])
        if self.repos.restaurant_tables.exists(name=v["name"], exclude_id=table_id):
            raise Conflict("A table with this name already exists")
        if table_id:
            self.repos.restaurant_tables.require(table_id)
            self.repos.restaurant_tables.update(table_id, **v)
        else:
            table_id = self.repos.restaurant_tables.insert(**v)
        self.audit("restaurant_table_save", "restaurant_table", table_id, v["name"])
        return self.repos.restaurant_tables.get(table_id)

    def delete_table(self, table_id: int) -> None:
        self.require(Perm.RESTAURANT_MANAGE)
        t = self.repos.restaurant_tables.require(table_id)
        if any(c["table_id"] == table_id for c in self.repos.checks.open_checks()):
            raise Conflict("This table has an open check")
        self.repos.restaurant_tables.delete(table_id)      # past checks keep the table's name
        self.audit("restaurant_table_delete", "restaurant_table", table_id, t["name"])

    def menu(self) -> list:
        self.require(Perm.RESTAURANT_SERVE)
        return [{k: m[k] for k in ("id", "name", "description", "category", "price")}
                for m in self.repos.menu.all() if m["available"]]

    def in_house(self) -> list:
        """Rooms a check can be charged to: guests who are staying right now."""
        self.require(Perm.RESTAURANT_SERVE)
        return [{"reservation_id": r["id"], "room_number": r["room_number"], "guest_name": r["guest_name"]}
                for r in self.repos.reservations.in_house()]

    # ------------------------------------------------------------ checks
    def _totals(self, check: dict) -> dict:
        """Adds the lines and, for an open check, the running totals with taxes."""
        check["lines"] = self.repos.checks.lines(check["id"])
        if check["status"] == "open":
            subtotal = money(sum(ln["quantity"] * ln["unit_price"] for ln in check["lines"] if ln["status"] != "void"))
            taxes = TaxCalculator(self.settings()).compute(subtotal)
            check.update(subtotal=subtotal, service_charge=taxes["service_charge"], vat=taxes["vat"], city_tax=taxes["city_tax"],
                         total=taxes["total"])
        s = self.settings()
        check["service_charge_rate"], check["vat_rate"] = s.get("service_charge_rate"), s.get("vat_rate")
        return check

    def check(self, check_id: int) -> dict:
        self.require(Perm.RESTAURANT_SERVE)
        return self._totals(self.repos.checks.require(check_id))

    def _open(self, check_id: int) -> dict:
        check = self.repos.checks.require(check_id)
        if check["status"] != "open":
            raise Conflict("This check is closed")
        return check

    def open_check(self, data: dict) -> dict:
        self.require(Perm.RESTAURANT_SERVE)
        v = OpenSchema.validate(data)
        table_name = "Takeaway"
        if v["table_id"]:
            table = self.repos.restaurant_tables.require(v["table_id"], "Table")
            if not table["active"]:
                raise ValidationError("This table is not in use", field="table_id")
            if any(c["table_id"] == table["id"] for c in self.repos.checks.open_checks()):
                raise Conflict(f"{table['name']} already has an open check")
            table_name = table["name"]
        cid = self.repos.checks.insert(code=self.new_code("CK", self.repos.checks, 5), table_id=v["table_id"],
                                       table_name=table_name, covers=v["covers"], customer_name=v["customer_name"],
                                       opened_by=self.actor_id)
        self.audit("check_open", "restaurant_check", cid, f"{table_name}, {v['covers']} guest(s)")
        return self.check(cid)

    def add_lines(self, check_id: int, data: dict) -> dict:
        """Adds dishes and sends them to the kitchen. Their ingredients leave the stock now, as cooking starts."""
        self.require(Perm.RESTAURANT_SERVE)
        check = self._open(check_id)
        v = LinesSchema.validate(data)
        inventory, need, summary = self.use(InventoryService), {}, []
        for line in v["lines"]:
            dish = self.repos.menu.require(line["menu_item_id"], "Menu item")
            if not dish["available"]:
                raise ValidationError(f"{dish['name']} is not available right now")
            self.repos.checks.add_line(check_id, dish["id"], dish["name"], line["quantity"], dish["price"], line["notes"],
                                       self.actor_id)
            summary.append(f"{line['quantity']} × {dish['name']}")
            for ing in self.repos.menu.ingredients(dish["id"]):
                need[ing["item_id"]] = need.get(ing["item_id"], 0) + ing["quantity"] * line["quantity"]
        for item_id, qty in need.items():
            inventory.move(self.repos.items.get(item_id), "consume", -round(qty, 4), f"Restaurant check {check['code']}",
                           reference=check["code"])
        self.audit("check_add", "restaurant_check", check_id, f"{check['code']}: {', '.join(summary)}")
        self.alert("New restaurant order", f"{check['table_name']}: {', '.join(summary)}", "#/tickets", permission=Perm.KITCHEN_ORDERS)
        return self.check(check_id)

    def void_line(self, check_id: int, line_id: int) -> dict:
        """Takes a dish off the bill. A waiter can do it until the kitchen marks it ready; after that a manager must."""
        self.require(Perm.RESTAURANT_SERVE)
        check = self._open(check_id)
        line = self.repos.checks.line(line_id)
        if not line or line["check_id"] != check_id or line["status"] == "void":
            raise ValidationError("This dish is not on the check")
        if line["status"] == "ready":
            self.require(Perm.RESTAURANT_MANAGE)
        self.repos.checks.set_line_status(line_id, "void")
        self.audit("check_void_line", "restaurant_check", check_id, f"{check['code']}: {line['quantity']} × {line['name']}")
        return self.check(check_id)

    # ------------------------------------------------------------ kitchen
    def tickets(self) -> list:
        if not self.actor.can_any(Perm.KITCHEN_VIEW, Perm.RESTAURANT_SERVE):
            self.require(Perm.KITCHEN_VIEW)
        return self.repos.checks.kitchen_tickets()

    def mark_ready(self, line_id: int) -> None:
        self.require(Perm.KITCHEN_ORDERS)
        line = self.repos.checks.line(line_id)
        if not line or line["status"] != "sent":
            raise Conflict("This dish is not waiting in the kitchen")
        check = self.repos.checks.require(line["check_id"])
        self.repos.checks.set_line_status(line_id, "ready")
        self.audit("check_line_ready", "restaurant_check", check["id"], f"{check['code']}: {line['name']}")
        self.alert("A dish is ready", f"{check['table_name']}: {line['quantity']} × {line['name']}",
                   f"#/restaurant/check/{check['id']}", user_id=line["created_by"])

    # ------------------------------------------------------------ settling
    def _closing(self, check_id: int) -> dict:
        check = self._totals(self._open(check_id))
        if not any(ln["status"] != "void" for ln in check["lines"]):
            raise Conflict("There is nothing on this check")
        return check

    def pay(self, check_id: int, method: str) -> dict:
        """The party pays at the table: a numbered receipt with service charge and VAT is issued."""
        self.require(Perm.RESTAURANT_SERVE)
        check = self._closing(check_id)
        if method not in PAYMENT_METHODS:
            raise ValidationError("Choose how the check is paid", field="method")
        shift = self.repos.shifts.open_for(self.actor_id)
        if method == "cash" and not shift and self.settings().get("cash_requires_shift") == "1":
            raise Conflict("Open a cashier shift before taking cash")
        number = self.repos.checks.next_receipt(dt.date.today().year)
        self.repos.checks.update(check_id, status="paid", paid_method=method, receipt_number=number,
                                 shift_id=shift["id"] if shift else None, closed_by=self.actor_id, closed_at=now_str(),
                                 **{k: check[k] for k in ("subtotal", "service_charge", "vat", "city_tax", "total")})
        self.audit("check_paid", "restaurant_check", check_id, f"{check['code']} {number}: {check['total']:.2f} {method}")
        return self.check(check_id)

    def charge_to_room(self, check_id: int, reservation_id) -> dict:
        """The party is staying in the hotel: the food goes on their room bill, where service charge and VAT are added."""
        self.require(Perm.RESTAURANT_SERVE)
        check = self._closing(check_id)
        res = self.repos.reservations.require(Int("Room", required=True).clean(reservation_id), "Reservation")
        if res["status"] != "checked_in":
            raise Conflict("Only guests who are staying can have a check charged to their room")
        self.use(BillingService).post_system_charge(res, f"Restaurant {check['code']} ({check['table_name']})", "Food & Beverage",
                                                    check["subtotal"])
        self.repos.checks.update(check_id, status="charged", reservation_id=res["id"], closed_by=self.actor_id, closed_at=now_str(),
                                 **{k: check[k] for k in ("subtotal", "service_charge", "vat", "city_tax", "total")})
        self.audit("check_charged", "restaurant_check", check_id, f"{check['code']} -> room {res['room_number']} ({res['code']})")
        return self.check(check_id)

    def void_check(self, check_id: int, reason: str) -> dict:
        self.require(Perm.RESTAURANT_MANAGE)
        check = self._open(check_id)
        reason = Str("Reason", required=True, max_len=200).clean(reason or "")
        if not reason:
            raise ValidationError("Reason is required", field="reason")
        for line in self.repos.checks.lines(check_id):
            if line["status"] != "void":
                self.repos.checks.set_line_status(line["id"], "void")
        self.repos.checks.update(check_id, status="void", notes=reason, closed_by=self.actor_id, closed_at=now_str())
        self.audit("check_void", "restaurant_check", check_id, f"{check['code']}: {reason}")
        return self.check(check_id)

    def receipt(self, check_id: int) -> dict:
        self.require(Perm.RESTAURANT_SERVE)
        check = self.check(check_id)
        if check["status"] != "paid":
            raise Conflict("A receipt is issued when the check is paid")
        s = self.settings()
        check["hotel"] = {k: s.get(k, "") for k in ("hotel_name", "hotel_name_ar", "address", "phone", "tax_registration_number",
                                                    "currency")}
        return check

    # ------------------------------------------------------------ reporting
    def sales(self, start: str, end: str) -> dict:
        """Restaurant takings in a period. Checks charged to rooms are counted on the room invoices instead."""
        checks = self.repos.checks.closed_between(start, end)
        paid = [c for c in checks if c["status"] == "paid"]
        by_method = {}
        for c in paid:
            by_method[c["paid_method"]] = money(by_method.get(c["paid_method"], 0) + c["total"])
        return {"checks": len(paid), "covers": sum(c["covers"] for c in paid),
                **{k: money(sum(c[k] for c in paid)) for k in ("subtotal", "service_charge", "vat", "city_tax", "total")},
                "by_method": by_method, "charged_to_rooms": money(sum(c["subtotal"] for c in checks if c["status"] == "charged")),
                "receipts": [{k: c[k] for k in ("receipt_number", "closed_at", "table_name", "covers", "subtotal", "service_charge", "vat",
                                                "city_tax", "total", "paid_method")} for c in paid]}
