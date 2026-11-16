#!/usr/bin/env python3
"""Download the bge-reranker-v2-m3 checkpoint into the build container's /workspace.

Run inside the build container (embed_build). ModelScope is the source: on
13.24 it serves this repo at ~9 MB/s while huggingface.co trickles at ~0.6 MB/s,
and the checkpoint is 2.3 GB.

Idempotent: a file already present at the size the server reports is kept, so a
retry after an interruption only refetches what is missing. The expected size
comes from the server (HEAD / Content-Length), never from a number in this
file -- a wrong constant here silently throws away a good 2 GiB download.
"""
import os
import sys
import urllib.request

BASE = "https://modelscope.cn/models/BAAI/bge-reranker-v2-m3/resolve/master/"
DEST = "/workspace/weights/bge-reranker-v2-m3"
FILES = [
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
]


def remote_size(name: str) -> int | None:
    """Size of ``name`` in bytes, or None if the server does not say.

    ModelScope answers HEAD without a Content-Length, so the size is read from
    the Content-Range of a one-byte GET: ``bytes 0-0/2271071852``.
    """
    req = urllib.request.Request(BASE + name, headers={"Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        crange = r.headers.get("Content-Range")
        if crange and "/" in crange:
            return int(crange.rsplit("/", 1)[1])
        length = r.headers.get("Content-Length")
        return int(length) if length else None


def fetch(name: str) -> None:
    dst = os.path.join(DEST, name)
    expect = remote_size(name)
    if os.path.exists(dst):
        size = os.path.getsize(dst)
        if expect is None or size == expect:
            print("skip", name, size, flush=True)
            return
        print("stale", name, size, "!=", expect, flush=True)
        os.remove(dst)
    tmp = dst + ".part"
    with urllib.request.urlopen(BASE + name, timeout=120) as src, open(tmp, "wb") as out:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    size = os.path.getsize(tmp)
    if expect is not None and size != expect:
        os.remove(tmp)
        raise RuntimeError("%s: got %d bytes, expected %d" % (name, size, expect))
    os.replace(tmp, dst)
    print("ok", name, size, flush=True)


def main() -> int:
    os.makedirs(DEST, exist_ok=True)
    for name in FILES:
        try:
            fetch(name)
        except Exception as exc:  # noqa: BLE001 - a report is all this needs
            print("ERR", name, exc, flush=True)
            return 1
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
