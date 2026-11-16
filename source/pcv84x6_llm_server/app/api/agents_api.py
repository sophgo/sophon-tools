"""The agent surface: install, run, configure and read logs.

Every route is admin-only for the same reason the model routes are: starting an
agent runs downloaded code as this service's user, and the agent's config holds
an API key.

Errors are shaped for the console rather than for a shell: a refusal the
operator can act on (not enough memory, port taken, not installed) is a 4xx
with a Chinese ``detail``, and the UI shows that string verbatim.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..agents.manager import AgentBusy, PortBusy
from ..agents.spec import AgentError
from ..core.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter()


class AgentPatch(BaseModel):
    """Only the settings the console exposes; anything absent is left alone."""

    port: int | None = None
    autostart: bool | None = None
    default_model: str | None = None
    thinking: bool | None = None


def _manager(request: Request):
    return request.app.state.agents


def _translate(exc: Exception) -> HTTPException:
    """Map the manager's exceptions onto the status codes the console expects."""
    if isinstance(exc, PortBusy):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, AgentBusy):
        # Memory refusal, already-installed, and a failed start are all "the
        # request was fine, the state is not", which is 409 rather than 400.
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, AgentError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.get("/agents")
async def list_agents(request: Request, _=Depends(require_admin)):
    mgr = _manager(request)
    return {"agents": mgr.status(host=_browser_host(request))}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, request: Request, _=Depends(require_admin)):
    try:
        return _manager(request).status_one(agent_id, host=_browser_host(request))
    except (AgentError, AgentBusy) as exc:
        raise _translate(exc) from exc


@router.post("/agents/{agent_id}/install", status_code=202)
async def install(agent_id: str, request: Request, _=Depends(require_admin)):
    """Start the download; poll GET /agents/{id}/job for progress."""
    try:
        job = await _manager(request).install(agent_id)
    except (AgentError, AgentBusy) as exc:
        raise _translate(exc) from exc
    return {"job": job.public()}


@router.get("/agents/{agent_id}/job")
async def job(agent_id: str, request: Request, _=Depends(require_admin)):
    try:
        return {"job": _manager(request).job(agent_id)}
    except (AgentError, AgentBusy) as exc:
        raise _translate(exc) from exc


async def _act(request: Request, agent_id: str, action: str):
    mgr = _manager(request)
    host = _browser_host(request)
    try:
        if action == "start":
            await mgr.start(agent_id)
        elif action == "stop":
            await mgr.stop(agent_id)
        elif action == "restart":
            await mgr.restart(agent_id)
        elif action == "reset":
            await mgr.reset(agent_id)
        elif action == "uninstall":
            await mgr.uninstall(agent_id)
        elif action == "sync":
            await mgr.sync(agent_id)
        else:
            raise HTTPException(status_code=404, detail=f"未知操作：{action}")
        # Always re-read with the caller's host rather than returning what the
        # manager saw: its own view defaults to loopback, which is the wrong
        # link for a browser, and after an uninstall/reset the manager replaced
        # the runtime the response would have quoted.
        return mgr.status_one(agent_id, host=host)
    except (AgentError, AgentBusy) as exc:
        raise _translate(exc) from exc


@router.post("/agents/{agent_id}/{action}")
async def agent_action(agent_id: str, action: str, request: Request, _=Depends(require_admin)):
    if action not in ("start", "stop", "restart", "reset", "uninstall", "sync"):
        raise HTTPException(status_code=404, detail=f"未知操作：{action}")
    return await _act(request, agent_id, action)


@router.patch("/agents/{agent_id}")
async def patch_agent(
    agent_id: str, body: AgentPatch, request: Request, _=Depends(require_admin),
):
    """Change port/autostart/model/thinking; a port change restarts a live agent."""
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return await _manager(request).patch(agent_id, changes)
    except (AgentError, AgentBusy) as exc:
        raise _translate(exc) from exc


@router.get("/agents/{agent_id}/logs")
async def agent_logs(
    agent_id: str, request: Request, tail: int = 200, _=Depends(require_admin),
):
    try:
        return {"log": _manager(request).logs(agent_id, tail)}
    except (AgentError, AgentBusy) as exc:
        raise _translate(exc) from exc


def _browser_host(request: Request) -> str:
    """The host the operator's browser reached us on.

    The agent serves its own UI on another port of this same board, so the link
    has to carry the host the browser already used -- ``request.url.hostname``
    is the board's address as the client knows it, which is what makes the URL
    work from another machine and not just from the board itself.
    """
    host = (request.url.hostname or "").strip()
    if not host or host in ("0.0.0.0", "::"):
        host = request.headers.get("host", "").split(":")[0] or "127.0.0.1"
    return host
