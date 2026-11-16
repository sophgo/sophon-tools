"""Model download and disk management.

The board is offline in normal operation but has to get models onto it somehow.
Two supported paths, both driven from the console:

1. **dfss pull** -- ``python -m dfss --url=open@sophgo.com:...``, the vendor's
   own distribution channel (this is what sophon-demo's ``download_bmodel.sh``
   uses). Requires the box to have a route to the internet at download time.
2. **Direct URL** -- an http(s) artifact on the local network (artifact server,
   NAS), which is the realistic option for a customer site.

Downloads run as background jobs with progress, because a 20 GB model over a
slow link must not block the UI or die with an HTTP timeout. Disk space is
checked *before* starting: a half-written 20 GB file that fails at 99% because
the disk filled is the most expensive failure mode here.

Our own builds are additionally published under dfss **download tags**
(``--dflag``): ``<tag> <file>`` lines in a ``.dfss_down_flag`` file on the
server, which the vendor's index exposes as ``/.dfss_flags``. A tag is what
makes a model upgradable without a new service release -- repoint it on the
server and every board notices that its installed copy is out of date. See
``docs/model-release.md`` for the publishing side.
"""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import re
import shutil
import signal
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Room to keep for logs/state and the extraction step's temporary copy.
DISK_HEADROOM = 512 * 1024 * 1024


@dataclass
class DownloadJob:
    id: str
    kind: str               # "dfss" | "url"
    target: str             # dfss url or http url (the first file of a set)
    name: str               # model directory name
    state: str = "pending"  # pending | running | done | error | cancelled
    total_bytes: int | None = None
    done_bytes: int = 0
    message: str = ""
    # dfss reports percentage only (no byte counts), so keep it separately
    # rather than faking done_bytes.
    percent_hint: float | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    #: Every file this job has to fetch, for models made of several bmodels.
    #: One entry per artifact; a single-file model has exactly one. Each is
    #: ``{"target": ..., "name": ..., "size_bytes": ...}``. Empty means "just
    #: ``target``", which is what every caller before OCR passed.
    files: list[dict] = field(default_factory=list)
    #: How many of ``files`` have landed, for the console's "3/4" label.
    files_done: int = 0
    #: Per-file digests to verify once downloaded, keyed by file name. Empty for
    #: the manual-URL path, where the operator did not declare one.
    digests: dict = field(default_factory=dict)
    #: How the bytes actually arrived, for the job message: ``"dflag"`` when
    #: every file came from a download tag, ``"dfss"``/``"url"`` when it did not.
    #: A tag that could not be used falls back to the fixed URL per file, so the
    #: message has to say which happened rather than claim the tag worked.
    transport: str = ""

    @property
    def percent(self) -> float:
        if self.percent_hint is not None:
            # A multi-file job's percentage comes from the files that finished
            # plus the current one's share: dfss reports each transfer's own
            # progress, so reporting it raw would go 100 → 0 → 100.
            if len(self.files) > 1 and self.total_bytes:
                landed = sum(int(f.get("size_bytes") or 0)
                             for f in self.files[: self.files_done])
                current = int((self.total_bytes - landed) * self.percent_hint / 100.0)
                return min(100.0, 100.0 * (landed + current) / self.total_bytes)
            return self.percent_hint
        if not self.total_bytes:
            return 0.0
        return min(100.0, 100.0 * self.done_bytes / self.total_bytes)

    def public(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "target": self.target,
            "name": self.name,
            "state": self.state,
            "total_bytes": self.total_bytes,
            "done_bytes": self.done_bytes,
            "percent": round(self.percent, 1),
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            # A model made of several bmodels says so: the console shows "2/4"
            # instead of a bar that looks stuck for twenty minutes per file.
            "file_count": len(self.files) or 1,
            "files_done": self.files_done,
        }


#: The vector family the two Qwen3-Embedding builds share (MYS-2706).
#:
#: ``vector_family`` answers one question: **are two embedding models' vectors
#: comparable?** Two catalogue entries can be different files -- seq512 and
#: seq2048 are different compiled graphs, 1.21 vs 1.23 GB -- and still produce
#: the same vector for the same text, because the only difference is how many
#: positions the static graph computes and padding is masked. Measured on
#: `.157`: min cosine 0.99963 between the seq2048 and seq8192 builds over 24
#: texts, and seq512 vs seq2048 identical to seven decimals on every text both
#: accept (``docs/research/aux-dynamic-seq.md`` §7).
#:
#: So a knowledge base built with one build stays usable with the other: append
#: with whichever is loaded, search with whichever is loaded. Rebuilding is only
#: required across *families*.
EMBED_FAMILY = "qwen3-embedding-0.6b"


