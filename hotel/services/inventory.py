"""Inventory: items, stock ledger, suppliers, purchase orders and departmental supply requests."""
from ..core.clock import money, now_str
from ..core.errors import Conflict, PermissionDenied, ValidationError
from ..core.permissions import Perm, Role
from ..core.validation import Bool, Date, Email, Int, ListOf, Money, Number, Schema, Str
from .base import Service

DEPARTMENTS = ("general", "housekeeping", "kitchen", "minibar", "maintenance", "front_office")


class ItemSchema(Schema):
    sku = Str("SKU", required=True, max_len=40, pattern=r"[A-Za-z0-9_\-.]+", upper=True)
    name = Str(required=True, max_len=120)
    category = Str(max_len=60, default="General")
    department = Str(choices=DEPARTMENTS, default="general")
    unit = Str(max_len=20, default="pcs")
    reorder_level = Number(min_value=0, max_value=1e7, places=3, default=0)
    cost = Money("Unit cost", default=0)
    price = Money("Sale price", default=0)
    chargeable = Bool()
    supplier_id = Int("Supplier", nullable=True, default=None)
    active = Bool(default=True)


class SupplierSchema(Schema):
    name = Str(required=True, max_len=120)
    contact = Str(max_len=120)
    phone = Str(max_len=40)
    email = Email()
    active = Bool(default=True)


class LineSchema(Schema):
    item_id = Int("Item", required=True)
    quantity = Number(required=True, min_value=0.001, max_value=1e7, places=3)
    unit_cost = Money("Unit cost", nullable=True, default=None)


class PurchaseOrderSchema(Schema):
    supplier_id = Int("Supplier", required=True)
    expected_date = Date(nullable=True, default=None)
    notes = Str(max_len=1000, multiline=True)
    lines = ListOf(LineSchema, min_items=1, max_items=200)


class StockRequestSchema(Schema):
    department = Str(choices=DEPARTMENTS, required=True)
    notes = Str(max_len=500, multiline=True)
    lines = ListOf(LineSchema, min_items=1, max_items=50)


ROLE_DEPARTMENT = {Role.CHEF: "kitchen", Role.HOUSEKEEPER: "housekeeping", Role.SUPERVISOR: "housekeeping",
                   Role.MAINTENANCE: "maintenance", Role.STAFF: "front_office", Role.MANAGER: "front_office"}


