"""
tests/test_auth.py — AUTH coverage for aikore/core/auth.py.

Covers the pure-ASGI AuthMiddleware:
  * disabled without AIKORE_API_KEY (pass-through)
  * enabled -> 401 without credential, pass with Bearer / X-API-Key,
    401 on wrong key
  * public paths / /favicon.ico /static/* + AIKORE_AUTH_PUBLIC_PATHS
  * WS Origin same-origin with non-default port PASSED, cross-origin blocked,
    X-Forwarded-Host fallback, AIKORE_WS_ALLOWED_ORIGINS
  * subprotocol ['aikore-auth', key] without echoing the key
  * OPTIONS pass-through
  * symmetric stripping of default ports 80/443

Runnable standalone (``python3 tests/test_auth.py``) and pytest-compatible
(``test_*`` functions using asserts).
"""

import asyncio
import os
import sys

# Bootstrap: make the `tests` package importable when run standalone.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests._stubs import Suite, run_suite, load_aikore_module

auth = load_aikore_module("aikore.core.auth")

_suite = Suite("auth")


def check(cond, label):
    _suite.check(cond, label)


# --- ASGI test doubles ------------------------------------------------------

class _Recorder:
    def __init__(self):
        self.messages = []

    async def send(self, message):
        self.messages.append(message)


class _PassThroughApp:
    """Records calls; for websocket scopes it answers accept() so the
    middleware's subprotocol wrapper can be observed."""

    def __init__(self):
        self.calls = 0
        self.accepted_subprotocol = None

    async def __call__(self, scope, receive, send):
        self.calls += 1
        if scope.get("type") == "websocket":
            await send({"type": "websocket.accept", "subprotocol": None})


async def _run(mw, scope):
    recv = None

    async def receive():
        return {}

    recorder = _Recorder()
    await mw(scope, receive, recorder.send)
    return recorder.messages


def _http_scope(path="/api/instances", method="GET", headers=()):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers],
    }


def _ws_scope(path="/api/ws", headers=(), subprotocols=()):
    return {
        "type": "websocket",
        "path": path,
        "scheme": "ws",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers],
        "subprotocols": list(subprotocols),
    }


def _status(messages):
    for m in messages:
        if m.get("type") == "http.response.start":
            return m.get("status")
    return None


def _reset_env():
    for k in ("AIKORE_API_KEY", "AIKORE_AUTH_PUBLIC_PATHS", "AIKORE_WS_ALLOWED_ORIGINS"):
        os.environ.pop(k, None)


# --- Tests -------------------------------------------------------------------

def test_disabled_without_key_passes_through():
    _reset_env()
    auth.init_auth_config(force=True)
    check(auth.AUTH_ENABLED is False, "auth disabled without AIKORE_API_KEY")

    app = _PassThroughApp()
    mw = auth.AuthMiddleware(app)
    msgs = asyncio.run(_run(mw, _http_scope()))
    check(app.calls == 1, "http request passes through when auth disabled")
    check(_status(msgs) is None, "no 401 sent when auth disabled")


def test_enabled_401_without_credential():
    _reset_env()
    os.environ["AIKORE_API_KEY"] = "k" * 32
    auth.init_auth_config(force=True)
    check(auth.AUTH_ENABLED is True, "auth enabled with AIKORE_API_KEY")

    app = _PassThroughApp()
    mw = auth.AuthMiddleware(app)
    msgs = asyncio.run(_run(mw, _http_scope()))
    check(app.calls == 0, "request blocked without credential")
    check(_status(msgs) == 401, "401 returned without credential")


def test_pass_with_bearer():
    _reset_env()
    key = "k" * 32
    os.environ["AIKORE_API_KEY"] = key
    auth.init_auth_config(force=True)

    app = _PassThroughApp()
    mw = auth.AuthMiddleware(app)
    msgs = asyncio.run(_run(mw, _http_scope(headers=[("Authorization", f"Bearer {key}")])))
    check(app.calls == 1, "request passes with Bearer credential")
    check(_status(msgs) is None, "no 401 with valid Bearer")


def test_pass_with_x_api_key():
    _reset_env()
    key = "k" * 32
    os.environ["AIKORE_API_KEY"] = key
    auth.init_auth_config(force=True)

    app = _PassThroughApp()
    mw = auth.AuthMiddleware(app)
    msgs = asyncio.run(_run(mw, _http_scope(headers=[("X-API-Key", key)])))
    check(app.calls == 1, "request passes with X-API-Key credential")
    check(_status(msgs) is None, "no 401 with valid X-API-Key")


def test_401_wrong_key():
    _reset_env()
    os.environ["AIKORE_API_KEY"] = "k" * 32
    auth.init_auth_config(force=True)

    app = _PassThroughApp()
    mw = auth.AuthMiddleware(app)
    msgs = asyncio.run(_run(mw, _http_scope(headers=[("Authorization", "Bearer wrongkey")])))
    check(app.calls == 0, "request blocked with wrong key")
    check(_status(msgs) == 401, "401 returned with wrong key")