# Models this release is built and tested for. The four 35B builds are our own
# (tpu-mlir 1.30.2, ``--use_history_kv``), published on dfss under
# /tools/cv84x6_llm_server/; the two auxiliary models are the vendor's official
# CV84X6 builds from LLM-TPU. The tokenizer config ships with the service, so a
# dfss pull of the bmodel alone is a complete model directory.
#
# Every entry declares its ``kind``. It is the same value the scan derives from
# the bmodel file name (see ``models.kind_of_bmodel``); stating it here means the
# console can label a model before it is downloaded, and a catalogue entry whose
# name and kind disagree is caught by tests/test_model_kind.py instead of at
# request time.
#
# Only the Qwen3.6 128k build was offered for download until 2026-11-04
# (MYS-2293): the Qwen3.5 builds and the 32k build were dropped from the list.
# Any of them placed in the models directory by hand still scans, loads and
# serves. MYS-2754 puts the two dense Qwen3.5 sizes back (below): 9B and 4B are
# a different weight class from the 35B-A3B, and a board that cannot give a
# chat model 23 GB of NPU is the case they exist for.
#
# **Download tags.** Our own builds carry a ``dflag``: the dfss download tag that
# currently points at the file, plus a ``<tag>.md5`` tag beside it whose target
# is a sidecar holding ``<md5>  <file name>``. Fetching the sidecar first is what
# tells us the *real* file name, and therefore which local file is stale -- the
# whole mechanism behind "有新版本" and one-click update (see ``update_status``
# and ``DownloadManager.start_update``). Both keep the fixed ``dfss`` URL as the
# fallback for an older dfss, a missing tag or no route to the server.
#
# The two vendor models (embedding, rerank) are not ours to republish, so they
# have no tag and keep downloading by URL only.
#
# sophon-demo's own seq2048 builds are deliberately *not* listed any more
# (MYS-2411): 2k context cannot hold the prompts this service is for, and the
# 32k/128k builds are the same weights. A seq2048 bmodel an operator drops into
# the models directory by hand still scans, loads and serves -- being absent
# from this download list is a catalogue decision, not an engine restriction.
CATALOG: list[dict] = [
    {
        "id": "qwen3.6-35b-a3b-128k",
        "kind": "chat",
        "title": "Qwen3.6-35B-A3B 长上下文 128k (int4, seq131072, history, 4core)",
        # The longest context that loads: 22.8 GB of 23.75 GB NPU. Concurrency
        # is limited by the ~1 GB left for parked sessions + prefix cache.
        "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/"
                "qwen3.6-35b-a3b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261025_051759.bmodel",
        "dflag": "cv84x6_llm_qwen3.6-35b-a3b-128k",
        # Since 2026-11-04 this dfss path serves the mask128 build (tpu-mlir
        # MASK_SIZE 64 -> 128, MYS-2588), swapped in under the same file name:
        # on the same board and service it cut cold-prefill time by 24/36/49/55%
        # at 16k/32k/64k/96k, kept short prompts and decode speed unchanged, and
        # matched the old build token for token (MYS-2592). Older releases do
        # not check a single-file entry's md5, so the swap is invisible to them.
        "md5": "76b3795892a6debc1159630c879ed05b",
        "size_bytes": 20681019392,
        "vision": True,
        "verified": True,
        "context": 131072,
        "prefix_cache": True,
    },
    # -- the dense Qwen3.5 sizes (MYS-2754) ---------------------------------
    # Same `qwen3_5` architecture as the 35B-A3B above but *dense*: no MoE, and
    # 32 layers of which 8 are full attention. Compiled with the identical
    # parameter set (128k, ``--use_history_kv``, ``--chunk_length 2048``,
    # ``--max_pixels 768,768``, ``--dynamic``, 4 core) and the same MASK_SIZE
    # tpu-mlir patch, so a board that serves the 35B needs no new engine.
    #
    # They exist because the 35B-A3B leaves ~1 GB of NPU: a board that has to
    # keep auxiliary models resident (embedding + rerank + ASR + OCR is ~5.5 GB)
    # cannot take it at all. 9B w4 is 9.7 GB and 4B w4 is 4.8 GB, which is what
    # makes those combinations possible -- ``docs/qwen35-small.md`` has the
    # measured arithmetic.
    #
    # `context` is 131072 for all three because that is what was compiled and
    # measured, not because it is the architectural maximum (the family is
    # natively 262144).
    {
        "id": "qwen3.5-9b-128k",
        "kind": "chat",
        "title": "Qwen3.5-9B 长上下文 128k (int4 AutoRound, seq131072, history, 4core, 视觉)",
        # 9.65B dense. Weights are the Intel AutoRound int4 release -- the same
        # quantisation recipe the 35B builds use (auto-round / bits 4 /
        # group_size 128 / packing_format auto_round:auto_gptq), so tpu-mlir's
        # ``init_quantization`` takes the INT4 path and ``-q w4bf16`` means what
        # it says. A bf16 source with ``-q w4bf16`` would silently *not*
        # quantise (``ModelHandle.init_quantization``:88-96), which is why a
        # pre-quantised checkpoint was required rather than derived.
        "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/"
                "qwen3.5-9b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261110_051942.bmodel",
        "dflag": "cv84x6_llm_qwen3.5-9b-128k",
        "md5": "7224f129dd233bf77665183e65a6b124",
        "size_bytes": 8843063296,
        "vision": True,
        "verified": True,
        "context": 131072,
        "prefix_cache": True,
    },
    {
        "id": "qwen3.5-4b-128k",
        "kind": "chat",
        "title": "Qwen3.5-4B 长上下文 128k (int4 AutoRound, seq131072, history, 4core, 视觉)",
        # 4.66B dense, same Intel AutoRound int4 recipe as the 9B. The smallest
        # model that still leaves room for every auxiliary model beside it.
        "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/"
                "qwen3.5-4b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261110_033630.bmodel",
        "dflag": "cv84x6_llm_qwen3.5-4b-128k",
        "md5": "af0bf863862a9f68ea2bdc10695f67c1",
        "size_bytes": 4019560448,
        "vision": True,
        "verified": True,
        "context": 131072,
        "prefix_cache": True,
    },
    # The 4B bf16 build (qwen3.5-4b-bf16-128k) was offered in v0.6.31 and
    # dropped in v0.6.32 at the user's request: at 13.3 GiB and 7.2 tok/s it
    # costs what the 9B w4 costs, runs at half its speed and agreed with its
    # reference less (83.8% vs 88.1%, docs/qwen35-small.md). A copy placed in the
    # models directory by hand still scans and serves.
    # -- auxiliary models ---------------------------------------------------
    # Not chat models: `kind` is what the console greys out and what the API
    # uses to refuse a request sent to the wrong endpoint. Both are the
    # vendor's official CV84X6 builds, and both are much smaller than a 35B --
    # which is the point: they are meant to be loaded *beside* a chat model on
    # boards where the NPU heap has room (the loader checks it, see
    # ModelManager._check_npu_admission).
    {
        "id": "qwen3-embedding-0.6b",
        "kind": "embedding",
        "title": "Qwen3-Embedding-0.6B 文本向量 (bf16, seq2048, 1024 维)",
        # 1024 dims, last-token pooling + L2, MRL truncation down to 32.
        #
        # Our own build (tpu-mlir 1.30.2, bm1684x2 4core static), parameter-
        # identical to the vendor's ext_model_information seq8192 file apart from
        # -s 2048. A static graph runs its whole compiled length on every
        # forward, so the compiled length *is* the per-text cost: 2811 ms at
        # 8192, 291 ms at 2048 on `.157` (MYS-2696). Padding is masked, so the
        # vectors are the same -- min cosine 0.99963 over 24 texts, 1..1932
        # tokens -- which is why an existing knowledge base does not need a
        # rebuild.
        "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/"
                "qwen3-embedding-0.6b_bf16_seq2048_bm1684x2_4core_static_20261108_011851.bmodel",
        "dflag": "cv84x6_llm_qwen3-embedding-0.6b",
        "md5": "b68c2f784b8c93d82c35334d5451cac2",
        "size_bytes": 1230409728,
        "vision": False,
        "verified": True,
        "context": 2048,
        "prefix_cache": False,
        "vector_family": EMBED_FAMILY,
    },
    {
        "id": "qwen3-embedding-0.6b-seq512",
        "kind": "embedding",
        "title": "Qwen3-Embedding-0.6B 文本向量 (bf16, seq512, 短文本, 与 seq2048 版向量互通)",
        # The same weights at `-s 512`, so a shorter text costs 83 ms instead of
        # 291 ms (MYS-2702, docs/research/aux-dynamic-seq.md §3). Padding is
        # masked, so the vectors agree with the seq2048 build to 7 decimals --
        # which is why `vector_family` exists: a library built with either build
        # can be appended to and searched with the other.
        #
        # **Not a default.** It is not downloaded and not loaded unless an
        # operator asks for it: the chat-shaped defaults must not silently move
        # a deployment onto the shorter graph, where a 1000-character chunk goes
        # through the split-and-pool path instead of one forward.
        "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/"
                "qwen3-embedding-0.6b_bf16_seq512_bm1684x2_4core_static_20261108_045357.bmodel",
        "dflag": "cv84x6_llm_qwen3-embedding-0.6b-seq512",
        "md5": "864f09b7e7e2a37d420243d8be7a8346",
        "size_bytes": 1205460992,
        "vision": False,
        "verified": True,
        "context": 512,
        "prefix_cache": False,
        "vector_family": EMBED_FAMILY,
    },
    {
        "id": "wemm-embedding-2b",
        "kind": "embedding",
        "title": "WeMM-Embedding-2B 图文向量 (w8bf16, seq2048, 2048 维)",
        "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/wemm-embedding-2b_w8bf16_seq2048_pixels1310720_cv84x6_4core_buckets_gdnmixed_20261114_091623.bmodel",
        "dflag": "cv84x6_llm_wemm-embedding-2b",
        "md5": "2065f4c866be364c0607b705c07f3dc4",
        "size_bytes": 3121778688,
        "vision": True,
        "verified": True,
        "context": 2048,
        "prefix_cache": False,
        "vector_family": "tencent/WeMM-Embedding-2B"
    },
    {
        "id": "bge-reranker-v2-m3",
        "kind": "rerank",
        "title": "BGE-Reranker-v2-M3 重排序 (bf16, seq2048, cross-encoder)",
        # Scores one (query, document) pair per forward; sigmoid maps the logit
        # to [0, 1] at the API layer.
        "dfss": "open@sophgo.com:/ext_model_information/LLM/LLM-TPU/"
                "bge-reranker-v2-m3_bf16_seq2048_cv84x6_4core_static_20261009_110923.bmodel",
        "md5": "aa1636c9b6479a4b6cb280fab28271a6",
        "size_bytes": 1144569856,
        "vision": False,
        "verified": True,
        "context": 2048,
        "prefix_cache": False,
    },
    # ASR. Our own builds (stage 1B, tpu-mlir 1.30.2, bm1684x2 4core static),
    # because the vendor has no CV84X6 Qwen3-ASR on dfss. Both sizes are offered
    # for the reason the user gave: 1.7B transcribes better and needs ~4 GB,
    # 0.6B needs ~1.5 GB and fits beside a 32k chat model.
    #
    # `context` is MAX_INPUT_LENGTH (the prompt window), not SEQLEN: it is what
    # /v1/models can honestly report, and what the segment length is derived
    # from. 13 audio tokens per second of audio.
    {
        "id": "qwen3-asr-0.6b",
        "kind": "asr",
        "title": "Qwen3-ASR-0.6B 语音转写 (bf16, seq1024, 38 秒/段)",
        "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/"
                "qwen3-asr-0.6b_bf16_seq1024_bm1684x2_4core_static_20261103_120455.bmodel",
        "dflag": "cv84x6_llm_qwen3-asr-0.6b",
        "md5": "8df49b25d6ab7775bb86961c3e407465",
        "size_bytes": 1588723712,
        "vision": False,
        "verified": True,
        "context": 512,
        "prefix_cache": False,
    },
    {
        "id": "qwen3-asr-1.7b",
        "kind": "asr",
        "title": "Qwen3-ASR-1.7B 语音转写 (bf16, seq1024, 38 秒/段)",
        "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/"
                "qwen3-asr-1.7b_bf16_seq1024_bm1684x2_4core_static_20261103_120829.bmodel",
        "dflag": "cv84x6_llm_qwen3-asr-1.7b",
        "md5": "d5bcfe6205f67d9e589d32b409773ea8",
        "size_bytes": 4099940352,
        "vision": False,
        "verified": True,
        "context": 512,
        "prefix_cache": False,
    },
    # PP-OCRv6 medium. Unlike every entry above this is **five bmodels in one
    # model**: a detector, the recogniser at three input widths, and (since
    # `mode: "layout"`) the PP-DocLayout-M page segmenter. The worker loads the
    # detector at start, each rec tier on first use (a 320-tier page never maps
    # the 1600 model) and the layout model on the first `layout` request, so
    # they have to arrive together -- a directory with some of them is refused
    # at load with the missing names.
    #
    # The `files` form is what makes that one download job instead of five: the
    # downloader fetches each into staging and moves the whole set into
    # models/<id>/ in one step, so an interrupted pull never leaves a directory
    # that looks loadable.
    {
        "id": "ppocrv6-medium",
        "kind": "ocr",
        "title": "PP-OCRv6 medium 文字识别 (f16, det 736 + rec 320/640/1600 + 版面 M)",
        # ``dfss`` on a set entry is its **first** file, not the whole model.
        # Two callers read it that way on purpose: the console's catalogue card
        # enables its download button when ``dfss`` is present (and posts only
        # url+name), and a person copying an entry by hand has to start
        # somewhere. The API expands a catalogue id back into ``files`` -- see
        # ``catalog_files`` -- so neither of those paths can download a
        # fragment by accident.
        "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/"
                "ppocrv6-medium-det_f16_736_bm1684x2_static_20261103.bmodel",
        "files": [
            {
                "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/"
                        "ppocrv6-medium-det_f16_736_bm1684x2_static_20261103.bmodel",
                "dflag": "cv84x6_llm_ppocrv6-medium-det",
                "md5": "eb8e897f3ef318f9e829007f7287ea20",
                "size_bytes": 74915840,
            },
            {
                "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/"
                        "ppocrv6-medium-rec_f16_48x320_bm1684x2_static_20261103.bmodel",
                "dflag": "cv84x6_llm_ppocrv6-medium-rec-320",
                "md5": "2fb497f3d76ea80f0b1148a677895173",
                "size_bytes": 50884608,
            },
            {
                "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/"
                        "ppocrv6-medium-rec_f16_48x640_bm1684x2_static_20261103.bmodel",
                "dflag": "cv84x6_llm_ppocrv6-medium-rec-640",
                "md5": "d7f29a1f60a29d16fcd4be9fd0739b1a",
                "size_bytes": 46067712,
            },
            {
                "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/"
                        "ppocrv6-medium-rec_f16_48x1600_bm1684x2_static_20261103.bmodel",
                "dflag": "cv84x6_llm_ppocrv6-medium-rec-1600",
                "md5": "66820946777c7c01dc8a0ea105439995",
                "size_bytes": 51089408,
            },
            # The layout segmenter, added for `mode: "layout"`. PP-DocLayout-M,
            # not -S: S classifies a table as `image`, which is exactly the
            # region the layout mode exists to report (docs/ocr-structure.md §2).
            #
            # The name follows this catalogue's own convention (our build, our
            # ``_f16_<side>_bm1684x2_static_<date>`` shape) rather than the
            # compiler's internal ``dlM_...``: every other entry here names the
            # model, the precision, the input side and the chip, and a reader
            # deciding whether to re-download should not have to decode ``dlM``.
            {
                "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/"
                        "ppdoclayout-m_f16_640_bm1684x2_static_20261104.bmodel",
                "dflag": "cv84x6_llm_ppdoclayout-m",
                "md5": "9a898e57059f616380e48904c74eab48",
                "size_bytes": 18214912,
            },
        ],
        # The sums of the five files above, so `size_bytes` keeps its meaning
        # for the disk check and the console's "已下载 / 总计" bar.
        "size_bytes": 74915840 + 50884608 + 46067712 + 51089408 + 18214912,
        "vision": False,
        "verified": True,
        "context": 736,
        "prefix_cache": False,
    },
    # PaddleOCR-VL-1.5: a chat-shaped OCR model, not an auxiliary one. It is a
    # 2.27 GB bmodel that takes ~3.3 GB of NPU memory and ~7 s to map, so it is
    # loaded and unloaded by hand like a 35B -- see ``models.AUX_KINDS``.
    #
    # `kind: "ocr_vl"` rather than `chat` is what keeps it out of the agents'
    # model menu and off the knowledge base's answer stage (it answers the same
    # /v1/chat/completions, but it only knows how to read one image). The file
    # name carries the facts the rest of the service reads off it: `paddleocr-vl`
    # gives the kind, `seq2048` the context.
    {
        "id": "paddleocr-vl-1.5",
        "kind": "ocr_vl",
        "title": "PaddleOCR-VL-1.5 文档识别 (bf16, seq2048, vit 784, 输出 OTSL)",
        # Straight from dfss's tag index. ``md5`` is the digest of the file that
        # tag currently resolves to, so an update that swaps the file under the
        # same tag is caught by the downloader rather than half-installed.
        "dfss": "open@sophgo.com:/tools/cv84x6_llm_server/"
                "paddleocr-vl-1.5_bf16_seq2048_bm1684x2_4core_static_20261103.bmodel",
        "dflag": "cv84x6_llm_paddleocr-vl-1.5",
        "md5": "db604d464924b9a7d87a77924cb432cc",
        "size_bytes": 2268594176,
        # The model takes an image; the flag is what ``/v1/models`` and the
        # console's card read. Read off the bmodel's graphs on the board (the
        # vit graph is there), not guessed from the name.
        "vision": True,
        "verified": True,
        "context": 2048,
        # No KV snapshots: the engine owns one KV cache and cannot copy it out.
        "prefix_cache": False,
    },
]


def _safe_name(name: str) -> str:
    """A model directory name is user input; never let it escape models_root.

    Anything containing a path separator or a parent reference is *rejected*
    rather than sanitised: silently turning ``../../etc`` into ``etc`` would
    hide a bad request and could still land data somewhere the operator did not
    intend.
    """
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise ValueError("模型名不能包含路径分隔符")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    if not cleaned or cleaned in (".", ".."):
        raise ValueError("invalid model name")
    return cleaned[:80]


def _clean_file_set(files: list[dict], first: str) -> list[dict]:
    """Normalise a ``files`` list into ``{target, name, size_bytes, md5, dflag}``.

    One shape for both transports: ``dfss`` and ``url`` entries name their
    location with the same key here, because everything downstream (the digest
    check, the progress arithmetic, the install) cares about the artifact, not
    about which tool fetched it.

    ``dflag`` is carried through rather than resolved here: whether a tag can be
    used is only knowable at download time (the index may have moved, the tool
    may be too old), and each file falls back to its ``target`` on its own.
    """
    cleaned = []
    for entry in files:
        target = str(entry.get("dfss") or entry.get("url") or "")
        if not target:
            raise ValueError("files 里的每一项都需要 dfss 或 url 地址")
        name = target.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
        if not name:
            raise ValueError(f"地址里没有文件名：{target}")
        cleaned.append({
            "target": target,
            "name": name,
            "size_bytes": int(entry.get("size_bytes") or 0),
            "md5": (entry.get("md5") or "").lower() or None,
            "dflag": (str(entry.get("dflag") or "").strip() or None),
        })
    if not cleaned:
        raise ValueError("files 不能是空数组")
    return cleaned


def catalog_entry(model_id: str) -> dict | None:
    """The catalogue entry whose id is ``model_id``, or None."""
    for entry in CATALOG:
        if entry["id"] == model_id:
            return entry
    return None


