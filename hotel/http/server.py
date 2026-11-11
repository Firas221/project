"""HTTP transport: turns raw HTTP into :class:`Request` objects, serves the web portals, adds security headers."""
import logging
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from .messages import Request, Response

log = logging.getLogger("hotel.http")
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static")

# Friendly URLs for each portal
PAGES = {
    "/": "index.html",
    "/login": "login.html",
    "/admin": "admin.html",
    "/staff": "staff.html",
    "/kitchen": "kitchen.html",
    "/housekeeping": "housekeeping.html",
    "/account": "account.html",
    "/privacy": "privacy.html",
}

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; object-src 'none'; "
       "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "HotelPMS"
    sys_version = ""
    app = None  # injected by HotelApp.make_server

    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def log_message(self, fmt, *args):
        log.info("%s %s", self._client_ip(), fmt % args)

    def _client_ip(self) -> str:
        if self.app and self.app.config.trust_proxy:
            fwd = self.headers.get("X-Forwarded-For", "")
            if fwd:
                return fwd.split(",")[0].strip()[:64]
        return self.client_address[0]

    def _handle(self, method: str):
        url = urlsplit(self.path)
        if url.path.startswith("/api/"):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > self.app.router.body_limit(method, url.path, self.app.config.max_body_bytes):
                self._send(Response.json({"error": "Request body too large"}, 413), api=True)
                return
            req = Request(method=method, path=url.path, query={k: v[0] for k, v in parse_qs(url.query).items()},
                          headers={k.lower(): v for k, v in self.headers.items()},
                          raw_body=self.rfile.read(length) if length else b"", ip=self._client_ip())
            self._send(self.app.dispatcher.handle(req), api=True)
        elif method == "GET":
            self._send(self._static(url.path), api=False)
        else:
            self._send(Response.json({"error": "Method not allowed"}, 405), api=True)

    def _static(self, path: str) -> Response:
        path = unquote(path)
        rel = PAGES.get(path.rstrip("/") or "/") or path.lstrip("/")
        root = os.path.realpath(STATIC_DIR)
        full = os.path.realpath(os.path.join(root, rel))
        if not full.startswith(root + os.sep) or not os.path.isfile(full) or os.path.basename(full).startswith("."):
            full = os.path.join(root, "404.html")
            status = 404
        else:
            status = 200
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            resp = Response(status, f.read(), ctype)
        resp.headers.append(("Cache-Control", "no-cache"))
        return resp

    def _send(self, resp: Response, api: bool):
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", CSP)
        if self.app.config.secure_cookies or self.app.config.tls_cert:
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if api and not any(k.lower() == "cache-control" for k, _ in resp.headers):
            self.send_header("Cache-Control", "no-store")
        for k, v in resp.headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(resp.body)


class HotelHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64
