"""Composition root: wires configuration, database, security services, router and background jobs."""
import logging
import ssl
import threading

from .api.controllers import CONTROLLERS
from .api.dispatcher import Dispatcher
from .api.router import Router
from .config import Config
from .core.security import PasswordHasher, RateLimiter
from .db.database import Database
from .db.seed import Bootstrapper
from .http.server import HotelHTTPServer, RequestHandler
from .infrastructure.backup import BackupManager
from .infrastructure.mailer import MailDispatcher

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
