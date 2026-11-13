"""All API controllers, registered with the router in :mod:`hotel.app`."""
from .admin import (AlertController, AuditController, RosterController, ExportController, ReportController, RoleController, SettingsController,
                    UserController)
from .auth import AuthController
from .front_office import (CashierController, CompanyController, DashboardController, GuestController,
                           InvoiceController, ReservationController, RoomController, WaitlistController)
from .inventory import InventoryController, PurchasingController, StockRequestController
from .operations import (GuestRequestController, HousekeepingController, KitchenController, LostFoundController,
                         MaintenanceController, RestaurantController, ReviewController)
from .portal import GuestPortalController, PublicController

CONTROLLERS = [
    AuthController, PublicController, GuestPortalController,
    DashboardController, ReservationController, InvoiceController, GuestController, RoomController,
    WaitlistController, CashierController, CompanyController,
    HousekeepingController, MaintenanceController, GuestRequestController, LostFoundController, ReviewController,
    KitchenController, RestaurantController,
    InventoryController, PurchasingController, StockRequestController,
    UserController, AlertController, RosterController, RoleController, SettingsController, AuditController, ReportController, ExportController,
]
