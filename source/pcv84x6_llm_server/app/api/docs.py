"""Attach the ``/api`` documentation metadata to the live routes (MYS-2676).

FastAPI reads a route's ``tags`` / ``summary`` / ``responses`` when it builds the
OpenAPI document, and the document is rebuilt on every ``/api/openapi.json``
request -- so setting those attributes on the route objects *after*
``include_router`` is enough, and it is what lets the metadata live in
:mod:`app.api.api_docs` as pure data instead of as a dozen keyword arguments on
each of sixty decorators.

FastAPI 0.143 keeps the routes of an included router behind an
``_IncludedRouter`` wrapper and builds a cached presentation record per route, so
"after include_router" means two extra steps: reach the *original* ``APIRoute``
objects through that wrapper, then tell the router its presentation cache is
stale. Both are handled in :func:`_api_routes` and :func:`_invalidate`.

What is enforced, for every ``/api`` route:

* a ``tags`` entry naming one of :data:`app.api.api_docs.TAGS` -- the module the
  page belongs to, which is how Swagger groups them;
* a Chinese ``summary`` (one line) and ``description`` (a paragraph);
* a documented **success** response with a schema (or an explicit content type
  for the streaming/download routes, whose body is not JSON);
* every documented **error** as the shared ``ErrorOut`` body, plus the two the
  auth dependency produces on every route (401 / 403), plus 422 where the route
  takes a body or parameters;
* an ``operationId`` derived from tag + path, so generated clients get stable
  method names instead of ``list_models_api_models_get``.

``tests/test_admin_api_docs.py`` walks the built document and fails if any of
that is missing, if an entry here matches no route, or if a route's status code
disagrees with the one documented here -- so this file cannot silently rot.
"""

from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.routing import APIRoute

from ..core.errors import ERROR_CODES
from . import admin_schemas as s
from .api_docs import COMMON_ERRORS, DOCS, TAGS


#: Statuses whose set of codes is small enough to print on every operation. A
#: 409 can carry any of a dozen "wrong state" codes and a 503 three, so those two
#: point at the error table instead of repeating it under every route -- a
#: response block listing eleven codes for one route reads as noise and stops
#: being read at all.
_ENUMERATE_CODES = frozenset({400, 404, 405, 413, 415, 422, 429, 500})


def _error_responses(statuses) -> dict[int, dict]:
    """``{status: {"model": ErrorOut}}`` for the given statuses.

    One shared body for every error is the point of the contract: a client
    parses ``{detail, code}`` once and applies it everywhere.
    """
    codes_by_status: dict[int, list[str]] = {}
    for row in ERROR_CODES:
        codes_by_status.setdefault(row.status, []).append(row.code)
    out: dict[int, dict] = {}
    for status in sorted(statuses):
        detail = "错误响应：`detail` 是中文说明，`code` 是稳定错误码。"
        names = codes_by_status.get(status, []) if status in _ENUMERATE_CODES else []
        if names:
            detail += "该状态可能出现的 `code`：" + "、".join(f"`{c}`" for c in names) + "。"
        elif status in codes_by_status:
            detail += f"该状态的具体 `code` 见「错误码」一节（{status} 有多种）。"
        out[status] = {"model": s.ErrorOut, "description": detail}
    return out


def operation_id(tag: str, method: str, path: str) -> str:
    """``models`` + ``GET /api/models/{model_id}/log`` -> ``models_get_model_log``.

    Derived rather than hand-written so a renamed path cannot leave two routes
    sharing an ``operationId`` (FastAPI would accept the collision silently and
    a generated client would keep only one of the two methods). The method is
    part of the name because several paths serve two verbs -- ``GET`` and ``PUT``
    on ``/api/models/{id}/settings`` are different operations. The path's
    parameters keep their noun (minus the ``_id`` suffix) and lose the braces, and
    a leading word equal to the tag is dropped, so the name reads as
    ``models_post_model_load`` rather than ``models_post_models_model_load``.
    """
    words = [part for part in re.split(r"[/\-]", path.removeprefix("/api").strip("/"))
             if part]
    if words and words[0] == tag:
        words = words[1:]
    words = [w.strip("{}").removesuffix("_id") for w in words]
    return "_".join([tag, method.lower(), *words])