class InventoryService(Service):
    # ------------------------------------------------------------ ledger primitive (used by billing & kitchen)
    def move(self, item: dict, kind: str, change: float, reason: str = "", *, reservation_id=None, unit_cost=None,
             reference: str = "") -> float:
        new_qty = round(item["quantity"] + change, 4)
        if new_qty < 0:
            raise Conflict(f"Insufficient stock of {item['name']}: {item['quantity']:g} {item['unit']} available")
        self.repos.items.update(item["id"], quantity=new_qty)
        self.repos.movements.insert(item_id=item["id"], kind=kind, change=change, balance_after=new_qty,
                                    unit_cost=unit_cost, reason=reason[:300], reference=reference[:60],
                                    reservation_id=reservation_id, created_by=self.actor_id)
        item["quantity"] = new_qty
        return new_qty

    # ------------------------------------------------------------ items
    def search(self, **filters):
        self.require(Perm.INVENTORY_VIEW) if not filters.get("chargeable") else None
        return self.repos.items.search(**filters)

    def requestable(self):
        """Lightweight item list for supply-request forms (any role allowed to request)."""
        self.require(Perm.INVENTORY_REQUEST)
        return [{k: i[k] for k in ("id", "sku", "name", "unit", "department", "category", "quantity")}
                for i in self.repos.items.search()]

    def detail(self, item_id: int) -> dict:
        self.require(Perm.INVENTORY_VIEW)
        item = self.repos.items.require(item_id, "Item")
        item["movements"] = self.repos.movements.search(item_id=item_id, limit=200)
        return item

    def save(self, data: dict, item_id: int = None) -> dict:
        self.require(Perm.INVENTORY_MANAGE)
        v = ItemSchema.validate(data)
        if v["supplier_id"]:
            self.repos.suppliers.require(v["supplier_id"], "Supplier")
        if self.repos.items.exists(sku=v["sku"], exclude_id=item_id):
            raise Conflict("SKU already exists")
        v["chargeable"], v["active"] = int(v["chargeable"]), int(v["active"])
        if item_id:
            self.repos.items.require(item_id, "Item")
            self.repos.items.update(item_id, **v)
        else:
            item_id = self.repos.items.insert(**v)
            opening = Number(min_value=0, max_value=1e7).clean(data.get("quantity") or 0)
            if opening:
                self.move(self.repos.items.get(item_id), "receive", opening, "Opening stock", unit_cost=v["cost"])
        self.audit("item_save", "item", item_id, f"{v['sku']} {v['name']}")
        return self.repos.items.get(item_id)

    def delete(self, item_id: int) -> dict:
        self.require(Perm.INVENTORY_MANAGE)
        item = self.repos.items.require(item_id, "Item")
        used = (self.repos.movements.scalar("SELECT 1 FROM charges WHERE item_id=? LIMIT 1", (item_id,))
                or self.repos.movements.scalar("SELECT 1 FROM menu_ingredients WHERE item_id=? LIMIT 1", (item_id,))
                or self.repos.movements.scalar("SELECT 1 FROM purchase_order_lines WHERE item_id=? LIMIT 1", (item_id,))
                or self.repos.movements.scalar("SELECT 1 FROM stock_request_lines WHERE item_id=? LIMIT 1", (item_id,)))
        if used:
            self.repos.items.update(item_id, active=0)
            self.audit("item_deactivate", "item", item_id, item["sku"])
            return {"deactivated": True}
        self.repos.items.delete(item_id)
        self.audit("item_delete", "item", item_id, item["sku"])
        return {"deactivated": False}

    def adjust(self, item_id: int, data: dict) -> dict:
        kind = data.get("kind")
        item = self.repos.items.require(item_id, "Item")
        reason = Str(max_len=300).clean(data.get("reason") or "") if data.get("reason") else ""
        if kind == "receive":
            self.require(Perm.INVENTORY_MANAGE)
            qty = Number("Quantity", min_value=0.001, max_value=1e7).clean(data.get("quantity"))
            unit_cost = Money("Unit cost").clean(data["unit_cost"]) if data.get("unit_cost") not in (None, "") else None
            if unit_cost is not None:
                total = item["quantity"] + qty
                self.repos.items.update(item_id, cost=money((item["quantity"] * item["cost"] + qty * unit_cost) / total))
            self.move(item, "receive", qty, reason or "Stock received", unit_cost=unit_cost)
        elif kind == "issue":
            self.require(Perm.INVENTORY_APPROVE)
            qty = Number("Quantity", min_value=0.001, max_value=1e7).clean(data.get("quantity"))
            self.move(item, "issue", -qty, reason or "Issued")
        elif kind == "adjust":
            self.require(Perm.INVENTORY_MANAGE)
            counted = Number("Counted quantity", min_value=0, max_value=1e7).clean(data.get("counted"))
            change = round(counted - item["quantity"], 4)
            if change == 0:
                raise ValidationError("Counted quantity equals current stock")
            if not reason:
                raise ValidationError("A reason is required for stock adjustments", field="reason")
            self.move(item, "adjust", change, reason)
        else:
            raise ValidationError("Movement type must be receive, issue or adjust")
        self.audit("stock_" + kind, "item", item_id, item["sku"])
        return self.repos.items.get(item_id)

    def movements(self, **filters):
        self.require(Perm.INVENTORY_VIEW)
        return self.repos.movements.search(**filters)

    # ------------------------------------------------------------ suppliers
    def suppliers(self):
        self.require(Perm.INVENTORY_VIEW)
        return self.repos.suppliers.all()

    def save_supplier(self, data: dict, supplier_id: int = None) -> dict:
        self.require(Perm.PURCHASING_MANAGE)
        v = SupplierSchema.validate(data)
        v["active"] = int(v["active"])
        if self.repos.suppliers.exists(name=v["name"], exclude_id=supplier_id):
            raise Conflict("Supplier already exists")
        if supplier_id:
            self.repos.suppliers.require(supplier_id, "Supplier")
            self.repos.suppliers.update(supplier_id, **v)
        else:
            supplier_id = self.repos.suppliers.insert(**v)
        self.audit("supplier_save", "supplier", supplier_id, v["name"])
        return self.repos.suppliers.get(supplier_id)


