"""
Application-level authentication for AiKore.

Static token authentication driven by environment variables:

- AIKORE_API_KEY set (non-empty)  -> auth ENABLED, every non-public path
  requires the key (fail-closed).
- AIKORE_API_KEY absent or empty  -> auth DISABLED, with a loud warning at
  startup (preserves the historical open behaviour for local/LAN setups).

Credential extraction:
- HTTP       : "Authorization: Bearer <key>" OR "X-API-Key: <key>" header.
- WebSocket  : same headers (not settable from browsers), so additionally the
               client may offer the WebSocket subprotocols
               ['aikore-auth', '<key>']. The server then answers with the
               'aikore-auth' subprotocol and NEVER echoes the raw key back.

Additional hardening:
- WebSocket Origin validation: if an Origin header is present and its host
  differs from the request Host / X-Forwarded-Host headers (and from the extra
  origins listed in AIKORE_WS_ALLOWED_ORIGINS), the handshake is refused
  BEFORE accept().
- CORS preflight: HTTP OPTIONS requests are passed through unverified, ready
  for a future CORS layer.

This module is a PURE ASGI middleware (deliberately NOT BaseHTTPMiddleware,
which drops/breaks 'websocket' scopes): it handles both 'http' and 'websocket'
scope types and rejects unauthenticated WebSocket handshakes before the
endpoint's accept() is ever reached.

Only the standard library is used here so the module can be unit-tested
without FastAPI/Starlette installed.
"""

import os
from secrets import compare_digest
from urllib.parse import urlsplit

# --- Module state (populated by init_auth_config()) --------------------------

AUTH_ENABLED = False
API_KEY = ""

# Public (unauthenticated) paths: exact matches and path prefixes.
_DEFAULT_PUBLIC_EXACT = ("/", "/favicon.ico")
_DEFAULT_PUBLIC_PREFIXES = ("/static/",)

# Extra WebSocket origins allowed by the operator (comma-separated env var).
WS_ALLOWED_ORIGINS = ()

_MIN_KEY_LENGTH = 24
_API_KEY_ENV = "AIKORE_API_KEY"
_PUBLIC_PATHS_ENV = "AIKORE_AUTH_PUBLIC_PATHS"
_WS_ORIGINS_ENV = "AIKORE_WS_ALLOWED_ORIGINS"
_WS_AUTH_PROTOCOL = "aikore-auth"

# Default ports stripped when comparing authorities (Origin vs Host header).
_DEFAULT_PORTS = {"http": "80", "https": "443", "ws": "80", "wss": "443"}


def _parse_csv(value: str) -> tuple:
    """Split a comma-separated env value into a tuple of non-empty strings."""
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


class _PublicPathMatcher:
    """Matches request paths that bypass authentication.

    Defaults: '/', '/favicon.ico' and the '/static/' prefix. Extra entries come
    from AIKORE_AUTH_PUBLIC_PATHS (comma-separated); an entry ending with '*'
    is treated as a prefix, anything else as an exact path.
    """

    def __init__(self, extra_csv: str = ""):
        exact = set(_DEFAULT_PUBLIC_EXACT)
        prefixes = list(_DEFAULT_PUBLIC_PREFIXES)
        for entry in _parse_csv(extra_csv):
            if not entry.startswith("/"):
                print(
                    f"[Startup] [WARNING] {_PUBLIC_PATHS_ENV}: entry '{entry}' does not "
                    "start with '/' - entry ignored."
                )
                continue
            if entry.endswith("*"):
                prefixes.append(entry[:-1])
            else:
                exact.add(entry.rstrip("/") or "/")
        self._exact = exact
        self._prefixes = tuple(p for p in prefixes if p)

    def is_public(self, path: str) -> bool:
        if path in self._exact:
            return True
        trimmed = path.rstrip("/") or "/"
        if trimmed in self._exact:
            return True
        return any(path.startswith(prefix) for prefix in self._prefixes)


# Populated by init_auth_config(); safe defaults until then.
_PUBLIC_PATHS = _PublicPathMatcher()

# Set to True by init_auth_config(); makes it idempotent (safe to call from
# both module import time and the lifespan handler without duplicate work).
_initialized = False


