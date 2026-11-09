"""Front office: dashboard, reservations, guests, rooms, pricing, billing, cashier, companies."""
from ...core.clock import today_iso
from ...core.permissions import Perm
from ...core.validation import Bool, Int, Number
from ...services import (BillingService, CashierService, CompanyService, DashboardService, GuestService,
                         InvoiceService, PricingService, PrivacyService, ReservationService, RoomService)
from ..router import Controller, delete, get, post, put


class DashboardController(Controller):
    @get("/dashboard", perm=Perm.DASHBOARD_VIEW)
    def dashboard(self):
        return self.svc(DashboardService).front_desk()


class ReservationController(Controller):
    def rs(self) -> ReservationService:
        return self.svc(ReservationService)

    @get("/reservations", perm=Perm.RESERVATIONS_VIEW)
    def list(self):
        return self.rs().search(status=self.q("status"), q=self.q("q"), date_from=self.q("from"), date_to=self.q("to"))

    @post("/reservations", perm=Perm.RESERVATIONS_MANAGE)
    def create(self):
        return self.rs().create(self.body)

    @post("/reservations/group", perm=Perm.RESERVATIONS_MANAGE)
    def create_group(self):
        return self.rs().create_group(self.body)

    @get("/reservations/{reservation_id}", perm=Perm.RESERVATIONS_VIEW)
    def detail(self, reservation_id):
        return self.rs().detail(reservation_id)

    @put("/reservations/{reservation_id}", perm=Perm.RESERVATIONS_MANAGE)
    def update(self, reservation_id):
        return self.rs().update(reservation_id, self.body)

    @post("/reservations/{reservation_id}/move", perm=Perm.RESERVATIONS_MANAGE)
    def move(self, reservation_id):
        return self.rs().move(reservation_id, Int("Room", required=True).clean(self.body.get("room_id")),
                              keep_rate=not Bool().clean(self.body.get("reprice", False)))

    @post("/reservations/{reservation_id}/checkin", perm=Perm.FRONTDESK_CHECKIN)
    def check_in(self, reservation_id):
        return self.rs().check_in(reservation_id, force_dirty=Bool().clean(self.body.get("force", False)))

    @post("/reservations/{reservation_id}/checkout", perm=Perm.FRONTDESK_CHECKIN)
    def check_out(self, reservation_id):
        return self.rs().check_out(reservation_id, early_departure=Bool().clean(self.body.get("early_departure", False)),
                                   force=Bool().clean(self.body.get("force", False)))

    @post("/reservations/{reservation_id}/cancel", perm=Perm.RESERVATIONS_MANAGE)
    def cancel(self, reservation_id):
        return self.rs().cancel(reservation_id, self.body.get("fee"), self.body.get("reason", ""))

    @post("/reservations/{reservation_id}/noshow", perm=Perm.RESERVATIONS_MANAGE)
    def no_show(self, reservation_id):
        self.rs().no_show(reservation_id, self.body.get("fee"))
        return self.rs().detail(reservation_id)

    # ---- folio
    @post("/reservations/{reservation_id}/charges", perm=Perm.BILLING_CHARGE)
    def add_charge(self, reservation_id):
        self.svc(BillingService).add_charge(reservation_id, self.body)
        return self.rs().detail(reservation_id)

    @delete("/reservations/{reservation_id}/charges/{charge_id}", perm=Perm.BILLING_VOID)
    def void_charge(self, reservation_id, charge_id):
        self.svc(BillingService).void_charge(reservation_id, charge_id)
        return self.rs().detail(reservation_id)

    @post("/reservations/{reservation_id}/charges/{charge_id}/transfer", perm=Perm.BILLING_CHARGE)
    def transfer_charge(self, reservation_id, charge_id):
        self.svc(BillingService).transfer_charge(reservation_id, charge_id, self.body.get("target_code"))
        return self.rs().detail(reservation_id)

    @post("/reservations/{reservation_id}/payments", perm=Perm.BILLING_PAYMENT)
    def add_payment(self, reservation_id):
        self.svc(BillingService).add_payment(reservation_id, self.body)
        return self.rs().detail(reservation_id)

    @delete("/reservations/{reservation_id}/payments/{payment_id}", perm=Perm.BILLING_VOID)
    def void_payment(self, reservation_id, payment_id):
        self.svc(BillingService).void_payment(reservation_id, payment_id)
        return self.rs().detail(reservation_id)

    @get("/availability", perm=Perm.RESERVATIONS_VIEW)
    def availability(self):
        return self.rs().availability(self.q("check_in"), self.q("check_out"),
                                      Int(min_value=1, max_value=20).clean(self.q("guests", 1)),
                                      Int().clean(self.q("type_id")) if self.q("type_id") else None,
                                      Int().clean(self.q("exclude")) if self.q("exclude") else None)

    @get("/quote", perm=Perm.RESERVATIONS_VIEW)
    def quote(self):
        return self.svc(PricingService).quote(Int("Room type", required=True).clean(self.q("room_type_id")),
                                              self.q("check_in"), self.q("check_out"), self.q("promo_code", ""),
                                              Int().clean(self.q("company_id")) if self.q("company_id") else None)

    @get("/calendar", perm=Perm.RESERVATIONS_VIEW)
    def calendar(self):
        days = Int(min_value=1, max_value=62).clean(self.q("days", 14))
        return self.svc(RoomService).calendar(self.q("start") or today_iso(), days)


