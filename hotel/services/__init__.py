"""Business-logic layer. Controllers call services; services use repositories.

Each service is instantiated per request via ``ctx.service(ServiceClass)`` so that
collaborating services share one transaction.
"""
from .admin import AlertService, AuditService, PrivacyService, RoleService, SettingsService, UserAdminService
from .auth import AuthService
from .base import Service, ServiceContext
from .billing import BillingService, CashierService, CompanyService, InvoiceService, TaxCalculator
from .front_office import GuestService, PricingService, RoomService
from .inventory import InventoryService, PurchasingService, StockRequestService
from .kitchen import MenuService, OrderService
from .loyalty import LoyaltyService
from .notifications import NotificationService
from .operations import (GuestRequestService, HousekeepingService, LostFoundService, MaintenanceService,
                         ReviewService)
from .portal import GuestPortalService, PublicService
from .reports import DashboardService, NightAuditService, ReportService
from .reservations import ReservationService
from .waitlist import WaitlistService

__all__ = [
    "AlertService", "AuditService", "AuthService", "BillingService", "CashierService", "CompanyService", "DashboardService",
    "GuestPortalService", "GuestRequestService", "GuestService", "HousekeepingService", "InventoryService",
    "InvoiceService", "LostFoundService", "LoyaltyService", "MaintenanceService", "MenuService", "NightAuditService",
    "NotificationService", "OrderService", "PricingService", "PrivacyService", "PublicService", "PurchasingService",
    "ReportService", "ReservationService", "ReviewService", "RoleService", "RoomService", "Service", "ServiceContext",
    "SettingsService", "StockRequestService", "TaxCalculator", "UserAdminService", "WaitlistService",
]
