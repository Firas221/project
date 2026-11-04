"""Public website and the guest (client) portal."""
from ...services import GuestPortalService, PublicService, SettingsService
from ...http.messages import Download
from ..router import Controller, delete, get, post, put
import json


class PublicController(Controller):
    @get("/public/info", audience="public")
    def info(self):
        return {"settings": self.svc(SettingsService).public(), "room_types": self.svc(PublicService).room_types()}

    @post("/public/search", audience="public", csrf=False)
    def search(self):
        return self.svc(PublicService).search(self.body)

    @get("/public/reviews", audience="public")
    def reviews(self):
        return self.svc(GuestPortalService).public_reviews()


class GuestPortalController(Controller):
    def portal(self) -> GuestPortalService:
        return self.svc(GuestPortalService)

    @get("/portal/profile", audience="guest")
    def profile(self):
        return self.portal().profile()

    @put("/portal/profile", audience="guest")
    def update_profile(self):
        return self.portal().update_profile(self.body)

    @get("/portal/reservations", audience="guest")
    def reservations(self):
        return self.portal().reservations()

    @post("/portal/reservations", audience="guest")
    def book(self):
        return self.portal().book(self.body)

    @get("/portal/reservations/{reservation_id}", audience="guest")
    def reservation(self, reservation_id):
        return self.portal().reservation(reservation_id)

    @post("/portal/reservations/{reservation_id}/cancel", audience="guest")
    def cancel(self, reservation_id):
        return self.portal().cancel(reservation_id)

    @get("/portal/reservations/{reservation_id}/invoice", audience="guest")
    def invoice(self, reservation_id):
        return self.portal().invoice(reservation_id)

    @get("/portal/menu", audience="guest")
    def menu(self):
        return self.portal().menu()

    @post("/portal/reservations/{reservation_id}/orders", audience="guest")
    def order(self, reservation_id):
        return self.portal().order(reservation_id, self.body)

    @post("/portal/reservations/{reservation_id}/requests", audience="guest")
    def request(self, reservation_id):
        return self.portal().request(reservation_id, self.body.get("kind"), self.body.get("message"))

    @post("/portal/reservations/{reservation_id}/review", audience="guest")
    def review(self, reservation_id):
        return self.portal().review(reservation_id, self.body.get("rating"), self.body.get("comment"))

    @get("/portal/privacy/export", audience="guest")
    def export(self):
        return Download(json.dumps(self.portal().export_my_data(), ensure_ascii=False, indent=2),
                        "application/json", "my-data.json")

    @delete("/portal/account", audience="guest")
    def delete_account(self):
        self.portal().delete_my_account(self.body.get("password"))
        return {"ok": True}
