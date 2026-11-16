"""Behaviour when a worker dies or hangs -- the failure modes seen on this board."""

import asyncio
import os
import signal
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.client import WorkerClient, WorkerError
from app.main import create_app


def make_model(root: Path, name: str):
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{name}_seq2048_4core.bmodel").write_bytes(b"\x00" * 512)
    (d / "config" / "config.json").write_text("{}")


@pytest.fixture()
def client_and_app(tmp_path):
    models = tmp_path / "models"
    make_model(models, "m")
    app = create_app(data_dir=tmp_path / "data", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web",
                     context_length_override=4096)
    with TestClient(app) as c:
        c.post("/api/login", json={"password": "admin"})
        c.post("/api/models/m/load")
        yield c, app


def test_killed_worker_reports_error_not_hang(client_and_app):
    """A crashed worker must produce a prompt error, not a stuck request."""
    c, app = client_and_app
    key = c.post("/api/keys", json={"name": "k"}).json()["key"]
    info = app.state.models.get("m")
    assert info is not None

    os.kill(info.pid, signal.SIGKILL)
    time.sleep(0.5)

    r = c.post("/v1/chat/completions",
               headers={"Authorization": f"Bearer {key}"},
               json={"model": "m", "messages": [{"role": "user", "content": "hi"}],
                     "max_tokens": 4})
    # 503 = backend unavailable (retryable after a reload), not a bare 500.
    assert r.status_code == 503, (r.status_code, r.text)
    assert "模型进程" in r.json()["detail"]
    # The service itself is still up: it did not take the management plane down.
    assert c.get("/healthz").status_code == 200


def test_unload_after_crash_still_works(client_and_app):
    """The operator must be able to recover through the UI after a crash."""
    c, app = client_and_app
    info = app.state.models.get("m")
    os.kill(info.pid, signal.SIGKILL)
    time.sleep(0.4)
    r = c.post("/api/models/m/unload")
    assert r.status_code == 200, r.text
    assert c.get("/api/models").json()["models"][0]["loaded"] is False
    # And it can be loaded again.
    assert c.post("/api/models/m/load").status_code == 200


@pytest.mark.asyncio
async def test_client_raises_when_worker_closes_mid_call():
    """A worker that drops the connection must wake every waiter, not hang.

    The handler reads the request, then closes -- which is what a worker does
    when it is killed or hits an OOM: the reply never arrives.
    """
    async def handler(reader, writer):
        await reader.readline()
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    c = WorkerClient(port)
    try:
        # Must raise rather than block until the 10s timeout, and must be a
        # WorkerError so callers can show a useful message.
        with pytest.raises(WorkerError):
            await asyncio.wait_for(c.health(), timeout=5)
    finally:
        await c.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_client_raises_when_nothing_is_listening():
    """Connecting to a dead worker port must fail fast with WorkerError."""
    c = WorkerClient(1)  # nothing listens on port 1
    with pytest.raises(WorkerError):
        await asyncio.wait_for(c.health(), timeout=5)
    await c.close()
