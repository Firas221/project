"""Runtime configuration, read from environment variables with safe defaults."""
import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Config:
    db_path: str = os.path.join("data", "hotel.db")
    host: str = "127.0.0.1"
    port: int = 8000
    seed_demo: bool = True

    # --- security
    pbkdf2_iterations: int = 600_000          # OWASP 2023 recommendation for PBKDF2-SHA256
    session_idle_minutes: int = 60            # sign out after inactivity
    session_absolute_hours: int = 12          # hard session lifetime
    secure_cookies: bool = False              # set True when served over HTTPS
    trust_proxy: bool = False                 # honour X-Forwarded-For (only behind a trusted proxy)
    max_body_bytes: int = 256 * 1024
    login_max_failures: int = 5               # per account, then lock
    login_lock_minutes: int = 15
    login_ip_limit_per_minute: int = 20       # per client IP
    api_limit_per_minute: int = 600           # per client IP, all API calls
    public_limit_per_minute: int = 60         # per client IP, unauthenticated endpoints
    allowed_origins: tuple = field(default_factory=tuple)  # extra origins allowed for state-changing requests
    tls_cert: str = ""                        # PEM certificate -> serve HTTPS directly
    tls_key: str = ""
    public_url: str = ""                      # e.g. https://hotel.example.com (used in e-mail links)

    # --- e-mail (leave smtp_host empty to keep mails in the admin outbox only)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@hotel.local"
    smtp_starttls: bool = True

    # --- backups
    backup_dir: str = os.path.join("data", "backups")
    backup_interval_hours: int = 24           # 0 disables automatic backups
    backup_keep: int = 14

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        cfg = cls(
            db_path=os.environ.get("HOTEL_DB", cls.db_path),
            host=os.environ.get("HOTEL_HOST", cls.host),
            port=_int("HOTEL_PORT", cls.port),
            seed_demo=_bool("HOTEL_SEED_DEMO", cls.seed_demo),
            pbkdf2_iterations=_int("HOTEL_PBKDF2_ITERATIONS", cls.pbkdf2_iterations),
            session_idle_minutes=_int("HOTEL_SESSION_IDLE_MINUTES", cls.session_idle_minutes),
            session_absolute_hours=_int("HOTEL_SESSION_HOURS", cls.session_absolute_hours),
            secure_cookies=_bool("HOTEL_SECURE_COOKIES", cls.secure_cookies),
            trust_proxy=_bool("HOTEL_TRUST_PROXY", cls.trust_proxy),
            tls_cert=os.environ.get("HOTEL_TLS_CERT", ""),
            tls_key=os.environ.get("HOTEL_TLS_KEY", ""),
            public_url=os.environ.get("HOTEL_PUBLIC_URL", "").rstrip("/"),
            smtp_host=os.environ.get("HOTEL_SMTP_HOST", ""),
            smtp_port=_int("HOTEL_SMTP_PORT", 587),
            smtp_user=os.environ.get("HOTEL_SMTP_USER", ""),
            smtp_password=os.environ.get("HOTEL_SMTP_PASSWORD", ""),
            smtp_from=os.environ.get("HOTEL_SMTP_FROM", cls.smtp_from),
            smtp_starttls=_bool("HOTEL_SMTP_STARTTLS", True),
            backup_dir=os.environ.get("HOTEL_BACKUP_DIR", cls.backup_dir),
            backup_interval_hours=_int("HOTEL_BACKUP_HOURS", 24),
            backup_keep=_int("HOTEL_BACKUP_KEEP", 14),
            allowed_origins=tuple(o.strip() for o in os.environ.get("HOTEL_ALLOWED_ORIGINS", "").split(",") if o.strip()),
        )
        for k, v in overrides.items():
            if not hasattr(cfg, k):
                raise AttributeError(f"Unknown config option: {k}")
            setattr(cfg, k, v)
        return cfg
