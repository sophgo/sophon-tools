"""On-disk layout for the knowledge-base app.

Everything lives under one directory per knowledge base::

    <data root>/apps/kb/<kb_id>/
        kb.json                 name, created_at, build-time embedding model + dims
        docs/<doc_id>/          the uploaded file, meta.json, pages/<n>.png
        chunks.jsonl            one JSON object per chunk, in index order
        vectors.npy             float32, one unit vector per row, aligned to chunks

Two rules shape the code here:

* **A reader never sees a half-written file.** Every write goes to a temporary
  file in the same directory and is then ``os.replace``d into place, which is
  atomic on every filesystem this service runs on. A power cut leaves either the
  old file or the new one; ``chunks.jsonl`` and ``vectors.npy`` are rewritten
  together on every change, and a mismatched pair is detected on load rather
  than silently pairing chunk *i* with vector *j*.
* **The aggregate is the truth.** Per-document copies would double ~80 MB of
  vectors on a full library, so the knowledge base's own ``chunks.jsonl`` /
  ``vectors.npy`` are the single source and a document delete filters them.
  Deletion is O(library) but needs no re-embedding, which is the trade that
  matters when the alternative is minutes of NPU time.
* **When the two cannot be kept aligned, say so instead of guessing.** A crash
  between the two writes, or a library edited by an older build, leaves a matrix
  whose row count no longer matches the chunk file. The chunk file wins, the
  matrix is dropped, and ``kb.json`` carries ``needs_reindex`` until a rebuild
  finishes -- that flag is what the console turns into a Reindex button and what
  the vector stage quotes as its reason for being skipped. Appending to a matrix
  known to be misaligned would make every later row point at the wrong text.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: ``<doc_id>`` is a lowercase uuid4 hex: a filesystem-safe name that cannot
#: collide and cannot be confused with a title.
DOC_ID_RE = re.compile(r"^[0-9a-f]{32}$")
#: Same for a knowledge base, so a path parameter can never escape its parent.
KB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class KbError(Exception):
    """A refusal or failure worth explaining to the caller (HTTP 400)."""


class KbNotFound(KbError):
    """No such knowledge base or document (HTTP 404)."""


def new_id() -> str:
    return uuid.uuid4().hex


def write_bytes_atomic(path: Path, data: bytes, *,
                       create_parents: bool = True) -> None:
    """Write ``data`` so a reader sees the old file or the new one, never a mix.

    ``create_parents`` is ``False`` for the files that live *inside* a document
    directory. Creating one on demand is how a delete used to be undone: the
    parser was still running when the operator removed the document, its next
    progress write re-created ``docs/<id>/`` around nothing, and the delete's
    ``rmtree`` then failed with ``ENOTEMPTY``. A document directory only ever
    exists because an upload created it, so a write that cannot find it is a
    write to a document that is gone -- it must fail, not resurrect.
    """
    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:  # pragma: no cover - best effort
                pass


def write_json_atomic(path: Path, payload, *,
                      create_parents: bool = True) -> None:
    write_bytes_atomic(
        path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        create_parents=create_parents)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as exc:
        raise KbError(f"{path.name} 无法读取：{exc}") from exc


@dataclass
class Kb:
    """One knowledge base's metadata (``kb.json``)."""

    id: str
    name: str
    created_at: float
    #: The embedding model the vectors were built with, and their width. Both
    #: are ``None``/0 until the first document is indexed: a library can exist
    #: (and be searched with BM25 alone) before any embedding model is loaded.
    embedding_model: str | None = None
    dims: int = 0
    #: ``vectors.npy`` is known not to line up with ``chunks.jsonl`` (or was
    #: dropped for that reason) and no rebuild has finished since. While it is
    #: set, the vector stage is skipped and nothing is appended to a matrix --
    #: see the module docstring.
    needs_reindex: bool = False
    #: Cached counts, so ``GET /kb`` is a directory read rather than a parse of
    #: every library's ``chunks.jsonl`` (20 000 lines each on a full one). Kept
    #: in step by :meth:`KbStore.save_chunks`; a library written by an older
    #: build reports 0 here and is corrected by the next write.
    doc_count: int = 0
    chunk_count: int = 0

    def public(self, *, docs: int | None = None, chunks: int | None = None) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "docs": self.doc_count if docs is None else docs,
            "chunks": self.chunk_count if chunks is None else chunks,
            "embedding_model": self.embedding_model,
            "dims": self.dims,
            "needs_reindex": self.needs_reindex,
        }


