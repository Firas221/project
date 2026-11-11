"""Food & beverage: menu, recipes and the room-service order workflow.

pending → preparing (ingredients deducted from stock) → ready → delivered (charged to the guest folio)
"""
from ..core.clock import money, now_str
from ..core.errors import Conflict, PermissionDenied, ValidationError
from ..core.permissions import Perm
from ..core.validation import Bool, Int, ListOf, Money, Number, Schema, Str
from .base import Service
from .billing import BillingService
from .inventory import InventoryService


class IngredientSchema(Schema):
    item_id = Int("Ingredient", required=True)
    quantity = Number(required=True, min_value=0.0001, max_value=1000, places=4)


class MenuItemSchema(Schema):
    name = Str(required=True, max_len=100)
    description = Str(max_len=300)
    category = Str(max_len=40, default="Mains")
    price = Money(required=True)
    prep_minutes = Int(min_value=0, max_value=240, default=15)
    available = Bool(default=True)
    ingredients = ListOf(IngredientSchema, max_items=30)


class OrderLineSchema(Schema):
    menu_item_id = Int("Menu item", required=True)
    quantity = Int(min_value=1, max_value=50, default=1)
    notes = Str(max_len=200)


class OrderSchema(Schema):
    reservation_id = Int("Reservation", required=True)
    notes = Str(max_len=500, multiline=True)
    lines = ListOf(OrderLineSchema, min_items=1, max_items=30)


TRANSITIONS = {
    "pending": ("preparing", "cancelled"),
    "preparing": ("ready", "cancelled"),
    "ready": ("delivered",),
}


class MenuService(Service):
    def list(self, available_only=False):
        rows = self.repos.menu.search(available_only)
        if not available_only:
            for r in rows:
                r["ingredients"] = self.repos.menu.ingredients(r["id"])
        return rows

    def save(self, data: dict, menu_id: int = None) -> dict:
        self.require(Perm.MENU_MANAGE)
        v = MenuItemSchema.validate(data)
        ingredients = v.pop("ingredients")
        v["available"] = int(v["available"])
        if self.repos.menu.exists(name=v["name"], exclude_id=menu_id):
            raise Conflict("A menu item with this name already exists")
        for ing in ingredients:
            self.repos.items.require(ing["item_id"], "Ingredient")
        if menu_id:
            self.repos.menu.require(menu_id)
            self.repos.menu.update(menu_id, **v)
        else:
            menu_id = self.repos.menu.insert(**v)
        self.repos.menu.set_ingredients(menu_id, ingredients)
        self.audit("menu_save", "menu_item", menu_id, f"{v['name']} {v['price']:.2f}")
        item = self.repos.menu.get(menu_id)
        item["ingredients"] = self.repos.menu.ingredients(menu_id)
        return item

    def set_available(self, menu_id: int, available: bool) -> dict:
        self.require(Perm.KITCHEN_ORDERS)
        m = self.repos.menu.require(menu_id)
        self.repos.menu.update(menu_id, available=int(bool(available)))
        self.audit("menu_availability", "menu_item", menu_id, f"{m['name']}: {'available' if available else '86'}")
        return self.repos.menu.get(menu_id)

    def delete(self, menu_id: int) -> None:
        self.require(Perm.MENU_MANAGE)
        m = self.repos.menu.require(menu_id)
        if self.repos.menu.used_in_orders(menu_id):
            self.repos.menu.update(menu_id, available=0)
        else:
            self.repos.menu.delete(menu_id)
        self.audit("menu_delete", "menu_item", menu_id, m["name"])


