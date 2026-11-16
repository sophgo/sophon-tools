"""End-to-end proof: restart the real service around a real worker and agent.

Not a pytest case because it needs two separate service processes (that is what
a restart is) and a real HTTP client against both. Everything here is what the
board would do:

  1. start ``python -m app.main`` on a temp data root, ``--backend mock``;
  2. load a model through the API and start an agent with autostart on;
  3. kill -9 the service -- no shutdown hook runs, so the children are orphaned
     exactly as the unit's ``KillMode=process`` leaves them;
  4. start the service again on the same data root;
  5. assert: the worker pid and the agent pid are unchanged, no new pid was
     spawned, the model is ``loaded`` with a working completion, the agent is
     ``running`` with a reachable ``web_url`` and the proxy answers.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ADMIN = "admin"

FAKE_AGENT = """\
import http.server, json, os, socketserver, sys

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_GET(self):
        body = json.dumps({'ok': True, 'pid': os.getpid()}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

class Server(socketserver.TCPServer):
    allow_reuse_address = True

port = int(sys.argv[sys.argv.index('--port') + 1])
Server(('0.0.0.0', port), Handler).serve_forever()
"""

SPEC = '''\
from pathlib import Path
import sys
from app.agents.spec import AgentSpec

class E2ESpec(AgentSpec):
    id = "e2e"
    name = "e2e agent"
    version = "1.0.0"
    default_port = %(port)d
    embeddable = True
    proxied = True
    start_timeout = 20.0
    executable = "e2e-agent"
    payload_root = "bin"
    key_in_config = False

    def command(self, directory: Path, port: int) -> list[str]:
        return [sys.executable, str(Path(directory) / "bin" / "e2e-agent"),
                "--port", str(port)]
'''


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_model(root: Path, name: str = "m") -> None:
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{name}_int4_w4bf16_seq2048_4core_dynamic.bmodel").write_bytes(b"\x00" * 1024)
    (d / "config" / "config.json").write_text("{}")


class Client:
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self.cookie = ""
        self.bearer = ""

    def call(self, path: str, *, method: str = "GET", body: dict | None = None,
             timeout: float = 60.0):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        if self.bearer:
            req.add_header("Authorization", f"Bearer {self.bearer}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                for header in r.headers.get_all("Set-Cookie") or []:
                    if header.startswith("cv84x6_admin="):
                        self.cookie = header.split(";")[0]
                return r.status, json.loads(raw or b"null")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"null")

    def login(self) -> None:
        code, _ = self.call("/api/login", method="POST", body={"password": ADMIN})
        assert code == 200, code


def wait_http(port: int, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as r:
                if r.status == 200:
                    return True
        except OSError:
            time.sleep(0.2)
    return False


def start_service(data_root: Path, port: int, spec_file: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BASE)
    log = open(data_root.parent / f"service-{port}.log", "ab")
    return subprocess.Popen(
        [sys.executable, "-m", "app.main", "--host", "127.0.0.1", "--port", str(port),
         "--backend", "mock", "--data-root", str(data_root),
         "--install-dir", str(BASE)],
        cwd=str(BASE), env=env, stdout=log, stderr=log, start_new_session=True,
    )


def frozen_worker_case(tmp: Path, env: dict) -> list[tuple[str, bool, str]]:
    """The other half: a survivor that cannot serve must be refused, not doubled.

    A worker frozen with SIGSTOP is the shape of "still mapping weights": the
    process is provably ours (right argv, right cwd, right model) and it never
    answers. The service must report a conflict, refuse a load (409) instead of
    starting a second worker, and only ``unload`` may end it -- with SIGTERM.
    """
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))
        print(("  PASS  " if ok else "  FAIL  ") + name + (f"  [{detail}]" if detail else ""))

    data_root = tmp / "root2"
    (data_root / "models").mkdir(parents=True)
    make_model(data_root / "models")
    worker_port = free_port()
    bmodel = next((data_root / "models" / "m").glob("*.bmodel"))
    worker = subprocess.Popen(
        [sys.executable, "-m", "app.engine.worker", "--model-id", "m",
         "--port", str(worker_port), "--backend", "mock",
         "--model-path", str(bmodel),
         "--config-path", str(data_root / "models" / "m" / "config")],
        cwd=str(BASE), env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + 20
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", worker_port)) == 0:
                break
        time.sleep(0.1)
    os.kill(worker.pid, signal.SIGSTOP)
    svc_port = free_port()
    launcher = tmp / "serve2.py"
    launcher.write_text(
        "import sys, uvicorn\n"
        f"sys.path.insert(0, {str(BASE)!r})\n"
        "from pathlib import Path\n"
        "from app.main import create_app\n"
        f"app = create_app(data_root=Path({str(data_root)!r}), backend_kind='mock',\n"
        f"                  service_port={svc_port}, agent_specs=[])\n"
        f"uvicorn.run(app, host='127.0.0.1', port={svc_port}, log_level='warning')\n")
    logs = open(tmp / "service2.log", "ab")
    svc = subprocess.Popen([sys.executable, str(launcher)], cwd=str(BASE), env=env,
                           stdout=logs, stderr=logs, start_new_session=True)
    try:
        assert wait_http(svc_port)
        c = Client(svc_port)
        c.login()
        code, body = c.call("/api/models")
        m = {x["id"]: x for x in body["models"]}["m"]
        check("frozen worker reported as conflict, not loaded",
              m["loaded"] is False and bool(m["conflict"]),
              json.dumps({k: m.get(k) for k in ("loaded", "pid", "conflict")}))
        check("conflict names the real pid", m.get("pid") == worker.pid,
              f"{m.get('pid')} vs {worker.pid}")
        code, body = c.call("/api/models/m/load", method="POST")
        check("load refused with 409", code == 409, f"HTTP {code}")
        # Critically: no second worker appeared.
        same = _matching_workers(worker_port)
        check("no second worker was spawned", same == [worker.pid], f"{same}")
        # Let it answer the SIGTERM, then unload is the way out.
        os.kill(worker.pid, signal.SIGCONT)
        code, body = c.call("/api/models/m/unload", method="POST", timeout=180)
        check("unload clears the conflict", code == 200 and not body["model"]["conflict"],
              f"HTTP {code}")
        deadline = time.time() + 30
        while time.time() < deadline and worker.poll() is None:
            time.sleep(0.1)
        check("the conflicted worker exited", worker.poll() is not None)
        code, body = c.call("/api/models")
        m = {x["id"]: x for x in body["models"]}["m"]
        check("model is idle again (no stale conflict)",
              m["loaded"] is False and m["conflict"] is None)
    finally:
        os.killpg(os.getpgid(svc.pid), signal.SIGKILL)
        svc.wait(timeout=20)
        if worker.poll() is None:
            os.killpg(os.getpgid(worker.pid), signal.SIGKILL)
            worker.wait(timeout=10)
    return checks


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mys2392-e2e-"))
    data_root = tmp / "root"
    spec_file = tmp / "e2e_spec.py"
    agent_port = free_port()
    spec_file.write_text(SPEC % {"port": agent_port})
    print(f"data root: {data_root}")
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))
        print(("  PASS  " if ok else "  FAIL  ") + name + (f"  [{detail}]" if detail else ""))

    # -- boot the service with the agent spec ------------------------------
    svc_port = free_port()
    # The spec has to reach create_app; the service is normally started with the
    # built-in specs, so a tiny launcher is used instead of app.main's CLI.
    launcher = tmp / "serve.py"
    launcher.write_text(
        "import sys, uvicorn\n"
        f"sys.path.insert(0, {str(tmp)!r})\n"
        f"sys.path.insert(0, {str(BASE)!r})\n"
        "import e2e_spec\n"
        "from pathlib import Path\n"
        "from app.main import create_app\n"
        f"app = create_app(data_root=Path({str(data_root)!r}), backend_kind='mock',\n"
        f"                  service_port={svc_port}, agent_specs=[e2e_spec.E2ESpec(artifacts={{}})])\n"
        f"uvicorn.run(app, host='127.0.0.1', port={svc_port}, log_level='warning')\n"
    )

    env = dict(os.environ)
    env["PYTHONPATH"] = str(BASE)
    logs = open(tmp / "service.log", "ab")

    def launch() -> subprocess.Popen:
        return subprocess.Popen([sys.executable, str(launcher)], cwd=str(BASE), env=env,
                                stdout=logs, stderr=logs, start_new_session=True)

    # Make the agent installable: put the payload where installed() looks.
    agent_dir = data_root / "agents" / "e2e"
    (agent_dir / "bin").mkdir(parents=True)
    (agent_dir / "bin" / "e2e-agent").write_text(FAKE_AGENT)
    (agent_dir / "bin" / "e2e-agent").chmod(0o755)
    (data_root / "models").mkdir(parents=True)
    make_model(data_root / "models")

    first = launch()
    try:
        assert wait_http(svc_port), "the service did not come up"
        c = Client(svc_port)
        c.login()
        # -- configure: agent autostart + port, then start it ---------------
        code, _ = c.call("/api/agents/e2e", method="PATCH",
                         body={"port": agent_port, "autostart": True})
        check("PATCH agent autostart/port", code == 200, f"HTTP {code}")
        code, body = c.call("/api/agents/e2e/start", method="POST")
        check("start agent before restart", code == 200, f"HTTP {code} {body}")
        agent_pid = body.get("pid") if code == 200 else None
        check("agent has a pid", bool(agent_pid), str(agent_pid))
        code, body = c.call("/api/models/m/load", method="POST", timeout=180)
        check("load model before restart", code == 200 and body["model"]["loaded"],
              f"HTTP {code}")
        worker_pid = body["model"]["pid"] if code == 200 else None
        worker_port = body["model"]["port"] if code == 200 else None
        check("worker has a pid and port", bool(worker_pid and worker_port),
              f"{worker_pid}:{worker_port}")
        key = None
        code, body = c.call("/api/keys", method="POST", body={"name": "e2e"})
        if code == 200:
            key = body["key"]
        check("API key created", bool(key))
    finally:
        # -- SIGKILL: no shutdown hook, children orphaned -------------------
        os.killpg(os.getpgid(first.pid), signal.SIGKILL)
        first.wait(timeout=20)
    for pid in (worker_pid, agent_pid):
        alive = pid and Path(f"/proc/{pid}").exists()
        check(f"pid {pid} survived the SIGKILL", bool(alive))

    # -- restart on the same data root ------------------------------------
    second = launch()
    try:
        assert wait_http(svc_port), "the service did not come back"
        c2 = Client(svc_port)
        c2.login()
        code, body = c2.call("/api/models")
        m = {x["id"]: x for x in body["models"]}["m"] if code == 200 else {}
        check("model reports loaded after restart", m.get("loaded") is True, json.dumps(
            {k: m.get(k) for k in ("loaded", "pid", "port", "adopted", "conflict")}))
        check("same worker pid (no second spawn)", m.get("pid") == worker_pid,
              f"{m.get('pid')} vs {worker_pid}")
        check("same worker port", m.get("port") == worker_port)
        check("model marked adopted", m.get("adopted") is True)

        code, body = c2.call("/api/agents/e2e")
        check("agent running after restart", body.get("running") is True and
              body.get("status") == "running", json.dumps(
                  {k: body.get(k) for k in ("running", "status", "pid", "adopted",
                                            "orphan_pid", "last_error")}))
        check("same agent pid (no second spawn)", body.get("pid") == agent_pid,
              f"{body.get('pid')} vs {agent_pid}")
        check("agent marked adopted", body.get("adopted") is True)
        check("agent health true", body.get("health") is True)
        web_url = body.get("web_url") or ""
        check("agent web_url present", bool(web_url), web_url)
        # The proxy must reach the adopted process.
        code, _ = c2.call("/agents/e2e/health")
        check("agent proxy answers on the adopted pid", code == 200, f"HTTP {code}")

        if key:
            c2.bearer = key
            code, body = c2.call("/v1/chat/completions", method="POST",
                                 body={"model": "m", "max_tokens": 4,
                                       "messages": [{"role": "user", "content": "hi"}]})
            ok = code == 200 and body["choices"][0]["message"]["content"]
            check("completion served by the adopted worker", bool(ok), f"HTTP {code}")

        # Nothing extra was spawned: exactly one worker, one agent.
        check("exactly one worker for this model",
              _matching_workers(worker_port) == [worker_pid],
              f"{_matching_workers(worker_port)}")
        agents_now = _matching_agents(agent_port)
        check("exactly one agent process on its port", agents_now == [agent_pid],
              f"{agents_now}")
    finally:
        os.killpg(os.getpgid(second.pid), signal.SIGKILL)
        second.wait(timeout=20)
        for pid in (worker_pid, agent_pid):
            if pid and Path(f"/proc/{pid}").exists():
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except OSError:
                    pass

    checks.extend(frozen_worker_case(tmp, env))

    failed = [c for c in checks if not c[1]]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    print(f"logs: {tmp}")
    return 1 if failed else 0


def _read(path: Path) -> str:
    try:
        return path.read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return ""


def _matching_workers(port: int) -> list[int]:
    out = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        cmd = _read(entry / "cmdline")
        if "app.engine.worker" in cmd and f"--port {port}" in cmd:
            out.append(int(entry.name))
    return out


def _matching_agents(port: int) -> list[int]:
    out = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        cmd = _read(entry / "cmdline")
        if "e2e-agent" in cmd and f"--port {port}" in cmd:
            out.append(int(entry.name))
    return out


if __name__ == "__main__":
    sys.exit(main())