def init_auth_config(force: bool = False) -> None:
    """Read and validate auth-related environment variables.

    Idempotent: repeated calls are no-ops unless ``force=True`` (used to
    re-read the environment, e.g. in tests). Called at import time by
    aikore.main AND in its lifespan, so the configuration is active even for
    launches without a lifespan (uvicorn --lifespan off). Must run early,
    before serving requests. Logs follow the project's '[Startup]' convention.
    """
    global AUTH_ENABLED, API_KEY, _PUBLIC_PATHS, WS_ALLOWED_ORIGINS, _initialized

    if _initialized and not force:
        return
    _initialized = True

    raw = os.environ.get(_API_KEY_ENV)
    raw = raw.strip() if raw else ""

    if not raw:
        AUTH_ENABLED = False
        API_KEY = ""
        print(
            "[Startup] [WARNING] AIKORE_API_KEY is not set - API authentication is DISABLED. "
            "All endpoints (instances, terminals, builder) are exposed unauthenticated. "
            "Set AIKORE_API_KEY to enable auth (see docs/AUTH.md)."
        )
    else:
        API_KEY = raw
        AUTH_ENABLED = True
        if len(raw) < _MIN_KEY_LENGTH:
            print(
                f"[Startup] [WARNING] AIKORE_API_KEY is shorter than {_MIN_KEY_LENGTH} characters - "
                "generate a strong key with: openssl rand -hex 32"
            )
        print(
            "[Startup] Authentication ENABLED "
            "(Authorization: Bearer / X-API-Key headers, WS subprotocol 'aikore-auth')."
        )

    _PUBLIC_PATHS = _PublicPathMatcher(os.environ.get(_PUBLIC_PATHS_ENV, ""))
    WS_ALLOWED_ORIGINS = _parse_csv(os.environ.get(_WS_ORIGINS_ENV, ""))


def get_auth_status() -> dict:
    """Small introspection helper (for logs/diagnostics only)."""
    return {
        "auth_enabled": AUTH_ENABLED,
        "public_paths_env": _PUBLIC_PATHS_ENV,
        "ws_allowed_origins": WS_ALLOWED_ORIGINS,
    }


# --- Low-level ASGI helpers ---------------------------------------------------


def _get_header(scope: dict, name: str) -> str:
    """Return the first header value matching `name` (case-insensitive), or ''."""
    lower = name.lower().encode("latin-1")
    for key, value in scope.get("headers") or ():
        if key == lower:
            return value.decode("latin-1", errors="replace")
    return ""


def _safe_equals(presented: str, expected: str) -> bool:
    """Constant-time string comparison, tolerant of exotic unicode."""
    try:
        return compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))
    except UnicodeEncodeError:
        return False


def _iter_credentials(scope: dict):
    """Yield every credential presented on the request/handshake."""
    authz = _get_header(scope, "authorization")
    if authz:
        parts = authz.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
            if token:
                yield token
    api_key = _get_header(scope, "x-api-key")
    if api_key and api_key.strip():
        yield api_key.strip()
    # WebSocket only: subprotocols offered by the client (e.g. by xterm.js,
    # which cannot set custom headers). Never echoed back to the client.
    if scope.get("type") == "websocket":
        for protocol in scope.get("subprotocols") or ():
            if protocol:
                yield protocol


def _credentials_valid(scope: dict) -> bool:
    """Fail-closed credential check: True only if auth is disabled or a
    presented credential matches the configured key."""
    if not AUTH_ENABLED:
        return True
    if not API_KEY:
        return False
    for presented in _iter_credentials(scope):
        if _safe_equals(presented, API_KEY):
            return True
    return False


# --- WebSocket Origin validation ----------------------------------------------


def _split_origin(origin: str):
    """Return the normalized authority (host[:port], default port stripped)
    of an Origin value such as 'https://example.com:443'. (None, None) if
    the value cannot be parsed."""
    try:
        parts = urlsplit(origin.strip())
    except ValueError:
        return None
    scheme = (parts.scheme or "").lower()
    authority = parts.netloc.lower()
    if not authority:
        return None
    default_port = _DEFAULT_PORTS.get(scheme)
    if default_port and authority.endswith(":" + default_port):
        authority = authority[: -(len(default_port) + 1)]
    return authority


def _normalize_authority(value: str, scheme: str = "") -> str:
    """Normalize a Host header / bare authority (lowercase, default port
    stripped for the given scheme)."""
    authority = (value or "").strip().lower()
    if "://" in authority:
        authority = authority.split("://", 1)[1]
    if "/" in authority:
        authority = authority.split("/", 1)[0]
    default_port = _DEFAULT_PORTS.get((scheme or "").lower())
    if default_port and authority.endswith(":" + default_port):
        authority = authority[: -(len(default_port) + 1)]
    return authority


