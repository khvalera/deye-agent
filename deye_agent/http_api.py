import json
import os
import socketserver
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from .web_auth import WebAuthManager


API_ERROR_SCHEMA = "deye-agent.api-error.v1"
WEB_ROOT = os.path.join(
    os.path.dirname(__file__),
    "web"
)

PUBLIC_WEB_ASSETS = {
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/login.js": (
        "login.js",
        "application/javascript; charset=utf-8"
    ),
    "/i18n/en.json": (
        os.path.join("i18n", "en.json"),
        "application/json; charset=utf-8"
    ),
    "/i18n/uk.json": (
        os.path.join("i18n", "uk.json"),
        "application/json; charset=utf-8"
    ),
    "/i18n/pl.json": (
        os.path.join("i18n", "pl.json"),
        "application/json; charset=utf-8"
    ),
    "/i18n/de.json": (
        os.path.join("i18n", "de.json"),
        "application/json; charset=utf-8"
    ),
}

PROTECTED_WEB_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": (
        "app.js",
        "application/javascript; charset=utf-8"
    ),
}


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Python 3.6 compatible threaded HTTPServer."""

    daemon_threads = True
    allow_reuse_address = True


class _APIRequestHandler(BaseHTTPRequestHandler):
    server_version = "DeyeAgentHTTP/1"

    def log_message(self, fmt, *args):
        if getattr(self.server, "debug", False):
            print("HTTP API: " + (fmt % args))

    def _send_bytes(
            self,
            status_code,
            payload,
            content_type,
            extra_headers=None):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")

        for name, value in extra_headers or []:
            self.send_header(name, value)

        self.end_headers()
        self.wfile.write(payload)

    def _send_json(
            self,
            status_code,
            document,
            extra_headers=None):
        payload = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=False,
            separators=(",", ":")
        ).encode("utf-8")

        self._send_bytes(
            status_code,
            payload,
            "application/json; charset=utf-8",
            extra_headers=extra_headers
        )

    def _redirect(
            self,
            location,
            cookie_header=None):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")

        if cookie_header:
            self.send_header(
                "Set-Cookie",
                cookie_header
            )

        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_web_asset(
            self,
            relative_path,
            content_type):
        full_path = os.path.join(
            WEB_ROOT,
            relative_path
        )

        try:
            with open(full_path, "rb") as handle:
                payload = handle.read()
        except OSError:
            self._send_json(
                404,
                self._error_document(
                    404,
                    "not_found",
                    "Web asset is not available"
                )
            )
            return

        self._send_bytes(
            200,
            payload,
            content_type
        )

    def _error_document(
            self,
            status_code,
            error,
            message):
        return {
            "schema": API_ERROR_SCHEMA,
            "schema_version": 1,
            "read_only": True,
            "status_code": status_code,
            "error": error,
            "message": message,
        }

    def _session_token(self):
        raw_cookie = self.headers.get("Cookie")

        if not raw_cookie:
            return None

        cookie = SimpleCookie()

        try:
            cookie.load(raw_cookie)
        except Exception:
            return None

        morsel = cookie.get("deye_session")

        if morsel is None:
            return None

        return morsel.value

    def _is_authenticated(self):
        auth = getattr(
            self.server,
            "auth_manager",
            None
        )

        if auth is None:
            return True

        return auth.is_session_valid(
            self._session_token()
        )

    def _require_api_auth(self):
        if self._is_authenticated():
            return True

        self._send_json(
            401,
            self._error_document(
                401,
                "authentication_required",
                "Authentication is required"
            )
        )
        return False

    def _read_form(self):
        try:
            content_length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )
        except (TypeError, ValueError):
            return None

        if content_length < 1 or content_length > 8192:
            return None

        content_type = self.headers.get(
            "Content-Type",
            ""
        )

        if not content_type.startswith(
                "application/x-www-form-urlencoded"):
            return None

        try:
            body = self.rfile.read(
                content_length
            ).decode("utf-8")
        except (UnicodeError, OSError):
            return None

        return parse_qs(
            body,
            keep_blank_values=True
        )

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        state = self.server.runtime_state
        auth = getattr(
            self.server,
            "auth_manager",
            None
        )

        asset = PUBLIC_WEB_ASSETS.get(path)

        if asset is not None:
            self._send_web_asset(
                asset[0],
                asset[1]
            )
            return

        if path == "/login":
            if auth is None:
                self._redirect("/")
                return

            if self._is_authenticated():
                self._redirect("/")
                return

            self._send_web_asset(
                "login.html",
                "text/html; charset=utf-8"
            )
            return

        asset = PROTECTED_WEB_ASSETS.get(path)

        if asset is not None:
            if not self._is_authenticated():
                self._redirect("/login")
                return

            self._send_web_asset(
                asset[0],
                asset[1]
            )
            return

        if path.startswith("/api/v1/"):
            if not self._require_api_auth():
                return

        if path == "/api/v1/health":
            self._send_json(
                200,
                state.get_health()
            )
            return

        if path == "/api/v1/overview":
            document = state.get_overview()

            if document is None:
                self._send_json(
                    503,
                    self._error_document(
                        503,
                        "not_ready",
                        "Overview is not available before the first cycle"
                    )
                )
                return

            self._send_json(200, document)
            return

        if path == "/api/v1/history":
            query = parse_qs(
                parsed.query,
                keep_blank_values=True
            )
            raw_minutes = query.get(
                "minutes",
                ["60"]
            )[0]

            try:
                minutes = int(
                    raw_minutes
                )
            except (TypeError, ValueError):
                self._send_json(
                    400,
                    self._error_document(
                        400,
                        "invalid_minutes",
                        "minutes must be an integer"
                    )
                )
                return

            if minutes < 1 or minutes > 1440:
                self._send_json(
                    400,
                    self._error_document(
                        400,
                        "invalid_minutes",
                        "minutes must be between 1 and 1440"
                    )
                )
                return

            self._send_json(
                200,
                state.get_history(
                    minutes=minutes
                )
            )
            return

        if path == "/api/v1/metrics":
            document = state.get_metrics()

            if document is None:
                self._send_json(
                    503,
                    self._error_document(
                        503,
                        "not_ready",
                        "Metrics are not available before the first cycle"
                    )
                )
                return

            self._send_json(200, document)
            return

        if path == "/api/v1/snapshot":
            document = state.get_snapshot()

            if document is None:
                self._send_json(
                    503,
                    self._error_document(
                        503,
                        "not_ready",
                        "Snapshot is not available before the first cycle"
                    )
                )
                return

            self._send_json(200, document)
            return

        self._send_json(
            404,
            self._error_document(
                404,
                "not_found",
                "Unknown API endpoint"
            )
        )

    def do_POST(self):
        path = urlsplit(self.path).path
        auth = getattr(
            self.server,
            "auth_manager",
            None
        )

        if path == "/login":
            if auth is None:
                self._redirect("/")
                return

            form = self._read_form()

            if form is None:
                self._send_json(
                    400,
                    self._error_document(
                        400,
                        "invalid_form",
                        "Invalid login form"
                    )
                )
                return

            username = form.get(
                "username",
                [""]
            )[0]
            password = form.get(
                "password",
                [""]
            )[0]

            if not auth.authenticate(
                    username,
                    password):
                # A small fixed delay reduces trivial high-rate guessing
                # without affecting the polling/runtime thread.
                time.sleep(0.25)
                self._redirect(
                    "/login?error=1"
                )
                return

            token = auth.create_session()

            self._redirect(
                "/",
                cookie_header=auth.cookie_header(
                    token
                )
            )
            return

        if path == "/logout":
            if auth is None:
                self._redirect("/")
                return

            auth.destroy_session(
                self._session_token()
            )

            self._redirect(
                "/login",
                cookie_header=(
                    auth.clear_cookie_header()
                )
            )
            return

        self._method_not_allowed()

    def _method_not_allowed(self):
        self._send_json(
            405,
            self._error_document(
                405,
                "method_not_allowed",
                "This endpoint does not support this HTTP method"
            )
        )

    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed


class HTTPAPIHandle:
    """Own the HTTP server and background thread lifecycle."""

    def __init__(
            self,
            server,
            thread):
        self.server = server
        self.thread = thread

    @property
    def address(self):
        return self.server.server_address

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(
            timeout=2.0
        )


def start_http_api(
        runtime_state,
        host="127.0.0.1",
        port=8765,
        debug=False,
        auth_username=None,
        auth_password_hash=None,
        auth_session_seconds=43200,
        auth_cookie_secure=False):
    """Start the cached HTTP API with mandatory session authentication."""
    if runtime_state is None:
        raise ValueError(
            "runtime_state is required"
        )

    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ValueError(
            "HTTP API port must be an integer"
        )

    if port < 0 or port > 65535:
        raise ValueError(
            "HTTP API port must be between 0 and 65535"
        )

    # Fail closed: starting the HTTP API always requires credentials.
    auth_manager = WebAuthManager(
        username=auth_username,
        password_hash=auth_password_hash,
        session_seconds=(
            auth_session_seconds
        ),
        cookie_secure=(
            auth_cookie_secure
        )
    )

    server = _ThreadingHTTPServer(
        (host, port),
        _APIRequestHandler
    )
    server.runtime_state = runtime_state
    server.auth_manager = auth_manager
    server.debug = bool(debug)

    thread = threading.Thread(
        target=server.serve_forever,
        name="deye-agent-http-api"
    )
    thread.daemon = True
    thread.start()

    return HTTPAPIHandle(
        server,
        thread
    )
