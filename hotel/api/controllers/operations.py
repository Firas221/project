"""Operations: housekeeping, maintenance, guest requests, lost & found, reviews, kitchen."""
from ...core.permissions import Perm
from ...core.validation import Bool, Int
from ...services import (GuestRequestService, HousekeepingService, LostFoundService, MaintenanceService, MenuService,
                         OrderService, ReviewService)
from ..router import Controller, delete, get, post, put


class HousekeepingController(Controller):
    def hk(self) -> HousekeepingService:
        return self.svc(HousekeepingService)

    @get("/housekeeping/tasks")
    def board(self):
        return self.hk().board(self.q("status"), mine=self.flag("mine"))

    @get("/housekeeping/history")
    def history(self):
        return self.hk().history()

    @get("/housekeeping/staff", perm=Perm.HOUSEKEEPING_MANAGE)
    def staff(self):
        return self.hk().housekeepers()

    @post("/housekeeping/tasks", perm=Perm.HOUSEKEEPING_MANAGE)
    def create(self):
        return self.hk().create(self.body)

    @post("/housekeeping/generate", perm=Perm.HOUSEKEEPING_MANAGE)
    def generate(self):
        return self.hk().generate_stayovers()

    @post("/housekeeping/tasks/{task_id}/assign", perm=Perm.HOUSEKEEPING_MANAGE)
    def assign(self, task_id):
        return self.hk().assign(task_id, self.body.get("user_id"))

    @post("/housekeeping/tasks/{task_id}/start")
    def start(self, task_id):
        return self.hk().start(task_id)

    @post("/housekeeping/tasks/{task_id}/complete")
    def complete(self, task_id):
        return self.hk().complete(task_id, self.body.get("notes", ""))

    @post("/housekeeping/tasks/{task_id}/inspect", perm=Perm.HOUSEKEEPING_MANAGE)
    def inspect(self, task_id):
        return self.hk().inspect(task_id, Bool().clean(self.body.get("passed", True)), self.body.get("notes", ""))

    @post("/housekeeping/tasks/{task_id}/cancel", perm=Perm.HOUSEKEEPING_MANAGE)
    def cancel(self, task_id):
        return self.hk().cancel(task_id)


class MaintenanceController(Controller):
    @get("/maintenance")
    def list(self):
        return self.svc(MaintenanceService).list(self.q("status", "active"))

    @post("/maintenance", perm=Perm.MAINTENANCE_REPORT)
    def report(self):
        return self.svc(MaintenanceService).report(self.body)

    @put("/maintenance/{ticket_id}", perm=Perm.MAINTENANCE_MANAGE)
    def update(self, ticket_id):
        return self.svc(MaintenanceService).update(ticket_id, self.body)


class GuestRequestController(Controller):
    @get("/requests", perm=Perm.REQUESTS_MANAGE)
    def list(self):
        return self.svc(GuestRequestService).list(self.q("status", "active"))

    @post("/requests/{request_id}", perm=Perm.REQUESTS_MANAGE)
    def respond(self, request_id):
        return self.svc(GuestRequestService).respond(request_id, self.body.get("status"), self.body.get("response", ""))


class LostFoundController(Controller):
    @get("/lost-found")
    def list(self):
        return self.svc(LostFoundService).list(self.q("status"))

    @post("/lost-found", perm=Perm.LOSTFOUND_REPORT)
    def log(self):
        return self.svc(LostFoundService).log(self.body)

    @post("/lost-found/{item_id}/close", perm=Perm.LOSTFOUND_MANAGE)
    def close(self, item_id):
        return self.svc(LostFoundService).close(item_id, self.body.get("status"), self.body.get("notes", ""))


class ReviewController(Controller):
    @get("/reviews", perm=Perm.REVIEWS_MANAGE)
    def list(self):
        return self.svc(ReviewService).list()

    @put("/reviews/{review_id}", perm=Perm.REVIEWS_MANAGE)
    def moderate(self, review_id):
        return self.svc(ReviewService).moderate(review_id, Bool().clean(self.body.get("published", False)),
                                                self.body.get("reply", ""))


class KitchenController(Controller):
    @get("/kitchen/orders", perm=Perm.KITCHEN_VIEW)
    def queue(self):
        return self.svc(OrderService).queue(include_done=self.flag("all"))

    @post("/kitchen/orders", perm=Perm.ORDERS_CREATE)
    def place(self):
        return self.svc(OrderService).place(self.body)

    @post("/kitchen/orders/{order_id}/status", perm=Perm.KITCHEN_VIEW)
    def advance(self, order_id):
        return self.svc(OrderService).advance(order_id, str(self.body.get("status", "")))

    @get("/kitchen/in-house", perm=Perm.ORDERS_CREATE)
    def in_house(self):
        return self.svc(OrderService).in_house_guests()

    @get("/menu", perm=Perm.KITCHEN_VIEW)
    def menu(self):
        return self.svc(MenuService).list(available_only=self.flag("available"))

    @post("/menu", perm=Perm.MENU_MANAGE)
    def create(self):
        return self.svc(MenuService).save(self.body)

    @put("/menu/{menu_id}", perm=Perm.MENU_MANAGE)
    def update(self, menu_id):
        return self.svc(MenuService).save(self.body, menu_id)

    @post("/menu/{menu_id}/availability", perm=Perm.KITCHEN_ORDERS)
    def availability(self, menu_id):
        return self.svc(MenuService).set_available(menu_id, Bool().clean(self.body.get("available", True)))

    @delete("/menu/{menu_id}", perm=Perm.MENU_MANAGE)
    def delete(self, menu_id):
        self.svc(MenuService).delete(menu_id)


_ = Int
