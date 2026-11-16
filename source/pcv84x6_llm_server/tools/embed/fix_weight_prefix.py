#!/usr/bin/env python3
"""Rewrite a Qwen3 checkpoint's safetensors keys to the names tpu-mlir expects.

Why this exists: tpu-mlir's ``LlmInfo.COMMON_INFO`` (the qwen3/qwen2/llama map)
addresses the decoder as ``model.layers.<i>.…``, ``model.embed_tokens`` and
``model.norm``. The published ``Qwen/Qwen3-Embedding-0.6B`` checkpoint -- the
same on HuggingFace and ModelScope -- stores them **unprefixed**
(``layers.<i>.…``, ``embed_tokens.weight``, ``norm.weight``), because it was
saved from the bare ``Qwen3Model``. Conversion therefore dies on the first block
with::

    RuntimeError: Can't find key: model.layers.1.input_layernorm

Hence ``llm_convert.py -m <dir>`` cannot be pointed at the upstream download as
is; it needs a directory whose keys carry the prefix. This script produces one,
by rewriting only the JSON header and copying the tensor bytes verbatim -- the
weights are not touched, so the output is bit-identical apart from the names.

    python3 tools/embed/fix_weight_prefix.py <src-dir> <dst-dir>

Idempotent: a checkpoint whose keys already carry ``model.`` is copied as is,
and re-running into an existing ``dst-dir`` skips a file that is already there.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import sys
from pathlib import Path

#: The three top-level names that gain the prefix, and nothing else: the
#: per-layer suffixes (``self_attn.q_proj`` …) are already what LlmInfo wants.
TOP_LEVEL = ("layers.", "embed_tokens.", "norm.")


def needs_prefix(keys: list[str]) -> bool:
    return any(key.startswith(TOP_LEVEL) for key in keys)


def _is_prefixed(path: Path) -> bool:
    """Whether ``path``'s header already carries the prefix.

    The `model.` rename changes the header's length, so the file size alone is
    not a safe "already done" test: compare the keys instead.
    """
    with path.open("rb") as f:
        (header_len,) = struct.unpack("<Q", f.read(8))
        header = json.loads(f.read(header_len))
    return not needs_prefix([k for k in header if k != "__metadata__"])


def rename(key: str) -> str:
    return "model." + key if key.startswith(TOP_LEVEL) else key


def convert(src: Path, dst: Path) -> None:
    raw = src.read_bytes()
    (header_len,) = struct.unpack("<Q", raw[:8])
    header = json.loads(raw[8:8 + header_len])
    keys = [k for k in header if k != "__metadata__"]
    if not needs_prefix(keys):
        print("%s: already prefixed, skipping" % src.name, flush=True)
        shutil.copyfile(src, dst)
        return
    body = raw[8 + header_len:]

    out: dict = {"__metadata__": header.get("__metadata__", {"format": "pt"})}
    # Offsets are rewritten below from the sizes in the original order, so the
    # data section is copied unchanged and only the header grows by len("model.")
    # per renamed key.
    offset = 0
    data_order = sorted((v["data_offsets"][0], k) for k, v in header.items()
                        if k != "__metadata__")
    for _, key in data_order:
        entry = dict(header[key])
        start, end = entry["data_offsets"]
        entry["data_offsets"] = [offset, offset + (end - start)]
        offset += end - start
        out[rename(key)] = entry
    assert offset == len(body), (offset, len(body))

    payload = json.dumps(out, separators=(",", ":")).encode()
    # safetensors pads the header to an 8-byte boundary with spaces.
    payload += b" " * (-(8 + len(payload)) % 8)
    dst.write_bytes(struct.pack("<Q", len(payload)) + payload + body)
    print("%s: %d tensors, %d renamed" % (
        src.name, len(keys), sum(1 for k in keys if rename(k) != k)), flush=True)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    src_dir, dst_dir = Path(argv[1]), Path(argv[2])
    dst_dir.mkdir(parents=True, exist_ok=True)
    for entry in sorted(os.listdir(src_dir)):
        src = src_dir / entry
        if not src.is_file():
            # 1_Pooling/ holds the sentence-transformers config; llm_convert
            # copies the whole model dir into the bmodel's config dir, and the
            # engine's tokenizer lookup reads tokenizer files from there.
            shutil.copytree(src, dst_dir / entry, dirs_exist_ok=True)
            continue
        dst = dst_dir / entry
        if src.suffix.lower() == ".safetensors":
            if dst.exists() and _is_prefixed(dst):
                print("%s: exists, skipping" % entry, flush=True)
                continue
            convert(src, dst)
        elif not dst.exists():
            # config.json, tokenizer files, 1_Pooling/…: llm_convert reads these
            # from the model dir and copies them into the bmodel's config dir.
            shutil.copyfile(src, dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
