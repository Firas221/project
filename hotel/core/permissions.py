"""Roles, permissions and the authenticated principal.

Access control is permission based: every API route declares the permission it
needs; roles are bundles of permissions. The ``admin`` role implicitly holds
every permission and cannot be edited. The permissions of every other staff
role (front desk, chef, housekeeper, housekeeping supervisor, maintenance
technician, storekeeper, accountant, manager) are stored in the database and
can be changed by an administrator. The ``guest`` role is used by hotel clients and
only reaches the guest-portal endpoints, which additionally enforce ownership.
"""
from dataclasses import dataclass, field
from typing import FrozenSet, Optional


class Role:
    ADMIN = "admin"
    STAFF = "staff"
    CHEF = "chef"
    HOUSEKEEPER = "housekeeper"
    SUPERVISOR = "supervisor"        # housekeeping supervisor: assigns and inspects, does not clean
    MAINTENANCE = "maintenance"      # maintenance technician
    STOREKEEPER = "storekeeper"
    ACCOUNTANT = "accountant"
    MANAGER = "manager"              # runs the hotel day to day; no users, settings or backups
    GUEST = "guest"

    EDITABLE = (MANAGER, STAFF, ACCOUNTANT, CHEF, SUPERVISOR, HOUSEKEEPER, MAINTENANCE, STOREKEEPER)
    EMPLOYEES = (ADMIN,) + EDITABLE
    ALL = EMPLOYEES + (GUEST,)

    LABELS = {
        ADMIN: "Administrator",
        MANAGER: "Manager",
        STAFF: "Front desk staff",
        ACCOUNTANT: "Accountant",
        CHEF: "Chef / kitchen",
        SUPERVISOR: "Housekeeping supervisor",
        HOUSEKEEPER: "Housekeeper",
        MAINTENANCE: "Maintenance technician",
        STOREKEEPER: "Storekeeper",
        GUEST: "Guest (client)",
    }
    # The web portal each role lands on after signing in.
    PORTALS = {
        ADMIN: "/admin",
        MANAGER: "/manager",
        STAFF: "/staff",
        ACCOUNTANT: "/finance",
        CHEF: "/kitchen",
        SUPERVISOR: "/housekeeping",
        HOUSEKEEPER: "/housekeeping",
        MAINTENANCE: "/maintenance",
        STOREKEEPER: "/store",
        GUEST: "/account",
    }


class Perm:
    """Permission identifiers. Grouped by area for the admin permission matrix."""

    DASHBOARD_VIEW = "dashboard.view"

    RESERVATIONS_VIEW = "reservations.view"
    RESERVATIONS_MANAGE = "reservations.manage"
    FRONTDESK_CHECKIN = "frontdesk.checkin"

    BILLING_VIEW = "billing.view"
    BILLING_CHARGE = "billing.charge"
    BILLING_PAYMENT = "billing.payment"
    BILLING_VOID = "billing.void"

    GUESTS_VIEW = "guests.view"
    GUESTS_MANAGE = "guests.manage"

    ROOMS_VIEW = "rooms.view"
    ROOMS_MANAGE = "rooms.manage"
    ROOMS_STATUS = "rooms.status"

    HOUSEKEEPING_VIEW = "housekeeping.view"
    HOUSEKEEPING_MANAGE = "housekeeping.manage"
    HOUSEKEEPING_WORK = "housekeeping.work"

    MAINTENANCE_VIEW = "maintenance.view"
    MAINTENANCE_REPORT = "maintenance.report"
    MAINTENANCE_MANAGE = "maintenance.manage"

    INVENTORY_VIEW = "inventory.view"
    INVENTORY_MANAGE = "inventory.manage"
    INVENTORY_REQUEST = "inventory.request"
    INVENTORY_APPROVE = "inventory.approve"
    PURCHASING_MANAGE = "purchasing.manage"

    KITCHEN_VIEW = "kitchen.view"
    KITCHEN_ORDERS = "kitchen.orders"
    MENU_MANAGE = "menu.manage"
    ORDERS_CREATE = "orders.create"

    REQUESTS_MANAGE = "requests.manage"
    LOSTFOUND_REPORT = "lostfound.report"
    LOSTFOUND_MANAGE = "lostfound.manage"
    REVIEWS_MANAGE = "reviews.manage"

    REPORTS_VIEW = "reports.view"
    NIGHT_AUDIT_CLOSE = "nightaudit.close"

    USERS_MANAGE = "users.manage"
    ROLES_MANAGE = "roles.manage"
    SETTINGS_MANAGE = "settings.manage"
    AUDIT_VIEW = "audit.view"

    PORTAL_GUEST = "portal.guest"