def catalog_files(model_id: str, url: str) -> list[dict] | None:
    """The file set of a catalogue entry, when this request is that entry.

    The console's model page posts a catalogue card as ``{url, name}`` -- it has
    no field for a file set, and adding one would mean changing ``web/``, which
    this stage is not allowed to touch. So the expansion happens here: when the
    ``name`` is a catalogue id and the ``url`` is that entry's ``dfss``, the
    caller meant the whole model, and a download of just the first file would
    leave a directory with the detector and no recogniser.

    A single-file entry is expanded too -- into a one-element list -- and that is
    not cosmetic: the entry's ``dflag`` lives on the entry, so a card click that
    sent only ``{url, name}`` would never reach the tag path and every model
    would download from the fixed URL, silently losing the upgrade mechanism.

    Deliberately narrow. Both conditions have to hold, so:
      * the manual "paste a dfss URL" box still downloads exactly what was
        pasted (its name is operator-chosen and its url arbitrary);
      * a caller that *did* send ``files`` keeps its own list (see the route);
      * a hand-typed copy of a catalogue entry's id and URL is expanded, which
        is the right answer -- it is the same model.
    """
    entry = catalog_entry(model_id)
    if entry is None:
        return None
    if url.rstrip("/") != entry["dfss"].rstrip("/"):
        return None
    return catalog_file_set(entry)


def catalog_file_set(entry: dict) -> list[dict]:
    """Every artifact of a catalogue entry as one ``files`` list.

    A single-file entry is a one-element list. This is the shape the downloader
    and the update path both work in, so "one model, N files" has exactly one
    representation regardless of how the catalogue spells it.
    """
    if entry.get("files"):
        files = [dict(f) for f in entry["files"]]
        for f in files:
            f.setdefault("dfss", f.get("url"))
        return files
    return [{"dfss": entry.get("dfss"), "dflag": entry.get("dflag"),
             "md5": entry.get("md5"), "size_bytes": entry.get("size_bytes") or 0}]


# -- dfss download tags (``--dflag``) ---------------------------------------
#: Where the vendor publishes the tag index. The tool resolves this against its
#: own ``open@sophgo.com`` server list, so it is a dfss URL like any other.
DFSS_FLAGS_URL = "open@sophgo.com:/.dfss_flags"

#: Suffix that turns a model's tag into the tag of its md5 sidecar. The sidecar
#: is what makes a swap detectable: it names the *real* file, so a board can see
#: that the file it installed under that tag is no longer the one the tag points
#: at, without downloading twenty gigabytes to find out.
DFLAG_MD5_SUFFIX = ".md5"

#: How long the index is reused. The server rescans its flag files about once a
#: minute, so a shorter cache would re-download a file that cannot have changed.
FLAGS_TTL_S = 600.0

#: The index download must not hold up a console page. It is a few KB, but the
#: board's route to the server can be down, and this runs behind ``GET
#: /api/catalog``.
FLAGS_TIMEOUT_S = 15.0

#: How long a *failed* index refresh is left alone before the next attempt.
#: Shorter than the success TTL because the failure is usually transient (a
#: route coming back), but not zero: retrying on every poll means a dfss process
#: and a 15 s timeout behind each catalogue page load while the board is offline.
FLAGS_RETRY_TTL_S = 120.0

# Parses a sidecar: ``<md5>  <file name>``, the same shape ``md5sum`` writes.
_SIDECAR = re.compile(r"^\s*([0-9a-fA-F]{32})\s+\*?(\S.*?)\s*$")


def parse_sidecar(text: str) -> tuple[str, str] | None:
    """``(md5, file name)`` from a ``<md5>  <file>`` sidecar, or None.

    The first non-empty line wins: a file with a stray blank line or a trailing
    newline is normal, one with two digest lines is not something to guess at.
    """
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _SIDECAR.match(line)
        if m is None:
            return None
        return m.group(1).lower(), Path(m.group(2)).name
    return None


class DfssFlags:
    """The tag index (``/.dfss_flags``), downloaded and cached.

    The index is ``{"<tag>": {"filepath": "<path relative to the open root>"}}``.
    Its only use here is the *file name* a tag points at -- enough to tell an
    installed model from an outdated one -- so the whole document is kept as the
    raw mapping and the interpretation lives in ``tag_filename``.

    Failure is never an error the caller has to handle: an offline board, a
    server without the index, or a timeout all leave ``tags`` empty, which the
    catalogue turns into "no update information" rather than a broken page.
    """

    def __init__(self, ttl_s: float = FLAGS_TTL_S,
                 timeout_s: float = FLAGS_TIMEOUT_S,
                 retry_ttl_s: float = FLAGS_RETRY_TTL_S) -> None:
        self.ttl_s = ttl_s
        self.timeout_s = timeout_s
        #: How long a *failed* refresh is left alone. Retrying on every poll
        #: would put a 15 s dfss run (and its subprocess) behind each catalogue
        #: page while the board is offline; a shorter TTL still recovers the
        #: moment the route comes back, without a restart.
        self.retry_ttl_s = retry_ttl_s
        self.tags: dict[str, str] = {}
        #: When the last refresh *succeeded*. Zero until it ever has: an empty
        #: index is a legitimate answer and must not be re-fetched every poll,
        #: which is why freshness is keyed on the attempt and not on ``tags``.
        self.fetched_at: float = 0.0
        #: When the last refresh failed, for the retry TTL above.
        self.failed_at: float = 0.0
        #: Why the last refresh failed, for the console to say so plainly
        #: instead of silently claiming everything is up to date.
        self.error: str = ""
        #: The in-flight background refresh (see ``schedule_refresh``).
        self._task: asyncio.Task | None = None
        #: One refresh at a time: the console polls the catalogue, and three
        #: concurrent pages must not launch three downloads of the index.
        self._lock: asyncio.Lock | None = None
        self._lock_loop: object | None = None

    def fresh(self) -> bool:
        """Whether the cache answers "what does the index say" right now.

        Two clocks, because a failure is not the same as a success: a good
        index is reused for the full TTL, a failed attempt only for the much
        shorter retry TTL. Keying this on ``tags`` being non-empty was wrong in
        both directions -- a server with an empty index would be re-downloaded
        on every poll, and a failure would be retried on every poll too.
        """
        now = time.monotonic()
        if self.fetched_at and (now - self.fetched_at) < self.ttl_s:
            return True
        if self.failed_at and (now - self.failed_at) < self.retry_ttl_s:
            return True
        return False

    def tag_filename(self, tag: str) -> str | None:
        """The file name the tag currently points at, or None if unknown."""
        hit = self.tags.get(tag)
        if not hit:
            return None
        return Path(hit).name or None

    def _loop_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    async def refresh(self, force: bool = False) -> dict[str, str]:
        """Download the index if the cache is stale; return the tags.

        Every failure is recorded in ``error`` and returns whatever is cached
        (possibly nothing). Callers on a request path must never see an
        exception from this: "the catalogue could not check for updates" is
        information, not an outage.
        """
        if not force and self.fresh():
            return self.tags
        async with self._loop_lock():
            # A caller that waited on the lock may find a refresh it did not do.
            if not force and self.fresh():
                return self.tags
            try:
                self.tags = await self._fetch()
                self.fetched_at = time.monotonic()
                self.failed_at = 0.0
                self.error = ""
            except Exception as exc:  # noqa: BLE001 - see the docstring
                self.error = f"{type(exc).__name__}: {exc}"
                logger.warning("could not refresh the dfss tag index: %s", self.error)
                # Start the retry clock even when there is no cache to keep:
                # otherwise an offline board runs a doomed dfss (and its 15 s
                # timeout) behind every single catalogue poll. A stale index is
                # still kept -- better than telling the operator every model is
                # up to date.
                self.failed_at = time.monotonic()
            return self.tags

    async def _fetch(self) -> dict[str, str]:
        scratch = Path(tempfile.mkdtemp(prefix=".dfss-flags-"))
        try:
            # ``bootstrap=False``: this runs behind a console page. Installing
            # dfss means pip, PyPI and up to five minutes inside a request the
            # operator did not ask to wait for. A box without dfss simply gets
            # no update information (the error is recorded, the page renders).
            rc, tail = await asyncio.wait_for(
                run_dfss(DFSS_FLAGS_URL, scratch, bootstrap=False),
                timeout=self.timeout_s)
            if rc != 0:
                raise RuntimeError(f"dfss 退出码 {rc}：{dfss_reason(tail)}")
            path = scratch / Path(DFSS_FLAGS_URL).name
            if not path.is_file():
                found = [p.name for p in scratch.iterdir() if p.is_file()]
                raise RuntimeError(
                    f"dfss 未产出标签索引（目录内为：{'、'.join(found) or '空'}）")
            raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(raw, dict):
                raise RuntimeError("标签索引格式不对：顶层不是对象")
            out: dict[str, str] = {}
            for tag, info in raw.items():
                filepath = info.get("filepath") if isinstance(info, dict) else None
                if isinstance(filepath, str) and filepath.strip():
                    out[str(tag)] = filepath.strip()
            return out
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def reset(self) -> None:
        """Drop the cache (tests, and a storage move that changes nothing here)."""
        self.tags = {}
        self.fetched_at = 0.0
        self.failed_at = 0.0
        self.error = ""
        self._lock = None
        self._lock_loop = None

    def schedule_refresh(self) -> dict[str, str]:
        """Return what is cached and refresh in the background when stale.

        This is what the catalogue route calls: the console page must open even
        when the board's route to dfss is down, so a stale cache is served
        immediately and the network work happens on a task nobody waits for.
        The first call after a start simply returns nothing, and the page fills
        its update column in on the next poll.
        """
        if self.fresh():
            return self.tags
        task = getattr(self, "_task", None)
        if task is None or task.done():
            try:
                self._task = asyncio.create_task(self._refresh_quietly())
            except RuntimeError:  # no running loop (a sync caller): serve cache
                return self.tags
        return self.tags

    async def _refresh_quietly(self) -> None:
        try:
            await self.refresh(force=True)
        except Exception:  # noqa: BLE001 - refresh already records its own error
            logger.debug("background tag-index refresh failed", exc_info=True)

    async def aclose(self) -> None:
        """Stop a background refresh that is still running.

        The catalogue route hands the network work to a task nobody awaits, so
        nothing would otherwise own it at shutdown -- and a task left pending
        when the loop closes reports "destroyed but it is pending", which reads
        as a crash on the way out.
        """
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


def model_bmodel_names(model_dir: Path) -> list[str]:
    """The ``.bmodel`` file names actually present in a model directory."""
    if not model_dir.is_dir():
        return []
    return [p.name for p in model_dir.rglob("*") if p.suffix == ".bmodel"]


def update_status(entry: dict, model_dir: Path | None,
                  flags: DfssFlags) -> dict | None:
    """Whether an installed catalogue entry is older than what its tags serve.

    ``None`` means "cannot say": no tags on this entry, no index, or the model
    is not installed. An empty dict is never returned -- callers overlay the
    result onto the catalogue row, and a row must not claim to be up to date
    because the check could not run.

    The comparison is by **file name**, which is the only thing the index and
    the disk have in common. A tag that points at a name the directory does not
    contain means the installed copy is the old file (the whole point of the
    tag: a new build is published under a new name, then the tag is repointed).
    """
    tags = [f.get("dflag") for f in catalog_file_set(entry) if f.get("dflag")]
    if not tags or model_dir is None or not flags.tags:
        return None
    expected: list[str] = []
    for tag in tags:
        name = flags.tag_filename(tag)
        if name is None:
            # The index does not know this tag: it was removed or has not been
            # scanned yet. Either way there is nothing to compare against, and
            # "up to date" would be a guess.
            return None
        expected.append(name)
    local = set(model_bmodel_names(model_dir))
    stale = [name for name in expected if name not in local]
    return {
        # The file the console names in "有新版本：<latest_file>". For a
        # multi-file model this is the first (the detector / the single
        # bmodel), and ``latest_files`` carries the whole set.
        "latest_file": expected[0],
        "latest_files": expected,
        # A partial set counts: a directory holding three of four bmodels is
        # just as much "not the released version" as one holding none.
        "update_available": bool(stale),
        "missing_files": stale,
    }


def _md5_file(path: Path, chunk: int = 1 << 20) -> str:
    """The MD5 of a file, read in chunks (a bmodel is hundreds of MB).

    Checked against the catalogue's declared digest for every file of a set.
    A truncated bmodel is the failure this exists for: dfss reports success on
    a short read often enough that the alternative is `bmrt_load_bmodel failed
    (wrong chip or corrupt file?)` at load time, which sends an operator
    looking at the board instead of at the download.

    Synchronous on purpose: the stub the tests check against, and the body that
    actually reads the bytes. Callers inside the event loop must go through
    ``md5_file_async`` -- see there for why.
    """
    import hashlib

    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


