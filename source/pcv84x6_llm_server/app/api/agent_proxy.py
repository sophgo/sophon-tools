"""Reverse proxy for an agent's own web UI, so the console can embed it.

An agent serves its own UI on its own port, and the console has to show that UI
*from the console's origin*. Two things make that necessary rather than nice:

* **Reachability.** On a customer site the board is reached from another subnet
  through one forwarded port (8000). A link to ``http://<board>:14096`` is a
  different port on a different host as far as the browser is concerned, so it
  simply does not resolve -- the embedded frame stays blank and "打开" dead-ends.
* **Framing.** OpenClaw's Control UI refuses to be framed at all
  (``X-Frame-Options: DENY`` and a CSP whose ``frame-ancestors 'none'`` outranks
  anything the embedding page can do).

So both agents are put on this service's own origin under ``/agents/<id>/``:

    browser  /agents/<id>/...  ->  service  ->  127.0.0.1:<agent port>/...

What the proxy does, and why each part is needed:

* **Authentication.** The console's admin session cookie is required, for HTTP
  and for the WebSocket upgrade alike. Without it the agent's UI -- and the
  agent's own API behind it -- would be open to anyone who can reach the board.
* **Framing.** ``X-Frame-Options`` is dropped and ``frame-ancestors`` is
  narrowed to ``'self'``, which is exactly the same-origin embed the console
  does. Everything else in the CSP is passed through untouched; relaxing more
  than the one directive would be a real hole.
* **Origin.** The upstream gateway checks the browser's ``Origin`` against
  ``gateway.controlUi.allowedOrigins``. The proxy has already authenticated the
  caller, so it presents the loopback origin the agent's config allows rather
  than trusting a browser-supplied one -- which also means the agent's config
  does not have to enumerate every address the board is reachable on.
* **Prefix rewriting** (``prefix_root`` agents, i.e. opencode). opencode is
  built to be served from an origin's root: its HTML names ``/assets/...``, its
  router reads ``location.pathname`` as a route, and its API client uses
  ``location.origin`` as the server address. Served under a prefix, every one
  of those leaves the prefix, which is exactly the "it opens the original port"
  failure this module exists to remove. See ``_PrefixRewriter``.

WebSocket forwarding needs a server that speaks WebSocket at all: uvicorn only
does when ``websockets`` (or ``wsproto``) is importable, which is why
``requirements-vendor.txt`` pins it and ``app/main.py`` passes
``ws="websockets"``.
"""

from __future__ import annotations

import logging
import re

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, StreamingResponse
from starlette.responses import Response

from ..core.auth import COOKIE_NAME

logger = logging.getLogger(__name__)

router = APIRouter()

# Headers that describe one hop and must not be copied to the next one.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}

# Long enough for a slow board to answer; the UI polls status endpoints that do
# real work, and a premature timeout shows up as a broken console.
CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 300.0

# The injected script's path, under the agent's own prefix. It is served by this
# proxy, not by the agent, and the agent's own routes never collide with it
# because the agent does not know this prefix exists.
SHIM_NAME = "_console_proxy.js"

# Content types whose bodies are rewritten for a prefix_root agent. Anything
# else (JSON, SSE, images, fonts, archives) is streamed through untouched --
# rewriting those would corrupt them, and none of them can name a URL the
# browser resolves.
HTML_TYPES = ("text/html",)
CSS_TYPES = ("text/css",)
JS_TYPES = ("javascript", "ecmascript")


def _is(content_type: str, kinds: tuple[str, ...]) -> bool:
    ctype = (content_type or "").lower()
    return any(kind in ctype for kind in kinds)


def _proxy_target(request_or_ws, agent_id: str):
    """The agent's spec and live port, or an HTTP error explaining why not.

    Only agents that declare themselves proxied are served: everything else
    keeps its own port and its own origin, which is a deliberate choice per
    agent (measured, not a policy of the console).
    """
    app = request_or_ws.app
    mgr = app.state.agents
    spec = mgr.specs.get(agent_id)
    if spec is None or not getattr(spec, "proxied", False):
        raise HTTPException(status_code=404, detail="没有可代理的 agent")
    if not mgr.installed(agent_id):
        raise HTTPException(status_code=409, detail=f"{spec.name} 尚未安装")
    status = mgr.status_one(agent_id)
    if not status["running"]:
        raise HTTPException(status_code=409, detail=f"{spec.name} 没有在运行")
    return spec, int(status["port"])


def _authenticated_http(request: Request) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if not token or not request.app.state.sessions.verify(token):
        raise HTTPException(status_code=401, detail="admin login required")


def _authenticated_ws(websocket: WebSocket) -> bool:
    token = websocket.cookies.get(COOKIE_NAME)
    return bool(token) and websocket.app.state.sessions.verify(token)


def _rewrite_headers(headers: list[tuple[str, str]], service_port: int,
                     spec=None) -> list[tuple[str, str]]:
    """Drop the framing refusal, keep everything else.

    ``frame-ancestors`` is replaced rather than the whole CSP: the rest of the
    policy (script hashes, ``connect-src``) is what keeps the UI from being a
    script-injection surface, and it stays as the agent wrote it.

    ``Location`` is rewritten when the upstream redirects to its own absolute
    URL, which it does after some login flows; leaving it alone would send the
    browser to the loopback port it cannot reach.
    """
    out: list[tuple[str, str]] = []
    for name, value in headers:
        low = name.lower()
        if low in HOP_BY_HOP:
            continue
        if low == "x-frame-options":
            continue
        if low == "content-security-policy":
            value = _relax_frame_ancestors(value)
        elif low == "location":
            value = _rewrite_location(value, service_port, spec)
        out.append((name, value))
    return out


def _relax_frame_ancestors(csp: str) -> str:
    """``frame-ancestors 'none'`` -> ``frame-ancestors 'self'``.

    Only the same-origin case is allowed: a page served by this service may
    frame the UI, an arbitrary site may not.
    """
    parts = [p.strip() for p in csp.split(";")]
    found = False
    for i, part in enumerate(parts):
        if part.lower().startswith("frame-ancestors"):
            parts[i] = "frame-ancestors 'self'"
            found = True
    if not found:
        parts.append("frame-ancestors 'self'")
    return "; ".join(p for p in parts if p)


# An absolute loopback URL, with or without a port, that the browser cannot use.
_LOOPBACK = re.compile(r"^https?://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?")


def _rewrite_location(value: str, service_port: int, spec=None) -> str:
    """Move a redirect under the prefix, whatever form the agent wrote it in.

    An origin-root agent redirects in one of three ways, and all three escape
    ``/agents/<id>/``:

    * ``http://127.0.0.1:18800/launcher-login`` -- an absolute loopback URL the
      browser cannot reach at all;
    * ``/launcher-login`` -- root-relative. Measured against PicoClaw 0.3.1: its
      dashboard answers ``/`` with exactly this, and passed through unchanged the
      browser leaves the agent's subtree and lands on the *console's* router
      (which has no such route, so the frame renders the console instead);
    * ``login`` -- relative to the request path, which is already inside the
      prefix, so it is the one form that needs nothing.

    A non-prefix agent (OpenClaw) is different: its ``basePath`` is the prefix,
    so its own redirects are already correct and only the loopback form has to be
    replaced.
    """
    prefix = f"/agents/{getattr(spec, 'id', '')}"
    prefix_root = bool(getattr(spec, "prefix_root", False))
    m = _LOOPBACK.match(value)
    if m:
        rest = value[m.end():] or "/"
        if not rest.startswith("/"):
            rest = "/" + rest
        return _under_prefix(rest, prefix) if prefix_root else rest
    if not prefix_root or not value.startswith("/"):
        # A relative value resolves against the request path, which is already
        # under the prefix; an absolute one belongs to a non-prefix agent.
        return value
    return _under_prefix(value, prefix)


