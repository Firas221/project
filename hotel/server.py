"""HTTP server: serves the JSON API and the single-page web GUI."""
import json
import logging
import mimetypes
import os
import sqlite3
import traceback
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from . import api
from .db import connect, init_db

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
MAX_BODY = 1_000_000
log = logging.getLogger("hotel")


class Handler(BaseHTTPRequestHandler):
    server_version = "HotelPMS/1.0"
    db_path = None  # set by make_server

    # ------------------------------------------------------------------ plumbing
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")

    def _send(self, status, body: bytes, content_type, extra_headers=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        for k, v in extra_headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, data, extra_headers=()):
        body = json.dumps(data, default=str).encode()
        self._send(status, body, "application/json; charset=utf-8",
                   list(extra_headers) + [("Cache-Control", "no-store")])

    def _dispatch(self, method):
        url = urlsplit(self.path)
        if url.path.startswith("/api/"):
            self._api(method, url)
        elif method == "GET":
            self._static(url.path)
        else:
            self._json(405, {"error": "Method not allowed"})

    # ------------------------------------------------------------------ static files
    def _static(self, path):
        path = unquote(path)
        if path in ("", "/") or not os.path.splitext(path)[1]:
            path = "/index.html"
        full = os.path.realpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not full.startswith(os.path.realpath(STATIC_DIR) + os.sep) or not os.path.isfile(full):
            self._send(404, b"Not found", "text/plain")
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype, [("Cache-Control", "no-cache")])

    # ------------------------------------------------------------------ API
    def _api(self, method, url):
        extra = []
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise api.ApiError(413, "Request body too large")
            body = {}
            if length:
                if "application/json" not in (self.headers.get("Content-Type") or ""):
                    raise api.ApiError(415, "Content-Type must be application/json")
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except (ValueError, UnicodeDecodeError):
                    raise api.ApiError(400, "Invalid JSON body")
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            fn, role, needs_auth, params = api.find_route(method, url.path)
        except api.ApiError as e:
            self._json(e.status, {"error": e.message})
            return

        jar = cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie") or "")
        except cookies.CookieError:
            pass
        token = jar["session"].value if "session" in jar else None

        db = connect(self.db_path)
        try:
            user = api.user_from_token(db, token)
            if needs_auth and not user:
                raise api.ApiError(401, "Please sign in")
            if role and (not user or user["role"] != role):
                raise api.ApiError(403, "You do not have permission to do this")
            ctx = api.Ctx(db, user, body, query, params)
            ctx.token = token
            if method != "GET":
                db.execute("BEGIN IMMEDIATE")
            result = fn(ctx)
            if db.in_transaction:
                db.execute("COMMIT")
            extra = [("Set-Cookie", c) for c in ctx.cookies]
            if isinstance(result, api.Raw):
                headers = [("Cache-Control", "no-store")]
                if result.filename:
                    headers.append(("Content-Disposition", f'attachment; filename="{result.filename}"'))
                self._send(200, result.body.encode("utf-8-sig"), result.content_type, headers)
            else:
                self._json(201 if method == "POST" and fn.__name__.endswith("_create") else 200, result, extra)
        except api.ApiError as e:
            if db.in_transaction:
                db.execute("ROLLBACK")
            self._json(e.status, {"error": e.message}, extra)
        except sqlite3.IntegrityError as e:
            if db.in_transaction:
                db.execute("ROLLBACK")
            self._json(409, {"error": f"Data conflict: {e}"})
        except Exception:  # pragma: no cover - unexpected failures
            if db.in_transaction:
                db.execute("ROLLBACK")
            log.error("Unhandled error on %s %s\n%s", method, url.path, traceback.format_exc())
            self._json(500, {"error": "Internal server error"})
        finally:
            db.close()


def make_server(db_path, host="127.0.0.1", port=8000, seed=True):
    init_db(db_path, seed=seed)
    handler = type("BoundHandler", (Handler,), {"db_path": db_path})
    return ThreadingHTTPServer((host, port), handler)
