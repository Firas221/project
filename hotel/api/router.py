"""Declarative routing.

Controllers are classes whose methods are decorated with ``@get``/``@post``/...
Each route declares *who* may call it:

* ``audience="staff"`` (default) — any signed-in employee; ``perm`` narrows it further
* ``audience="guest"``  — signed-in hotel guests only (client portal)
* ``audience="user"``   — any signed-in user
* ``audience="public"`` — no sign-in required (rate-limited)
"""
import re
from dataclasses import dataclass
from typing import Optional

from ..core.errors import MethodNotAllowed, NotFound

AUDIENCES = ("staff", "guest", "user", "public")


@dataclass
class RouteSpec:
    method: str
    path: str
    perm: Optional[str] = None
    audience: str = "staff"
    csrf: bool = True                 # require the CSRF header on state-changing requests
    allow_restricted: bool = False    # reachable while a password change / 2FA enrolment is pending
    limit: Optional[str] = None       # named rate-limit bucket ("login", "reset", "register"; "none" = only the global limit)
    max_body: Optional[int] = None    # larger request-body limit in bytes (photo uploads); default is Config.max_body_bytes


def _decorator(method):
    def factory(path, perm=None, audience="staff", csrf=True, allow_restricted=False, limit=None, max_body=None):
        if audience not in AUDIENCES:
            raise ValueError(f"Unknown audience {audience}")

        def wrap(fn):
            fn._route = RouteSpec(method, path, perm, audience, csrf, allow_restricted, limit, max_body)
            return fn
        return wrap
    return factory


get, post, put, delete = (_decorator(m) for m in ("GET", "POST", "PUT", "DELETE"))


class Controller:
    """Base class for API controllers. One instance is created per request."""

    def __init__(self, request):
        self.req = request

    @property
    def body(self) -> dict:
        return self.req.body

    def q(self, name: str, default=None):
        value = self.req.query.get(name, default)
        return value if value != "" else default

    def flag(self, name: str) -> bool:
        return str(self.req.query.get(name, "")).lower() in ("1", "true", "yes", "on")

    def paging(self) -> dict:
        """`?page=2&per_page=50` asks for one page ({items, total, page, pages}); without it the full list is returned."""
        if self.q("page") is None:
            return {}
        return {"page": self.q("page"), "per_page": self.q("per_page")}

    def svc(self, cls):
        return self.req.ctx.service(cls)


class Route:
    _param = re.compile(r"\{(\w+)\}")

    def __init__(self, controller_cls, attr: str, spec: RouteSpec):
        self.controller_cls, self.attr, self.spec = controller_cls, attr, spec
        pattern = self._param.sub(lambda m: rf"(?P<{m.group(1)}>\d+)" if m.group(1).endswith("id") else rf"(?P<{m.group(1)}>[A-Za-z0-9_\-]+)",
                                  spec.path)
        self.regex = re.compile("^/api" + pattern + "$")

    def invoke(self, request, params: dict):
        controller = self.controller_cls(request)
        clean = {k: int(v) if k.endswith("id") else v for k, v in params.items()}
        return getattr(controller, self.attr)(**clean)


class Router:
    def __init__(self, controllers):
        self.routes = []
        for cls in controllers:
            for attr in dir(cls):
                spec = getattr(getattr(cls, attr), "_route", None)
                if spec:
                    self.routes.append(Route(cls, attr, spec))

    def match(self, method: str, path: str):
        path_found = False
        for route in self.routes:
            m = route.regex.match(path)
            if m:
                path_found = True
                if route.spec.method == method:
                    return route, m.groupdict()
        if path_found:
            raise MethodNotAllowed()
        raise NotFound()

    def body_limit(self, method: str, path: str, default: int) -> int:
        """The request-body limit for a path, so oversized uploads are refused before they are read."""
        for route in self.routes:
            if route.spec.method == method and route.spec.max_body and route.regex.match(path):
                return route.spec.max_body
        return default

    def describe(self) -> list:
        return sorted((r.spec.method, "/api" + r.spec.path, r.spec.audience, r.spec.perm or "") for r in self.routes)