def _under_prefix(path: str, prefix: str) -> str:
    """``/x`` -> ``/agents/<id>/x``, leaving a path already there alone."""
    if path == prefix or path.startswith(prefix + "/"):
        return path
    return prefix + path


class _PrefixRewriter:
    """Makes an origin-root web app work under ``/agents/<id>/``.

    Why this exists, concretely: opencode 1.19.4 serves an HTML page whose asset
    URLs are ``/assets/index-<hash>.js``, a router that treats
    ``location.pathname`` as its route, an API client whose server address is
    ``location.origin``, and a bundle whose dynamic imports resolve relative to
    the module URL. Put that page on ``/agents/opencode/`` and every one of those
    escapes to the origin root: the browser fetches the agent's assets from the
    console's own root (404), the router matches nothing (a blank frame), and
    even if the HTML loaded, ``fetch("/global/health")`` would hit the console.

    Two mechanisms, deliberately both:

    1. **Server-side rewriting** of the three text types the browser resolves
       URLs from -- HTML attributes and CSS ``url()``, plus the two bundle
       constructs that name an absolute asset path or read the raw pathname.
       Static, exact, and it happens before the first paint.
    2. **A same-origin shim** (``SHIM_NAME``) that instruments the runtime
       primitives which *build* URLs after load: ``fetch``, ``XMLHttpRequest``,
       ``WebSocket``, ``EventSource``, ``history.pushState/replaceState``,
       element ``src``/``href`` setters, and ``Element.setAttribute``. This is
       what keeps an SPA's own navigation and API calls inside the prefix.

    Neither alone is enough: (1) cannot see a URL a script computes, and (2)
    cannot run before the module graph starts loading.

    The rewrite is intentionally narrow. Only a leading ``/`` that is not
    already the prefix is touched; protocol-relative ``//host``, absolute URLs,
    ``data:``/``blob:`` and fragments are left exactly as they are, because
    rewriting those would point at the wrong origin or break the resource.
    """

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix.rstrip("/")

    # -- HTML -----------------------------------------------------------
    # src=/href=/action= in a tag, plus the form of the same inside an inline
    # script's string. Only attribute-position URLs are rewritten; the bundle
    # handles its own.
    _HTML_ATTR = re.compile(
        r"(?P<lead>\b(?:src|href|action|poster|data-src)\s*=\s*[\"'])"
        r"(?P<url>/(?!/)[^\"']*)"
        r"(?P<close>[\"'])"
    )

    def html(self, text: str) -> str:
        text = self._HTML_ATTR.sub(self._attr_sub, text)
        return self._inject_shim(text)

    def _attr_sub(self, m: re.Match) -> str:
        url = m.group("url")
        if self._already_prefixed(url):
            return m.group(0)
        return m.group("lead") + self.prefix + url + m.group("close")

    def _inject_shim(self, text: str) -> str:
        """Put the shim in front of the app's own scripts.

        Two tags: a classic external script that installs the hooks, and the
        prefix constant it reads. The constant is a separate ``data-`` attribute
        on that same tag rather than an inline script, because the agent's own
        CSP (which is passed through) generally has no ``'unsafe-inline'`` for
        scripts -- an inline initialiser would be blocked and every hook would
        then rewrite against an empty prefix.

        Both go first in ``<head>``, so they run before any module executes.
        """
        tag = (
            f'<script src="{self.prefix}/{SHIM_NAME}" '
            f'data-console-prefix="{self.prefix}"></script>'
        )
        head = re.search(r"<head[^>]*>", text, re.IGNORECASE)
        if head:
            at = head.end()
            return text[:at] + tag + text[at:]
        return tag + text

    # -- CSS ------------------------------------------------------------
    _CSS_URL = re.compile(r"url\((?P<q>[\"']?)(?P<url>/(?!/)[^)\"']*)(?P=q)\)")

    def css(self, text: str) -> str:
        def sub(m: re.Match) -> str:
            url = m.group("url")
            if self._already_prefixed(url):
                return m.group(0)
            return f"url({m.group('q')}{self.prefix}{url}{m.group('q')})"
        return self._CSS_URL.sub(sub, text)

    # -- JS -------------------------------------------------------------
    # The bundle names assets two ways, and both have to be redirected:
    #
    # * ``"/assets/worker-x.js"`` -- a static reference to a worker or an image;
    # * ``["assets/chunk.js", ...]`` inside Vite's ``__vite__mapDeps`` table,
    #   which its preload helper resolves with ``"/" + name`` at run time. Those
    #   entries are relative in the source, so matching only ``/assets/`` leaves
    #   every lazily-loaded chunk pointing at the console's own root.
    _JS_ASSET = re.compile(r"(?P<q>[\"'`])(?P<lead>/)assets/")

    # Wherever the app reads the address bar for a route. Its router does
    # ``window.location.pathname`` and parses that as one of *its* routes, so
    # under the prefix it matches nothing -- the blank frame. Handing it a
    # prefix-stripped pathname is the fix; the helper lives in the shim, so the
    # bundle needs nothing but a rename.
    #
    # The *whole* member expression has to be wrapped, receiver included. An
    # earlier version replaced the bare substring ``location.pathname``, which
    # also rewrote the receiver: ``e.location.pathname`` became
    # ``e.__consolePath(location.pathname)``. Measured on the board against
    # PicoClaw's bundle, that is exactly the reported crash --
    # ``TypeError: e.__consolePath is not a function`` in
    # ``index-B3x-7GgS.js``'s router ``Object.select``, where ``e`` is the
    # router store and never had such a method. The four sites in that bundle
    # are ``window.``, ``globalThis.``, ``t.`` and ``e.`` -- the first two only
    # worked by accident, because the helper happened to live on ``window``.
    #
    # The replacement calls the helper by its *bare* name rather than through a
    # receiver, so a bundle that shadows ``window`` locally (a namespace
    # parameter, a destructured alias) still reaches the real global. Set
    # ``window.__consolePath`` on the shim side is what makes the bare name
    # resolve.
    #
    # The trailing lookahead skips an assignment target (``location.pathname =
    # ...``): wrapping that would be a syntax error rather than a redirect.
    #
    # ``?.`` is part of a receiver chain in modern output (``e?.location.
    # pathname``), and the leading lookbehind refuses to start in the middle of
    # one -- ``x[0].location.pathname`` stays untouched rather than becoming
    # ``x[0].__consolePath(location.pathname)``. Leaving a form alone is always
    # safe here; rewriting only half of it is what crashed.
    _IDENT = r"[A-Za-z_$][\w$]*"
    _JS_PATHNAME = re.compile(
        r"(?<![\w$\].])"
        # Idempotent: a second pass must not re-wrap an already-wrapped read.
        r"(?<!__consolePath\()"
        r"(?P<expr>(?:" + _IDENT + r"(?:\?\.|\.))*location\.pathname)"
        r"(?![\w$])"
        # Skip an assignment target -- plain (``=``) or compound (``+=``,
        # ``??=``, ``>>>=``). Wrapping one is a SyntaxError that would take the
        # whole bundle down, which is far worse than missing a redirect.
        # ``==``, ``===`` and ``=>`` are reads and must still be wrapped.
        r"(?![ \t]*(?:>>>|>>|<<|\*\*|&&|\|\||\?\?|[+\-*/%&|^])?=(?![=>]))"
    )

    # Hard navigations: ``<recv>.location.assign(url)`` / ``.replace(url)``.
    # Measured call sites in PicoClaw 0.3.1: ``globalThis.location.assign(`/`)``
    # and ``window.location.replace(t)``. The receiver is captured rather than
    # replaced because ``location.assign`` is an own, non-configurable property
    # of the instance -- the hook has to receive the real one and call it.
    #
    # Only the *page's own* address bar is listed, not "any identifier chain
    # ending in ``location``". ``frame.contentWindow.location`` is a different
    # document whose paths are not this console's to prefix, and an object that
    # merely has a ``location`` field is not a Location at all. Rewriting those
    # would move the navigation to the wrong URL, which is worse than leaving a
    # redirect alone. The pathname rule needs no such list: it only reads.
    _PAGE_LOCATION = (r"(?:location|(?:window|globalThis|self|top|parent|document)"
                      r"\.location)")
    _JS_NAVIGATE = re.compile(
        r"(?<![\w$\].])"
        r"(?<!__consoleGo\()"
        r"(?P<receiver>" + _PAGE_LOCATION + r")"
        r"\.(?P<method>assign|replace)"
        r"\((?P<arg>[^()]*)\)"
    )

    # The other hard-navigation spelling, ``<recv>.location.href = url``. Also
    # measured in PicoClaw 0.3.1 (its SSO chunk assigns ``auth_url`` this way).
    # ``href`` is a non-configurable accessor on the ``Location`` instance, so
    # the left-hand side is replaced wholesale rather than hooked.
    #
    # The lookahead refuses ``==``/``===``/``=>`` so comparisons and arrows that
    # merely *end* in ``.href`` are left alone.
    _JS_HREF_ASSIGN = re.compile(
        r"(?<![\w$\].])"
        r"(?P<receiver>" + _PAGE_LOCATION + r")"
        r"\.href(?![ \t]*(?:[=!<>]=|\?\.))"
        r"[ \t]*=(?![=>])"
        r"[ \t]*(?P<arg>[^;,)\n]+)"
    )

    def js(self, text: str) -> str:
        """Rewrite only the *absolute* names in the bundle.

        The dep table's entries are relative (``"assets/chunk.js"``) and Vite's
        preload helper turns them into ``"/" + name`` at run time. Rewriting the
        literal to ``"/agents/<id>/assets/chunk.js"`` there looks helpful and is
        the opposite: the helper then produces ``"//agents/<id>/assets/..."``,
        which the browser reads as *protocol-relative* -- host ``agents`` -- and
        the lazy chunk fails with a CSP violation rather than a 404. Measured
        exactly that way against opencode 1.19.4.

        Those run-time URLs are left to the shim, which sees the finished
        ``/assets/...`` value on the ``<link>`` the helper creates and prefixes
        it once. So: absolute names here, computed names at run time.

        Full-page navigations are a third case, added after measuring PicoClaw
        0.3.1: its login screen answers a successful sign-in with
        ``globalThis.location.assign(`/`)`` and a fresh session with
        ``location.assign(`/launcher-login`)``. Both are *hard* navigations to a
        prefix-less path, so the browser leaves ``/agents/picoclaw/`` and loads
        the console's own SPA -- the frame then shows the console inside itself.
        A shim hook cannot catch these: ``location.assign``/``replace`` are
        non-configurable own properties of the ``Location`` instance and
        ``href`` is a non-configurable accessor (all measured in Chromium), so
        the only place left to move them is here, in the bundle.
        """
        text = self._JS_ASSET.sub(
            lambda m: m.group("q") + self.prefix + "/assets/", text)
        text = self._JS_PATHNAME.sub(
            lambda m: f"__consolePath({m.group('expr')})", text)
        text = self._JS_NAVIGATE.sub(
            lambda m: (f"__consoleGo({m.group('receiver')},"
                       f"{m.group('arg')},'{m.group('method')}')"), text)
        return self._JS_HREF_ASSIGN.sub(
            lambda m: (f"__consoleGo({m.group('receiver')},"
                       f"{m.group('arg')},'assign')"), text)

    def _already_prefixed(self, url: str) -> bool:
        return url == self.prefix or url.startswith(self.prefix + "/")


