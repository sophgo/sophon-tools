"""Authentication for the two faces of the service.

* ``/v1/*`` -- bearer API keys (``sk-...``), because that is what OpenAI SDKs send.
* ``/api/*`` -- an admin session cookie, because a browser cannot attach a
  bearer token to a navigation request -- **or** an ``admin``-scoped API key as
  ``Authorization: Bearer``, because a script cannot log in with a cookie
  without re-implementing the login page (MYS-2676).

Admin login issues a signed, expiring cookie. The secret is generated once and
persisted, so restarting the service does not log the operator out.

**Two credentials, two defences.** A cookie is sent by the browser by itself, so
a cookie-authenticated request must not be honoured when a *foreign* page made
it: that is CSRF, and the defence is the cookie's ``SameSite=Lax`` plus the
``Origin`` check in :func:`require_admin` for state-changing methods. A bearer
token is never attached by a browser on its own, so a bearer-authenticated
request **skips both** -- there is nothing to forge.

**Scope.** A key is either ``inference`` (the default, and what every key minted
before MYS-2676 is) or ``admin``. ``inference`` keys drive ``/v1`` and are
refused on ``/api`` with a 403; ``admin`` keys may do both. That is the whole
reason the field exists: an agent handed a key to call ``/v1`` must not thereby
be able to load models, change settings, or read the audit trail.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

from .errors import api_error
from .state import StateStore

COOKIE_NAME = "cv84x6_admin"
SESSION_TTL = 12 * 3600

#: The two permission scopes a key can carry. ``inference`` is the default so a
#: state file written by an older build keeps working unchanged: its keys have no
#: ``scope`` field, and ``ApiKey`` fills in this value.
SCOPE_INFERENCE = "inference"
SCOPE_ADMIN = "admin"
SCOPES = (SCOPE_INFERENCE, SCOPE_ADMIN)

#: Methods that change state and therefore need the cookie request's CSRF check.
#: A ``GET`` from a foreign page can still read a response the browser will not
#: hand back to that page (CORS without credentials), and requiring an Origin on
#: every poll would break a client that legitimately omits it -- so reads are
#: out of scope, which is also what the cookie's ``SameSite`` already covers.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Hosts an ``Origin`` may name when it must be checked. The same rule
#: ``app/mcp/server.py`` uses, and deliberately duplicated rather than imported:
#: ``mcp.server`` pulls in the tool registry, and this module is imported by
#: every route.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

#: Extra origins an operator may declare, ``;``-separated (e.g. the LAN address
#: the console is reached on). Same variable the MCP endpoint reads, so one
#: setting covers both browser-facing surfaces.
ORIGINS_ENV = "CV84X6_MCP_ORIGINS"


class AdminSessions:
    def __init__(self, secret: bytes) -> None:
        self._secret = secret

    @classmethod
    def load_or_create(cls, path: Path) -> "AdminSessions":
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return cls(path.read_bytes())
        secret = secrets.token_bytes(32)
        path.write_bytes(secret)
        path.chmod(0o600)
        return cls(secret)

    def _sign(self, payload: bytes) -> str:
        return urlsafe_b64encode(
            hmac.new(self._secret, payload, hashlib.sha256).digest()
        ).decode()

    def issue(self, username: str = "admin") -> str:
        payload = json.dumps({"u": username, "exp": int(time.time()) + SESSION_TTL}).encode()
        body = urlsafe_b64encode(payload).decode()
        return f"{body}.{self._sign(payload)}"

    def verify(self, token: str) -> bool:
        try:
            body, sig = token.rsplit(".", 1)
            payload = urlsafe_b64decode(body.encode())
            if not hmac.compare_digest(self._sign(payload), sig):
                return False
            data = json.loads(payload)
            return int(data.get("exp", 0)) > time.time()
        except Exception:
            return False


# ---------------------------------------------------------------------------
# cookie requests: CSRF
# ---------------------------------------------------------------------------
def _declared_origins() -> set[str]:
    return {
        item.strip().rstrip("/")
        for item in (os.environ.get(ORIGINS_ENV) or "").split(";")
        if item.strip()
    }


def origin_allowed(origin: str | None, host_header: str | None) -> bool:
    """Whether a cookie request's ``Origin`` may be honoured.

    A **missing** ``Origin`` is allowed. Browsers send it on every state-changing
    cross-origin request and on same-origin ``POST``s too, but a non-browser
    client (curl with a cookie jar, a test, the console's own server-side tools)
    may omit it -- and a rule that demanded one would break those while adding
    nothing: the attack this defends against is a *page*, and a page always
    sends it (``Origin: null`` for a sandboxed frame or a ``file://`` document,
    which is refused below).

    When present it must be loopback, an operator-declared origin, or exactly the
    host this request was addressed to -- i.e. same-origin in the browser's
    sense, which is what ``SameSite=Lax`` does not cover on its own (a
    same-site but different-port page, and any deployment whose console and API
    are reached through different names).
    """
    if not origin:
        return True
    try:
        parts = urlsplit(origin)
    except ValueError:  # pragma: no cover - urlsplit is very permissive
        return False
    if parts.scheme not in ("http", "https"):
        # ``file://``, ``null`` (a sandboxed frame), ``chrome-extension://``.
        return False
    if (parts.hostname or "").lower() in LOOPBACK_HOSTS:
        return True
    if origin.rstrip("/") in _declared_origins():
        return True
    if host_header and parts.netloc.lower() == host_header.strip().lower():
        return True
    return False


def require_admin(request: Request) -> None:
    """Authorise a management request: admin cookie, or an ``admin`` API key.

    A bearer token is tried first: it is unambiguous (the console never sends
    one), it needs no CSRF defence, and its presence is a statement that the
    caller is a script rather than a page. A request with neither credential is
    a 401; a request with a valid *inference* key is a 403, because "you may not
    do this" and "I do not know you" are different answers and a script author
    needs to be able to tell them apart.
    """
    app = request.app
    raw = _bearer_token(request)
    if raw:
        _require_admin_key(app, raw)
        return
    token = request.cookies.get(COOKIE_NAME)
    if not token or not app.state.sessions.verify(token):
        raise api_error(status.HTTP_401_UNAUTHORIZED, "unauthorized",
                        "admin login required")
    if request.method.upper() in UNSAFE_METHODS and not origin_allowed(
            request.headers.get("origin"), request.headers.get("host")):
        # The cookie is valid, so this is a real operator's browser being used
        # by someone else's page. Same answer as a missing session: the browser
        # shows nothing, and the operator's session is untouched.
        raise api_error(status.HTTP_403_FORBIDDEN, "forbidden_scope",
                        f"拒绝跨站请求：Origin {request.headers.get('origin')!r} "
                        "不是本服务")


def _bearer_token(request: Request) -> str:
    """The bearer token this request carries, or '' (``api-key`` counts too)."""
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    # Azure-style clients put the key in its own header; the /v1 surface has
    # accepted that since before this change, so /api does too.
    return (request.headers.get("api-key") or "").strip()


def _require_admin_key(app, raw: str) -> None:
    store: StateStore = app.state.store
    key = store.find_key(raw)
    if key is None:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "unauthorized",
                        "无效的 API key")
    if key.scope != SCOPE_ADMIN:
        raise api_error(
            status.HTTP_403_FORBIDDEN, "forbidden_scope",
            f"API key {key.name!r} 的权限范围是 {key.scope}，只能调用 /v1；"
            "管理接口 /api 需要 scope=admin 的 key")


def require_api_key(request: Request) -> str:
    """Validate the bearer token and return the key id (or '' when auth is off)."""
    store: StateStore = request.app.state.store
    if not store.settings.require_api_key:
        return ""
    header = request.headers.get("authorization") or ""
    raw = ""
    if header.lower().startswith("bearer "):
        raw = header[7:].strip()
    if not raw:
        # Some clients put it in api-key (Azure style); accept it too.
        raw = request.headers.get("api-key", "").strip()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"message": "missing API key", "type": "invalid_request_error"}},
        )
    key = store.find_key(raw)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"message": "invalid API key", "type": "invalid_request_error"}},
        )
    return key.id


def require_admin_docs(request: Request) -> None:
    """Authorise ``/api/docs`` and ``/api/openapi.json``.

    The same two credentials, with one difference worth stating: the browser
    that opens ``/api/docs`` in a tab sends the cookie, so a *navigation* must be
    accepted -- which means the CSRF check above (state-changing methods only)
    applies here unchanged, and a ``GET`` is fine. Nothing about the document
    itself is secret; what must not happen is an unauthenticated host on the LAN
    reading the whole management surface, which is what this gate prevents.
    """
    require_admin(request)
