"""Transport-independent request/response objects."""
import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Request:
    method: str
    path: str
    query: dict
    headers: dict
    raw_body: bytes
    ip: str
    body: dict = field(default_factory=dict)
    ctx: object = None           # ServiceContext, set by the dispatcher
    session: Optional[dict] = None
    session_token: Optional[str] = None

    def header(self, name: str, default: str = "") -> str:
        return self.headers.get(name.lower(), default)

    @property
    def user(self):
        return self.ctx.actor if self.ctx else None

    @property
    def user_agent(self) -> str:
        return self.header("user-agent")[:200]


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "application/json; charset=utf-8"
    headers: list = field(default_factory=list)

    @classmethod
    def json(cls, data, status: int = 200) -> "Response":
        return cls(status, json.dumps(data, default=str, ensure_ascii=False).encode("utf-8"))

    def set_cookie(self, value: str) -> None:
        self.headers.append(("Set-Cookie", value))


class Download:
    """A file returned by a controller (CSV, JSON export)."""

    def __init__(self, content: str, content_type: str, filename: str):
        self.content, self.content_type, self.filename = content, content_type, filename

    def to_response(self) -> Response:
        safe = "".join(c for c in self.filename if c.isalnum() or c in "-_.")
        r = Response(200, self.content.encode("utf-8-sig" if self.content_type.startswith("text/csv") else "utf-8"),
                     self.content_type)
        r.headers.append(("Content-Disposition", f'attachment; filename="{safe}"'))
        return r


class SessionCookie:
    """Signals the dispatcher to set (or clear) the session cookie."""

    def __init__(self, data, token: Optional[str] = None, max_age: int = 0, clear: bool = False):
        self.data, self.token, self.max_age, self.clear = data, token, max_age, clear