# A SHA-256 implementation for ``crypto.subtle`` when the browser withholds it.
#
# Why the console has to supply one: ``crypto.subtle`` is defined only in a
# **secure context** -- HTTPS, or ``localhost``. The board is reached at
# ``http://<board-ip>:8000``, which is neither, so ``crypto.subtle`` is
# ``undefined`` there by design (measured: ``isSecureContext === false``,
# ``typeof crypto.subtle === "undefined"``).
#
# Why that breaks attaching a file, measured against opencode 1.19.4: its
# composer hashes every attachment to derive the IndexedDB blob key
# (``crypto.subtle.digest("SHA-256", await file.arrayBuffer())`` in the bundle's
# ``putBlob``). With ``subtle`` withheld the call throws
# ``TypeError: Cannot read properties of undefined (reading 'digest')``, the
# promise rejects, and the attachment silently never enters the composer -- the
# reported "the page cannot upload files or images". The same page served
# straight from ``http://<board-ip>:14096`` fails byte-identically, so this is
# the deployment origin and not the reverse proxy; the proxy is simply the only
# place the console can add the missing primitive.
#
# Only SHA-256 is implemented, because that is the only algorithm the agents
# ask for; anything else rejects loudly instead of returning a wrong digest. A
# wrong digest would be worse than the missing method: it silently files
# attachments under colliding keys. The test suite pins this against the NIST
# vectors and against Node's own ``crypto.subtle`` output.
_SHA256_JS = r"""
var __consoleSha256=function(bytes){
  var K=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
  function rotr(x,n){return (x>>>n)|(x<<(32-n))}
  var l=bytes.length,total=((l+9+63)>>6)<<6,buf=new Uint8Array(total);
  buf.set(bytes);buf[l]=0x80;
  var bits=l*8,hi=Math.floor(bits/0x100000000);
  buf[total-8]=(hi>>>24)&255;buf[total-7]=(hi>>>16)&255;buf[total-6]=(hi>>>8)&255;buf[total-5]=hi&255;
  buf[total-4]=(bits>>>24)&255;buf[total-3]=(bits>>>16)&255;buf[total-2]=(bits>>>8)&255;buf[total-1]=bits&255;
  var h=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
  var w=new Uint32Array(64);
  for(var off=0;off<total;off+=64){
    for(var i=0;i<16;i++){w[i]=(buf[off+i*4]<<24)|(buf[off+i*4+1]<<16)|(buf[off+i*4+2]<<8)|buf[off+i*4+3]}
    for(var j=16;j<64;j++){
      var s0=rotr(w[j-15],7)^rotr(w[j-15],18)^(w[j-15]>>>3);
      var s1=rotr(w[j-2],17)^rotr(w[j-2],19)^(w[j-2]>>>10);
      w[j]=(w[j-16]+s0+w[j-7]+s1)>>>0;
    }
    var a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],k=h[7];
    for(var r=0;r<64;r++){
      var S1=rotr(e,6)^rotr(e,11)^rotr(e,25),ch=(e&f)^(~e&g);
      var t1=(k+S1+ch+K[r]+w[r])>>>0;
      var S0=rotr(a,2)^rotr(a,13)^rotr(a,22),maj=(a&b)^(a&c)^(b&c);
      var t2=(S0+maj)>>>0;
      k=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0;
    }
    h[0]=(h[0]+a)>>>0;h[1]=(h[1]+b)>>>0;h[2]=(h[2]+c)>>>0;h[3]=(h[3]+d)>>>0;
    h[4]=(h[4]+e)>>>0;h[5]=(h[5]+f)>>>0;h[6]=(h[6]+g)>>>0;h[7]=(h[7]+k)>>>0;
  }
  var out=new Uint8Array(32);
  for(var n=0;n<8;n++){
    out[n*4]=(h[n]>>>24)&255;out[n*4+1]=(h[n]>>>16)&255;
    out[n*4+2]=(h[n]>>>8)&255;out[n*4+3]=h[n]&255;
  }
  return out;
};
function __consoleInstallSubtle(){
  if(typeof crypto==='undefined'||!crypto)return;
  if(crypto.subtle)return;
  var subtle={digest:function(alg,data){
    var name=String(alg&&alg.name?alg.name:alg).toUpperCase();
    if(name!=='SHA-256'){
      return Promise.reject(new Error('console proxy: unsupported digest '+name));
    }
    try{
      return Promise.resolve(__consoleSha256(new Uint8Array(data)).buffer);
    }catch(err){
      return Promise.reject(err);
    }
  }};
  try{Object.defineProperty(crypto,'subtle',{value:subtle,configurable:true})}
  catch(e){try{crypto.subtle=subtle}catch(e2){}}
}
__consoleInstallSubtle();
"""