class OrderService(Service):
    def queue(self, include_done=False):
        self.require(Perm.KITCHEN_VIEW)
        statuses = None if include_done else ("pending", "preparing", "ready")
        rows = self.repos.orders.search(statuses=statuses, limit=200)
        for r in rows:
            r["lines"] = self.repos.orders.lines(r["id"])
        return rows

    def detail(self, order_id: int) -> dict:
        o = self.repos.orders.require(order_id, "Order")
        o["lines"] = self.repos.orders.lines(order_id)
        return o

    def place(self, data: dict, *, by_guest: bool = False) -> dict:
        if not by_guest:
            self.require(Perm.ORDERS_CREATE)
        v = OrderSchema.validate(data)
        res = self.repos.reservations.require(v["reservation_id"], "Reservation")
        if res["status"] != "checked_in":
            raise Conflict("Room service is available to in-house guests only")
        if by_guest and res["guest_id"] != self.actor.guest_id:
            raise PermissionDenied()
        total, lines = 0.0, []
        for line in v["lines"]:
            m = self.repos.menu.require(line["menu_item_id"], "Menu item")
            if not m["available"]:
                raise ValidationError(f"{m['name']} is not available right now")
            total += m["price"] * line["quantity"]
            lines.append((m, line))
        oid = self.repos.orders.insert(code=self.new_code("OR", self.repos.orders, 5), reservation_id=res["id"],
                                       notes=v["notes"], total=money(total), placed_via="guest" if by_guest else "staff",
                                       created_by=self.actor_id)
        for m, line in lines:
            self.repos.orders.add_line(oid, m["id"], m["name"], line["quantity"], m["price"], line["notes"])
        self.audit("order_place", "order", oid, f"{res['code']} {total:.2f}")
        self.alert("New room-service order", f"Room {res['room_number']}: " + ", ".join(f"{ln['quantity']:g} × {m['name']}" for m, ln in lines),
                   "#/orders", permission=Perm.KITCHEN_ORDERS)
        return self.detail(oid)

    def advance(self, order_id: int, status: str) -> dict:
        order = self.detail(order_id)
        if status == "delivered":
            if not self.actor.can_any(Perm.KITCHEN_ORDERS, Perm.ORDERS_CREATE):
                raise PermissionDenied()
        elif status == "cancelled" and order["status"] == "pending" and self.actor.can(Perm.ORDERS_CREATE):
            pass
        else:
            self.require(Perm.KITCHEN_ORDERS)
        if status not in TRANSITIONS.get(order["status"], ()):
            raise Conflict(f"An order that is {order['status']} cannot become {status}")
        if status == "preparing":
            self._consume_ingredients(order)
        if status == "cancelled" and order["status"] == "preparing":
            pass  # ingredients already used are not returned (waste); recorded in the ledger
        if status == "delivered":
            res = self.repos.reservations.require(order["reservation_id"])
            if res["status"] != "checked_in":
                raise Conflict("The guest has already checked out")
            self.use(BillingService).post_system_charge(res, f"Room service {order['code']}", "Food & Beverage",
                                                        order["total"], order_id=order["id"])
            self.repos.orders.update(order_id, status=status, updated_at=now_str(), delivered_at=now_str())
        else:
            self.repos.orders.update(order_id, status=status, updated_at=now_str())
        self.audit("order_" + status, "order", order_id, order["code"])
        return self.detail(order_id)

    def _consume_ingredients(self, order: dict) -> None:
        inv = self.use(InventoryService)
        need = {}
        for line in order["lines"]:
            if not line["menu_item_id"]:
                continue
            for ing in self.repos.menu.ingredients(line["menu_item_id"]):
                need[ing["item_id"]] = need.get(ing["item_id"], 0) + ing["quantity"] * line["quantity"]
        for item_id, qty in need.items():
            item = self.repos.items.get(item_id)
            inv.move(item, "consume", -round(qty, 4), f"Order {order['code']}", reservation_id=order["reservation_id"],
                     reference=order["code"])

    def in_house_guests(self) -> list:
        self.require(Perm.ORDERS_CREATE)
        return [{"id": r["id"], "code": r["code"], "room_number": r["room_number"], "guest_name": r["guest_name"]}
                for r in self.repos.reservations.in_house()]
