"""Composition root: wires configuration, database, security services, router and background jobs."""
import datetime as dt
import logging
import ssl
import threading

from .api.controllers import CONTROLLERS
from .api.dispatcher import Dispatcher
from .api.router import Router
from .config import Config
from .core.clock import add_days
from .core.permissions import system_principal
from .core.security import PasswordHasher, RateLimiter
from .db.database import Database
from .db.seed import Bootstrapper
from .http.server import HotelHTTPServer, RequestHandler
from .infrastructure.backup import BackupManager
from .infrastructure.mailer import MailDispatcher
from .repositories import Repositories
from .services.base import ServiceContext
from .services.reports import NightAuditService

log = logging.getLogger("hotel")


class HotelApp:
    def __init__(self, config: Config = None):
        self.config = config or Config.from_env()
        self.db = Database(self.config.db_path)
        self.hasher = PasswordHasher(self.config.pbkdf2_iterations)
        self.limiter = RateLimiter()
        self.router = Router(CONTROLLERS)
        self.dispatcher = Dispatcher(self)
        self.mailer = MailDispatcher(self.db, self.config)
        self.backups = BackupManager(self.config.db_path, self.config.backup_dir, self.config.backup_keep)
        self._stop = threading.Event()
        self.bootstrap_info = {}

    def initialize(self) -> dict:
        self.db.migrate()
        with self.db.unit_of_work(write=True) as conn:
            self.bootstrap_info = Bootstrapper(conn, self.hasher).run(self.config.seed_demo)
        return self.bootstrap_info

    # ------------------------------------------------------------ background jobs
    def start_background_jobs(self) -> None:
        threading.Thread(target=self._loop, name="hotel-jobs", daemon=True).start()

    def _loop(self) -> None:
        while not self._stop.wait(15):
            try:
                self.mailer.deliver_pending()
            except Exception:
                log.exception("Mail delivery failed")
            hours = self.config.backup_interval_hours
            if hours > 0:
                try:
                    age = self.backups.latest_age_hours()
                    if age is None or age >= hours:
                        self.backups.run()
                except Exception:
                    log.exception("Automatic backup failed")
            try:
                self.run_scheduled_night_audit()
            except Exception:
                log.exception("Automatic night audit failed")

    # ------------------------------------------------------------ scheduled night audit
    def run_scheduled_night_audit(self, now: dt.datetime = None) -> list:
        """Closes every business day that is due, if the administrator turned the automatic night audit on.

        A time before noon (the default 03:00) closes *yesterday* in the early morning; a time after noon
        (e.g. 23:30) closes *today* late in the evening. Days missed while the server was off are caught up.
        Returns the business dates that were closed.
        """
        now = now or dt.datetime.now()
        today, clock = now.date().isoformat(), now.strftime("%H:%M")
        closed = []
        for _ in range(31):  # catch up at most a month per run
            with self.db.unit_of_work(write=False) as conn:
                settings = Repositories(conn).settings.as_dict()
                if settings.get("auto_night_audit") != "1":
                    return closed
                at = settings.get("night_audit_time") or "03:00"
                business_date = NightAuditService(ServiceContext(conn, system_principal(), "", self)).business_date()
            if at < "12:00":
                due = business_date < add_days(today, -1) or (business_date == add_days(today, -1) and clock >= at)
            else:
                due = business_date < today or (business_date == today and clock >= at)
            if not due:
                return closed
            with self.db.unit_of_work(write=True) as conn:
                ctx = ServiceContext(conn, system_principal(), "", self)
                if ctx.repos.audit_days.get_day(business_date):
                    return closed  # someone closed it by hand in the meantime
                ctx.service(NightAuditService).close_day(True, "Automatic night audit")
            log.info("Automatic night audit closed %s", business_date)
            closed.append(business_date)
        return closed

    # ------------------------------------------------------------ restore
    def restore_backup(self, path: str) -> dict:
        """Restores a backup file over the live database, then upgrades it if it came from an older version."""
        result = self.backups.restore(path, Database.latest_version())
        self.db.migrate()
        with self.db.unit_of_work(write=True) as conn:
            Repositories(conn).audit.insert(user_id=None, username="system", action="backup_restored", entity="backup",
                                            entity_id=None, ip="",
                                            details=f"{result['restored']} (previous data saved as {result['safety_backup']})")
        return result

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------ server
    def make_server(self) -> HotelHTTPServer:
        handler = type("BoundHandler", (RequestHandler,), {"app": self})
        server = HotelHTTPServer((self.config.host, self.config.port), handler)
        if self.config.tls_cert:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(self.config.tls_cert, self.config.tls_key or None)
            server.socket = ctx.wrap_socket(server.socket, server_side=True)
        return server