def _apply_route(route: APIRoute, path: str, entry: dict,
                 seen: set[tuple[str, str]],
                 declared: dict[tuple[str, str], set[int]] | None = None) -> None:
    method = sorted(m.upper() for m in route.methods)[0]
    tag = entry["tag"]
    status = entry.get("status", 200)
    route.tags = [tag]
    route.summary = entry["summary"]
    route.description = entry["description"]
    route.operation_id = operation_id(tag, method, path)
    responses: dict[int, dict] = {}
    if entry.get("response") is not None:
        responses[status] = {"model": entry["response"],
                            "description": entry["summary"]}
    elif entry.get("content"):
        # A streaming or download route: the body is not JSON, so it is declared
        # by media type. This is what tells a reader that `/api/chat/stream`
        # answers SSE frames and that `-o file` on curl is the right move.
        responses[status] = {"description": entry["summary"],
                            "content": {entry["content"]: {"schema": {"type": "string"}}}}
    else:
        responses[status] = {"description": entry["summary"]}
    statuses = set(entry.get("errors") or ())
    if entry.get("auth", True):
        statuses.update(COMMON_ERRORS)
    if entry.get("body") is not None or _has_inputs(route):
        # FastAPI injects a 422 for any route with a body or parameters, and
        # would otherwise document pydantic's own array-of-errors shape -- which
        # this service does not return. Documenting it here replaces that entry.
        statuses.add(422)
    responses.update(_error_responses(statuses))
    route.responses = responses
    for m in route.methods:
        upper = m.upper()
        seen.add((upper, path))
        if declared is not None:
            declared.setdefault((upper, path), set()).add(status)


def _clean_responses(spec: dict, declared: dict[tuple[str, str], set[int]]) -> None:
    """Remove the placeholders FastAPI adds beside the responses this table sets.

    Two artifacts, both from ``get_openapi_path`` writing the route's *own*
    ``response_class`` media type underneath whatever ``route.responses`` said:

    * a route registered with ``status_code=202`` also gets a ``200`` entry with
      FastAPI's default description ("Successful Response") and an empty schema.
      No such response exists, and a client generator would emit a second method
      for it.
    * a route whose real body is SSE or NDJSON gets an ``application/json`` entry
      with an empty schema next to the media type declared here. ``POST
      /api/chat/stream`` does not answer JSON, and an empty schema reads as "a
      JSON body of unknown shape" -- the opposite of the truth.

    Both are identified precisely: an entry or media type whose schema is the
    empty object, and a status this table did not declare for that operation (a
    declared one keeps its description, which is what the second artifact leaves
    behind). A route that genuinely returns an empty JSON object still has its
    media type removed, so no schema is claimed for it -- which is honest, and
    none of them does.
    """
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            responses = operation.get("responses") or {}
            declared_statuses = declared.get((method.upper(), path), set())
            for code in list(responses):
                entry = responses[code]
                content = entry.get("content") or {}
                empty = [media for media, body in content.items()
                         if isinstance(body, dict) and body.get("schema") == {}]
                for media in empty:
                    # Keep a media type only if it is the one this table declared
                    # and there is nothing else to point at.
                    if len(content) > 1:
                        del content[media]
                if (entry.get("description") == "Successful Response"
                        and int(code) not in declared_statuses):
                    del responses[code]