def test_public_paths():
    _reset_env()
    os.environ["AIKORE_API_KEY"] = "k" * 32
    auth.init_auth_config(force=True)

    for path in ("/", "/favicon.ico", "/static/app.js", "/static/css/x.css"):
        app = _PassThroughApp()
        mw = auth.AuthMiddleware(app)
        asyncio.run(_run(mw, _http_scope(path=path)))
        check(app.calls == 1, f"public path passes: {path}")

    app = _PassThroughApp()
    mw = auth.AuthMiddleware(app)
    asyncio.run(_run(mw, _http_scope(path="/api/instances")))
    check(app.calls == 0, "non-public path blocked")


def test_auth_public_paths_env():
    _reset_env()
    os.environ["AIKORE_API_KEY"] = "k" * 32
    os.environ["AIKORE_AUTH_PUBLIC_PATHS"] = "/health,/open/*"
    auth.init_auth_config(force=True)

    for path in ("/health", "/open/foo", "/open/"):
        app = _PassThroughApp()
        mw = auth.AuthMiddleware(app)
        asyncio.run(_run(mw, _http_scope(path=path)))
        check(app.calls == 1, f"AIKORE_AUTH_PUBLIC_PATHS passes: {path}")

    app = _PassThroughApp()
    mw = auth.AuthMiddleware(app)
    asyncio.run(_run(mw, _http_scope(path="/api")))
    check(app.calls == 0, "path outside public list blocked")


def test_ws_same_origin_non_default_port_passes():
    _reset_env()
    auth.init_auth_config(force=True)

    app = _PassThroughApp()
    mw = auth.AuthMiddleware(app)
    scope = _ws_scope(
        headers=[("Origin", "http://example.com:8080"), ("Host", "example.com:8080")]
    )
    asyncio.run(_run(mw, scope))
    check(app.calls == 1, "WS same-origin with non-default port passes")


def test_ws_cross_origin_blocked():
    _reset_env()
    auth.init_auth_config(force=True)

    app = _PassThroughApp()
    mw = auth.AuthMiddleware(app)
    scope = _ws_scope(
        headers=[("Origin", "http://evil.com"), ("Host", "example.com")]
    )
    msgs = asyncio.run(_run(mw, scope))
    check(app.calls == 0, "WS cross-origin blocked")
    check(any(m.get("type") == "websocket.close" for m in msgs), "websocket.close sent on cross-origin")


def test_ws_x_forwarded_host_fallback():
    _reset_env()
    auth.init_auth_config(force=True)

    app = _PassThroughApp()
    mw = auth.AuthMiddleware(app)
    scope = _ws_scope(
        headers=[
            ("Origin", "http://example.com"),
            ("Host", "internal"),
            ("X-Forwarded-Host", "example.com"),
        ]
    )
    asyncio.run(_run(mw, scope))
    check(app.calls == 1, "WS passes via X-Forwarded-Host fallback")


def test_ws_allowed_origins_env():
    _reset_env()
    os.environ["AIKORE_WS_ALLOWED_ORIGINS"] = "https://allowed.example"
    auth.init_auth_config(force=True)

    app = _PassThroughApp()
    mw = auth.AuthMiddleware(app)
    scope = _ws_scope(
        headers=[("Origin", "https://allowed.example"), ("Host", "other")]
    )
    asyncio.run(_run(mw, scope))
    check(app.calls == 1, "WS passes via AIKORE_WS_ALLOWED_ORIGINS")


def test_ws_subprotocol_no_key_echo():
    _reset_env()
    key = "k" * 32
    os.environ["AIKORE_API_KEY"] = key
    auth.init_auth_config(force=True)

    app = _PassThroughApp()
    mw = auth.AuthMiddleware(app)
    scope = _ws_scope(subprotocols=["aikore-auth", key])
    msgs = asyncio.run(_run(mw, scope))
    check(app.calls == 1, "WS handshake passes with auth subprotocol")
    accept = next((m for m in msgs if m.get("type") == "websocket.accept"), None)
    check(accept is not None, "websocket.accept sent")
    check(accept.get("subprotocol") == "aikore-auth", "accept selects 'aikore-auth' subprotocol")
    check(accept.get("subprotocol") != key, "raw key is never echoed as subprotocol")


def test_options_pass_through():
    _reset_env()
    os.environ["AIKORE_API_KEY"] = "k" * 32
    auth.init_auth_config(force=True)

    app = _PassThroughApp()
    mw = auth.AuthMiddleware(app)
    asyncio.run(_run(mw, _http_scope(method="OPTIONS")))
    check(app.calls == 1, "OPTIONS passes through without credential")


def test_default_port_stripping_symmetric():
    check(auth._strip_default_port("example.com:80") == "example.com", "strips :80")
    check(auth._strip_default_port("example.com:443") == "example.com", "strips :443")
    check(auth._strip_default_port("example.com:8080") == "example.com:8080", "keeps :8080")
    check(auth._strip_default_port("example.com") == "example.com", "keeps bare authority")

    # Symmetric: Origin with default port matches Host without it, and vice versa.
    check(
        auth._ws_origin_allowed("http://example.com:80", ("example.com",), "ws"),
        "Origin :80 matches Host without port",
    )
    check(
        auth._ws_origin_allowed("https://example.com", ("example.com:443",), "wss"),
        "Origin without port matches Host :443",
    )
    check(
        not auth._ws_origin_allowed("http://example.com:8080", ("example.com",), "ws"),
        "non-default port mismatch is blocked",
    )


if __name__ == "__main__":
    sys.exit(run_suite(_suite, globals()))