class InvoiceController(Controller):
    @get("/invoices", perm=Perm.BILLING_VIEW)
    def list(self):
        return self.svc(InvoiceService).search(self.q("from"), self.q("to"))

    @get("/invoices/{invoice_id}", perm=Perm.BILLING_VIEW)
    def detail(self, invoice_id):
        return self.svc(InvoiceService).get(invoice_id)


class GuestController(Controller):
    @get("/guests", perm=Perm.GUESTS_VIEW)
    def list(self):
        return self.svc(GuestService).search(self.q("q"))

    @post("/guests", perm=Perm.GUESTS_MANAGE)
    def create(self):
        return self.svc(GuestService).create(self.body)

    @get("/guests/{guest_id}", perm=Perm.GUESTS_VIEW)
    def detail(self, guest_id):
        return self.svc(GuestService).get(guest_id)

    @put("/guests/{guest_id}", perm=Perm.GUESTS_MANAGE)
    def update(self, guest_id):
        return self.svc(GuestService).update(guest_id, self.body)

    @delete("/guests/{guest_id}", perm=Perm.GUESTS_MANAGE)
    def delete(self, guest_id):
        self.svc(GuestService).delete(guest_id)

    @get("/guests/{guest_id}/export", perm=Perm.GUESTS_MANAGE)
    def export(self, guest_id):
        return self.svc(PrivacyService).export_guest(guest_id)

    @post("/guests/{guest_id}/erase", perm=Perm.USERS_MANAGE)
    def erase(self, guest_id):
        return self.svc(PrivacyService).anonymize_guest(guest_id)

    @get("/guest-register", perm=Perm.GUESTS_VIEW)
    def register(self):
        return self.svc(GuestService).registration_report(self.q("date") or today_iso(),
                                                          foreign_only=not self.flag("all"))


# A 1.5 MB image is about 2 MB once base64-encoded inside JSON.
PHOTO_UPLOAD_LIMIT = 2_200_000


