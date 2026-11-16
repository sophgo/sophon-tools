#!/usr/bin/env python3
"""Download a pinned official checkpoint and verify each LFS SHA-256."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request

REPO = "Qwen/Qwen3-VL-Embedding-2B"
REVISION = "9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda"
SOURCES = {
    "qwen3-vl": (REPO, REVISION),
    "wemm": ("tencent/WeMM-Embedding-2B", "bbd6cd4bf52cfc6716f752a2df80b2706720bd95"),
}
MODELSCOPE_REPOS = {"wemm": "tencent-community/WeMM-Embedding-2B"}


def download_ranges(url, path, size, workers):
    """Bounded ranges avoid gateway truncation; verify every returned offset."""
    chunk_size = 32 * 1024 * 1024
    def fetch(start):
        end = min(size, start + chunk_size) - 1
        part = path.with_name(path.name + f".range-{start}")
        if part.exists() and part.stat().st_size == end - start + 1:
            return part
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    url + f"&range_start={start}",
                    headers={"Range": f"bytes={start}-{end}"})
                with urllib.request.urlopen(req, timeout=60) as response:
                    expected = f"bytes {start}-{end}/{size}"
                    if response.status != 206 or response.headers.get("Content-Range") != expected:
                        raise RuntimeError(f"Server did not honor range {expected}")
                    with part.open("wb") as stream:
                        remaining = end - start + 1
                        while remaining:
                            chunk = response.read(min(4 * 1024 * 1024, remaining))
                            if not chunk:
                                raise RuntimeError(f"Incomplete range at {start}")
                            stream.write(chunk)
                            remaining -= len(chunk)
                print(f"downloaded {end + 1}/{size}", flush=True)
                return part
            except Exception:
                if attempt == 2:
                    raise
    with ThreadPoolExecutor(max_workers=workers) as pool:
        parts = list(pool.map(fetch, range(0, size, chunk_size)))
    staging = path.with_name(path.name + ".assembled")
    with staging.open("wb") as stream:
        for part in parts:
            with part.open("rb") as source:
                while chunk := source.read(4 * 1024 * 1024):
                    stream.write(chunk)
    staging.replace(path)
    for part in parts:
        part.unlink()


def download(output, revision=None, mirror="huggingface", workers=8, family="qwen3-vl"):
    repo, pinned_revision = SOURCES[family]
    mirror_repo = MODELSCOPE_REPOS.get(family, repo)
    revision = revision or pinned_revision
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/api/models/{repo}/tree/{revision}?recursive=true"
    with urllib.request.urlopen(url, timeout=60) as response:
        entries = json.load(response)
    manifest = []
    # Metadata/tokenizers arrive first, allowing preprocessing checks while
    # the much larger checkpoint is being transferred.
    for entry in sorted(entries, key=lambda item: item.get("size", 0)):
        if entry["type"] != "file" or entry["path"] == ".gitattributes":
            continue
        path = root / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        size = entry["size"]
        expected = entry.get("lfs", {}).get("oid")
        if not path.exists() or path.stat().st_size != size:
            if size > 64 * 1024 * 1024:
                # The mirror's mutable branch is never trusted for identity:
                # the pinned Hugging Face LFS digest below remains authoritative.
                url = ((f"https://www.modelscope.cn/api/v1/models/{mirror_repo}/repo"
                        f"?Revision=master&FilePath={entry['path']}") if mirror == "modelscope" else
                       f"https://huggingface.co/{repo}/resolve/{revision}/{entry['path']}?download=true")
                download_ranges(url, path, size, workers)
            else:
                part = path.with_name(path.name + ".part")
                request = urllib.request.Request(
                    f"https://huggingface.co/{repo}/resolve/{revision}/{entry['path']}")
                offset = part.stat().st_size if part.exists() else 0
                if offset:
                    request.add_header("Range", f"bytes={offset}-")
                with urllib.request.urlopen(request, timeout=60) as response:
                    mode = "ab" if offset and response.status == 206 else "wb"
                    if mode == "ab" and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                        raise RuntimeError("Server returned an incorrect resume offset")
                    with part.open(mode) as stream:
                        while chunk := response.read(4 * 1024 * 1024):
                            stream.write(chunk)
                if part.stat().st_size != size:
                    raise RuntimeError(f"Incomplete download: {entry['path']}")
                part.replace(path)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(4 * 1024 * 1024):
                digest.update(chunk)
        actual = digest.hexdigest()
        if expected and actual != expected:
            raise RuntimeError(f"SHA-256 mismatch: {entry['path']}")
        manifest.append({"path": entry["path"], "size": size, "sha256": actual})
        print(f"verified {entry['path']} ({size} bytes)", flush=True)
    (root / "source_manifest.json").write_text(json.dumps(
        {"repo": repo, "revision": revision, "files": manifest}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--family", choices=list(SOURCES), default="qwen3-vl")
    parser.add_argument("--revision", help="defaults to the selected family's pinned checkpoint")
    parser.add_argument("--mirror", choices=["huggingface", "modelscope"], default="huggingface")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    download(args.output_dir, args.revision, args.mirror, max(1, min(16, args.workers)), args.family)
