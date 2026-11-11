"""Inventory, purchasing and departmental supply requests."""
from ...core.permissions import Perm
from ...core.validation import Bool, Int
from ...services import InventoryService, PurchasingService, StockRequestService
from ..router import Controller, delete, get, post, put


class InventoryController(Controller):
    def inv(self) -> InventoryService:
        return self.svc(InventoryService)

    @get("/items", perm=Perm.INVENTORY_VIEW)
    def list(self):
        return self.inv().search(q=self.q("q"), category=self.q("category"), department=self.q("department"),
                                 low=self.flag("low"), include_inactive=self.flag("include_inactive"))

    @get("/items/chargeable", perm=Perm.BILLING_CHARGE)
    def chargeable(self):
        return self.inv().search(chargeable=True)

    @get("/items/requestable", perm=Perm.INVENTORY_REQUEST)
    def requestable(self):
        return self.inv().requestable()

    @post("/items", perm=Perm.INVENTORY_MANAGE)
    def create(self):
        return self.inv().save(self.body)

    @get("/items/{item_id}", perm=Perm.INVENTORY_VIEW)
    def detail(self, item_id):
        return self.inv().detail(item_id)

    @put("/items/{item_id}", perm=Perm.INVENTORY_MANAGE)
    def update(self, item_id):
        return self.inv().save(self.body, item_id)

    @delete("/items/{item_id}", perm=Perm.INVENTORY_MANAGE)
    def delete(self, item_id):
        return self.inv().delete(item_id)

    @post("/items/{item_id}/movements", perm=Perm.INVENTORY_VIEW)
    def move(self, item_id):
        return self.inv().adjust(item_id, self.body)

    @get("/movements", perm=Perm.INVENTORY_VIEW)
    def movements(self):
        return self.inv().movements(item_id=Int().clean(self.q("item_id")) if self.q("item_id") else None,
                                    kind=self.q("kind"), date_from=self.q("from"), date_to=self.q("to"), **self.paging())

    @get("/suppliers", perm=Perm.INVENTORY_VIEW)
    def suppliers(self):
        return self.inv().suppliers()

    @post("/suppliers", perm=Perm.PURCHASING_MANAGE)
    def create_supplier(self):
        return self.inv().save_supplier(self.body)

    @put("/suppliers/{supplier_id}", perm=Perm.PURCHASING_MANAGE)
    def update_supplier(self, supplier_id):
        return self.inv().save_supplier(self.body, supplier_id)


class PurchasingController(Controller):
    @get("/purchase-orders", perm=Perm.PURCHASING_MANAGE)
    def list(self):
        return self.svc(PurchasingService).list(self.q("status"))

    @post("/purchase-orders", perm=Perm.PURCHASING_MANAGE)
    def create(self):
        return self.svc(PurchasingService).save(self.body)

    @post("/purchase-orders/from-low-stock", perm=Perm.PURCHASING_MANAGE)
    def from_low_stock(self):
        return self.svc(PurchasingService).from_low_stock(Int("Supplier", required=True).clean(self.body.get("supplier_id")))

    @get("/purchase-orders/{po_id}", perm=Perm.PURCHASING_MANAGE)
    def detail(self, po_id):
        return self.svc(PurchasingService).detail(po_id)

    @put("/purchase-orders/{po_id}", perm=Perm.PURCHASING_MANAGE)
    def update(self, po_id):
        return self.svc(PurchasingService).save(self.body, po_id)

    @post("/purchase-orders/{po_id}/status", perm=Perm.PURCHASING_MANAGE)
    def status(self, po_id):
        return self.svc(PurchasingService).set_status(po_id, str(self.body.get("status", "")))


class StockRequestController(Controller):
    @get("/stock-requests")
    def list(self):
        return self.svc(StockRequestService).list(self.q("status"), mine=self.flag("mine"))

    @post("/stock-requests", perm=Perm.INVENTORY_REQUEST)
    def create(self):
        return self.svc(StockRequestService).create(self.body)

    @post("/stock-requests/{request_id}/decide", perm=Perm.INVENTORY_APPROVE)
    def decide(self, request_id):
        return self.svc(StockRequestService).decide(request_id, Bool().clean(self.body.get("approve", False)),
                                                    self.body.get("response", ""))

    @post("/stock-requests/{request_id}/cancel")
    def cancel(self, request_id):
        return self.svc(StockRequestService).cancel(request_id)