# (permission, group, description) — drives the admin permission matrix UI.
PERMISSION_CATALOG = (
    (Perm.DASHBOARD_VIEW, "Front office", "See the front-desk dashboard"),
    (Perm.RESERVATIONS_VIEW, "Front office", "View reservations and the room calendar"),
    (Perm.RESERVATIONS_MANAGE, "Front office", "Create, edit, move, cancel reservations"),
    (Perm.FRONTDESK_CHECKIN, "Front office", "Check guests in and out"),
    (Perm.GUESTS_VIEW, "Front office", "View guest profiles"),
    (Perm.GUESTS_MANAGE, "Front office", "Create and edit guest profiles"),
    (Perm.REQUESTS_MANAGE, "Front office", "Handle guest requests"),
    (Perm.REVIEWS_MANAGE, "Front office", "Moderate guest reviews"),
    (Perm.BILLING_VIEW, "Billing", "View guest folios and invoices"),
    (Perm.BILLING_CHARGE, "Billing", "Post charges to folios"),
    (Perm.BILLING_PAYMENT, "Billing", "Record payments and refunds"),
    (Perm.BILLING_VOID, "Billing", "Void charges and payments"),
    (Perm.ROOMS_VIEW, "Rooms", "View rooms and room types"),
    (Perm.ROOMS_STATUS, "Rooms", "Change room housekeeping status"),
    (Perm.ROOMS_MANAGE, "Rooms", "Create and edit rooms, room types and rates"),
    (Perm.HOUSEKEEPING_VIEW, "Housekeeping", "View the housekeeping board"),
    (Perm.HOUSEKEEPING_MANAGE, "Housekeeping", "Create, assign and inspect cleaning tasks"),
    (Perm.HOUSEKEEPING_WORK, "Housekeeping", "Work on assigned cleaning tasks"),
    (Perm.LOSTFOUND_REPORT, "Housekeeping", "Log lost & found items"),
    (Perm.LOSTFOUND_MANAGE, "Housekeeping", "Return or dispose of lost & found items"),
    (Perm.MAINTENANCE_VIEW, "Maintenance", "View maintenance tickets"),
    (Perm.MAINTENANCE_REPORT, "Maintenance", "Report maintenance issues"),
    (Perm.MAINTENANCE_MANAGE, "Maintenance", "Assign, resolve tickets; take rooms out of order"),
    (Perm.KITCHEN_VIEW, "Kitchen", "View the kitchen order queue"),
    (Perm.KITCHEN_ORDERS, "Kitchen", "Prepare orders and update their status"),
    (Perm.MENU_MANAGE, "Kitchen", "Manage the menu and recipes"),
    (Perm.ORDERS_CREATE, "Kitchen", "Place room-service orders for guests"),
    (Perm.INVENTORY_VIEW, "Inventory", "View stock levels and movements"),
    (Perm.INVENTORY_REQUEST, "Inventory", "Request supplies from the store"),
    (Perm.INVENTORY_APPROVE, "Inventory", "Approve and issue supply requests"),
    (Perm.INVENTORY_MANAGE, "Inventory", "Manage items, receive and adjust stock"),
    (Perm.PURCHASING_MANAGE, "Inventory", "Manage suppliers and purchase orders"),
    (Perm.REPORTS_VIEW, "Administration", "View management reports"),
    (Perm.NIGHT_AUDIT_CLOSE, "Administration", "Close the business day (night audit)"),
    (Perm.USERS_MANAGE, "Administration", "Manage user accounts"),
    (Perm.ROLES_MANAGE, "Administration", "Change role permissions"),
    (Perm.SETTINGS_MANAGE, "Administration", "Change hotel settings"),
    (Perm.AUDIT_VIEW, "Administration", "View the security audit log"),
)
ALL_PERMISSIONS = frozenset(p for p, _, _ in PERMISSION_CATALOG)