def apply(app: FastAPI) -> None:
    """Attach metadata from :data:`DOCS` to every registered ``/api`` route."""
    seen: set[tuple[str, str]] = set()
    declared: dict[tuple[str, str], set[int]] = {}
    for router, path, route in _api_routes(app):
        method = sorted(m.upper() for m in route.methods)[0]
        entry = DOCS.get((method, path))
        if entry is None:
            continue
        _apply_route(route, path, entry, seen, declared)
    for router in {id(r): r for r, _, _ in _api_routes(app)}.values():
        # The presentation record FastAPI caches per route was built when the
        # router was included; without this it would keep serving the summary and
        # tags from before the mutation above.
        router._mark_routes_changed()
    stray = set(DOCS) - seen
    undocumented = [(m, path) for _router, path, route in _api_routes(app)
                    for m in sorted(x.upper() for x in route.methods)
                    if (m, path) not in DOCS]
    if stray or undocumented:
        # Loud at import time rather than a quietly incomplete document: an
        # undescribed route is exactly the failure this task exists to remove.
        raise RuntimeError(
            "admin API documentation table does not match the routes: "
            f"undocumented={undocumented} documented-but-missing={sorted(stray)}")
    app.openapi_tags = TAGS
    # The placeholders are stripped by wrapping ``openapi`` itself rather than by
    # building the document here and caching it: routes registered after this
    # call (the SPA catch-all and its mount, in ``_mount_web``) bump FastAPI's
    # route version, which makes the next ``openapi()`` rebuild from scratch --
    # and a document cached now would silently lose the cleanup. Wrapping keeps
    # the cleanup attached to the build, however many times it happens.
    _wrap_openapi(app, declared)


def _wrap_openapi(app: FastAPI, declared: dict[tuple[str, str], set[int]]) -> None:
    """Make ``app.openapi()`` clean the placeholders out of whatever it returns."""
    original = app.openapi

    def openapi() -> dict:
        spec = original()
        _clean_responses(spec, declared)
        return spec

    app.openapi = openapi  # type: ignore[method-assign]


def _has_inputs(route: APIRoute) -> bool:
    """True when the handler really takes a body, a path or a query parameter."""
    dependant = route.dependant
    return bool(dependant.body_params or dependant.path_params
                or dependant.query_params)


def _api_routes(app: FastAPI):
    """``(router, full path, APIRoute)`` for every ``/api`` operation.

    Two levels of indirection to undo. FastAPI 0.143 stores an included router as
    an ``_IncludedRouter`` whose ``original_router.routes`` are the real
    ``APIRoute`` objects -- mutating the wrapper changes nothing the document
    reads -- and those routes carry the *unprefixed* path, because the prefix
    lives on the include context. So the path is rebuilt here exactly the way the
    include did it, which is also what the document will print.
    """
    from fastapi.routing import _IncludedRouter

    def walk(routes, prefix: str):
        for route in routes:
            if isinstance(route, _IncludedRouter):
                yield from walk(route.original_router.routes,
                                prefix + route.include_context.prefix)
            elif (isinstance(route, APIRoute) and route.include_in_schema
                  and (prefix + route.path).startswith("/api/")):
                yield route, prefix + route.path

    for route, path in walk(app.router.routes, ""):
        yield _owning_router(app, route), path, route


def _owning_router(app: FastAPI, route: APIRoute):
    """The router ``route`` was declared on (the one whose cache must be dropped).

    Every router's own ``routes`` list holds the routes declared on *it*, so the
    owner is the router that lists ``route`` directly -- ``app.router`` for the
    handful of paths created inside ``create_app``, one of the included routers
    for everything else.
    """
    for candidate in _all_routers(app):
        if route in candidate.routes:
            return candidate
    return app.router


def _all_routers(app: FastAPI):
    from fastapi.routing import _IncludedRouter

    seen: set[int] = set()

    def walk(router):
        if id(router) in seen:
            return
        seen.add(id(router))
        yield router
        for route in router.routes:
            if isinstance(route, _IncludedRouter):
                yield from walk(route.original_router)

    yield from walk(app.router)


def api_route_count(app: FastAPI) -> int:
    """How many ``/api`` operations the document describes (used by the tests)."""
    return sum(len(route.methods) for _router, _path, route in _api_routes(app))