async def md5_file_async(path: Path, chunk: int = 1 << 20) -> str:
    """``_md5_file`` off the event loop.

    The service is one asyncio loop: a 20 GB bmodel takes well over a minute to
    hash, and reading it inline stops *everything* -- the catalogue page, the
    model status poll and every in-flight streamed generation in the other
    models -- for that minute. A thread is the right size of fix here: the work
    is pure I/O plus hashlib (which releases the GIL for chunks this size), and
    there is no shared state to protect.
    """
    return await asyncio.to_thread(_md5_file, path, chunk)


def check_space(dest_root: Path, need_bytes: int) -> tuple[bool, str]:
    free = shutil.disk_usage(dest_root).free
    if free < need_bytes + DISK_HEADROOM:
        return False, (
            f"磁盘空间不足：需要 {need_bytes / 2**30:.1f} GiB + "
            f"{DISK_HEADROOM / 2**30:.1f} GiB 余量，实际可用 {free / 2**30:.1f} GiB"
        )
    return True, ""


# dfss prints one progress bar per file; these two shapes are what it emits for
# the console. The bar carries the only byte counts dfss ever gives us.
_DFSS_BYTES = re.compile(r"\[\s*([\d.]+)\s*([KMG]i?B)\s*\]")
_DFSS_PERCENT = re.compile(r"(\d{1,3})%")
_DFSS_UNITS = {"B": 1, "KB": 1000, "KIB": 1024, "MB": 1000**2, "MIB": 1024**2,
               "GB": 1000**3, "GIB": 1024**3}

# Interpreter for the dfss module. It is not on every Python (the board keeps it
# in sophon-demo's venv), so this is overridable and defaults to the interpreter
# running this service, which is the one the service file chose for a reason.
DFSS_PYTHON_ENV = "CV84X6_DFSS_PYTHON"

# Whether this service may install dfss itself. On by default because a fresh
# board has pip but no dfss, and "download a model" must not require the
# operator to open a shell first; an operator who pins their environment can
# turn it off and get a plain "not installed" error instead.
DFSS_BOOTSTRAP_ENV = "CV84X6_DFSS_BOOTSTRAP"

# The release dfss is installed from. A floor, not an exact pin: the vendor
# publishes this package and its binary payload together, and every 1.10.x
# release carries the same CLI (``--url=``) this service drives. Checked against
# PyPI on 2026-10-26 (latest 1.10.8).
#
# 1.10.9 is the floor for ``--dflag`` (the download-tag mechanism), not for
# ``--url``. ``ensure_dfss`` therefore checks the feature separately, via the
# tool's own ``--help``, and upgrades an older wheel rather than failing:
# a board imaged last month has 1.10.6, which has no ``--dflag`` at all.
DFSS_SPEC = "dfss>=1.10.0"

#: The first release whose CLI has ``--dflag``. Used both to phrase the message
#: when a present-but-too-old dfss still needs upgrading and as the spec an
#: upgrade actually asks for: ``pip install --upgrade 'dfss>=1.10.0'`` against an
#: installed 1.10.8 is **already satisfied**, so it would install nothing and the
#: tag path would keep failing. Asking for the floor that has the feature is what
#: makes the upgrade real.
DFSS_DFLAG_MIN = "1.10.9"

#: The requirement an upgrade to tag support is expressed as.
DFSS_DFLAG_SPEC = f"dfss>={DFSS_DFLAG_MIN}"

# pip install bound: the wheel is ~11 MB and pip resolves a couple of
# dependencies, so this is generous while still failing a hung index.
DFSS_INSTALL_TIMEOUT_S = 300.0

# Serialises a bootstrap across every caller in this process. Two model
# downloads started together would otherwise race two pip runs into the same
# ``--user`` site, and pip is not safe against that (it can leave a half-written
# wheel in the cache and a mangled dist-info behind).
_dfss_install_lock: asyncio.Lock | None = None
_dfss_lock_loop: object | None = None
# The last bootstrap result, so a second download in the same process asks pip
# nothing: (ok, message, when). A success is remembered for the life of the
# process; a failure only for DFSS_FAILURE_COOLDOWN_S, because "the index was
# briefly unreachable" must not disable downloads until a restart, while three
# jobs started in the same second must not each run pip.
_dfss_install_result: tuple[bool, str, float] | None = None

# How long a failed bootstrap is remembered. Long enough that a burst of jobs
# shares one attempt, short enough that fixing the network is enough to retry.
DFSS_FAILURE_COOLDOWN_S = 30.0


def _lock() -> asyncio.Lock:
    """The bootstrap lock for the running event loop.

    Created lazily and per loop: a module-level ``asyncio.Lock()`` binds to
    whichever loop first awaited it, and reusing it from another loop raises
    "bound to a different event loop". The service runs one loop, but the test
    suite does not, and a lock that cannot be created outside a running loop is
    also simply harder to reason about.
    """
    global _dfss_install_lock, _dfss_lock_loop
    loop = asyncio.get_running_loop()
    if _dfss_install_lock is None or _dfss_lock_loop is not loop:
        _dfss_install_lock = asyncio.Lock()
        _dfss_lock_loop = loop
    return _dfss_install_lock


def reset_dfss_bootstrap_cache() -> None:
    """Forget the cached bootstrap result (tests, and an operator-triggered retry)."""
    global _dfss_install_result, _dfss_install_lock, _dfss_lock_loop
    _dfss_install_result = None
    _dfss_dflag_caps.clear()
    # The lock belongs to the loop that first used it; dropping it here keeps a
    # long-lived process (and any test suite with several loops) from reusing a
    # lock bound to a closed one.
    _dfss_install_lock = None
    _dfss_lock_loop = None


def dfss_python() -> str:
    """The interpreter ``python -m dfss`` should run under."""
    return os.environ.get(DFSS_PYTHON_ENV, "").strip() or sys.executable


def dfss_bootstrap_allowed() -> bool:
    return os.environ.get(DFSS_BOOTSTRAP_ENV, "").strip().lower() not in (
        "0", "false", "no", "off",
    )


def dfss_offline() -> bool:
    """Whether the board is told to stay off every network, PyPI included.

    ``CV84X6_AGENT_OFFLINE=1`` already means "agent installs use the dfss mirror
    only"; installing dfss itself needs PyPI, or a wheel the operator put
    somewhere local. Both paths are honoured here rather than pretending the
    install succeeded and failing later on a network timeout.
    """
    return os.environ.get("CV84X6_AGENT_OFFLINE", "").strip() not in (
        "", "0", "false", "False", "no", "off",
    )


