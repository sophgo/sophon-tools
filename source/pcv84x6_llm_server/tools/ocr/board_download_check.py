#!/usr/bin/env python3
"""The console's one-click download, against a server on the LAN.

dfss is not reachable from this site (``open.sophgo.com`` does not resolve on
the board, and the board's DNS resolves PyPI fine -- so it is the vendor host,
not the network), which means the *catalogue card click* cannot be exercised
here. What can be exercised is the code path it drives: ``POST /api/downloads``
with a catalogue id and url, the expansion into the four-file set, per-file
digest verification, and the one-step install.

So this points the same route at a local http server that serves the four real
bmodels with the catalogue's real md5s, which proves every part of the path
except the vendor host being up.

    python3 tools/ocr/board_download_check.py --repo /data/ocr-test/repo \\
        --lib /data/ocr-test/native/build/libcv84x6_llm.so \\
        --target /data/ocr-test/dl/models --port 8098 --file-port 8097
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--lib", required=True, type=Path)
    ap.add_argument("--source", type=Path,
                    default=Path("/data/ocr-test/models/ppocrv6-medium"))
    ap.add_argument("--target", type=Path, default=Path("/data/ocr-test/dl"))
    ap.add_argument("--port", type=int, default=8098)
    ap.add_argument("--file-port", type=int, default=8097)
    args = ap.parse_args()

    args.repo = args.repo.resolve()
    args.lib = args.lib.resolve()
    sys.path.insert(0, str(args.repo))

    import httpx

    from app.core.downloader import catalog_entry

    entry = catalog_entry("ppocrv6-medium")
    assert entry, "the catalogue has no ppocrv6-medium entry"
    names = [f["dfss"].rsplit("/", 1)[-1] for f in entry["files"]]

    # Serve the real bmodels, and check the digests the catalogue declares
    # against the bytes on disk first: a mismatch here would make the download
    # path fail for a reason that has nothing to do with the download path.
    for name, record in zip(names, entry["files"]):
        path = args.source / name
        actual = hashlib.md5(path.read_bytes()).hexdigest()
        print(f"{name}: {path.stat().st_size} bytes md5 {actual}"
              f"{'' if actual == record['md5'] else '  *** EXPECTED ' + record['md5']}")
        assert actual == record["md5"], f"{name} does not match the catalogue"

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(args.source), **kw)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", args.file_port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # The service's own models root is <data-root>/models; a dedicated root keeps
    # this run out of the one the acceptance passes use.
    root = args.target
    (root / "models").mkdir(parents=True, exist_ok=True)
    log = open("/data/ocr-test/dl-service.log", "wb")
    env = dict(os.environ)
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.main", "--backend", "native",
         "--port", str(args.port), "--host", "127.0.0.1",
         "--data-root", str(root), "--native-lib", str(args.lib)],
        cwd=str(args.repo), stdout=log, stderr=subprocess.STDOUT, env=env)
    base = f"http://127.0.0.1:{args.port}"
    try:
        with httpx.Client(timeout=120.0) as client:
            for _ in range(120):
                try:
                    if client.get(f"{base}/healthz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                print("service did not start; see /data/ocr-test/dl-service.log")
                return 1
            client.post(f"{base}/api/login", json={"password": "admin"})

            # What a client downloading a *set* posts. The catalogue-card
            # expansion (`downloader.catalog_files`) keys on the entry's dfss
            # url, so it does not fire for an http mirror of one file -- that is
            # by design, and it is covered by tests/test_downloader.py. What is
            # checked here is the route + downloader + install path with the real
            # bmodels and the real digests.
            print("catalogue declares:")
            for name, record in zip(names, entry["files"]):
                print(f"  {name}: {record['size_bytes']} bytes md5 {record['md5']}")
            files = [{"url": f"http://127.0.0.1:{args.file_port}/{name}",
                      "size_bytes": record["size_bytes"], "md5": record["md5"]}
                     for name, record in zip(names, entry["files"])]
            r = client.post(f"{base}/api/downloads", json={
                "url": files[0]["url"], "name": "ppocrv6-medium", "kind": "url",
                "expected_bytes": entry["size_bytes"], "files": files})
            assert r.status_code == 200, r.text
            job_id = r.json()["job"]["id"]
            for _ in range(1200):
                job = next(j for j in client.get(f"{base}/api/downloads").json()["jobs"]
                           if j["id"] == job_id)
                if job["state"] in ("done", "error", "cancelled"):
                    break
                time.sleep(0.1)
            print(f"multi-file job: state={job['state']} "
                  f"files={job['files_done']}/{job['file_count']} "
                  f"percent={job['percent']} message={job['message']}")
            on_disk = sorted(p.name for p in (root / "models" / "ppocrv6-medium").iterdir())
            print(f"models/ppocrv6-medium: {len(on_disk)} files")
            for name in names:
                print(f"  {name}: {'present' if name in on_disk else 'MISSING'}")

            models = {m["id"]: m for m in client.get(f"{base}/api/models").json()["models"]}
            found = models.get("ppocrv6-medium")
            print(f"scanned as: kind={found['kind'] if found else None} "
                  f"bmodel_files={len(found['bmodel_files']) if found else 0}")
            ok = (job["state"] == "done" and on_disk == sorted(names)
                  and found and found["kind"] == "ocr"
                  and len(found["bmodel_files"]) == 4)
            print("RESULT:", "PASS" if ok else "FAIL")
            return 0 if ok else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
