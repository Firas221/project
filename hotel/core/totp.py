"""Time-based one-time passwords (RFC 6238), compatible with Google/Microsoft Authenticator."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


class TOTP:
    DIGITS = 6
    PERIOD = 30

    @staticmethod
    def new_secret() -> str:
        return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")

    @classmethod
    def _code(cls, secret: str, step: int) -> str:
        key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
        digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
        return str(value % 10 ** cls.DIGITS).zfill(cls.DIGITS)

    @classmethod
    def current_step(cls, at: float = None) -> int:
        return int((at if at is not None else time.time()) // cls.PERIOD)

    @classmethod
    def code_at(cls, secret: str, at: float = None) -> str:
        return cls._code(secret, cls.current_step(at))

    @classmethod
    def verify(cls, secret: str, code: str, last_step: int = 0, window: int = 1):
        """Returns the matched time step (to prevent replay) or None."""
        code = "".join(ch for ch in str(code or "") if ch.isdigit())
        if len(code) != cls.DIGITS or not secret:
            return None
        now = cls.current_step()
        for step in range(now - window, now + window + 1):
            if step > last_step and hmac.compare_digest(cls._code(secret, step), code):
                return step
        return None

    @staticmethod
    def provisioning_uri(secret: str, account: str, issuer: str) -> str:
        return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}"
                f"&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30")
