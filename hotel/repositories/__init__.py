"""Repository registry: one lazily-created instance per repository per unit of work."""
from functools import cached_property

from .finance import (AuditDayRepository, ChallengeRepository, CompanyRepository, EmailVerificationRepository,
                      InvoiceRepository,
                      LedgerRepository, OutboxRepository, PasswordResetRepository, PromoRepository,
                      SeasonRepository, ShiftRepository)
from .guests import GuestRepository
from .identity import AuditRepository, RoleRepository, SessionRepository, SettingsRepository, UserRepository
from .inventory import (ItemRepository, MovementRepository, PurchaseOrderRepository, StockRequestRepository,
                        SupplierRepository)
from .kitchen import MenuRepository, OrderRepository
from .operations import (GuestRequestRepository, HousekeepingTaskRepository, LostFoundRepository,
                         MaintenanceRepository, ReviewRepository)
from .reservations import ChargeRepository, PaymentRepository, ReservationRepository
from .rooms import RoomPhotoRepository, RoomRepository, RoomTypeRepository


class Repositories:
    def __init__(self, conn):
        self.conn = conn

    # identity & administration
    users = cached_property(lambda self: UserRepository(self.conn))
    roles = cached_property(lambda self: RoleRepository(self.conn))
    sessions = cached_property(lambda self: SessionRepository(self.conn))
    audit = cached_property(lambda self: AuditRepository(self.conn))
    settings = cached_property(lambda self: SettingsRepository(self.conn))
    # front office
    guests = cached_property(lambda self: GuestRepository(self.conn))
    room_types = cached_property(lambda self: RoomTypeRepository(self.conn))
    rooms = cached_property(lambda self: RoomRepository(self.conn))
    room_photos = cached_property(lambda self: RoomPhotoRepository(self.conn))
    reservations = cached_property(lambda self: ReservationRepository(self.conn))
    charges = cached_property(lambda self: ChargeRepository(self.conn))
    payments = cached_property(lambda self: PaymentRepository(self.conn))
    # inventory
    suppliers = cached_property(lambda self: SupplierRepository(self.conn))
    items = cached_property(lambda self: ItemRepository(self.conn))
    movements = cached_property(lambda self: MovementRepository(self.conn))
    purchase_orders = cached_property(lambda self: PurchaseOrderRepository(self.conn))
    stock_requests = cached_property(lambda self: StockRequestRepository(self.conn))
    # food & beverage
    menu = cached_property(lambda self: MenuRepository(self.conn))
    orders = cached_property(lambda self: OrderRepository(self.conn))
    # operations
    housekeeping = cached_property(lambda self: HousekeepingTaskRepository(self.conn))
    maintenance = cached_property(lambda self: MaintenanceRepository(self.conn))
    guest_requests = cached_property(lambda self: GuestRequestRepository(self.conn))
    lost_found = cached_property(lambda self: LostFoundRepository(self.conn))
    reviews = cached_property(lambda self: ReviewRepository(self.conn))
    # commercial & finance
    companies = cached_property(lambda self: CompanyRepository(self.conn))
    ledger = cached_property(lambda self: LedgerRepository(self.conn))
    seasons = cached_property(lambda self: SeasonRepository(self.conn))
    promos = cached_property(lambda self: PromoRepository(self.conn))
    shifts = cached_property(lambda self: ShiftRepository(self.conn))
    invoices = cached_property(lambda self: InvoiceRepository(self.conn))
    audit_days = cached_property(lambda self: AuditDayRepository(self.conn))
    # security & messaging
    password_resets = cached_property(lambda self: PasswordResetRepository(self.conn))
    email_verifications = cached_property(lambda self: EmailVerificationRepository(self.conn))
    challenges = cached_property(lambda self: ChallengeRepository(self.conn))
    outbox = cached_property(lambda self: OutboxRepository(self.conn))