DEFAULT_ROLE_PERMISSIONS = {
    Role.STAFF: {
        Perm.DASHBOARD_VIEW, Perm.RESERVATIONS_VIEW, Perm.RESERVATIONS_MANAGE, Perm.FRONTDESK_CHECKIN,
        Perm.GUESTS_VIEW, Perm.GUESTS_MANAGE, Perm.REQUESTS_MANAGE, Perm.REVIEWS_MANAGE,
        Perm.BILLING_VIEW, Perm.BILLING_CHARGE, Perm.BILLING_PAYMENT,
        Perm.ROOMS_VIEW, Perm.ROOMS_STATUS,
        Perm.HOUSEKEEPING_VIEW, Perm.HOUSEKEEPING_MANAGE, Perm.LOSTFOUND_REPORT, Perm.LOSTFOUND_MANAGE,
        Perm.MAINTENANCE_VIEW, Perm.MAINTENANCE_REPORT, Perm.MAINTENANCE_MANAGE,
        Perm.KITCHEN_VIEW, Perm.ORDERS_CREATE,
        Perm.INVENTORY_VIEW, Perm.INVENTORY_REQUEST,
    },
    Role.CHEF: {
        Perm.KITCHEN_VIEW, Perm.KITCHEN_ORDERS, Perm.MENU_MANAGE,
        Perm.INVENTORY_VIEW, Perm.INVENTORY_REQUEST, Perm.MAINTENANCE_REPORT,
    },
    # Everything the departments do, plus rates, voids, reports, the audit log and closing the day.
    # Not users, role permissions, settings or backups: those stay with the administrator.
    Role.MANAGER: {
        Perm.DASHBOARD_VIEW, Perm.RESERVATIONS_VIEW, Perm.RESERVATIONS_MANAGE, Perm.FRONTDESK_CHECKIN,
        Perm.GUESTS_VIEW, Perm.GUESTS_MANAGE, Perm.REQUESTS_MANAGE, Perm.REVIEWS_MANAGE,
        Perm.BILLING_VIEW, Perm.BILLING_CHARGE, Perm.BILLING_PAYMENT, Perm.BILLING_VOID,
        Perm.ROOMS_VIEW, Perm.ROOMS_STATUS, Perm.ROOMS_MANAGE,
        Perm.HOUSEKEEPING_VIEW, Perm.HOUSEKEEPING_MANAGE, Perm.LOSTFOUND_REPORT, Perm.LOSTFOUND_MANAGE,
        Perm.MAINTENANCE_VIEW, Perm.MAINTENANCE_REPORT, Perm.MAINTENANCE_MANAGE,
        Perm.KITCHEN_VIEW, Perm.ORDERS_CREATE, Perm.MENU_MANAGE,
        Perm.INVENTORY_VIEW, Perm.INVENTORY_REQUEST, Perm.INVENTORY_APPROVE, Perm.INVENTORY_MANAGE, Perm.PURCHASING_MANAGE,
        Perm.REPORTS_VIEW, Perm.NIGHT_AUDIT_CLOSE, Perm.AUDIT_VIEW,
    },
    # Money: invoices, VAT, corporate accounts, cashier shifts, reports. Sees reservations and guests but cannot change them.
    Role.ACCOUNTANT: {
        Perm.BILLING_VIEW, Perm.BILLING_PAYMENT, Perm.BILLING_VOID, Perm.REPORTS_VIEW,
        Perm.RESERVATIONS_VIEW, Perm.GUESTS_VIEW, Perm.INVENTORY_VIEW,
    },
    # Runs the housekeeping board: creates, assigns and inspects tasks, sets room status. Does not clean rooms.
    Role.SUPERVISOR: {
        Perm.HOUSEKEEPING_VIEW, Perm.HOUSEKEEPING_MANAGE, Perm.ROOMS_VIEW, Perm.ROOMS_STATUS,
        Perm.LOSTFOUND_REPORT, Perm.LOSTFOUND_MANAGE, Perm.MAINTENANCE_VIEW, Perm.MAINTENANCE_REPORT,
        Perm.INVENTORY_REQUEST,
    },
    Role.MAINTENANCE: {
        Perm.MAINTENANCE_VIEW, Perm.MAINTENANCE_REPORT, Perm.MAINTENANCE_MANAGE, Perm.ROOMS_VIEW,
        Perm.LOSTFOUND_REPORT, Perm.INVENTORY_REQUEST,
    },
    Role.STOREKEEPER: {
        Perm.INVENTORY_VIEW, Perm.INVENTORY_MANAGE, Perm.INVENTORY_APPROVE, Perm.INVENTORY_REQUEST,
        Perm.PURCHASING_MANAGE, Perm.MAINTENANCE_REPORT,
    },
    Role.HOUSEKEEPER: {
        Perm.HOUSEKEEPING_WORK, Perm.LOSTFOUND_REPORT, Perm.MAINTENANCE_REPORT, Perm.INVENTORY_REQUEST,
    },
    Role.GUEST: {Perm.PORTAL_GUEST},
}


@dataclass(frozen=True)
class Principal:
    """The authenticated user making a request."""

    id: int
    username: str
    full_name: str
    role: str
    permissions: FrozenSet[str] = field(default_factory=frozenset)
    guest_id: Optional[int] = None
    session_id: Optional[int] = None
    must_change_password: bool = False
    must_enroll_2fa: bool = False
    must_verify_email: bool = False   # guest accounts: the e-mail address has not been confirmed yet

    @property
    def restricted(self) -> bool:
        """True while the user must finish a security step before using the system."""
        return self.must_change_password or self.must_enroll_2fa

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_guest(self) -> bool:
        return self.role == Role.GUEST

    def can(self, permission: str) -> bool:
        if self.is_admin:
            return permission != Perm.PORTAL_GUEST
        return permission in self.permissions

    def can_any(self, *permissions: str) -> bool:
        return any(self.can(p) for p in permissions)

    def to_dict(self) -> dict:
        perms = sorted(ALL_PERMISSIONS) if self.is_admin else sorted(self.permissions)
        return {
            "id": self.id, "username": self.username, "full_name": self.full_name, "role": self.role,
            "role_label": Role.LABELS.get(self.role, self.role), "permissions": perms,
            "portal": Role.PORTALS.get(self.role, "/"), "guest_id": self.guest_id,
            "must_change_password": self.must_change_password, "must_enroll_2fa": self.must_enroll_2fa,
            "must_verify_email": self.must_verify_email,
        }


def system_principal() -> Principal:
    """The actor used by scheduled jobs (automatic night audit). Shown as "system" in the audit log."""
    return Principal(id=None, username="system", full_name="System", role=Role.ADMIN)
