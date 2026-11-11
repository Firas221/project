"""Service-layer foundations.

A :class:`ServiceContext` is created per request (unit of work). It exposes
the repositories bound to the request's database connection, the acting
principal, and lazily-created services so that services can collaborate
(e.g. checkout → billing + housekeeping) inside one transaction.
"""
import secrets
import string
from typing import Optional

from ..core.errors import PermissionDenied
from ..core.permissions import Principal
from ..repositories import Repositories

CODE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "O0I1")


class ServiceContext:
    def __init__(self, conn, actor: Optional[Principal], ip: str = "", app=None):
        self.conn = conn
        self.actor = actor
        self.ip = ip
        self.app = app  # access to config / hasher / rate limiter
        self.repos = Repositories(conn)
        self._services = {}

    def service(self, cls):
        if cls not in self._services:
            self._services[cls] = cls(self)
        return self._services[cls]


class Service:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx
        self.repos = ctx.repos

    # ------------------------------------------------------------ helpers
    @property
    def actor(self) -> Optional[Principal]:
        return self.ctx.actor

    @property
    def actor_id(self):
        return self.ctx.actor.id if self.ctx.actor else None

    def require(self, permission: str) -> None:
        """Defence in depth: services re-check permissions for sensitive operations."""
        if not self.actor or not self.actor.can(permission):
            raise PermissionDenied()

    def use(self, cls):
        return self.ctx.service(cls)

    def audit(self, action: str, entity: str = "", entity_id=None, details: str = "") -> None:
        a = self.ctx.actor
        self.repos.audit.insert(user_id=a.id if a else None, username=a.username if a else "", action=action,
                                entity=entity, entity_id=entity_id, details=str(details)[:1000], ip=self.ctx.ip)

    def alert(self, title: str, body: str = "", link: str = "", *, permission: str = "", user_id: int = None) -> None:
        """Puts a line under the bell of one person (user_id), or of everyone who holds a permission.
        The person who caused it never sees their own alert."""
        if not permission and not user_id:
            return
        if user_id and user_id == self.actor_id:
            return
        self.repos.alerts.insert(user_id=user_id, permission="" if user_id else permission, title=title[:120],
                                 body=str(body)[:300], link=link[:200], actor_id=self.actor_id)

    def settings(self) -> dict:
        return self.repos.settings.as_dict()

    def new_code(self, prefix: str, repo, length: int = 6) -> str:
        while True:
            code = prefix + "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))
            if not repo.exists(code=code):
                return code