def _shim_js() -> str:
    """The runtime half of ``_PrefixRewriter``.

    Kept as a here-string rather than a static file because it must agree with
    ``prefix`` and must be impossible to serve stale: an installed service has
    no asset pipeline, and a shim that does not match the mount point would fail
    silently in exactly the way this module exists to fix.

    Each hook rewrites a URL that resolves to *this origin but outside the
    agent's subtree*. Everything else -- other origins, ``data:``, ``blob:``,
    fragments, URLs already under the prefix -- passes through untouched.

    It also supplies ``crypto.subtle`` when the browser withholds it: the board
    is served over plain HTTP, which is not a secure context, and the agent's
    composer cannot attach a file without it. See ``_SHA256_JS``.
    """
    return (
        ";(function(){"
        + _SHA256_JS +
        # The prefix is read from the tag that loaded this file. A ``?prefix=``
        # query would end up in the service's access log and in any proxy cache
        # key; the attribute is already in the document and costs nothing.
        "var t=document.currentScript,"
        "P=t&&t.getAttribute('data-console-prefix');"
        "if(!P)return;"
        "window.__CONSOLE_AGENT_PREFIX__=P;"
        # Handed to the app for its router: the path it was written for.
        #
        # This is a *property of the global object*, and the rewritten bundle
        # calls it by the bare name ``__consolePath(...)`` -- never as
        # ``window.__consolePath(...)`` or ``something.__consolePath(...)``.
        # The bare name is what makes it reachable no matter which expression
        # the bundle used to reach ``location``: PicoClaw's router store ``e``
        # has no such method (that was the crash), and a module that binds
        # ``window`` to a local namespace still resolves an undeclared
        # identifier through the global scope. Assigning to ``window`` here
        # (rather than declaring ``var`` inside this IIFE) is what puts it
        # there -- a ``var`` would be scoped to the shim and invisible.
        "window.__consolePath=function(p){"
        "if(p===P)return'/';"
        "return p.indexOf(P+'/')===0?p.slice(P.length):p};"
        # Hard navigations, for the two calls a URL hook cannot reach.
        #
        # ``location.assign``/``location.replace`` are own, non-configurable
        # properties of the ``Location`` instance, and ``href`` is a
        # non-configurable accessor (measured in Chromium: defining any of them
        # throws), so this cannot be a wrapper around the browser's method. The
        # bundle is rewritten instead to call ``__consoleGo(location, url)``,
        # which prefixes the path and then performs the real navigation.
        #
        # Prefixing only a same-origin absolute path is the whole contract: an
        # off-site redirect (an OAuth URL, say) must still leave the page. The
        # value is passed through ``R`` so the existing rule decides -- it
        # already returns other origins and already prefixed paths unchanged.
        "window.__consoleGo=function(loc,u,m){"
        "var w=R(u);"
        "if(w===u){loc[m](u);return}"
        "if(m==='replace'){loc.replace(w)}else{loc.href=w}};"
        "function R(u){"
        "if(u===undefined||u===null)return u;"
        "var s=String(u);"
        "if(!s||s.charAt(0)==='#'||s.indexOf('data:')===0||s.indexOf('blob:')===0"
        "||s.indexOf('javascript:')===0||s.indexOf('mailto:')===0)return u;"
        "var x;"
        "try{x=(typeof URL!=='undefined'&&u instanceof URL)?u:new URL(s,location.href)}"
        "catch(e){return u}"
        # A WebSocket URL is ``ws://host/...`` and ``URL.origin`` reports the
        # ``ws:`` scheme, so an exact string comparison against the page's
        # ``http:`` origin rejects same-host sockets -- PicoClaw's launcher
        # builds its chat URL as ```${wsScheme}//${location.host}/pico/ws```
        # from ``wss://``/``ws://``, which is exactly that case. Comparing host
        # and port instead of the scheme keeps other origins out while letting
        # the same address through whichever scheme names it.
        "if(x.host!==location.host)return u;"
        "if(x.protocol!=='http:'&&x.protocol!=='https:'"
        "&&x.protocol!=='ws:'&&x.protocol!=='wss:')return u;"
        "if(x.pathname===P||x.pathname.indexOf(P+'/')===0)return u;"
        # A socket's scheme is carried through: a browser turns a relative
        # socket URL into ``ws:``/``wss:`` by rule, but relying on that makes
        # the one channel the agent cannot work without depend on a conversion
        # nothing here can see. HTTP-family URLs stay relative, which is what
        # keeps the console working behind any host or forwarding port.
        "if(x.protocol==='ws:'||x.protocol==='wss:')"
        "return x.protocol+'//'+x.host+P+x.pathname+x.search+x.hash;"
        "return P+x.pathname+x.search+x.hash;"
        "}"
        # fetch: a string, a URL object, or a Request all have to be rewritten
        # *before* the request is created, or the browser has already decided
        # its address. A Request that carries a body (opencode's SDK passes
        # one for every POST) must not be re-wrapped as new Request(w, i):
        # that turns its body into a ReadableStream, which Chrome only uploads
        # over HTTP/2 (ERR_ALPN_NEGOTIATION_FAILED) and other browsers send
        # empty -- opencode then rejects the prompt with "Expected object, got
        # undefined". Buffer the body and rebuild the request from plain fields.
        "var F=window.fetch;"
        "window.fetch=function(i,n){"
        "if(typeof i==='string'||(typeof URL!=='undefined'&&i instanceof URL)){i=R(i)}"
        "else if(i&&i.url){var w=R(i.url);if(w!==i.url){"
        "if(i.method==='GET'||i.method==='HEAD'){i=new Request(w,i)}"
        "else{var q=i,s=this;return q.arrayBuffer().then(function(b){"
        "return F.call(s,new Request(w,{method:q.method,headers:q.headers,"
        "body:b.byteLength?b:undefined,credentials:q.credentials,cache:q.cache,"
        "redirect:q.redirect,signal:q.signal}),n)})}}}"
        "return F.call(this,i,n)};"
        # XHR: open() is the only place the URL is chosen.
        "var X=XMLHttpRequest.prototype.open;"
        "XMLHttpRequest.prototype.open=function(m,u){"
        "var a=Array.prototype.slice.call(arguments);a[1]=R(u);"
        "return X.apply(this,a)};"
        # WebSocket: the agent's live channel. Bound the same way, and the
        # constants are copied so feature detection keeps working.
        "var W=window.WebSocket;"
        "window.WebSocket=function(u,p){"
        "var a=Array.prototype.slice.call(arguments);a[0]=R(u);"
        "return new(Function.prototype.bind.apply(W,[null].concat(a)))()};"
        "window.WebSocket.prototype=W.prototype;"
        "['CONNECTING','OPEN','CLOSING','CLOSED'].forEach(function(k){"
        "window.WebSocket[k]=W[k]});"
        # EventSource: OpenClaw's and opencode's event streams.
        "if(window.EventSource){var E=window.EventSource;"
        "window.EventSource=function(u,c){return new E(R(u),c)};"
        "window.EventSource.prototype=E.prototype}"
        # The SPA's own navigation: keep the prefix in the address bar so a
        # reload lands back on the same route.
        "function H(n){var o=history[n];history[n]=function(s,t,u){"
        "if(u!==undefined&&u!==null&&u!=='')u=R(u);"
        "return o.call(history,s,t,u)}}"
        "H('pushState');H('replaceState');"
        # Elements built at runtime (Vite's preload links, worker scripts,
        # images) get their URL from a property setter, which no amount of
        # HTML rewriting can see.
        "function pin(el,prop){"
        "var d=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el),prop);"
        "if(!d||!d.set||!d.get)return;"
        "try{Object.defineProperty(el,prop,{enumerable:true,configurable:true,"
        "get:function(){return d.get.call(this)},"
        "set:function(v){d.set.call(this,R(v))}})}catch(e){}"
        "}"
        "var C=document.createElement;"
        "document.createElement=function(t){"
        "var el=C.apply(document,arguments),k=String(t).toLowerCase();"
        "if(k==='script'||k==='link'){pin(el,'src');pin(el,'href')}"
        "else if(k==='img'||k==='source'||k==='video'||k==='audio'"
        "||k==='iframe'||k==='track'||k==='embed'){pin(el,'src')}"
        "else if(k==='form'){pin(el,'action')}"
        "else if(k==='a'||k==='area'){pin(el,'href')}"
        "return el};"
        "var S=Element.prototype.setAttribute;"
        "Element.prototype.setAttribute=function(n,v){"
        "var k=String(n).toLowerCase();"
        "if(k==='src'||k==='href'||k==='action')v=R(v);"
        "return S.call(this,n,v)};"
        "})();"
    )


