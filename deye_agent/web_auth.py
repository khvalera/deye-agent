import base64
import hashlib
import hmac
import secrets
import threading
import time


PASSWORD_SCHEME = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 200000
MIN_ITERATIONS = 10000
MAX_ITERATIONS = 1000000


def _b64encode(value):
    return (
        base64.urlsafe_b64encode(value)
        .decode("ascii")
        .rstrip("=")
    )


def _b64decode(value):
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(
        (value + padding).encode("ascii")
    )


def hash_password(password, iterations=DEFAULT_ITERATIONS):
    """Create a salted PBKDF2-SHA256 password hash."""
    if not isinstance(password, str):
        raise TypeError("password must be a string")

    if not password:
        raise ValueError("password must not be empty")

    try:
        iterations = int(iterations)
    except (TypeError, ValueError):
        raise ValueError("iterations must be an integer")

    if iterations < MIN_ITERATIONS or iterations > MAX_ITERATIONS:
        raise ValueError(
            "iterations must be between {} and {}".format(
                MIN_ITERATIONS,
                MAX_ITERATIONS
            )
        )

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations
    )

    return "{}${}${}${}".format(
        PASSWORD_SCHEME,
        iterations,
        _b64encode(salt),
        _b64encode(digest)
    )


def verify_password(password, encoded_hash):
    """Verify a password against a PBKDF2-SHA256 hash."""
    if not isinstance(password, str):
        return False

    if not isinstance(encoded_hash, str):
        return False

    try:
        scheme, iterations_text, salt_text, digest_text = (
            encoded_hash.split("$", 3)
        )

        if scheme != PASSWORD_SCHEME:
            return False

        iterations = int(iterations_text)

        if (
                iterations < MIN_ITERATIONS
                or iterations > MAX_ITERATIONS):
            return False

        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)

        if len(salt) < 8 or len(expected) != 32:
            return False

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations
        )

        return hmac.compare_digest(
            actual,
            expected
        )

    except (TypeError, ValueError, UnicodeError):
        return False


class WebAuthManager:
    """Thread-safe in-memory session authentication manager."""

    def __init__(
            self,
            username,
            password_hash,
            session_seconds=43200,
            cookie_secure=False):
        username = str(username or "").strip()
        password_hash = str(password_hash or "").strip()

        if not username:
            raise ValueError(
                "HTTP_AUTH_USERNAME must not be empty"
            )

        if not password_hash:
            raise ValueError(
                "HTTP_AUTH_PASSWORD_HASH must not be empty"
            )

        # Validate format without needing the real password.
        parts = password_hash.split("$", 3)

        if len(parts) != 4 or parts[0] != PASSWORD_SCHEME:
            raise ValueError(
                "HTTP_AUTH_PASSWORD_HASH has an unsupported format"
            )

        try:
            iterations = int(parts[1])
        except (TypeError, ValueError):
            raise ValueError(
                "HTTP_AUTH_PASSWORD_HASH has invalid iterations"
            )

        if iterations < MIN_ITERATIONS or iterations > MAX_ITERATIONS:
            raise ValueError(
                "HTTP_AUTH_PASSWORD_HASH iterations are out of range"
            )

        try:
            salt = _b64decode(parts[2])
            digest = _b64decode(parts[3])
        except Exception:
            raise ValueError(
                "HTTP_AUTH_PASSWORD_HASH has invalid base64 data"
            )

        if len(salt) < 8 or len(digest) != 32:
            raise ValueError(
                "HTTP_AUTH_PASSWORD_HASH has invalid hash data"
            )

        try:
            session_seconds = int(session_seconds)
        except (TypeError, ValueError):
            raise ValueError(
                "HTTP_AUTH_SESSION_SECONDS must be an integer"
            )

        if session_seconds < 60 or session_seconds > 604800:
            raise ValueError(
                "HTTP_AUTH_SESSION_SECONDS must be between 60 and 604800"
            )

        self.username = username
        self.password_hash = password_hash
        self.session_seconds = session_seconds
        self.cookie_secure = bool(cookie_secure)

        self._lock = threading.RLock()
        self._sessions = {}

    def authenticate(self, username, password):
        """Check username and password without creating a session."""
        username_ok = hmac.compare_digest(
            str(username or ""),
            self.username
        )

        # Always verify the password hash even when the username is wrong,
        # keeping failed-login timing less dependent on which field failed.
        password_ok = verify_password(
            str(password or ""),
            self.password_hash
        )

        return username_ok and password_ok

    def _purge_expired_locked(self, now):
        expired = [
            token
            for token, expires_at in self._sessions.items()
            if expires_at <= now
        ]

        for token in expired:
            self._sessions.pop(token, None)

    def create_session(self):
        """Create a cryptographically random absolute-expiry session."""
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        expires_at = now + self.session_seconds

        with self._lock:
            self._purge_expired_locked(now)
            self._sessions[token] = expires_at

        return token

    def is_session_valid(self, token):
        if not token:
            return False

        now = time.monotonic()

        with self._lock:
            self._purge_expired_locked(now)
            expires_at = self._sessions.get(token)

            if expires_at is None:
                return False

            return expires_at > now

    def destroy_session(self, token):
        if not token:
            return

        with self._lock:
            self._sessions.pop(token, None)

    def cookie_header(self, token):
        parts = [
            "deye_session={}".format(token),
            "Path=/",
            "HttpOnly",
            "SameSite=Strict",
            "Max-Age={}".format(self.session_seconds),
        ]

        if self.cookie_secure:
            parts.append("Secure")

        return "; ".join(parts)

    def clear_cookie_header(self):
        parts = [
            "deye_session=",
            "Path=/",
            "HttpOnly",
            "SameSite=Strict",
            "Max-Age=0",
        ]

        if self.cookie_secure:
            parts.append("Secure")

        return "; ".join(parts)