class KbStore:
    """Filesystem access for one data root's knowledge bases."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # -- knowledge bases --------------------------------------------------
    def kb_dir(self, kb_id: str) -> Path:
        if not KB_ID_RE.match(kb_id or ""):
            raise KbNotFound("知识库不存在")
        path = self.root / kb_id
        if not path.is_dir():
            raise KbNotFound("知识库不存在")
        return path

    def list_kbs(self) -> list[Kb]:
        if not self.root.is_dir():
            return []
        out: list[Kb] = []
        for entry in sorted(self.root.iterdir()):
            if not entry.is_dir() or not KB_ID_RE.match(entry.name):
                continue
            try:
                out.append(self.load_kb(entry.name))
            except KbError:
                # A directory whose kb.json is unreadable is not a library this
                # service can serve; hiding it beats failing the whole list.
                continue
        out.sort(key=lambda kb: kb.created_at)
        return out

    def load_kb(self, kb_id: str) -> Kb:
        path = self.kb_dir(kb_id) / "kb.json"
        if not path.is_file():
            raise KbNotFound("知识库不存在")
        data = read_json(path, {}) or {}
        return Kb(
            id=kb_id,
            name=str(data.get("name") or kb_id),
            created_at=float(data.get("created_at") or 0.0),
            embedding_model=data.get("embedding_model") or None,
            dims=int(data.get("dims") or 0),
            needs_reindex=bool(data.get("needs_reindex") or False),
            doc_count=int(data.get("doc_count") or 0),
            chunk_count=int(data.get("chunk_count") or 0),
        )

    def create_kb(self, name: str) -> Kb:
        name = (name or "").strip()
        if not name:
            raise KbError("知识库名称不能为空")
        if len(name) > 100:
            raise KbError("知识库名称不能超过 100 个字符")
        kb_id = new_id()
        path = self.root / kb_id
        (path / "docs").mkdir(parents=True, exist_ok=True)
        kb = Kb(id=kb_id, name=name, created_at=time.time())
        self.save_kb(kb)
        return kb

    def save_kb(self, kb: Kb) -> None:
        write_json_atomic(self.root / kb.id / "kb.json", {
            "id": kb.id,
            "name": kb.name,
            "created_at": kb.created_at,
            "embedding_model": kb.embedding_model,
            "dims": kb.dims,
            "needs_reindex": kb.needs_reindex,
            "doc_count": kb.doc_count,
            "chunk_count": kb.chunk_count,
        })

    def delete_kb(self, kb_id: str) -> None:
        path = self.kb_dir(kb_id)
        shutil.rmtree(path, ignore_errors=False)

    # -- documents --------------------------------------------------------
    def docs_dir(self, kb_id: str) -> Path:
        return self.kb_dir(kb_id) / "docs"

    def doc_dir(self, kb_id: str, doc_id: str) -> Path:
        if not DOC_ID_RE.match(doc_id or ""):
            raise KbNotFound("文档不存在")
        path = self.docs_dir(kb_id) / doc_id
        if not path.is_dir():
            raise KbNotFound("文档不存在")
        return path

    def list_docs(self, kb_id: str) -> list[dict]:
        """Every document's ``meta.json``, oldest first."""
        directory = self.docs_dir(kb_id)
        if not directory.is_dir():
            return []
        out: list[dict] = []
        for entry in directory.iterdir():
            if not entry.is_dir() or not DOC_ID_RE.match(entry.name):
                continue
            meta = read_json(entry / "meta.json", None)
            if isinstance(meta, dict):
                meta.setdefault("id", entry.name)
                out.append(meta)
        out.sort(key=lambda m: (m.get("created_at") or 0.0, m.get("id") or ""))
        return out

    def read_doc_meta(self, kb_id: str, doc_id: str) -> dict:
        meta = read_json(self.doc_dir(kb_id, doc_id) / "meta.json", None)
        if not isinstance(meta, dict):
            raise KbNotFound("文档不存在")
        meta.setdefault("id", doc_id)
        return meta

    def doc_exists(self, kb_id: str, doc_id: str) -> bool:
        """Whether the document's record is still there. Never raises.

        The parser runs in a worker thread and keeps writing until its next page
        boundary, so "did this document go away" is a question it has to be able
        to ask from inside a write, without a 300-page parse turning a normal
        delete into an exception.

        The test is the *directory*, not ``meta.json``: an upload creates the
        directory and writes the record in two steps, and a document whose
        parser is on its first page has the directory before it has a record.
        """
        if not DOC_ID_RE.match(doc_id or ""):
            return False
        try:
            return (self.docs_dir(kb_id) / doc_id).is_dir()
        except KbError:
            return False

    def write_doc_meta(self, kb_id: str, doc_id: str, meta: dict) -> bool:
        """Write a document's ``meta.json``. Returns False if the doc is gone.

        The directory is **not** created here. A delete removes it while the
        parse may still be running; re-creating it would rewrite a ``meta.json``
        for a document nobody can see, and leave the directory behind so the
        delete's ``rmtree`` fails. A missing directory is therefore a no-op, and
        the caller decides whether that is normal (a progress write) or a
        failure (an index that was supposed to land).
        """
        if not self.doc_exists(kb_id, doc_id):
            return False
        try:
            write_json_atomic(self.doc_dir(kb_id, doc_id) / "meta.json", meta,
                              create_parents=False)
        except FileNotFoundError:
            # The directory went away between the check and the rename -- the
            # same delete, one instant later. Still a no-op, not a failure.
            return False
        return True

    def delete_doc(self, kb_id: str, doc_id: str) -> None:
        """Remove a document's directory. A directory already gone is not an error.

        ``rmtree`` raises ``FileNotFoundError`` on a target that vanished, which
        is what a *second* delete of the same document sees when it lands during
        the first one's wait for the parser: the first call removed the
        directory, the second arrives at the same ``rmtree`` a moment later and
        the route answered 500 for work that had already been done. Deleting
        something twice is a success, not a failure.

        ``ENOTEMPTY`` is *not* swallowed: the parse is stopped and waited for
        before this is called, so a file still appearing here means something is
        writing into a directory it should have left -- that is a real error and
        the operator needs to see it (the leftover is reported, not hidden).
        """
        # Not ``doc_dir``: that raises for a directory that is already gone,
        # which is exactly the state a repeated delete is in.
        path = self.docs_dir(kb_id) / doc_id
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            return
        except OSError:
            if not path.exists():  # pragma: no cover - removed from under us
                return
            raise

    def write_preview(self, kb_id: str, doc_id: str, page: int,
                      data: bytes) -> bool:
        """Write one preview image; a no-op (False) once the document is gone.

        Same rule as :meth:`write_doc_meta`, and the same bug if it is missing:
        a 300-page OCR pass writes a preview per page, so a delete landing at
        page 45 had 255 more chances to re-create the directory it removed.
        """
        if not self.doc_exists(kb_id, doc_id):
            return False
        try:
            write_bytes_atomic(self.doc_dir(kb_id, doc_id) / "pages" / f"{page}.png",
                               data, create_parents=False)
        except FileNotFoundError:  # pragma: no cover - the delete, one instant later
            return False
        return True

    # -- the aggregate index ---------------------------------------------
    def load_chunks(self, kb_id: str) -> list[dict]:
        path = self.kb_dir(kb_id) / "chunks.jsonl"
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise KbError(f"chunks.jsonl 无法读取：{exc}") from exc
        out: list[dict] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise KbError(f"chunks.jsonl 第 {len(out) + 1} 行损坏：{exc}") from exc
        return out

    def save_chunks(self, kb_id: str, chunks: list[dict], *,
                    doc_count: int | None = None) -> None:
        """Write the chunk file, and keep ``kb.json``'s cached counts in step.

        The counts live here rather than in the caller so they cannot drift from
        the file they describe: every write of ``chunks.jsonl`` is a write of
        its length. ``doc_count`` is passed by the callers that know it (they
        are already listing the document directory); when it is omitted the
        distinct ``doc_id`` values in ``chunks`` are used, which is the same
        number for every state this app can be in.
        """
        payload = "".join(
            json.dumps(c, ensure_ascii=False) + "\n" for c in chunks).encode("utf-8")
        write_bytes_atomic(self.kb_dir(kb_id) / "chunks.jsonl", payload)
        try:
            kb = self.load_kb(kb_id)
        except KbError:  # pragma: no cover - a chunk write without its kb.json
            return
        if doc_count is None:
            doc_count = len({c.get("doc_id") for c in chunks if c.get("doc_id")})
        if kb.chunk_count == len(chunks) and kb.doc_count == doc_count:
            return
        kb.chunk_count = len(chunks)
        kb.doc_count = doc_count
        self.save_kb(kb)

    def set_index_flag(self, kb_id: str, *, needs_reindex: bool,
                       embedding_model: str | None = None,
                       dims: int | None = None) -> None:
        """Record that the library's vectors do (not) match its chunks.

        ``embedding_model``/``dims`` are only written when the caller states
        them. Flagging a library does *not* clear the model it was built with: a
        Reindex button reads better as "迁移自 qwen3-embedding-0.6b", and the
        vector stage's reason quotes it either way.
        """
        kb = self.load_kb(kb_id)
        kb.needs_reindex = needs_reindex
        if embedding_model is not None:
            kb.embedding_model = embedding_model
        if dims is not None:
            kb.dims = int(dims)
        self.save_kb(kb)

    def load_vectors(self, kb_id: str):
        """The ``vectors.npy`` array, or ``None`` when it does not exist.

        numpy is already a dependency of the OCR path, so this costs nothing new
        on the board. The import is deferred so a text-only deployment that
        never builds vectors (no embedding model) does not pay for it.
        """
        import numpy as np

        path = self.kb_dir(kb_id) / "vectors.npy"
        if not path.is_file():
            return None
        try:
            with open(path, "rb") as fh:
                return np.load(fh, allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise KbError(f"vectors.npy 无法读取：{exc}") from exc

    def save_vectors(self, kb_id: str, array) -> None:
        """Write ``array`` atomically (``.npy`` has a header, so no append path)."""
        import io

        import numpy as np

        buffer = io.BytesIO()
        np.save(buffer, array, allow_pickle=False)
        write_bytes_atomic(self.kb_dir(kb_id) / "vectors.npy", buffer.getvalue())

    def delete_vectors(self, kb_id: str) -> None:
        try:
            (self.kb_dir(kb_id) / "vectors.npy").unlink()
        except FileNotFoundError:
            pass

    # -- preview images ---------------------------------------------------
    def page_png(self, kb_id: str, doc_id: str, page: int) -> Path:
        path = self.doc_dir(kb_id, doc_id) / "pages" / f"{page}.png"
        if not path.is_file():
            raise KbNotFound("没有这一页的预览图")
        return path

    def source_file(self, kb_id: str, doc_id: str) -> Path:
        """The uploaded file, whatever suffix it was stored under."""
        directory = self.doc_dir(kb_id, doc_id)
        for entry in directory.iterdir():
            if entry.is_file() and entry.name.startswith("source"):
                return entry
        raise KbNotFound("原始文件不存在")

    # -- the alignment invariant -----------------------------------------
    def aligned_vectors(self, kb_id: str, chunks: list[dict]):
        """``vectors.npy`` if its rows line up with ``chunks``, else ``None``.

        The invariant the whole index rests on is one row per chunk, in order.
        Anything else -- a crash between the two writes, a library a previous
        build left half-spliced, a hand-edited file -- is detected here, and the
        library is marked ``needs_reindex`` so the state is *durable*: without
        the flag the next upload would confidently append to a matrix it has no
        reason to think is wrong, and every row after the break would point at
        the wrong text.

        A *missing* file is a misalignment when there are chunks: a library that
        has one and no ``vectors.npy`` lost its matrix without the flag landing
        (see :meth:`mark_needs_reindex`), and appending the next document's rows
        to nothing would leave that document's vectors describing only itself.
        A library with no chunks yet has simply never been built, and is not
        flagged -- that is the state ``POST /kb`` creates.
        """
        matrix = self.load_vectors(kb_id)
        if matrix is None:
            if chunks:
                logger.warning("%s: %d chunks and no vectors.npy; flagging for reindex",
                               kb_id, len(chunks))
                self.mark_needs_reindex(kb_id)
            return None
        if len(matrix) == len(chunks):
            return matrix
        logger.warning("%s: %d vector rows for %d chunks; flagging for reindex",
                       kb_id, len(matrix), len(chunks))
        self.mark_needs_reindex(kb_id)
        return None

    def mark_needs_reindex(self, kb_id: str) -> None:
        """Record that a rebuild is required, then drop the unusable matrix.

        The order is the whole point. Dropping first left a window -- and a
        crash inside it leaves it permanently -- in which the library has
        chunks, no matrix, and no flag. Nothing detects that state on its own:
        ``aligned_vectors`` treats an absent file as "never built", and
        ``_replace_rows`` would then write a matrix holding only the *next*
        document's rows beside a chunk file holding every document's.

        With the flag written first, every intermediate state is one of the two
        that can be read: matrix + no flag (ordinary), or matrix + flag
        (ignored, and deleted on the way in).
        """
        try:
            self.set_index_flag(kb_id, needs_reindex=True)
            self.delete_vectors(kb_id)
        except KbError:  # pragma: no cover - a library deleted mid-call
            pass