@router.api_route(
    "/agents/{agent_id}", methods=["GET", "HEAD"],
    # GET and HEAD would share one generated operationId (see ``proxy_http``).
    # These paths are plumbing, not part of any documented surface.
    operation_id="agent_proxy_bare_prefix",
    include_in_schema=False,
)
async def proxy_bare_prefix(agent_id: str, request: Request):
    """``/agents/<id>`` with no trailing slash.

    Two agents, two answers, because they were measured to need different ones:

    * a ``prefix_root`` agent (opencode) is redirected to the slashed form. Its
      page has relative URLs in it, so served from ``/agents/<id>`` the browser
      would resolve them against ``/agents/`` and 404 the whole app.
    * a non-prefix agent (OpenClaw) is proxied as-is, exactly like any other
      path: its ``basePath`` *is* this URL, so the gateway expects it verbatim.

    Either way this route has to exist. Without it the bare URL falls through to
    the console's own SPA fallback, which answers the console's index.html --
    the console's page inside the agent's frame.
    """
    if request.headers.get("upgrade", "").lower() == "websocket":
        raise HTTPException(status_code=426, detail="WebSocket upgrade required")
    _authenticated_http(request)
    spec, _port = _proxy_target(request, agent_id)
    if not getattr(spec, "prefix_root", False):
        return await proxy_http(agent_id, "", request)
    return RedirectResponse(f"/agents/{agent_id}/", status_code=307)


@router.api_route(
    "/agents/{agent_id}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    # Seven methods on one path would give them all the same generated
    # operationId, and FastAPI warns (a client generator silently keeps one).
    # Naming it explicitly is the smallest fix; these paths are plumbing, not a
    # management surface, so they are out of every OpenAPI document anyway.
    operation_id="agent_proxy_http",
    include_in_schema=False,
)
async def proxy_http(agent_id: str, path: str, request: Request):
    """Forward one HTTP request to the agent and stream the answer back."""
    # ``{path:path}`` also matches the empty string, so this route is reached for
    # ``/agents/<id>`` as well -- the URL the Control UI opens its WebSocket on.
    # Starlette matches routes in registration order and the HTTP route is
    # declared first (readability), so the upgrade has to be handed to the
    # bridge explicitly instead of relying on the WebSocket route being tried.
    # Without this the browser got a 403 and the embedded panel said
    # "Gateway unreachable" while ``/agents/<id>/`` worked.
    if request.headers.get("upgrade", "").lower() == "websocket":
        raise HTTPException(status_code=426, detail="WebSocket upgrade required")
    _authenticated_http(request)
    spec, port = _proxy_target(request, agent_id)
    prefix_root = bool(getattr(spec, "prefix_root", False))
    origin_is_host = bool(getattr(spec, "origin_is_host", False))
    _refuse_foreign_origin(spec, request.headers.get("origin"), request)

    # The shim is ours; it is never forwarded upstream.
    if prefix_root and path == SHIM_NAME:
        return Response(_shim_js(), media_type="application/javascript")

    # prefix_root: the agent serves its app at its root, so the browser's
    # ``/agents/<id>/x`` is the agent's ``/x``. A non-prefix agent (OpenClaw)
    # is configured with this same path as its basePath and expects it intact.
    upstream_path = "/" + path
    if not prefix_root and request.url.path:
        upstream_path = request.url.path

    url = f"http://127.0.0.1:{port}{upstream_path}"
    if request.url.query:
        url += f"?{request.url.query}"

    headers = [
        (k, v) for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP and k.lower() != "host"
    ]
    # Ask for identity encoding on the request, for the agents whose bodies this
    # proxy rewrites. A rewritten body has to be read and re-emitted, which a
    # gzip stream makes impossible without decompressing it first -- DSH
    # compresses HTML over 1 KiB when asked, and forwarding the browser's
    # ``Accept-Encoding`` made it decode a half-rewritten stream (``zlib.error:
    # incorrect header check``; an empty page in the browser).
    #
    # ``identity`` rather than simply dropping the header: ``httpx`` puts its own
    # default ``Accept-Encoding`` on every request it sends, so a removed header
    # comes straight back.
    #
    # Driven by ``identity_encoding``, not by ``prefix_root``: opencode is
    # ``prefix_root`` too and never compressed, and its bodies stream through
    # untouched -- asking it for identity would only cost bandwidth. Only DSH
    # sets the flag.
    if getattr(spec, "identity_encoding", False):
        headers = [(k, v) for k, v in headers if k.lower() != "accept-encoding"]
        headers.append(("accept-encoding", "identity"))
    # The gateway validates Origin on state-changing requests too; present the
    # loopback one its config allows (the caller is already an authenticated
    # admin, so this is not trusting the browser's claim).
    #
    # Which loopback authority that is depends on the agent, and the two cases
    # are not interchangeable. OpenClaw checks Origin against a configured
    # allow-list -- ``controlUi.allowedOrigins``, which this service fills with
    # its *own* origin -- so it must be the service's authority. DSH compares
    # Origin against the request's own Host instead (``isSameAuthorityOrigin``
    # in its connection carrier), so any Origin that differs from Host is a 403
    # on every call, and Host has to be the agent's own authority for DSH to
    # recognise its bound address.
    origin = f"http://127.0.0.1:{port if origin_is_host else request.app.state.service_port}"
    headers = [(k, v) for k, v in headers if k.lower() != "origin"]
    headers.append(("origin", origin))
    headers.append(("host", f"127.0.0.1:{port}"))
    if origin_is_host:
        # DSH's browser-trust fence also refuses ``Sec-Fetch-Site: cross-site``
        # before it looks at Origin, while a page the console frames on its own
        # origin is same-origin by definition. Dropping the browser's claim
        # rather than rewriting it: the request the proxy sends is not a browser
        # request, and asserting fetch metadata the caller did not make would be
        # a lie the agent then relies on.
        headers = [(k, v) for k, v in headers if k.lower() != "sec-fetch-site"]
    if prefix_root:
        # opencode's own login. The console session already proved this caller
        # is the admin, and the agent's UI/API would otherwise 401 every asset
        # (its ``?auth_token=`` only applies to the request that carried it).
        auth = getattr(spec, "upstream_basic_auth", None)
        if callable(auth):
            credentials = auth(_agent_secret(request.app, agent_id))
            if credentials:
                import base64
                raw = f"{credentials[0]}:{credentials[1]}".encode()
                headers.append((
                    "authorization",
                    "Basic " + base64.b64encode(raw).decode(),
                ))

    body = await request.body()
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(CONNECT_TIMEOUT_S, read=READ_TIMEOUT_S),
        follow_redirects=False,
        trust_env=False,
    )
    try:
        upstream = await client.send(
            client.build_request(
                request.method, url, headers=headers, content=body or None,
            ),
            stream=True,
        )
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning("proxying to %s failed: %s", spec.name, exc)
        raise HTTPException(
            status_code=502,
            detail=f"{spec.name} 的界面暂时不可用（{exc.__class__.__name__}）",
        ) from exc

    # An agent whose page needs a session the console cannot type (DSH) answers
    # the first, cookieless visit with 401. That is the moment to spend the
    # launch token: the agent's own startup URL mints a cookie, and the browser
    # only has to be sent to the page again. Doing it here rather than in the
    # spec keeps the token inside the proxy, which is the one component that
    # already speaks both sides.
    handoff = await _handoff_page(spec, agent_id, request, upstream, client,
                                  port, headers, body)
    if handoff is not None:
        return handoff

    response_headers = _rewrite_headers(
        list(upstream.headers.items()), request.app.state.service_port, spec,
    )
    # Multiple Set-Cookie headers must survive as separate lines; httpx keeps
    # them in .headers but a dict would collapse them.
    response_headers = [
        (k, v) for k, v in response_headers if k.lower() != "set-cookie"
    ] + [("set-cookie", _rewrite_cookie(v, prefix_root, agent_id))
         for v in upstream.headers.get_list("set-cookie")]

    ctype = upstream.headers.get("content-type", "")
    if prefix_root and _is(ctype, HTML_TYPES + CSS_TYPES + JS_TYPES):
        # These three are small and are the only bodies a browser reads URLs
        # out of; buffering them is what makes the rewrite possible at all.
        try:
            payload = await upstream.aread()
        finally:
            await upstream.aclose()
            await client.aclose()
        rewriter = _PrefixRewriter(f"/agents/{agent_id}")
        text = payload.decode("utf-8", "replace")
        if _is(ctype, HTML_TYPES):
            text = rewriter.html(text)
        elif _is(ctype, CSS_TYPES):
            text = rewriter.css(text)
        else:
            text = rewriter.js(text)
        # ``aread()`` returns the *decoded* body -- httpx decompresses on read --
        # so the upstream's ``Content-Encoding`` no longer describes these bytes.
        # Passing it on made the browser try to gunzip plain text.
        response_headers = [(k, v) for k, v in response_headers
                            if k.lower() not in ("content-encoding", "content-length")]
        return _buffered(upstream.status_code, ctype, text, response_headers)

    return _streaming(upstream, client, response_headers)