async def _terminate_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill a spawned tool *and everything it spawned*, then reap it.

    ``proc.kill()`` signals only the direct child. Both tools driven here are
    Python wrappers that run their real work through ``sh -c`` (dfss' native
    downloader) or through a build backend (pip), so signalling only the wrapper
    leaves the actual worker running. The tools are started with
    ``start_new_session=True`` precisely so the whole group can be signalled
    here.

    This runs on cancel paths, so it must not raise: a process that has already
    gone is the normal case rather than an error.
    """
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        # Not a group leader, or already reaped: signal the child itself.
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass
    try:
        await proc.wait()
    except asyncio.CancelledError:
        pass


async def _dfss_help(python: str) -> tuple[bool, str, list[str]]:
    """``(importable, why not, --help output lines)`` for one interpreter.

    ``--help`` is the cheapest probe that proves the module resolved *and* its
    binary payload is present: the wrapper prints its banner before parsing
    arguments, so a missing/incompatible wheel fails here rather than 20 GB into
    a transfer.

    The output is kept as well, because it is also the answer to "does this dfss
    have ``--dflag``": the option list is printed by the tool itself, so reading
    it here is authoritative for the *installed* version, without parsing a
    version string the vendor does not promise to format one way.
    """
    proc = await asyncio.create_subprocess_exec(
        python, "-m", "dfss", "--help",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        await _terminate_tree(proc)
        return False, "dfss --help 超时（60 s）", []
    except asyncio.CancelledError:
        # A cancelled refresh (or a shutting-down service) must not leave the
        # probe behind: the caller may be gone, the interpreter is not.
        await _terminate_tree(proc)
        raise
    text = out.decode("utf-8", "replace").strip()
    lines = text.splitlines()
    if proc.returncode == 0:
        return True, "", lines
    return False, dfss_reason(lines), lines


#: ``--dflag`` support per interpreter, filled by ``ensure_dfss``. A capability,
#: not a version: it is read from the tool's own ``--help``.
_dfss_dflag_caps: dict[str, bool] = {}


def reset_dfss_caps() -> None:
    """Forget the probed capabilities (tests, and a manual dfss upgrade)."""
    _dfss_dflag_caps.clear()


def help_has_dflag(lines: list[str]) -> bool:
    """Whether a dfss ``--help`` listing offers ``--dflag``.

    Both spellings the tool has used are accepted -- ``--dflag DFLAG`` in the
    option list, and a ``--dflag=`` mention in a usage line -- because the exact
    layout is the vendor's to change.
    """
    return any("--dflag" in line for line in lines)


def dfss_dflag_supported(python: str | None = None) -> bool:
    """Whether the last bootstrap proved ``--dflag`` works on this interpreter.

    Unknown counts as unsupported: the download path then uses the fixed URL,
    which always works, instead of attempting an option the tool may reject.
    """
    return _dfss_dflag_caps.get(python or dfss_python(), False)


def _pip_install_argv(python: str, spec: str = DFSS_SPEC) -> list[str]:
    """``pip install --user`` through the interpreter that will run dfss.

    ``--user`` rather than a system install: the service user owns that directory
    and a customer site's Python is not ours to modify. ``--upgrade`` makes a
    too-old dfss move forward instead of pip answering "already satisfied".

    ``spec`` is what the upgrade asks for. Installing afresh and upgrading an
    old-but-present wheel are different requirements: ``dfss>=1.10.0`` is
    satisfied by the 1.10.8 that has no ``--dflag``, so the tag path has to ask
    for ``DFSS_DFLAG_SPEC`` or pip would answer "already satisfied" and change
    nothing.
    """
    return [
        python, "-m", "pip", "install",
        "--user", "--upgrade",
        "--disable-pip-version-check", "--no-input",
        spec,
    ]


async def ensure_dfss(
    python: str | None = None,
    on_line: Callable[[str], None] | None = None,
    *,
    require_dflag: bool = False,
) -> str:
    """Make ``python -m dfss`` runnable, installing it if needed.

    Returns the interpreter that now has dfss. Raises ``RuntimeError`` with a
    message an operator can act on when it cannot be made to work -- the caller
    turns that into the download job's error text, so it must say *why* (offline,
    no pip, pip's own words) rather than a bare "dfss missing".

    Rules, in order:

    1. Already importable -> nothing happens. No pip on every download.
    2. ``CV84X6_AGENT_OFFLINE=1`` -> refuse. A board told to stay off the network
       must not have this service quietly reach PyPI.
    3. ``CV84X6_DFSS_BOOTSTRAP=0`` -> refuse, with the manual command.
    4. Otherwise ``python -m pip install --user --upgrade`` under a lock, then
       verify by importing; pip's own output is streamed to ``on_line`` so the
       failure is in the job log, not just in the service log.

    ``require_dflag`` additionally *prefers* a dfss that understands download
    tags (``--dflag``, 1.10.9 and later). An interpreter with an older wheel is
    **upgraded**, and every way that upgrade can fail -- offline, bootstrap
    disabled, pip unable to reach an index, pip timing out -- leaves a dfss that
    still downloads over ``--url``. Tags are therefore a preference, never a
    precondition: this function returns the working interpreter, records "no
    --dflag" (see ``dfss_dflag_supported``) and lets the caller fall back to the
    fixed URL. The only thing that raises is a box with **no** dfss at all,
    which is the baseline behaviour and a real "cannot download" (the message
    says which rule refused).

    The one case that must not be papered over is ``help`` failing for a
    different reason than "too old": that is still just "no dfss", and the
    baseline error explains it.
    """
    global _dfss_install_result
    python = python or dfss_python()

    # dfss works but tags do not: everything that follows is an *upgrade
    # attempt*, and a failure there must degrade to the fixed URL rather than
    # fail a download the interpreter could already do. Kept as one closure so
    # no branch can accidentally re-raise, and so every path records the same
    # "no --dflag" capability and says the same thing to the job log.
    def _tags_unavailable(reason: str) -> str:
        _dfss_dflag_caps[python] = False
        _announce(on_line, (
            f"当前 dfss 不支持 --dflag（需要 ≥ {DFSS_DFLAG_MIN}），{reason}；"
            f"本次使用固定地址下载"))
        return python

    # A refresh from an older interpreter must not inherit the previous answer.
    _dfss_dflag_caps.pop(python, None)
    try:
        ok, _why, lines = await _dfss_help(python)
    except FileNotFoundError as exc:
        raise RuntimeError(f"找不到 Python 解释器 {python}：{exc}；可用 CV84X6_DFSS_PYTHON 指定") from exc
    if ok:
        _dfss_dflag_caps[python] = help_has_dflag(lines)
        if _dfss_dflag_caps[python] or not require_dflag:
            return python
        if dfss_offline():
            return _tags_unavailable("且 CV84X6_AGENT_OFFLINE=1（离线模式）不允许升级")
        if not dfss_bootstrap_allowed():
            return _tags_unavailable("且 CV84X6_DFSS_BOOTSTRAP 已禁用升级")
    else:
        # No dfss at all: the baseline rules decide, and they raise.
        if dfss_offline():
            raise RuntimeError(
                f"{python} 里没有 dfss，且 CV84X6_AGENT_OFFLINE=1（离线模式）不允许联网安装。"
                f"请在有网的机器上下载 {DFSS_SPEC} 的 wheel 拷到板子上，执行 "
                f"{python} -m pip install --user <wheel>；或用 CV84X6_DFSS_PYTHON "
                f"指向已经装好 dfss 的解释器"
            )
        if not dfss_bootstrap_allowed():
            raise RuntimeError(
                f"{python} 里没有 dfss，且 CV84X6_DFSS_BOOTSTRAP 已禁用自动安装。"
                f"请手动执行 {python} -m pip install --user '{DFSS_SPEC}'"
            )

    async with _lock():
        # Another caller may have finished the install while this one waited.
        cached = _dfss_install_result
        if cached is not None:
            installed, message, at = cached
            if installed:
                # The capability was recorded by whichever caller did the probe;
                # if this one is asking for the first time (a fresh env var) it
                # gets a probe here rather than an unearned "yes".
                if python in _dfss_dflag_caps:
                    return python
                ok2, _why, lines2 = await _dfss_help(python)
                _dfss_dflag_caps[python] = ok2 and help_has_dflag(lines2)
                return python
            # A stale failure is retried: a fixed network or a reachable index
            # should not require restarting the service.
            if time.monotonic() - at < DFSS_FAILURE_COOLDOWN_S:
                if ok:
                    # The remembered failure was an upgrade, not an install:
                    # the tool still works, so fall back instead of raising the
                    # upgrade's error at a download that does not need it.
                    return _tags_unavailable(f"且此前的升级失败（{message}）")
                raise RuntimeError(message)
        ok, _why, lines = await _dfss_help(python)
        if ok and (help_has_dflag(lines) or not require_dflag):
            _dfss_dflag_caps[python] = help_has_dflag(lines)
            _dfss_install_result = (True, "", time.monotonic())
            return python

        if ok:
            _announce(on_line, (
                f"当前 dfss 不支持 --dflag（需要 ≥ {DFSS_DFLAG_MIN}），"
                f"正在升级到 {DFSS_DFLAG_SPEC}…"))
        else:
            _announce(on_line, f"未找到 dfss，正在用 {python} 安装 {DFSS_SPEC}（用户级）…")
        spec = DFSS_DFLAG_SPEC if (ok and require_dflag) else DFSS_SPEC
        #: Was there a *working* dfss before this pip run? If so the run is an
        #: upgrade, and a failure has to degrade to the fixed URL rather than
        #: fail a download the interpreter can still do (see the docstring).
        upgrading = ok
        try:
            rc, tail = await _pip_install(_pip_install_argv(python, spec), on_line)
        except RuntimeError as exc:
            # pip timed out (``_pip_install`` raises its own RuntimeError).
            if upgrading:
                return _tags_unavailable(f"升级失败（{exc}）")
            raise

        ok, why, lines = await _dfss_help(python)
        if ok:
            has = help_has_dflag(lines)
            _dfss_dflag_caps[python] = has
            _dfss_install_result = (True, "", time.monotonic())
            _announce(on_line, f"dfss 安装完成（{spec}）")
            if require_dflag and not has:
                # Upgrading reported success but the option is still missing:
                # an index serving an old wheel. Not fatal -- fall back.
                _announce(on_line, (
                    f"升级后的 dfss 仍不支持 --dflag；本次使用固定地址下载"))
            return python

        message = (
            f"dfss 自动安装失败：pip 退出码 {rc}"
            f"（{dfss_reason(tail)}）；安装后仍无法导入：{why}"
        )
        _dfss_install_result = (False, message, time.monotonic())
        if upgrading:
            return _tags_unavailable(f"且升级未成功（pip 退出码 {rc}）")
        raise RuntimeError(message)


def _announce(on_line: Callable[[str], None] | None, text: str) -> None:
    """Report a bootstrap step to the job and the service log alike."""
    logger.info("%s", text)
    if on_line is not None:
        on_line(text)


async def _pip_install(
    argv: list[str],
    on_line: Callable[[str], None] | None = None,
) -> tuple[int, list[str]]:
    """Run pip, streaming its output; returns (exit code, tail).

    pip's progress and, more importantly, the reason a resolve failed (no
    network, no matching wheel, a proxy rejecting the index) only exist in this
    output, so it is forwarded to the job rather than swallowed.
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env=_pip_env(),
        start_new_session=True,
    )
    assert proc.stdout is not None
    tail: list[str] = []

    async def pump() -> None:
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                return
            text = raw.decode("utf-8", "replace").strip()
            if not text:
                continue
            tail.append(text)
            del tail[:-40]
            if on_line is not None:
                on_line(text[:300])

    try:
        await asyncio.wait_for(asyncio.gather(pump(), proc.wait()),
                               timeout=DFSS_INSTALL_TIMEOUT_S)
    except asyncio.TimeoutError:
        await _terminate_tree(proc)
        raise RuntimeError(
            f"pip install {DFSS_SPEC} 超过 {DFSS_INSTALL_TIMEOUT_S:.0f} 秒未完成；"
            f"请检查到 PyPI 的网络或配置 pip 镜像"
        ) from None
    except asyncio.CancelledError:
        # pip keeps resolving after its parent stops waiting; one left behind
        # goes on writing the ``--user`` site while the service has moved on.
        await _terminate_tree(proc)
        raise
    return proc.returncode or 0, tail


def _pip_env() -> dict[str, str]:
    """pip's environment: never prompt, and never wait forever on a dead index."""
    env = dict(os.environ)
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PIP_NO_INPUT", "1")
    env.setdefault("PIP_DEFAULT_TIMEOUT", "30")
    return env


async def run_dfss(
    target: str,
    dest_dir: Path,
    on_line: Callable[[str], None] | None = None,
    *,
    bootstrap: bool = True,
) -> tuple[int, list[str]]:
    """Run ``python -m dfss --url=<target>`` in ``dest_dir``.

    Shared by the model downloads and the agent installers so the vendor tool is
    called exactly one way. Returns ``(exit code, last lines of output)``; the
    caller decides what a non-zero code means. ``on_line`` sees every line of
    dfss output as it arrives, which is where both progress and the reason for a
    failure come from.

    ``bootstrap`` installs dfss first when the interpreter lacks it (see
    ``ensure_dfss``). It is a keyword with a default so every existing caller
    gets the self-healing behaviour without being changed, and a test can pin
    "no install" while checking the run itself.
    """
    python = dfss_python()
    if bootstrap:
        python = await ensure_dfss(python, on_line)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    return await _run_dfss_process(
        [python, "-m", "dfss", f"--url={target}"], dest_dir, on_line,
    )


async def run_dfss_flag(
    tag: str,
    dest_dir: Path,
    on_line: Callable[[str], None] | None = None,
) -> tuple[int, list[str]]:
    """Run ``python -m dfss --dflag=<tag>`` in ``dest_dir``.

    The tag, not a URL: the server decides which file that means right now,
    which is the whole point -- repointing the tag on the server is how a model
    is upgraded without a new service release. dfss writes the file under its
    **real** name in the working directory, so the caller has to discover what
    arrived rather than assume (see ``_dfss_tag_download``).

    Runs with ``bootstrap=False`` semantics: the caller has already been through
    ``ensure_dfss``, because whether tags work at all is decided there.
    """
    python = dfss_python()
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    return await _run_dfss_process(
        [python, "-m", "dfss", f"--dflag={tag}"], dest_dir, on_line,
    )


async def download_dfss_file(
    target: str,
    dest: Path,
    on_line: Callable[[str], None] | None = None,
) -> list[str]:
    """Pull one file to ``dest`` through dfss, raising if it did not arrive.

    dfss always writes the file under the *remote* base name in its working
    directory, which is not necessarily the name the caller wants, so the
    download runs in a scratch directory next to ``dest`` and the result is
    moved into place -- a half-written file can then never be mistaken for a
    complete one.
    """
    dest = Path(dest)
    remote_name = target.rstrip("/").rsplit("/", 1)[-1]
    if not remote_name:
        raise RuntimeError(f"dfss 地址里没有文件名：{target}")
    scratch = dest.parent / f".dfss-{dest.name}"
    shutil.rmtree(scratch, ignore_errors=True)
    try:
        rc, tail = await run_dfss(target, scratch, on_line)
        if rc != 0:
            raise RuntimeError(f"dfss 退出码 {rc}：{dfss_reason(tail)}")
        produced = scratch / remote_name
        if not produced.is_file():
            # Saying what did arrive beats unpacking the wrong file later.
            found = [p.name for p in scratch.iterdir() if p.is_file()]
            raise RuntimeError(
                f"dfss 未产出 {remote_name}（目录内为：{'、'.join(found) or '空'}）"
            )
        os.replace(produced, dest)
        return tail
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def dfss_reason(tail: list[str]) -> str:
    """The line that explains a dfss failure, not the wrapper's sign-off.

    dfss prints ``ERROR main.cpp:1383: Cannot download /path from host`` and
    then a version banner for the Python wrapper, so taking the last few lines
    verbatim reports the banner and hides the reason.
    """
    for pattern in (r"\bERROR\b", r"Cannot download", r"Unable to open", r"error"):
        hits = [line for line in tail if re.search(pattern, line, re.IGNORECASE)]
        if hits:
            return hits[-1][:300]
    return " | ".join(line[:200] for line in tail[-3:]) or "（无输出）"


async def _run_dfss_process(
    argv: list[str],
    cwd: Path,
    on_line: Callable[[str], None] | None = None,
) -> tuple[int, list[str]]:
    """Spawn the dfss tool, stream its output, return (code, tail).

    dfss draws its progress bar with ``\\r`` and no newline, so a fixed
    ``readline`` would either block until the transfer ends or (with asyncio's
    default 64 KiB limit) die with "Separator is not found" on a large file.
    Reading raw chunks and splitting on both characters keeps the bar visible as
    it moves, which is the whole reason to look at this output.
    """
    # Its own session makes the tool and everything it spawns one process
    # group, so a cancel can stop all of it (see below).
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    assert proc.stdout is not None
    tail: list[str] = []

    def emit(raw: bytes) -> None:
        for piece in re.split(r"[\r\n]+", raw.decode("utf-8", "replace")):
            text = piece.strip()
            if not text:
                continue
            tail.append(text)
            del tail[:-20]
            if on_line is not None:
                on_line(text)

    try:
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            emit(chunk)
        return await proc.wait(), tail
    except asyncio.CancelledError:
        # The tool is a child of this service; a cancelled model download must
        # not leave it writing into the data root. dfss is a Python wrapper that
        # runs its native downloader through ``sh -c``: killing only the wrapper
        # orphaned that downloader, which kept writing the .bmodel -- into a
        # deleted file once the model was removed (seen on .151, v0.6.17).
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        raise


def dfss_progress(text: str, total_bytes: int | None) -> tuple[int, float | None] | None:
    """Read dfss' progress bar: ``(bytes so far, percent)``, or None.

    dfss reports a running ``[3.10 KiB] 100% [====] 3.89 MiB/s`` bar; the
    percentage is the reliable part, the byte count is what it has moved so far
    (never a total), so a caller with the expected size can turn it into bytes.
    """
    m = _DFSS_PERCENT.search(text)
    percent = float(m.group(1)) if m else None
    b = _DFSS_BYTES.search(text)
    if not b:
        return (0, percent) if percent is not None else None
    unit = b.group(2).upper().replace("I", "I")
    scale = _DFSS_UNITS.get(unit)
    if scale is None:
        return (0, percent)
    done = int(float(b.group(1)) * scale)
    if total_bytes and percent is not None:
        done = max(done, int(total_bytes * percent / 100.0))
    return done, percent


