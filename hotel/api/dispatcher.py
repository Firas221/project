"""The API pipeline: every request passes through the same ordered security checks.

1. Per-IP rate limit                        6. Restricted-account gate (forced password change / 2FA)
2. Route lookup                             7. Audience & permission check (RBAC)
3. Body size / content-type / JSON parse    8. CSRF token + Origin check for state-changing requests
4. Unit of work (transaction) opened        9. Controller → service → repository
5. Session resolution (idle + absolute)    10. Commit, or roll back on any error
"""
import json
import logging
import sqlite3
import traceback
from urllib.parse import urlsplit

from ..core.errors import (AppError, AuthenticationError, PayloadTooLarge, PermissionDenied, UnsupportedMediaType,
                           ValidationError)
from ..http.messages import Binary, Download, Request, Response, SessionCookie
from ..services.auth import AuthService
from ..services.base import ServiceContext

log = logging.getLogger("hotel.api")
STATE_CHANGING = ("POST", "PUT", "DELETE")


class Dispatcher:
    def __init__(self, app):
        self.app = app
        self.cfg = app.config

    # ------------------------------------------------------------ cookies
    @property
    def cookie_name(self) -> str:
        return "__Host-hms_session" if self.cfg.secure_cookies else "hms_session"

    def _cookie(self, token: str, max_age: int) -> str:
        secure = "; Secure" if self.cfg.secure_cookies else ""
        return f"{self.cookie_name}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}{secure}"

    # ------------------------------------------------------------ checks
    def _check_origin(self, req: Request) -> None:
        origin = req.header("origin") or req.header("referer")
        if not origin:
            return  # non-browser clients; still protected by the CSRF token
        o = urlsplit(origin)
        host = req.header("host")
        trusted = {f"http://{host}", f"https://{host}"} | set(self.cfg.allowed_origins)
        if f"{o.scheme}://{o.netloc}" not in trusted:
            raise PermissionDenied("Cross-site request blocked")

    def _parse_body(self, route, req: Request) -> None:
        if len(req.raw_body) > (route.spec.max_body or self.cfg.max_body_bytes):
            raise PayloadTooLarge()
        if not req.raw_body:
            req.body = {}
            return
        if "application/json" not in req.header("content-type"):
            raise UnsupportedMediaType()
        try:
            data = json.loads(req.raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValidationError("Malformed JSON body")
        if not isinstance(data, dict):
            raise ValidationError("Request body must be a JSON object")
        req.body = data

    def _authorize(self, route, req: Request) -> None:
        spec, user = route.spec, req.user
        if spec.audience == "public":
            return
        if user is None:
            raise AuthenticationError()
        if user.restricted and not spec.allow_restricted:
            raise PermissionDenied("Finish the required security step first (change your password or set up 2FA)")
        if spec.audience == "guest" and not user.is_guest:
            raise PermissionDenied("This area is for hotel guests")
        if spec.audience == "staff" and user.is_guest:
            raise PermissionDenied()
        if spec.perm and not user.can(spec.perm):
            raise PermissionDenied()
        if req.method in STATE_CHANGING and spec.csrf:
            sent = req.header("x-csrf-token")
            if not req.session or not sent or sent != req.session["csrf_token"]:
                raise PermissionDenied("Security token missing or invalid. Reload the page and try again.")

    def _rate_limit(self, route, req: Request) -> None:
        lim = self.app.limiter
        lim.check(f"api:{req.ip}", self.cfg.api_limit_per_minute)
        bucket = route.spec.limit
        if bucket == "login":
            lim.check(f"login:{req.ip}", self.cfg.login_ip_limit_per_minute,
                      message="Too many sign-in attempts from your network. Wait a minute and try again.")
        elif bucket == "reset":
            lim.check(f"reset:{req.ip}", 5, 900, message="Too many requests. Try again later.")
        elif bucket == "register":
            lim.check(f"register:{req.ip}", 5, 3600, message="Too many registrations from your network. Try later.")
        elif route.spec.audience == "public" and bucket != "none":
            lim.check(f"public:{req.ip}", self.cfg.public_limit_per_minute)

    # ------------------------------------------------------------ main entry
    def handle(self, req: Request) -> Response:
        try:
            route, params = self.app.router.match(req.method, req.path)
            self._rate_limit(route, req)
            self._parse_body(route, req)
            if req.method in STATE_CHANGING:
                self._check_origin(req)
            req.session_token = self._read_cookie(req)
            with self.app.db.unit_of_work(write=req.method in STATE_CHANGING) as conn:
                req.ctx = ServiceContext(conn, None, req.ip, self.app)
                principal, session = req.ctx.service(AuthService).resolve_session(req.session_token)
                req.ctx.actor, req.session = principal, session
                self._authorize(route, req)
                result = route.invoke(req, params)
            return self._to_response(result, req)
        except AppError as e:
            resp = Response.json(e.to_dict(), e.status)
            if isinstance(e, AuthenticationError) and req.session_token:
                resp.set_cookie(self._cookie("", 0))
            return resp
        except sqlite3.IntegrityError as e:
            log.warning("Integrity error on %s %s: %s", req.method, req.path, e)
            return Response.json({"error": "The change conflicts with existing data"}, 409)
        except Exception:  # pragma: no cover
            log.error("Unhandled error on %s %s\n%s", req.method, req.path, traceback.format_exc())
            return Response.json({"error": "Internal server error"}, 500)

    def _read_cookie(self, req: Request):
        for part in req.header("cookie").split(";"):
            name, _, value = part.strip().partition("=")
            if name == self.cookie_name and value:
                return value
        return None

    def _to_response(self, result, req: Request) -> Response:
        if isinstance(result, (Download, Binary)):
            return result.to_response()
        if isinstance(result, SessionCookie):
            resp = Response.json(result.data)
            resp.set_cookie(self._cookie("", 0) if result.clear else self._cookie(result.token, result.max_age))
            return resp
        status = 201 if req.method == "POST" and isinstance(result, dict) and result.get("_created") else 200
        if isinstance(result, dict):
            result.pop("_created", None)
        return Response.json(result if result is not None else {"ok": True}, status)