def _agent_secret(app, agent_id: str) -> str:
    try:
        return app.state.agents.state(agent_id).secret
    except Exception:  # noqa: BLE001 - no secret means no basic auth
        return ""


def _refuse_foreign_origin(spec, origin: str | None, request_or_ws) -> None:
    """Refuse a browser request whose ``Origin`` is not the console's own.

    Why this exists, and why it is checked *before* the rewrite below: for an
    ``origin_is_host`` agent the proxy replaces ``Origin`` with the agent's own
    authority and drops ``Sec-Fetch-Site``, because that agent compares the two
    headers and would 403 otherwise. Doing that unconditionally means the agent's
    own CSRF fence is switched off for every caller, and the only protection left
    is the console session cookie's ``SameSite=Lax``.

    ``Lax`` is not enough here. Another page on the same board at a different
    port -- ``http://<board>:8080/``, say -- is *same-site* (same registrable
    host, scheme-agnostic for this purpose), so its ``fetch`` carries the session
    cookie; ``Origin`` is the only thing that says the request came from a page
    this console did not serve. Without this check such a page could open the
    agent's WebSocket and drive its shell tool, because the agent sees a request
    that looks perfectly same-origin.

    A request with **no** ``Origin`` is allowed: that is a same-origin
    ``GET``/navigation from the console's own page (browsers omit ``Origin`` for
    those), a ``curl``, or the handoff's own server-side exchange. Refusing those
    would break the page for everyone to stop an attack that needs a page to be
    served from somewhere.

    Only ``origin_is_host`` agents are checked: the others (OpenClaw, opencode)
    validate ``Origin`` themselves against a configured allow-list, which this
    proxy already satisfies, so their behaviour is deliberately unchanged.
    """
    if not getattr(spec, "origin_is_host", False):
        return
    if not origin:
        return
    # Compare against the host the *browser* used, which is the only authority
    # that means anything here: the console may be reached by IP, hostname or a
    # forwarding port, and all of those are the caller's own origin.
    headers = getattr(request_or_ws, "headers", {})
    host = headers.get("host") or ""
    if not host:
        return
    parsed = _origin_host(origin)
    if parsed is None:
        # A malformed Origin, or the opaque ``null`` one: no page this console
        # serves can produce either, so treat it as foreign.
        raise HTTPException(status_code=403, detail="跨站请求被拒绝")
    authority, default_port = parsed
    if _same_authority(authority, default_port, host):
        return
    logger.warning("proxying to %s refused: Origin %r is not this console (%r)",
                   getattr(spec, "name", "?"), origin, host)
    raise HTTPException(status_code=403, detail="跨站请求被拒绝")


def _origin_host(origin: str) -> tuple[str, int] | None:
    """``http://host[:port]`` -> (``host[:port]``, the scheme's default port).

    ``None`` when the value is not an http(s) origin at all.
    """
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(origin)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    # urlsplit lower-cases .hostname but not the port; rebuild the authority the
    # same way the browser spells Host so the two compare directly.
    host = parts.hostname.lower()
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    default = 443 if parts.scheme == "https" else 80
    return (f"{host}:{parts.port}" if parts.port else host), default


def _same_authority(origin_authority: str, default_port: int,
                    host_header: str) -> bool:
    """Whether an Origin's authority names the same host:port as ``Host``.

    ``Host`` always carries the port the browser connected to, while ``Origin``
    omits it when it is the scheme's default (``http://h`` has no ``:80``). So
    both are normalised to ``(host, port)``, with the Origin's own scheme
    supplying the default for each side -- the same rule DSH's
    ``isSameAuthorityOrigin`` applies, and for the same reason.
    """
    from urllib.parse import urlsplit

    def split(authority: str, fallback: int) -> tuple[str, int]:
        parts = urlsplit("//" + authority)
        return (parts.hostname or ""), (parts.port or fallback)

    o_host, o_port = split(origin_authority, default_port)
    h_host, h_port = split(host_header, default_port)
    return o_host == h_host and o_port == h_port