class PurchasingService(Service):
    def list(self, status=None):
        self.require(Perm.PURCHASING_MANAGE)
        return self.repos.purchase_orders.search(status)

    def detail(self, po_id: int) -> dict:
        self.require(Perm.PURCHASING_MANAGE)
        po = self.repos.purchase_orders.require(po_id, "Purchase order")
        po["lines"] = self.repos.purchase_orders.lines(po_id)
        return po

    def save(self, data: dict, po_id: int = None) -> dict:
        self.require(Perm.PURCHASING_MANAGE)
        v = PurchaseOrderSchema.validate(data)
        self.repos.suppliers.require(v["supplier_id"], "Supplier")
        if po_id:
            po = self.repos.purchase_orders.require(po_id)
            if po["status"] != "draft":
                raise Conflict("Only draft purchase orders can be edited")
            self.repos.purchase_orders.update(po_id, supplier_id=v["supplier_id"], expected_date=v["expected_date"],
                                              notes=v["notes"])
            self.repos.purchase_orders.clear_lines(po_id)
        else:
            po_id = self.repos.purchase_orders.insert(code=self.new_code("PO", self.repos.purchase_orders, 5),
                                                      supplier_id=v["supplier_id"], expected_date=v["expected_date"],
                                                      notes=v["notes"], created_by=self.actor_id)
        for line in v["lines"]:
            item = self.repos.items.require(line["item_id"], "Item")
            cost = item["cost"] if line["unit_cost"] is None else line["unit_cost"]
            self.repos.purchase_orders.add_line(po_id, item["id"], line["quantity"], cost)
        self.audit("po_save", "purchase_order", po_id)
        return self.detail(po_id)

    def from_low_stock(self, supplier_id: int) -> dict:
        """Drafts a purchase order that tops low items up to twice their reorder level."""
        self.require(Perm.PURCHASING_MANAGE)
        self.repos.suppliers.require(supplier_id, "Supplier")
        low = self.repos.items.low_stock(supplier_id)
        if not low:
            raise ValidationError("No low-stock items for this supplier")
        lines = [{"item_id": i["id"], "quantity": max(1, round(i["reorder_level"] * 2 - i["quantity"], 3)),
                  "unit_cost": i["cost"]} for i in low]
        return self.save({"supplier_id": supplier_id, "notes": "Auto-generated from low stock", "lines": lines})

    def set_status(self, po_id: int, status: str) -> dict:
        self.require(Perm.PURCHASING_MANAGE)
        po = self.repos.purchase_orders.require(po_id, "Purchase order")
        allowed = {"draft": ("ordered", "cancelled"), "ordered": ("received", "cancelled")}
        if status not in allowed.get(po["status"], ()):
            raise Conflict(f"Cannot change a {po['status']} order to {status}")
        if status == "received":
            inv = self.use(InventoryService)
            for line in self.repos.purchase_orders.lines(po_id):
                item = self.repos.items.get(line["item_id"])
                total = item["quantity"] + line["quantity"]
                self.repos.items.update(item["id"], cost=money((item["quantity"] * item["cost"]
                                                                + line["quantity"] * line["unit_cost"]) / total))
                inv.move(item, "receive", line["quantity"], f"Purchase order {po['code']}", unit_cost=line["unit_cost"],
                         reference=po["code"])
            self.repos.purchase_orders.update(po_id, status="received", received_at=now_str())
        elif status == "ordered":
            self.repos.purchase_orders.update(po_id, status="ordered", ordered_at=now_str())
        else:
            self.repos.purchase_orders.update(po_id, status=status)
        self.audit("po_" + status, "purchase_order", po_id, po["code"])
        return self.detail(po_id)


class StockRequestService(Service):
    """Departments (kitchen, housekeeping, front office) request supplies; the store approves and issues them."""

    def list(self, status=None, mine=False):
        if mine or not self.actor.can(Perm.INVENTORY_APPROVE):
            self.require(Perm.INVENTORY_REQUEST)
            rows = self.repos.stock_requests.search(status, requested_by=self.actor_id)
        else:
            rows = self.repos.stock_requests.search(status)
        for r in rows:
            r["lines"] = self.repos.stock_requests.lines(r["id"])
        return rows

    def create(self, data: dict) -> dict:
        self.require(Perm.INVENTORY_REQUEST)
        data = dict(data)
        data.setdefault("department", ROLE_DEPARTMENT.get(self.actor.role, "general"))
        v = StockRequestSchema.validate(data)
        rid = self.repos.stock_requests.insert(code=self.new_code("SR", self.repos.stock_requests, 5),
                                               department=v["department"], notes=v["notes"], requested_by=self.actor_id)
        for line in v["lines"]:
            item = self.repos.items.require(line["item_id"], "Item")
            if not item["active"]:
                raise ValidationError(f"{item['name']} is no longer stocked")
            self.repos.stock_requests.add_line(rid, item["id"], line["quantity"])
        self.audit("supply_request", "stock_request", rid, v["department"])
        return self._get(rid)

    def _get(self, rid):
        r = self.repos.stock_requests.require(rid, "Supply request")
        r["lines"] = self.repos.stock_requests.lines(rid)
        return r

    def decide(self, request_id: int, approve: bool, response: str = "") -> dict:
        self.require(Perm.INVENTORY_APPROVE)
        req = self._get(request_id)
        if req["status"] != "pending":
            raise Conflict("This request was already handled")
        if approve:
            inv = self.use(InventoryService)
            for line in req["lines"]:
                item = self.repos.items.get(line["item_id"])
                inv.move(item, "issue", -line["quantity"], f"Supply request {req['code']} ({req['department']})",
                         reference=req["code"])
        self.repos.stock_requests.update(request_id, status="issued" if approve else "rejected",
                                         response=str(response or "")[:300], handled_by=self.actor_id, handled_at=now_str())
        self.audit("supply_" + ("issued" if approve else "rejected"), "stock_request", request_id, req["code"])
        return self._get(request_id)

    def cancel(self, request_id: int) -> dict:
        req = self._get(request_id)
        if req["requested_by"] != self.actor_id and not self.actor.can(Perm.INVENTORY_APPROVE):
            raise PermissionDenied()
        if req["status"] != "pending":
            raise Conflict("Only pending requests can be cancelled")
        self.repos.stock_requests.update(request_id, status="cancelled", handled_at=now_str())
        self.audit("supply_cancel", "stock_request", request_id, req["code"])
        return self._get(request_id)
