"""Security primitives: password hashing, password policy, tokens and rate limiting."""
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import deque

from .errors import RateLimited, ValidationError


class PasswordHasher:
    """PBKDF2-HMAC-SHA256 with a per-password random salt.

    Stored format: ``pbkdf2_sha256$<iterations>$<salt hex>$<digest hex>``.
    The iteration count is stored with each hash, so it can be raised later and
    old hashes are transparently upgraded on the next successful sign-in.
    """

    ALGORITHM = "pbkdf2_sha256"

    def __init__(self, iterations: int = 600_000):
        self.iterations = max(1_000, int(iterations))
        # A real hash used to equalise timing when the user does not exist.
        self._dummy = self.hash(secrets.token_hex(16))

    def hash(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, self.iterations)
        return f"{self.ALGORITHM}${self.iterations}${salt.hex()}${digest.hex()}"

    def verify(self, password: str, stored: str) -> bool:
        try:
            algorithm, iterations, salt, digest = stored.split("$")
            if algorithm != self.ALGORITHM:
                return False
            calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
            return hmac.compare_digest(calc.hex(), digest)
        except (ValueError, TypeError, AttributeError):
            return False

    def verify_dummy(self, password: str) -> None:
        """Spend the same time as a real verification (prevents user enumeration by timing)."""
        self.verify(password, self._dummy)

    def needs_rehash(self, stored: str) -> bool:
        try:
            return int(stored.split("$")[1]) < self.iterations
        except (IndexError, ValueError):
            return True


class PasswordPolicy:
    MIN_LENGTH = 10
    MAX_LENGTH = 128
    COMMON = {
        "password1234", "password123", "qwerty123456", "1234567890", "letmein1234", "welcome1234",
        "administrator", "admin12345", "iloveyou123", "passw0rd123", "hotel12345", "changeme123",
    }

    @classmethod
    def validate(cls, password: str, *, username: str = None, field: str = "password") -> str:
        if not isinstance(password, str):
            raise ValidationError("Password is required", field=field)
        if len(password) < cls.MIN_LENGTH:
            raise ValidationError(f"Password must be at least {cls.MIN_LENGTH} characters", field=field)
        if len(password) > cls.MAX_LENGTH:
            raise ValidationError(f"Password must be at most {cls.MAX_LENGTH} characters", field=field)
        if not (re.search(r"[a-z]", password) and re.search(r"[A-Z]", password) and re.search(r"\d", password)):
            raise ValidationError("Password needs upper-case, lower-case letters and a digit", field=field)
        if password.lower() in cls.COMMON:
            raise ValidationError("This password is too common", field=field)
        if username and len(username) >= 3 and username.lower() in password.lower():
            raise ValidationError("Password must not contain the username", field=field)
        return password


class Tokens:
    """Opaque random tokens. Only a SHA-256 digest of session tokens is stored server-side."""

    @staticmethod
    def new(nbytes: int = 32) -> str:
        return secrets.token_urlsafe(nbytes)

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def equal(a: str, b: str) -> bool:
        return bool(a) and bool(b) and hmac.compare_digest(str(a), str(b))

    @staticmethod
    def temporary_password() -> str:
        """A random password that satisfies :class:`PasswordPolicy`."""
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
        while True:
            pw = "".join(secrets.choice(alphabet) for _ in range(14))
            if re.search(r"[a-z]", pw) and re.search(r"[A-Z]", pw) and re.search(r"\d", pw):
                return pw


class RateLimiter:
    """Thread-safe sliding-window rate limiter kept in memory."""

    def __init__(self):
        self._hits = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def check(self, key: str, limit: int, window_seconds: float = 60.0, message: str = None) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - window_seconds:
                q.popleft()
            if len(q) >= limit:
                retry = int(q[0] + window_seconds - now) + 1
                raise RateLimited(message or f"Too many requests. Try again in {retry} seconds.")
            q.append(now)
            if now - self._last_sweep > 300:
                self._sweep(now, window_seconds)

    def reset(self, key: str = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)

    def _sweep(self, now, window):
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - window]:
            del self._hits[k]
        self._last_sweep = now