async def _handoff_page(spec, agent_id: str, request: Request, upstream,
                        client: httpx.AsyncClient, port: int,
                        headers: list[tuple[str, str]], body: bytes):
    """Log the browser in with the agent's own launch token, once.

    DSH's web profile answers every request without a session cookie with 401,
    and the only way to get one is its startup URL: ``GET /?token=<43 chars>``
    mints a signed cookie and 303-redirects. The token is printed to the agent's
    log and read by the spec, so it never has to reach the console.

    The exchange runs on the *first page request* only. A browser that already
    holds the cookie gets a normal 200, so the ordinary path costs one upstream
    request and nothing else. Returns ``None`` when this is not a handoff, in
    which case the caller carries on with the response it was given.

    Why the redirect is a 303 to the same URL: the browser must re-ask with the
    cookie it was just handed. Anything else -- replaying the body, proxying the
    upstream 303 verbatim -- would send it to DSH's own ``./`` (treated as
    ``/``), which is outside the prefix.
    """
    launch = getattr(spec, "upstream_launch_url", None)
    # ``None`` is how the base class says "this agent has no launch token". The
    # ``callable`` test alone is not enough: every spec inherits the method, so it
    # would be true for opencode, PicoClaw and OpenClaw too -- and their plain
    # 401 would have been replaced by DSH's "no token in the log" explanation,
    # which is a lie about an agent that has no token to look for.
    if not callable(launch):
        return None
    if upstream.status_code != 401:
        return None
    # Only a page navigation is worth a cookie: an asset or an XHR that 401s
    # means the cookie is gone mid-session, and re-minting it here would hide
    # that from the operator while racing every other in-flight request.
    accept = request.headers.get("accept", "")
    if request.method != "GET" or "text/html" not in accept.lower():
        return None
    directory = request.app.state.agents.directory(agent_id)
    try:
        token_url = launch(directory, port)
    except Exception:  # noqa: BLE001 - a broken spec must not break the proxy
        logger.exception("reading %s's launch URL failed", spec.name)
        token_url = ""
    if token_url is None:
        # This agent declared no handoff after all (the base class's answer, or
        # a spec that opted out). Its 401 is the truth: forward it rather than
        # explaining a token that does not exist.
        return None
    # From here the 401 is this service's to resolve, so the upstream response
    # the caller was carrying is of no further use.
    await upstream.aclose()
    if not token_url:
        await client.aclose()
        return _need_login(spec)

    exchange = [(k, v) for k, v in headers if k.lower() != "cookie"]
    try:
        minted = await _spend_token(client, token_url, exchange)
    finally:
        await client.aclose()
    if minted is None:
        return _need_login(spec)
    if minted.status_code not in (200, 303, 302):
        logger.warning("%s: launch-token exchange answered HTTP %d",
                       spec.name, minted.status_code)
        return _need_login(spec)

    cookies = [_rewrite_cookie(v, True, agent_id)
               for v in minted.headers.get_list("set-cookie")]
    if not cookies:
        logger.warning("%s: launch-token exchange set no cookie", spec.name)
        return _need_login(spec)

    redirect = RedirectResponse(request.url.path + (
        f"?{request.url.query}" if request.url.query else ""), status_code=303)
    for cookie in cookies:
        redirect.headers.append("set-cookie", cookie)
    logger.info("%s: exchanged the launch token for a session cookie", spec.name)
    return redirect


async def _spend_token(client: httpx.AsyncClient, token_url: str,
                       headers: list[tuple[str, str]]):
    """``GET`` the agent's tokenized startup URL without logging the token.

    ``httpx`` logs every request at INFO -- ``HTTP Request: GET
    http://127.0.0.1:14099/?token=… "HTTP/1.1 303 See Other"`` -- and this
    service's root logger is INFO, so the obvious implementation would write the
    one credential DSH never shows anywhere into the service log, which an
    operator is far more likely to paste into a bug report than the agent's own
    log.

    So a filter on the ``httpx`` logger redacts ``token=`` in every record it
    emits. A filter rather than raising the logger's level around the call: the
    level is process-global, and two exchanges overlapping across the ``await``
    would restore each other's saved level -- leaking the second token at INFO
    and silencing ``httpx`` for good. And a transport error -- whose message carries the full
    URL -- is logged here with the token already redacted rather than re-raised
    with the URL intact.

    Returns the response, or ``None`` when the exchange could not be made at all
    (which the caller reports as "no usable credential", the same answer as an
    empty launch URL).
    """
    _install_token_redaction()
    try:
        return await client.get(token_url, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("launch-token exchange failed: %s", _redact_token(str(exc)))
        return None


class _TokenRedactor(logging.Filter):
    """Rewrite ``token=<value>`` in a log record before any handler sees it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a malformed record is not ours to fix
            return True
        redacted = _redact_token(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


_TOKEN_FILTER = _TokenRedactor()


def _install_token_redaction() -> None:
    """Attach the redactor to ``httpx``'s logger once; idempotent."""
    httpx_logger = logging.getLogger("httpx")
    if _TOKEN_FILTER not in httpx_logger.filters:
        httpx_logger.addFilter(_TOKEN_FILTER)


def _redact_token(text: str) -> str:
    return re.sub(r"token=[A-Za-z0-9_-]+", "token=<redacted>", str(text))


def _need_login(spec) -> Response:
    """The page the console shows when the handoff could not be made.

    A 401 with no body renders as the console's own error overlay inside the
    frame, which says nothing about what to do. This says it once, in the same
    words as the other agent refusals.
    """
    return Response(
        f"{spec.name} 还没有可用的登录凭据：启动日志里没有带 token 的地址。"
        "请在 Agent 页点「重启」，或查看日志后重试。",
        status_code=503, media_type="text/plain; charset=utf-8",
    )


def _upstream_ws_path(spec, browser_path: str) -> str:
    """The path the agent's own server answers a WebSocket upgrade on.

    Same rule as the HTTP side, and it has to be here too: a ``prefix_root``
    agent serves its sockets from its own root. PicoClaw's launcher opens
    ``/pico/ws`` from the page, which the shim moves to
    ``/agents/picoclaw/pico/ws``; forwarding that unchanged asks the launcher
    for a path it has never heard of and the upgrade fails with a 404 the
    console cannot distinguish from "the agent is down".

    A non-prefix agent (OpenClaw) is configured with this prefix as its
    ``basePath``, so the path it receives must stay exactly as the browser sent
    it.
    """
    if not getattr(spec, "prefix_root", False):
        return browser_path
    prefix = f"/agents/{getattr(spec, 'id', '')}"
    if browser_path == prefix:
        return "/"
    if browser_path.startswith(prefix + "/"):
        return browser_path[len(prefix):]
    return browser_path


def _rewrite_cookie(value: str, prefix_root: bool, agent_id: str) -> str:
    """Keep the agent's cookies inside its subtree.

    A ``Path=/`` cookie from an origin-root app would be sent to every console
    route as well, and two agents (or two consoles) would then fight over the
    same name. Narrowing it to the agent's prefix is what makes several agents
    coexist on one origin.
    """
    if not prefix_root:
        return value
    prefix = f"/agents/{agent_id}"
    parts = [p.strip() for p in value.split(";")]
    out: list[str] = []
    had_path = False
    for part in parts:
        if part.lower().startswith("path="):
            had_path = True
            path = part.split("=", 1)[1].strip()
            if path in ("", "/"):
                out.append(f"Path={prefix}/")
            elif not (path == prefix or path.startswith(prefix + "/")):
                out.append(f"Path={prefix}{path if path.startswith('/') else '/' + path}")
            else:
                out.append(part)
        else:
            out.append(part)
    if not had_path:
        out.append(f"Path={prefix}/")
    return "; ".join(out)


def _buffered(status_code: int, content_type: str, text: str,
              headers: list[tuple[str, str]]) -> Response:
    """A Response carrying rewritten text and the upstream's header list."""
    response = Response(text.encode("utf-8"), status_code=status_code,
                        media_type=content_type or None)
    # Drop the upstream's content-length: the rewrite changed the length, and a
    # wrong one truncates the body in the browser.
    keep = [(k, v) for k, v in headers if k.lower() != "content-length"]
    response.raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in keep
    ] + [(b"content-length", str(len(response.body)).encode("latin-1"))]
    return response