# -- one file, by tag when possible -----------------------------------------
#: What a tag download needs to agree with itself. The sidecar is fetched first
#: so a tag never installs a file under a name the server does not call it.
SIDECAR_MAX_BYTES = 4096


async def _fetch_sidecar(tag: str, scratch: Path,
                         on_line: Callable[[str], None] | None) -> tuple[str, str] | None:
    """``(md5, file name)`` from ``<tag>.md5``, or None when it did not arrive.

    Deliberately quiet about failure: the sidecar is an upgrade over the
    catalogue's hard-coded digest, not a replacement for it. A server that has
    not published the sidecar yet must not break a download that the catalogue
    can verify on its own.
    """
    md5_tag = tag + DFLAG_MD5_SUFFIX
    before = {p.name for p in scratch.iterdir()} if scratch.is_dir() else set()
    rc, tail = await run_dfss_flag(md5_tag, scratch, on_line)
    if rc != 0:
        logger.info("sidecar tag %s unavailable: %s", md5_tag, dfss_reason(tail))
        return None
    landed = [p for p in scratch.iterdir()
              if p.is_file() and p.name not in before]
    if not landed:
        return None
    produced = landed[0]
    try:
        if produced.stat().st_size > SIDECAR_MAX_BYTES:
            raise ValueError(f"sidecar 有 {produced.stat().st_size} 字节，不像 md5 文件")
        parsed = parse_sidecar(produced.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        logger.info("sidecar tag %s is unusable: %s", md5_tag, exc)
        parsed = None
    finally:
        # It is a 100-byte scratch file beside a 20 GB one; leaving it would
        # make the "what arrived" check for the model ambiguous.
        produced.unlink(missing_ok=True)
    return parsed


async def _dfss_tag_download(
    entry: dict,
    scratch: Path,
    on_line: Callable[[str], None] | None,
) -> tuple[Path, str] | None:
    """Fetch one catalogue file through its tag; ``(path, md5)`` or None.

    ``None`` means "the tag could not be used", and the caller must fall back to
    the entry's fixed URL. That covers the whole of the card's list -- an old
    dfss that rejects the option, a server whose index has no such tag, and any
    other failure of the transfer itself (a dead route, a full disk halfway
    through). The distinction that matters is *when* the failure happened:

    * nothing usable arrived -> the tag is unavailable, so fall back;
    * a file already arrived under this tag and then failed verification (wrong
      name, no digest, digest mismatch) -> raise. That file is not the published
      build, and re-downloading twenty gigabytes over the fixed URL to fetch
      something else would hide a corrupt or mislabelled release.

    The sequence is what makes a tag trustworthy:

    1. ``<tag>.md5`` -> the digest **and the real file name**;
    2. ``<tag>`` -> the model;
    3. the name that arrived must be the name the sidecar promised (a tag
       repointed between the two requests would otherwise install a file whose
       digest belongs to a different build);
    4. the digest must match.
    """
    tag = entry.get("dflag")
    if not tag:
        return None
    sidecar = await _fetch_sidecar(tag, scratch, on_line)
    before = {p.name for p in scratch.iterdir()} if scratch.is_dir() else set()

    def discard_partial() -> None:
        """Drop whatever this attempt wrote, so the fallback cannot inherit it.

        The fixed-URL retry runs in the same staging directory and looks for the
        *catalogue's* file name there. A truncated file a failed tag attempt left
        under that name would be picked up as if the URL download had produced
        it -- an unverified, half-written bmodel installed as a model.
        """
        for stale in scratch.iterdir() if scratch.is_dir() else []:
            if stale.is_file() and stale.name not in before:
                stale.unlink(missing_ok=True)

    rc, tail = await run_dfss_flag(tag, scratch, on_line)
    if rc != 0:
        # Every non-zero exit is "the tag did not work": a pre-1.10.9 tool, a
        # tag the server has never seen (exit 65280), a network error, a disk
        # that filled. None of those is a reason to refuse a download the fixed
        # URL can still complete; the fallback is reported to the job either
        # way, so the operator is not left guessing why.
        logger.info("tag %s not usable (dfss exit %s): %s",
                    tag, rc, dfss_reason(tail))
        discard_partial()
        return None
    landed = sorted(p for p in scratch.iterdir()
                    if p.is_file() and p.name not in before)
    if not landed:
        raise RuntimeError(f"标签 {tag} 没有产出任何文件")
    produced = landed[0]
    expected_md5 = None
    if sidecar is not None:
        expected_md5, promised_name = sidecar
        if produced.name != promised_name:
            # Two different files arrived under one tag: the index moved
            # between the requests. Installing either would be installing an
            # unverified build, so this is an error, not a fallback.
            produced.unlink(missing_ok=True)
            raise RuntimeError(
                f"标签 {tag} 下载到的是 {produced.name}，而对应的 md5 文件写的是 "
                f"{promised_name}；标签可能在下载过程中被改动，请重试")
    else:
        # No sidecar: trust the catalogue's declared digest and file name.
        expected_md5 = entry.get("md5")
    if not expected_md5:
        produced.unlink(missing_ok=True)
        raise RuntimeError(
            f"标签 {tag} 下载到 {produced.name}，但既没有 md5 sidecar，"
            f"目录里也没有声明的 md5，无法校验")
    actual = await md5_file_async(produced)
    if actual != expected_md5:
        produced.unlink(missing_ok=True)
        raise RuntimeError(
            f"{produced.name} 的 md5 不匹配：期望 {expected_md5}，实际 {actual}"
            f"（文件已丢弃，请重试）")
    return produced, actual


class DownloadManager:
    """Runs download jobs and tracks them for the UI."""

    def __init__(self, models_root: Path, staging_root: Path | None = None) -> None:
        self.models_root = Path(models_root)
        # A model is downloaded into its own directory here and moved into
        # models/<name> only once complete. Writing straight into models/ (what
        # dfss does in its working directory) made a half-written .bmodel look
        # like a model -- loadable while downloading, and still loadable after a
        # failed or cancelled pull. ``<data root>/downloads`` is the data root's
        # place for download temp files and is never scanned for models.
        self.staging_root = (Path(staging_root) if staging_root is not None
                             else self.models_root.parent / "downloads" / "models")
        self.jobs: dict[str, DownloadJob] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        # The download-tag index, for "有新版本". Lives here because it shares
        # the manager's lifetime and its dfss interpreter; the catalogue route
        # reads it, and the update route refreshes it.
        self.flags = DfssFlags()
        #: Called with the model id once a job has changed what is in
        #: ``models/<id>/``. The model manager uses it to re-scan, because an
        #: update renames the file: without it a load in the window between the
        #: swap and the next poll would name a bmodel that no longer exists.
        self.on_installed: Callable[[str], None] | None = None
        # A crashed install can leave ``models/<id>/x.bmodel.bak`` with no
        # ``x.bmodel``: the previous build was moved aside and the process died
        # before the new file was renamed over it. Put it back before anything
        # scans the directory, or the model is gone with its only copy sitting
        # under a name nothing loads.
        self._recover_backups()
        self._clear_stale_staging()

    def _recover_backups(self) -> None:
        """Restore every ``.bak`` whose destination is missing.

        ``_install_all`` moves the installed build aside for the length of one
        rename, so a ``.bak`` with the destination present is a leftover from a
        rollback that did not finish deleting it -- harmless, and
        ``orphan_free_space`` reports it. A ``.bak`` with the destination
        *missing* is the opposite: it is the only copy of the build, and the
        directory otherwise looks like a model that was never installed.
        """
        if not self.models_root.is_dir():
            return
        for dest_dir in self.models_root.iterdir():
            if not dest_dir.is_dir():
                continue
            for backup in dest_dir.glob("*.bak"):
                target = backup.with_name(backup.name[:-len(".bak")])
                if target.exists():
                    continue
                try:
                    os.replace(backup, target)
                except OSError:  # pragma: no cover - a read-only models tree
                    logger.exception("could not restore %s", backup)
                    continue
                logger.warning("restored %s from its interrupted install", target)

    def _clear_stale_staging(self) -> None:
        """Remove staging left by an earlier run.

        Jobs live in memory only, so anything already here when the manager is
        created belongs to a process that is gone (a crash, a reboot mid-pull):
        an incomplete file nobody will finish or install.
        """
        if not self.staging_root.is_dir():
            return
        for entry in self.staging_root.iterdir():
            logger.info("removing stale download staging %s", entry)
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)

    def staging_dir(self, job: DownloadJob) -> Path:
        return self.staging_root / job.id

    def _install(self, job: DownloadJob, produced: Path) -> Path:
        """Move a completed download into ``models/<name>/`` and return its path."""
        dest_dir = self.models_root / job.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / produced.name
        part = dest.with_name(dest.name + ".part")
        _stage_beside(produced, part)
        try:
            os.replace(part, dest)
        except BaseException:
            # A failed rename leaves a ``.part`` inside models/<id>/ where
            # ``orphan_free_space`` hunts for leftovers and where nothing will
            # ever clean it up (the staging tree is what normally gets removed).
            # Remove it on the way out, so a failed install leaves the directory
            # exactly as it found it.
            part.unlink(missing_ok=True)
            raise
        produced.unlink(missing_ok=True)
        return dest

    def _install_set(self, job: DownloadJob, fetched: list[Path]) -> list[str]:
        """Move a verified set into ``models/<name>/``, replacing what it supersedes.

        Both entry points -- a first install and an in-place upgrade -- end
        here, because on disk they are the same operation: afterwards the
        directory holds exactly the bmodels that were just served, and none of
        the ones they replace.

        Leaving the old file *beside* the new one is not cosmetic.
        ``discover_models`` picks a bmodel by name, so a directory holding two
        builds loads whichever sorts first -- for an upgrade that is the old
        one, while ``update_available`` (a name comparison) keeps reporting
        "有新版本" for the build the operator just installed.

        **All of it or none of it.** A multi-file set is installed to staged
        names first and renamed into place only once every file is across, so a
        set that fails half way (a full disk, an EXDEV copy that dies, a delete
        racing the install) leaves the directory as it was instead of holding
        three of the release's four bmodels. Without this the operator saw a
        model that scanned as installed, reported four files served, and was
        refused at load for the one that never landed.

        Only bmodels are removed: a tokenizer or a config directory beside them
        belongs to the operator, not to the release. Files just installed are
        never candidates, because ``keep`` is consulted by name.

        Returns the names removed.
        """
        keep = {path.name for path in fetched}
        self._install_all(job, fetched)
        removed: list[str] = []
        dest = self.models_root / job.name
        for old in dest.rglob("*.bmodel"):
            if old.name not in keep:
                old.unlink()
                removed.append(old.name)
        return removed

    def _install_all(self, job: DownloadJob, fetched: list[Path]) -> None:
        """Place every fetched file in ``models/<name>/``, or put back what was there.

        Two phases, and the second only runs if the first finished:

        1. every file is **renamed** beside its destination as ``.part`` (the
           scanner ignores those, so nothing half-installed is ever picked up).
           Only if the staging tree is on another filesystem (``EXDEV``) is the
           bytes-copying fallback taken. Renaming matters: staging lives on the
           same filesystem as ``models/``, so a copy here would double the peak
           footprint of an install -- and ``check_space`` only ever reserved one
           copy, which is why a large model upgrade used to fail on a disk that
           had room for it. On a 20 GB bmodel the copy would also be minutes of
           ``write()`` on this board's eMMC;
        2. each destination that already exists is moved aside to ``.bak``, then
           its ``.part`` is renamed over it.

        Phase 2 is the one that can leave a directory mid-upgrade, so each step
        is undone on failure: the new file is removed and the previous build's
        file is renamed back. Afterwards the directory holds exactly what it held
        before the job started, which is what "nothing on disk is touched on
        failure" promises. The move-aside is a rename, not a copy, so a 20 GB
        bmodel costs nothing to roll back.

        A single-file set takes the ordinary ``_install`` path -- one rename has
        nothing to be half way through.

        **Blocking.** This is filesystem work over gigabytes: it runs in a
        worker thread (``asyncio.to_thread`` at every call site), because doing
        it on the event loop froze the whole API -- inference streams and
        ``/healthz`` included -- for the length of the copy.
        """
        dest_dir = self.models_root / job.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        if len(fetched) == 1:
            self._install(job, fetched[0])
            return

        staged: list[tuple[Path, Path]] = []
        seen: set[Path] = set()
        try:
            for produced in fetched:
                dest = dest_dir / produced.name
                if dest in seen:
                    # Two parts for one destination would install in whatever
                    # order the renames happened to run.
                    raise RuntimeError(f"文件集里有重复的文件名 {produced.name}")
                seen.add(dest)
                part = dest.with_name(dest.name + ".part")
                _stage_beside(produced, part)
                staged.append((part, dest))
        except BaseException:
            for part, _ in staged:
                part.unlink(missing_ok=True)
            raise

        done: list[tuple[Path, Path | None]] = []
        try:
            for part, dest in staged:
                backup = None
                if dest.exists():
                    backup = dest.with_name(dest.name + ".bak")
                    os.replace(dest, backup)
                os.replace(part, dest)
                done.append((dest, backup))
        except BaseException:
            # Undo in reverse: the last rename is the one that may have half
            # happened, and putting the previous build back for every swapped
            # file is what makes "nothing on disk is touched on failure" true.
            for dest, backup in reversed(done):
                dest.unlink(missing_ok=True)
                if backup is not None:
                    os.replace(backup, dest)
            for part, dest in staged:
                part.unlink(missing_ok=True)
                # A destination moved aside whose replacement never landed.
                leftover = dest.with_name(dest.name + ".bak")
                if leftover.exists() and not dest.exists():
                    os.replace(leftover, dest)
            raise
        for _, backup in done:
            if backup is not None:
                backup.unlink(missing_ok=True)
        for produced in fetched:
            produced.unlink(missing_ok=True)

    def list(self) -> list[dict]:
        return [j.public() for j in sorted(self.jobs.values(), key=lambda j: j.started_at, reverse=True)]

    def get(self, job_id: str) -> DownloadJob | None:
        return self.jobs.get(job_id)

    def active_names(self) -> set[str]:
        """Model names a job is still downloading.

        The bytes go to staging, but a re-download of a model already on disk
        replaces its file in ``models/<name>`` when the job finishes: a worker
        mapping that file, or a delete racing the install, would see it swapped
        underneath. The model manager and the delete route ask this set before
        loading or deleting.
        """
        return {j.name for j in self.jobs.values() if j.state in ("pending", "running")}

    def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        job = self.jobs.get(job_id)
        if task is None or job is None or job.state not in ("pending", "running"):
            return False
        task.cancel()
        job.state = "cancelled"
        job.finished_at = time.time()
        return True

    async def cancel_and_wait(self, job_id: str, timeout: float = 10.0) -> bool:
        """Cancel ``job_id`` and return once its transfer has really stopped.

        ``cancel`` only requests the stop; the job keeps reading as running
        until the task has killed the tool. Waiting here keeps the model locked
        (see ``active_names``) for exactly that long, so no load can start on a
        file something is still writing.
        """
        task = self._tasks.get(job_id)
        job = self.jobs.get(job_id)
        if task is None or job is None or job.state not in ("pending", "running"):
            return False
        task.cancel()
        await asyncio.wait({task}, timeout=timeout)
        if job.state in ("pending", "running"):
            # A task cancelled before it first ran never reaches its handlers.
            job.state = "cancelled"
            job.finished_at = time.time()
        return True

    def start_url(self, url: str, name: str, expected_bytes: int | None = None,
                  files: list[dict] | None = None) -> DownloadJob:
        """Start an http(s) pull.

        ``files`` works exactly as it does for ``start_dfss``: a model made of
        several artifacts downloads as one job and installs as a set. It exists
        here too because a customer site with no route to dfss is the case the
        URL path is *for* -- and an OCR model fetched one file at a time leaves a
        directory that looks loadable and is not.
        """
        name = _safe_name(name)
        cleaned = _clean_file_set(files, url) if files else []
        if cleaned:
            expected_bytes = (sum(f["size_bytes"] for f in cleaned)
                              or expected_bytes)
        if expected_bytes:
            ok, msg = check_space(self.models_root, expected_bytes)
            if not ok:
                raise ValueError(msg)
        job = DownloadJob(id=uuid.uuid4().hex, kind="url", target=url, name=name,
                          total_bytes=expected_bytes, files=cleaned)
        self.jobs[job.id] = job
        self._tasks[job.id] = asyncio.create_task(self._run_url(job))
        return job

    def start_dfss(self, dfss_url: str, name: str,
                   expected_bytes: int | None = None,
                   files: list[dict] | None = None) -> DownloadJob:
        """Start a dfss pull.

        ``files`` is for a model made of several artifacts (OCR: a detector plus
        three recogniser widths). Each entry is ``{"dfss", "md5", "size_bytes"}``
        and the whole set lands in ``models/<name>/`` together, so an
        interrupted pull cannot leave a directory that looks loadable. Omitted --
        every caller before OCR, and the manual URL box -- means the single
        ``dfss_url``, which is the same job with a one-element list.
        """
        name = _safe_name(name)
        cleaned = _clean_file_set(files, dfss_url) if files else []
        if cleaned:
            expected_bytes = sum(f["size_bytes"] for f in cleaned) or expected_bytes
        if expected_bytes:
            # dfss gives no size up front; the catalog does. Refuse before
            # writing tens of GB into a disk that cannot hold it.
            ok, msg = check_space(self.models_root, expected_bytes)
            if not ok:
                raise ValueError(msg)
        job = DownloadJob(id=uuid.uuid4().hex, kind="dfss", target=dfss_url, name=name,
                          total_bytes=expected_bytes, files=cleaned)
        self.jobs[job.id] = job
        self._tasks[job.id] = asyncio.create_task(self._run_dfss(job))
        return job

    def start_update(self, entry: dict, expected_bytes: int | None = None) -> DownloadJob:
        """Start an in-place upgrade of an installed catalogue model.

        Distinct from ``start_dfss`` in exactly one way, and it is the reason the
        route exists separately: the new file is downloaded to staging, verified,
        and only then **swapped in**, with the file it replaces removed. A
        re-download reads as an install of whatever the tag serves; an upgrade
        has to leave a directory holding *one* build, not both -- two bmodels
        side by side is a model that loads the wrong weights (see
        ``discover_models``, which picks one by name).

        The job name is the model id, so it takes the same download lock: the
        console greys the card out and ``GET /api/models`` reports
        ``downloading`` while the swap is in flight.
        """
        files = catalog_file_set(entry)
        if not any(f.get("dflag") for f in files):
            raise ValueError(
                f"模型 {entry['id']} 没有下载标签，无法检测或执行更新；"
                "请用固定地址重新下载")
        name = _safe_name(entry["id"])
        cleaned = _clean_file_set(files, entry.get("dfss") or "")
        total = expected_bytes or (sum(f["size_bytes"] for f in cleaned) or None)
        if total:
            ok, msg = check_space(self.models_root, total)
            if not ok:
                raise ValueError(msg)
        job = DownloadJob(id=uuid.uuid4().hex, kind="dfss",
                          target=entry.get("dfss") or cleaned[0]["target"],
                          name=name, total_bytes=total, files=cleaned)
        self.jobs[job.id] = job
        self._tasks[job.id] = asyncio.create_task(self._run_update(job))
        return job

    async def _run_update(self, job: DownloadJob) -> None:
        """Download every file of the entry, then replace the installed build.

        Same fetch as ``_run_dfss`` (via ``_fetch_set``) so a tag that works for
        a first install works for an upgrade. The difference is on the way out:
        each arrived file replaces the installed one and every *other* bmodel in
        the directory is removed, because the tag names the build that should be
        there -- keeping the old one would leave two candidates for the loader.

        On failure nothing on disk is touched: the installed model is still the
        model, and a half-upgraded directory would be worse than an old one.
        """
        staging = self.staging_dir(job)
        try:
            fetched, notes = await self._fetch_set(job, staging,
                                                   require_tags=True)
            if fetched is None:
                return  # _fetch_set already recorded the state and message

            dest = self.models_root / job.name
            if not dest.is_dir():
                # Deleted while the bytes were arriving (the delete route
                # refuses a "downloading" model, but the directory can go away
                # by other means). Re-creating it here would resurrect a model
                # nobody asked for; the fetched files go with the staging dir.
                raise RuntimeError(
                    f"模型目录 {job.name} 在更新过程中消失了，已放弃更新")
            removed = await asyncio.to_thread(self._install_set, job, fetched)
            job.state = "done"
            job.message = f"已更新 models/{job.name}{notes}"
            if removed:
                job.message += f"；已删除旧文件 {'、'.join(sorted(removed))}"
            # The directory's contents changed (a new name, and the old one
            # gone), so the manager's idea of which files to load is stale.
            if self.on_installed is not None:
                try:
                    self.on_installed(job.name)
                except Exception:  # noqa: BLE001 - a rescan must not fail the job
                    logger.exception("rescan of %s after its update failed", job.name)
        except asyncio.CancelledError:
            job.state = "cancelled"
            raise
        except FileNotFoundError as exc:
            job.state = "error"
            job.message = f"找不到 dfss 解释器：{exc}；可用 CV84X6_DFSS_PYTHON 指定"
        except RuntimeError as exc:
            job.state = "error"
            job.message = str(exc)
        except Exception as exc:
            job.state = "error"
            job.message = f"{type(exc).__name__}: {exc}"
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            job.finished_at = time.time()

    # -- url download ----------------------------------------------------
    async def _run_url(self, job: DownloadJob) -> None:
        """Fetch every http(s) file of the job, then install the set.

        Same shape as the dfss path -- one loop over the files, a digest check
        per file, one install at the end -- because the two differ only in the
        transport. Keeping them separate would mean two places that decide what
        "the model arrived" means.
        """
        staging = self.staging_dir(job)
        wanted = job.files or [{
            "target": job.target,
            "name": os.path.basename(job.target).split("?")[0],
            "size_bytes": 0,
            "md5": None,
        }]
        try:
            ok, why = check_space(self.models_root, job.total_bytes or 0)
            if not ok and job.total_bytes:
                job.state, job.message = "error", why
                return
            staging.mkdir(parents=True, exist_ok=True)
            job.state = "running"

            import httpx

            async with httpx.AsyncClient(
                    timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True) as c:
                for index, entry in enumerate(wanted):
                    name = entry["name"]
                    job.message = (f"正在下载 {name}（{index + 1}/{len(wanted)}）"
                                   if len(wanted) > 1 else "正在下载…")
                    async with c.stream("GET", entry["target"]) as r:
                        r.raise_for_status()
                        total = r.headers.get("content-length")
                        if total and not entry["size_bytes"]:
                            entry["size_bytes"] = int(total)
                        with open(staging / name, "wb") as f:
                            async for chunk in r.aiter_bytes(1 << 20):
                                f.write(chunk)
                                job.done_bytes += len(chunk)
                    expected_md5 = entry.get("md5")
                    if expected_md5:
                        actual = await md5_file_async(staging / name)
                        if actual != expected_md5:
                            job.state = "error"
                            job.message = (f"{name} 的 md5 不匹配：期望 {expected_md5}，"
                                           f"实际 {actual}（文件已丢弃，请重试）")
                            return
                    job.files_done = index + 1

            # Only move into place once the whole set is complete and verified: a
            # truncated file -- or a directory holding three of four bmodels --
            # must never look like a usable model.
            #
            # `_install_set`, not a loop of `_install`: a URL download onto an
            # already-installed model is the same operation as an upgrade, and
            # leaving the previous build's bmodel beside the new one made
            # `discover_models` load whichever sorted first (the old one) while
            # the console reported the download had succeeded. It is also what
            # gives a multi-file set one all-or-nothing install.
            replaced = await asyncio.to_thread(
                self._install_set, job,
                [staging / entry["name"] for entry in wanted])
            job.state = "done"
            job.message = (f"已保存到 models/{job.name}"
                           if len(wanted) == 1
                           else f"已下载 {len(wanted)} 个文件到 models/{job.name}")
            if replaced:
                job.message += f"；已替换旧文件 {'、'.join(sorted(replaced))}"
                if self.on_installed is not None:
                    try:
                        self.on_installed(job.name)
                    except Exception:  # noqa: BLE001 - a rescan must not fail the job
                        logger.exception("rescan of %s after its download failed",
                                         job.name)
        except asyncio.CancelledError:
            job.state = "cancelled"
            raise
        except Exception as exc:
            job.state = "error"
            job.message = f"{type(exc).__name__}: {exc}"
            logger.exception("download failed: %s", job.target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            job.finished_at = time.time()

    # -- dfss pull -------------------------------------------------------
    async def _fetch_set(self, job: DownloadJob,
                         staging: Path,
                         *,
                         require_tags: bool = False
                         ) -> tuple[list[Path] | None, str]:
        """Fetch and verify every file of ``job`` into ``staging``.

        Returns ``(paths, message)``; ``paths`` is None when the job already
        carries the failure (``state`` and ``message`` are set) and the caller
        should just stop. Any other problem raises.

        Shared by the first-install and the upgrade paths so a tag that works in
        one works in the other: the discipline -- tag first, fixed URL as the
        reported fallback, digest always -- must not be re-implemented per
        caller. Each ``entry`` in ``job.files`` is updated with the name that
        actually arrived, because a tag may serve a build whose file name this
        release has never heard of.

        ``require_tags`` turns "the fixed URL would do" into a failure, and is
        what an **upgrade** uses. An update means "make the disk match what the
        tag serves"; the fixed URL is the address of whatever this release was
        built against, which may well be the build already installed. Falling
        back there would download that old file, replace the (possibly newer)
        installed one with it, report "已更新", and leave ``update_available``
        true -- a silent downgrade. Only the per-file tag path can answer the
        question an update asks, so if any file cannot come from its tag the
        whole job fails with that said plainly, before anything on disk moves.
        """
        wanted = job.files or [{
            "target": job.target,
            "name": job.target.rstrip("/").rsplit("/", 1)[-1],
            "size_bytes": job.total_bytes or 0,
            "md5": None,
            "dflag": None,
        }]
        if not wanted[0]["name"]:
            raise RuntimeError(f"dfss 地址里没有文件名：{wanted[0]['target']}")
        staging.mkdir(parents=True, exist_ok=True)
        job.state = "running"
        job.message = "正在通过 dfss 下载…"

        # The file the current transfer is fetching, so the progress bar's
        # percentage can be read against *its* size rather than the set's:
        # dfss reports one transfer at a time and a set-sized denominator
        # would make every file look like it finished at 30 %.
        current = {"size": wanted[0]["size_bytes"] or None}

        def on_line(text: str) -> None:
            job.message = text[:300]
            # dfss prints progress percentages; surfacing them beats a
            # spinner that looks frozen for twenty minutes. The bar also
            # carries the bytes moved so far, which the console shows next
            # to the catalog size.
            step = dfss_progress(text, current["size"])
            if step is not None:
                done, percent = step
                if percent is not None:
                    job.percent_hint = percent
                landed = sum(int(f.get("size_bytes") or 0)
                             for f in wanted[: job.files_done])
                job.done_bytes = max(job.done_bytes, landed + done)

        # Install dfss *before* the transfer starts, so a bootstrap failure
        # is reported as itself instead of "dfss 退出码 1" from an
        # interpreter that never had the module. The message already names
        # the cause (offline, disabled, pip's own line).
        #
        # ``require_dflag`` asks the bootstrap to prove the tool understands
        # download tags. It upgrades a dfss that is present but too old, and
        # never raises just because tags are unavailable -- the per-file
        # branch below falls back to the fixed URL. Only asked for when a tag
        # is actually in play: a plain URL pull has no reason to upgrade dfss.
        wants_tag = any(entry.get("dflag") for entry in wanted)
        if wants_tag:
            await ensure_dfss(on_line=on_line, require_dflag=True)
        else:
            await ensure_dfss(on_line=on_line)
        tag_capable = dfss_dflag_supported()

        fetched: list[Path] = []
        used_tag: list[bool] = []
        for index, entry in enumerate(wanted):
            name = entry["name"]
            current["size"] = entry.get("size_bytes") or None
            job.message = (f"正在下载 {name}（{index + 1}/{len(wanted)}）"
                           if len(wanted) > 1 else "正在通过 dfss 下载…")
            produced = None
            if tag_capable and entry.get("dflag"):
                # The tag names the file on the server, which may not be the
                # name this release knew about -- that is precisely how an
                # upgraded build is published.
                got = await _dfss_tag_download(entry, staging, on_line)
                if got is not None:
                    produced, _digest = got
                    if produced.name != name:
                        logger.info("%s: tag %s serves %s (catalogue had %s)",
                                    job.name, entry["dflag"], produced.name, name)
                    # Everything downstream (the install, the update's
                    # replacement step) works off the name that arrived.
                    entry["name"] = produced.name
                    used_tag.append(True)
            if produced is None:
                if require_tags:
                    # An upgrade cannot be served by the fixed URL: that address
                    # is whatever this release shipped with, so downloading it
                    # would at best change nothing and at worst replace a newer
                    # installed build with an older one. Nothing has been
                    # installed at this point, so the message is the whole
                    # outcome.
                    raise RuntimeError(
                        f"标签 {entry['dflag'] or '（无）'} 不可用，无法更新 {job.name}；"
                        f"固定地址只提供本版本发布时登记的文件，用它「更新」可能把已安装的"
                        f"新版本换回旧版本。已安装的文件保持不动")
                if entry.get("dflag"):
                    # The fallback is a deliberate, reported decision, not a
                    # silent one: an operator reading the job must be able
                    # to tell a tag download from a fixed-address one.
                    job.message = (f"标签 {entry['dflag']} 不可用，"
                                   f"已改用固定地址下载 {name}")
                    logger.info("%s: tag %s unusable, using the fixed URL",
                                job.name, entry["dflag"])
                rc, tail = await run_dfss(entry["target"], staging, on_line,
                                          bootstrap=False)
                if rc != 0:
                    job.state = "error"
                    job.message = f"dfss 退出码 {rc}（{name}）：" + " | ".join(tail[-3:])
                    return None, job.message
                produced = staging / name
                if not produced.is_file():
                    found = [p.name for p in staging.iterdir() if p.is_file()]
                    raise RuntimeError(
                        f"dfss 未产出 {name}（目录内为：{'、'.join(found) or '空'}）")
                expected_md5 = entry.get("md5")
                if expected_md5:
                    actual = await md5_file_async(produced)
                    if actual != expected_md5:
                        job.state = "error"
                        job.message = (f"{name} 的 md5 不匹配：期望 {expected_md5}，"
                                       f"实际 {actual}（文件已丢弃，请重试）")
                        return None, job.message
                used_tag.append(False)
            fetched.append(produced)
            job.files_done = index + 1
            job.percent_hint = None
            landed = sum(int(f.get("size_bytes") or 0)
                         for f in wanted[: job.files_done])
            job.done_bytes = max(job.done_bytes, landed)

        job.transport = "dflag" if used_tag and all(used_tag) else "dfss"
        # The notes describe what actually happened, per file. `transport` is a
        # single word, but a set can be mixed, and three distinct outcomes need
        # three messages:
        #   * every file by tag               -> "通过下载标签"
        #   * some by tag, some fell back     -> "部分文件标签不可用"
        #   * nothing by tag                  -> "标签不可用"
        # Tagless files (a vendor entry, or a hand-pasted URL) are not a fallback
        # and must not be reported as one: only the files that *had* a tag and
        # did not use it count.
        tagged = [bool(e.get("dflag")) for e in wanted]
        tagged_used = [t for t, by_tag in zip(tagged, used_tag) if t and by_tag]
        tagged_total = sum(tagged)
        if tagged_total and len(tagged_used) == tagged_total:
            notes = "（通过下载标签，md5 校验通过）"
        elif tagged_used:
            notes = "（部分文件标签不可用，已用固定地址；md5 校验通过）"
        elif tagged_total:
            notes = "（标签不可用，已使用固定地址；md5 校验通过）"
        else:
            notes = ""
        return fetched, notes

    async def _run_dfss(self, job: DownloadJob) -> None:
        """Fetch every file of the job, then install the set in one step.

        A single-file model is the same code with a one-element list: the
        ``files`` field was added for OCR, and keeping one path means the
        staging/verify/install discipline cannot differ between the two.
        """
        staging = self.staging_dir(job)
        try:
            fetched, notes = await self._fetch_set(job, staging)
            if fetched is None:
                return

            wanted = job.files or [{"name": path.name} for path in fetched]
            # Everything arrived and verified: move the whole set into place.
            # Only the files asked for -- whatever else dfss leaves in its
            # working directory stays out of the model directory. A download
            # onto a directory that already holds a *different* build replaces
            # it, exactly like an upgrade: see ``_install_set``. Without that,
            # clicking download on an installed model after its tag moved left
            # two bmodels side by side, the loader picked the older one by name,
            # and the console went on reporting an update that had just been
            # downloaded.
            replaced = await asyncio.to_thread(self._install_set, job, fetched)
            job.state = "done"
            base = (f"已下载到 models/{job.name}"
                    if len(wanted) == 1
                    else f"已下载 {len(wanted)} 个文件到 models/{job.name}")
            job.message = base + notes
            if replaced:
                job.message += f"；已替换旧文件 {'、'.join(sorted(replaced))}"
            # The directory's bmodels may have changed name, so the manager's
            # file list for it is stale -- same reason as after an upgrade.
            if replaced and self.on_installed is not None:
                try:
                    self.on_installed(job.name)
                except Exception:  # noqa: BLE001 - a rescan must not fail the job
                    logger.exception("rescan of %s after its download failed", job.name)
        except asyncio.CancelledError:
            job.state = "cancelled"
            raise
        except FileNotFoundError as exc:
            job.state = "error"
            job.message = f"找不到 dfss 解释器：{exc}；可用 CV84X6_DFSS_PYTHON 指定"
        except RuntimeError as exc:
            # ensure_dfss and the transfer both raise RuntimeError with a
            # complete Chinese explanation; the class name would only add noise.
            job.state = "error"
            job.message = str(exc)
        except Exception as exc:
            job.state = "error"
            job.message = f"{type(exc).__name__}: {exc}"
        finally:
            # The tool is dead by now (a cancel kills its process group before
            # re-raising), so nothing is still writing here. Staging goes in
            # every case: a failed set must leave no half-installed model, and
            # the partial files are worthless without the rest.
            shutil.rmtree(staging, ignore_errors=True)
            job.finished_at = time.time()

    async def shutdown(self) -> None:
        await self.flags.aclose()
        for t in list(self._tasks.values()):
            t.cancel()
        for t in list(self._tasks.values()):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()


def _stage_beside(produced: Path, part: Path) -> None:
    """Put ``produced`` beside its destination as ``part``, writing no new bytes if it can.

    A rename is the whole point: the staging tree lives on the same filesystem as
    ``models/`` in every layout this service creates, so the file arrives under
    the staged name without a second copy on disk. Copying here used to make the
    peak footprint of an upgrade "old build + 2 x new build" while ``check_space``
    reserved only one, which turned a large model upgrade on a nearly full disk
    into a failure -- and minutes of synchronous ``write()`` on the eMMC.

    ``EXDEV`` is the one case that cannot be a rename (an operator pointed the
    staging tree at a different mount). Then, and only then, the bytes are
    copied; a failed copy leaves no ``part`` behind.
    """
    try:
        os.replace(produced, part)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    try:
        shutil.copyfile(produced, part)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    # The bytes were copied rather than moved: the staged source is still there.
    # The caller removes its staging dir either way, but an install that is
    # asked to finish on its own (a test, a manual call) must not leave the
    # original behind as if the move had failed.
    produced.unlink(missing_ok=True)


def orphan_free_space(models_root: Path) -> dict:
    """Report leftover ``.part``/``.bak`` files, waste after a failed pull.

    ``.bak`` is a previous build moved aside by ``_install_all`` for the length of
    one rename. A ``.bak`` whose destination is *present* is what a rollback that
    did not get to finish deleting leaves: the new build landed and this is a
    duplicate, so it is reported (and reclaimable) exactly like a partial
    download.

    A ``.bak`` whose destination is **missing** is not waste at all -- it is the
    only copy of the build, with the install crashed between "move aside" and
    "rename into place". ``_recover_backups`` puts it back at startup; reporting
    it here as garbage would invite an operator to delete the model, so it is
    excluded.
    """
    root = Path(models_root)
    leftovers = [p for pattern in ("*.part", "*.bak")
                 for p in list(root.glob(pattern)) + list(root.glob(f"*/{pattern}"))]
    reclaimable = [
        p for p in leftovers
        if p.suffix != ".bak"
        or p.with_name(p.name[:-len(".bak")]).exists()
    ]
    return {
        "files": [str(p) for p in reclaimable],
        "bytes": sum(p.stat().st_size for p in reclaimable if p.exists()),
        # Kept out of ``files`` so nothing offers to delete it, but visible: an
        # operator whose model "disappeared" should see where it went.
        "recoverable": [str(p) for p in leftovers if p not in reclaimable],
    }