def _ws_origin_allowed(origin: str, host_headers, scheme: str) -> bool:
    """True if the WS Origin is same-host as the request or explicitly allowed.

    ``host_headers`` holds the request's Host and/or X-Forwarded-Host values:
    some reverse proxies do not preserve the Host header but set
    X-Forwarded-Host instead, so a match on either identifies a legitimate
    same-deployment origin. A str is accepted for convenience.
    """
    origin_authority = _split_origin(origin)
    if origin_authority is None:
        return False  # malformed Origin -> fail closed
    if isinstance(host_headers, str):
        host_headers = (host_headers,)
    for host_value in host_headers:
        # X-Forwarded-Host may carry a proxy chain ("internal, public");
        # consider every comma-separated element.
        for candidate in (host_value or "").split(","):
            request_authority = _normalize_authority(candidate, scheme)
            if request_authority and origin_authority == request_authority:
                return True
    for allowed in WS_ALLOWED_ORIGINS:
        allowed_authority = _split_origin(allowed) or _normalize_authority(allowed)
        if allowed_authority and allowed_authority == origin_authority:
            return True
    return False


# --- Response helpers ----------------------------------------------------------


async def _send_401(send) -> None:
    """Send a plain ASGI 401 JSON response with a Bearer challenge."""
    body = b'{"detail":"Invalid or missing API key"}'
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"www-authenticate", b"Bearer"),
    ]
    await send({"type": "http.response.start", "status": 401, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _reject_websocket(send, code: int = 1008) -> None:
    """Reject a WebSocket handshake BEFORE any accept() is sent.

    Per the ASGI spec, sending 'websocket.close' while still in the CONNECTING
    state makes the server complete the HTTP handshake with a rejection
    (403) instead of upgrading the connection.
    """
    await send({"type": "websocket.close", "code": code, "reason": "Unauthorized"})


# --- Middleware -----------------------------------------------------------------


class AuthMiddleware:
    """Pure ASGI middleware enforcing the static API key on http AND websocket
    scopes. Must be added last (outermost) so it runs before everything else.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope_type = scope.get("type")
        if scope_type == "http":
            await self._handle_http(scope, receive, send)
        elif scope_type == "websocket":
            await self._handle_websocket(scope, receive, send)
        else:  # 'lifespan' and anything else: pass through untouched
            await self.app(scope, receive, send)

    async def _handle_http(self, scope, receive, send) -> None:
        # CORS preflight (OPTIONS) carries no credentials by design: pass it
        # through unconditionally so a future CORS layer can answer it.
        if (scope.get("method") or "GET").upper() == "OPTIONS":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "/")
        if _PUBLIC_PATHS.is_public(path) or _credentials_valid(scope):
            await self.app(scope, receive, send)
        else:
            await _send_401(send)

    async def _handle_websocket(self, scope, receive, send) -> None:
        path = scope.get("path", "/")

        # 1. Origin validation (CSRF hardening) - applies even when auth is
        #    disabled, so anonymous installs keep drive-by protection. Behind
        #    a proxy that does not preserve Host, X-Forwarded-Host carries the
        #    public host: accept a match on either header.
        origin = _get_header(scope, "origin")
        if origin:
            host_candidates = [
                h
                for h in (_get_header(scope, "host"), _get_header(scope, "x-forwarded-host"))
                if h
            ]
            if not _ws_origin_allowed(origin, host_candidates, scope.get("scheme", "ws")):
                print(f"[AUTH] Blocked cross-origin WS handshake to {path} (Origin: {origin})")
                await _reject_websocket(send)
                return

        # 2. Credential check (fail-closed when auth is enabled).
        if not _credentials_valid(scope):
            print(f"[AUTH] Blocked unauthenticated WS handshake to {path}")
            await _reject_websocket(send)
            return

        # 3. Pass through. If the client offered our auth subprotocol, make sure
        #    the accept() answer selects 'aikore-auth' (never the raw key),
        #    regardless of how the endpoint calls websocket.accept().
        if _WS_AUTH_PROTOCOL in (scope.get("subprotocols") or ()):
            outer_send = send

            async def send_wrapper(message):
                if message["type"] == "websocket.accept" and not message.get("subprotocol"):
                    message = dict(message)
                    message["subprotocol"] = _WS_AUTH_PROTOCOL
                await outer_send(message)

            await self.app(scope, receive, send_wrapper)
        else:
            await self.app(scope, receive, send)