class RoomController(Controller):
    @get("/room-types", audience="user")
    def types(self):
        return self.svc(RoomService).types()

    @post("/room-types", perm=Perm.ROOMS_MANAGE)
    def create_type(self):
        return self.svc(RoomService).save_type(self.body)

    @put("/room-types/{type_id}", perm=Perm.ROOMS_MANAGE)
    def update_type(self, type_id):
        return self.svc(RoomService).save_type(self.body, type_id)

    @delete("/room-types/{type_id}", perm=Perm.ROOMS_MANAGE)
    def delete_type(self, type_id):
        self.svc(RoomService).delete_type(type_id)

    @post("/room-types/{type_id}/photos", perm=Perm.ROOMS_MANAGE, max_body=PHOTO_UPLOAD_LIMIT)
    def add_photo(self, type_id):
        return {**self.svc(RoomService).add_photo(type_id, self.body.get("data")), "_created": True}

    @delete("/room-photos/{photo_id}", perm=Perm.ROOMS_MANAGE)
    def delete_photo(self, photo_id):
        self.svc(RoomService).delete_photo(photo_id)

    @post("/room-photos/{photo_id}/cover", perm=Perm.ROOMS_MANAGE)
    def cover_photo(self, photo_id):
        self.svc(RoomService).set_cover_photo(photo_id)

    @get("/rooms")
    def rooms(self):
        return self.svc(RoomService).rooms(status=self.q("status"))

    @post("/rooms", perm=Perm.ROOMS_MANAGE)
    def create_room(self):
        return self.svc(RoomService).save_room(self.body)

    @put("/rooms/{room_id}", perm=Perm.ROOMS_MANAGE)
    def update_room(self, room_id):
        return self.svc(RoomService).save_room(self.body, room_id)

    @delete("/rooms/{room_id}", perm=Perm.ROOMS_MANAGE)
    def delete_room(self, room_id):
        self.svc(RoomService).delete_room(room_id)

    @post("/rooms/{room_id}/status", perm=Perm.ROOMS_STATUS)
    def set_status(self, room_id):
        return self.svc(RoomService).set_status(room_id, self.body.get("status"), self.body.get("notes"))

    # ---- pricing
    @get("/seasons", perm=Perm.ROOMS_VIEW)
    def seasons(self):
        return self.svc(PricingService).seasons()

    @post("/seasons", perm=Perm.ROOMS_MANAGE)
    def create_season(self):
        return self.svc(PricingService).save_season(self.body)

    @put("/seasons/{season_id}", perm=Perm.ROOMS_MANAGE)
    def update_season(self, season_id):
        return self.svc(PricingService).save_season(self.body, season_id)

    @delete("/seasons/{season_id}", perm=Perm.ROOMS_MANAGE)
    def delete_season(self, season_id):
        self.svc(PricingService).delete_season(season_id)

    @get("/promos", perm=Perm.ROOMS_MANAGE)
    def promos(self):
        return self.svc(PricingService).promos()

    @post("/promos", perm=Perm.ROOMS_MANAGE)
    def create_promo(self):
        return self.svc(PricingService).save_promo(self.body)

    @put("/promos/{promo_id}", perm=Perm.ROOMS_MANAGE)
    def update_promo(self, promo_id):
        return self.svc(PricingService).save_promo(self.body, promo_id)

    @delete("/promos/{promo_id}", perm=Perm.ROOMS_MANAGE)
    def delete_promo(self, promo_id):
        self.svc(PricingService).delete_promo(promo_id)


class CashierController(Controller):
    @get("/cashier/shifts", perm=Perm.BILLING_PAYMENT)
    def shifts(self):
        return {"current": self.svc(CashierService).current(), "shifts": self.svc(CashierService).list()}

    @post("/cashier/open", perm=Perm.BILLING_PAYMENT)
    def open(self):
        return self.svc(CashierService).open(self.body.get("opening_float", 0))

    @post("/cashier/close", perm=Perm.BILLING_PAYMENT)
    def close(self):
        return self.svc(CashierService).close(self.body.get("counted_cash"), self.body.get("notes", ""))

    @get("/cashier/shifts/{shift_id}", perm=Perm.BILLING_PAYMENT)
    def detail(self, shift_id):
        return self.svc(CashierService).detail(shift_id)


class CompanyController(Controller):
    @get("/companies", perm=Perm.RESERVATIONS_VIEW)
    def list(self):
        return self.svc(CompanyService).list()

    @get("/companies/{company_id}", perm=Perm.BILLING_VIEW)
    def detail(self, company_id):
        return self.svc(CompanyService).get(company_id)

    @post("/companies", perm=Perm.BILLING_VOID)
    def create(self):
        return self.svc(CompanyService).save(self.body)

    @put("/companies/{company_id}", perm=Perm.BILLING_VOID)
    def update(self, company_id):
        return self.svc(CompanyService).save(self.body, company_id)

    @post("/companies/{company_id}/payments", perm=Perm.BILLING_PAYMENT)
    def payment(self, company_id):
        return self.svc(CompanyService).record_payment(company_id, self.body)


_ = Number  # re-exported validators are used by other controllers