def _streaming(upstream, client, headers: list[tuple[str, str]]) -> StreamingResponse:
    """A StreamingResponse that can carry duplicate headers (Set-Cookie)."""

    async def body_iter():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    response = StreamingResponse(
        body_iter(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )
    # Starlette stores headers in a mutable list; replacing it wholesale is how
    # duplicates (Set-Cookie) survive.
    response.raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers
    ]
    return response


@router.websocket("/agents/{agent_id}/{path:path}")
async def proxy_ws(websocket: WebSocket, agent_id: str, path: str):
    """Bridge one browser WebSocket to the agent's gateway.

    The Control UI is a live WebSocket client: everything it shows comes over
    this socket, so a broken proxy here looks like a console that connects and
    then does nothing.
    """
    await _bridge_ws(websocket, agent_id)


@router.websocket("/agents/{agent_id}")
async def proxy_ws_at_the_prefix(websocket: WebSocket, agent_id: str):
    """The same bridge one level up, for the URL the Control UI actually uses.

    Measured against OpenClaw 2026.10.7: the UI's default gateway URL is
    ``<origin>/agents/openclaw`` -- ``controlUi.basePath`` with no trailing
    slash. Starlette's ``{path:path}`` only matches when the segment after the
    prefix exists, so that exact URL fell through to the HTTP route and the
    upgrade was answered with 403 (a real "Gateway unreachable" in the embedded
    panel, while ``/agents/openclaw/`` connected fine). Registering the bare
    prefix keeps the UI's own default working instead of patching it in
    JavaScript we do not own.
    """
    await _bridge_ws(websocket, agent_id)


def _ws_connect_kwargs(headers: list[tuple[str, str]]) -> dict:
    """The header keyword ``websockets.connect`` wants, whatever version it is.

    The handshake headers were renamed in websockets 14: ``extra_headers`` (≤13)
    became ``additional_headers`` (≥14). ``requirements-vendor.txt`` allows
    ``>=13,<15``, so both spellings are live on real installations, and passing
    the wrong one is not a warning -- 13.1 hands it to the loop's
    ``create_connection`` and raises ``TypeError``, which is a dead WebSocket and
    so a Control UI that connects and then shows nothing.

    Detected from the installed signature rather than from a version string: a
    downstream package can be vendored under a different version number, but the
    keyword it accepts is the thing that actually matters.
    """
    import inspect

    import websockets

    try:
        params = inspect.signature(websockets.connect).parameters
    except (TypeError, ValueError):  # pragma: no cover - exotic build
        params = {}
    name = "additional_headers" if "additional_headers" in params else "extra_headers"
    return {name: headers}


async def _bridge_ws(websocket: WebSocket, agent_id: str) -> None:
    if not _authenticated_ws(websocket):
        # Accept first, then close: a refusal before accept reaches the browser
        # as an opaque HTTP 403 on the upgrade, which looks identical to "the
        # agent is down". Accepting and closing with 1008 is a WebSocket-level
        # "policy violation", which the embedded page can recognise and react to
        # (it reloads the console login instead of showing a blank frame).
        await websocket.accept()
        await websocket.close(code=1008, reason="admin login required")
        return
    try:
        spec, port = _proxy_target(websocket, agent_id)
    except HTTPException as exc:
        await websocket.accept()
        await websocket.close(code=1011, reason=str(exc.detail))
        return

    # The same Origin rule as the HTTP side, and it matters more here: a
    # WebSocket carries no CORS preflight and no ``Sec-Fetch-Site`` the agent
    # would still see (the handshake cannot set that header), so a page on
    # another port of this board could otherwise open the agent's channel and
    # drive its tools. Checked before the upstream connection so a foreign page
    # never reaches the agent at all.
    try:
        _refuse_foreign_origin(spec, websocket.headers.get("origin"), websocket)
    except HTTPException as exc:
        await websocket.accept()
        await websocket.close(code=1008, reason=str(exc.detail))
        return

    import websockets

    query = websocket.url.query
    upstream_url = f"ws://127.0.0.1:{port}{_upstream_ws_path(spec, websocket.url.path)}"
    if query:
        upstream_url += f"?{query}"
    service_port = websocket.app.state.service_port
    # ``Host`` is deliberately NOT set: the WebSocket client derives it from the
    # URL, and passing one as an extra handshake header sends a second, malformed
    # ``Host`` line -- measured against PicoClaw 0.3.1's launcher, which answers
    # that upgrade with 400 while the identical connection without it succeeds.
    # OpenClaw tolerated the duplicate, which is why this only showed up now.
    #
    # Origin follows the same rule as the HTTP side: an agent that compares it
    # against Host (DSH) is sent no Origin at all rather than one naming a
    # different authority. Its fence treats a missing Origin as trusted -- the
    # handshake already had to present the session cookie -- while a mismatched
    # one is refused before the cookie is even read.
    headers = [] if getattr(spec, "origin_is_host", False) else [
        ("Origin", f"http://127.0.0.1:{service_port}")]
    if getattr(spec, "prefix_root", False):
        # Same reasoning as the HTTP side: the agent's own login, spoken by the
        # proxy for the admin session it already verified.
        auth = getattr(spec, "upstream_basic_auth", None)
        if callable(auth):
            credentials = auth(_agent_secret(websocket.app, agent_id))
            if credentials:
                import base64
                raw = f"{credentials[0]}:{credentials[1]}".encode()
                headers.append(("Authorization",
                                "Basic " + base64.b64encode(raw).decode()))
    # Client cookies carry the agent's own session once the UI has logged in;
    # without them the gateway would treat every reconnect as unauthenticated.
    cookie = websocket.headers.get("cookie")
    if cookie:
        headers.append(("Cookie", cookie))

    try:
        upstream = await websockets.connect(
            upstream_url,
            **_ws_connect_kwargs(headers),
            open_timeout=30,
            max_size=None,
            ping_interval=None,
        )
    except Exception as exc:  # noqa: BLE001 - any failure means "not reachable"
        logger.warning("websocket to %s failed: %s", spec.name, exc)
        await websocket.close(code=1011, reason="agent gateway unreachable")
        return

    await websocket.accept()

    import asyncio

    async def browser_to_agent() -> None:
        try:
            while True:
                message = await websocket.receive()
                kind = message.get("type")
                if kind == "websocket.disconnect":
                    return
                if message.get("text") is not None:
                    await upstream.send(message["text"])
                elif message.get("bytes") is not None:
                    await upstream.send(message["bytes"])
        except (WebSocketDisconnect, RuntimeError):
            return
        except Exception:  # noqa: BLE001 - a closed socket ends the pump
            return

    async def agent_to_browser() -> None:
        try:
            async for message in upstream:
                if isinstance(message, str):
                    await websocket.send_text(message)
                else:
                    await websocket.send_bytes(message)
        except Exception:  # noqa: BLE001 - a closed socket ends the pump
            return

    tasks = [
        asyncio.create_task(browser_to_agent()),
        asyncio.create_task(agent_to_browser()),
    ]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in pending:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    finally:
        try:
            await upstream.close()
        except Exception:  # noqa: BLE001 - closing anyway
            pass
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001 - already closed by the browser
            pass
