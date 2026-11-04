"""All API controllers, registered with the router in :mod:`hotel.app`."""
from .admin import (AuditController, ExportController, ReportController, RoleController, SettingsController,
                    UserController)
from .auth import AuthController
from .front_office import (CashierController, CompanyController, DashboardController, GuestController,
                           InvoiceController, ReservationController, RoomController)
from .inventory import InventoryController, PurchasingController, StockRequestController
from .operations import (GuestRequestController, HousekeepingController, KitchenController, LostFoundController,
                         MaintenanceController, ReviewController)
from .portal import GuestPortalController, PublicController

CONTROLLERS = [
    AuthController, PublicController, GuestPortalController,
    DashboardController, ReservationController, InvoiceController, GuestController, RoomController,
    CashierController, CompanyController,
    HousekeepingController, MaintenanceController, GuestRequestController, LostFoundController, ReviewController,
    KitchenController,
    InventoryController, PurchasingController, StockRequestController,
    UserController, RoleController, SettingsController, AuditController, ReportController, ExportController,
]
