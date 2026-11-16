"""The background ingestion queue.

One global FIFO worker, deliberately. Parsing a 300-page PDF and embedding 20 000
chunks are long operations; running two documents at once would interleave OCR
calls with embedding calls on a device that serves one model at a time, and the
console's progress bars would each advance at an unpredictable fraction of the
speed. Serial is also what makes "the library's ``kb.json`` embedding model is
the model every vector was made with" true: only one build can be in flight.

The states a document moves through are the design's::

    queued -> parsing -> ocr -> embedding -> ready
                   \\-> failed (with a Chinese error)

``ocr`` is entered only for a PDF that actually has a page needing it, and its
progress counts pages; a text-only document goes straight to ``embedding``.

The queue survives a crash only as ``failed``: on start, every document left
mid-flight is marked failed with "服务重启，处理中断", which is what the console
offers a Retry button for. That includes a *queued* one whose upload never got
as far as the worker -- its original file was written to disk by the POST, so
Retry works for it too.

Two invariants this file exists to keep, both of them about the aggregate index:

* ``vectors.npy`` has exactly one row per line of ``chunks.jsonl``, or it does
  not exist at all. A document whose chunks could not be embedded is *refused*
  rather than spliced in without a vector.
* a library whose two files disagree is never appended to. It is flagged
  ``needs_reindex`` (``store.mark_needs_reindex``) and stays out of the vector
  stage until a rebuild finishes -- see ``store``'s module docstring.
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from dataclasses import dataclass

from . import models as model_resolve
from . import parse as doc_parse
from .chunker import Chunk, chunk_text, normalise
from .retrieval import EMBED_BATCH, InputRefused, embed_passages
from .store import KbError, KbStore, write_bytes_atomic

logger = logging.getLogger(__name__)

#: A document record's status values.
QUEUED = "queued"
PARSING = "parsing"
OCR = "ocr"
EMBEDDING = "embedding"
READY = "ready"
FAILED = "failed"

#: Statuses a restart must not leave claiming to be in flight.
IN_FLIGHT = (QUEUED, PARSING, OCR, EMBEDDING)

#: How long :meth:`Ingestor.stop` waits for the running document to reach a page
#: boundary. A page is a render plus (for a scan) one OCR round trip -- the
#: client's own timeout bounds that at ~45 s, and 30 s covers the ordinary case
#: without holding a shutdown for a wedged NPU: past it the task is cancelled and
#: the store guard (a deleted or moved-away document takes no writes) is what
#: keeps the outcome correct.
STOP_GRACE_S = 30.0


@dataclass
class Job:
    """One queued unit of work.

    Two shapes share the queue because both write the library's aggregate index
    and both must not run concurrently with each other:

    * a document (``doc_id`` set): index or re-index one file. The upload's
      bytes are **not** carried -- the POST wrote them to
      ``docs/<doc_id>/source.<ext>`` before it returned, so the job holds a path
      and a retry and a fresh upload take the same route. That is what makes a
      document queued across a restart retryable, and it keeps a 50 MiB body
      from sitting in memory for however long the queue is.
    * a whole library (``doc_id`` empty): re-embed every chunk. One job rather
      than one per document, because ``vectors.npy`` is a single matrix and
      rebuilding it document by document would misalign the rows that have not
      been redone yet.
    """

    kb_id: str
    doc_id: str = ""
    #: The FastAPI request, so the job can resolve models and open worker
    #: connections. Held only for the duration of the queue entry.
    request: object | None = None
    #: The store this job was queued against. Pinned at submit time, not read
    #: from the ingestor when the worker picks it up: a data-directory move
    #: repoints ``Ingestor.store`` at the new root while a parse that was
    #: already running is still in a worker thread. Without this the thread's
    #: next page write would land in the *new* library and undo the ``failed``
    #: that ``recover`` had just written there.
    store: object | None = None

    @property
    def is_reindex(self) -> bool:
        return not self.doc_id


def _pool_pieces(vectors: list[list[float]], counts: list[int]) -> list[list[float]]:
    """Fold each chunk's piece vectors back into one vector per chunk.

    ``counts[i]`` is how many pieces chunk ``i`` was split into, and ``vectors``
    are all the pieces in order. A count of 1 returns that vector untouched --
    the case for every chunk ordinary prose produces -- so the common path does
    no arithmetic and cannot drift.

    A split chunk gets the mean of its pieces, renormalised: the pieces together
    are the same text the chunk was, and the mean of unit vectors is the
    standard way to pool them. It is not identical to embedding the whole chunk
    (which the model refuses), but it is the closest thing available and keeps
    the stored vector unit-length, which is what the search path assumes.
    """
    if all(n == 1 for n in counts):
        return vectors
    out: list[list[float]] = []
    at = 0
    for n in counts:
        group = vectors[at:at + n]
        at += n
        if n == 1:
            out.append(group[0])
            continue
        acc = [0.0] * len(group[0])
        for vec in group:
            for i, x in enumerate(vec):
                acc[i] += x
        norm = sum(x * x for x in acc) ** 0.5
        out.append([x / norm for x in acc] if norm else acc)
    return out


#: How many times one chunk may be halved before a refusal is treated as final.
MAX_SPLIT_DEPTH = 8


class Ingestor:
    """Serial background indexing, owned by the app instance."""

    def __init__(self, store: KbStore) -> None:
        self.store = store
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        #: Set while a document is being processed, so the API can report that
        #: the queue is draining rather than idle.
        self.current: Job | None = None
        #: Serialises the read-modify-write of the library's aggregate index
        #: against a delete/reindex issued from a request handler.
        self.lock = asyncio.Lock()
        #: Libraries whose vectors are being rebuilt right now. A reindex reads
        #: the chunk list, embeds for minutes, then writes the whole matrix; a
        #: delete landing in the middle would leave the matrix with more rows
        #: than the chunk file. So while a library is in here, its document
        #: mutations are refused with 409 ("正在重建索引") instead of racing.
        self._reindexing: set[str] = set()
        #: Documents whose delete is in progress. The parser polls this between
        #: pages -- a 300-page OCR pass is minutes of NPU time and must stop when
        #: the file it is working on is gone, rather than run to the end and then
        #: fail writing to a deleted directory.
        self._cancelled: set[tuple[str, str]] = set()
        #: Set by ``stop()``: the worker is going away, so whatever is running
        #: must give up at its next page or batch even though nothing was
        #: deleted.
        self._stopping = False
        #: Documents whose parse is running in a worker *thread* right now,
        #: keyed ``(kb_id, doc_id)``. The key is added before the thread is
        #: submitted and removed by the thread's own ``finally`` -- which is the
        #: only place that knows it is really done. Cancelling the asyncio task
        #: does **not** stop a thread, so this, and not ``current``, is what
        #: ``stop`` waits on.
        self._parsing: set[tuple[str, str]] = set()
        #: Parses ``stop()`` has told to give up, keyed like ``_parsing``.
        #:
        #: Separate from ``_cancelled`` because of *who* clears it. A delete
        #: clears its flag in the worker's ``finally`` -- the job is over and the
        #: document is gone. A shutdown cannot: ``task.cancel()`` runs that
        #: ``finally`` immediately, while the parse thread is still inside a
        #: page, so a flag cleared there is cleared *before* the thread ever
        #: reads it. Only the thread's own ``finally`` clears this set, which is
        #: what makes the stop survive past ``stop()``'s grace period: a page
        #: that takes longer than 30 s still ends the document at the page after
        #: it, instead of running the rest of the file into a tree the move is
        #: copying.
        self._halted: set[tuple[str, str]] = set()

    # -- lifecycle --------------------------------------------------------
    def recover(self) -> int:
        """Mark every document that was mid-flight as failed. Returns the count.

        A document in ``queued`` was never touched either: the in-memory queue
        did not survive the restart.
        """
        fixed = 0
        for kb in self.store.list_kbs():
            for meta in self.store.list_docs(kb.id):
                if meta.get("status") not in IN_FLIGHT:
                    continue
                meta["status"] = FAILED
                meta["progress"] = None
                meta["error"] = "服务重启，处理中断"
                try:
                    self.store.write_doc_meta(kb.id, meta["id"], meta)
                    fixed += 1
                except Exception:  # pragma: no cover - one bad doc must not
                    logger.exception("could not reset %s/%s", kb.id, meta.get("id"))
        if fixed:
            logger.info("marked %d interrupted document(s) as failed", fixed)
        return fixed

    def start(self) -> None:
        """Begin draining the queue (idempotent)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="kb-ingest")

    async def stop(self) -> None:
        """Stop the worker, and make sure its parse has really given up.

        Not "finish the document": a shutdown that waited for a 300-page OCR
        pass would hold the service for minutes. But not "cancel the asyncio
        task" either, which is what this did -- the parse runs in a worker
        thread (``asyncio.to_thread``), and cancelling the task that awaits it
        leaves the thread running to the end of the document. That thread is the
        bug a data-directory move turned into a stuck document: it kept writing
        ``meta.json`` into ``docs/<id>/`` through ``Ingestor.store``, which the
        move had already repointed at the *new* root, so the ``failed`` that
        ``recover`` wrote for it was overwritten with ``ocr`` and the Retry
        answered 409 forever.

        So: raise the stop flag first (the parser polls it per page), give the
        threads ``STOP_GRACE_S`` to reach a page boundary, and only then cancel.
        The job's writes cannot reach the moved library in any case -- the store
        is pinned on the job at submit time -- so the grace period is about
        ending cleanly, not about correctness of the *record*. It is about
        correctness of the *copy*: a thread still writing under the old root
        while the move copies it produces a tree that fails verification.

        The flag must outlive this method. It used to be a single ``_stopping``
        boolean that was reset on the way out, which made the wait above the only
        thing standing between a slow page and a thread that keeps going: past
        30 s the flag came back ``False`` and the parse ran to the end of the
        document. ``_halted`` is per-thread and is cleared by the thread itself,
        so nothing here can un-ask it.
        """
        self._stopping = True
        try:
            # ``list``: the worker thread discards from this set in its own
            # ``finally``, and iterating it live is a "Set changed size during
            # iteration" waiting for the wrong page boundary.
            for key in list(self._parsing):
                self._halted.add(key)
            # Whatever has not started yet will never run under the old root: its
            # job is still in the queue with the old store pinned. Dropping it is
            # what keeps it from working on NPU time -- or re-creating a document
            # directory through ``save_chunks`` -- after the move has deleted the
            # old tree. ``recover`` marks those records ``failed`` on the new
            # root, which is the same outcome a restart gives.
            self.forget_queued()
            if self._task is not None:
                task, self._task = self._task, None
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            await self._wait_for_parses(STOP_GRACE_S)
        finally:
            self._stopping = False

    def forget_queued(self) -> int:
        """Drop every queued job. Returns how many. (The in-flight one stays.)"""
        dropped = 0
        while not self._queue.empty():
            job = self._queue.get_nowait()
            if job.is_reindex:
                self.end_reindex(job.kb_id)
            self._queue.task_done()
            dropped += 1
        if dropped:
            logger.info("dropped %d queued job(s) at shutdown; recover will mark "
                        "them failed on the new root", dropped)
        return dropped

    async def _wait_for_parses(self, timeout: float) -> None:
        """Wait until no parse thread is running, up to ``timeout`` seconds.

        A thread that ignores the stop flag past ``timeout`` is left to finish on
        its own: it writes to the store it started with, and every one of those
        writes checks the document is still there.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        while self._parsing and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if self._parsing:
            logger.warning("%d parse thread(s) still running after %.0f s; "
                           "leaving them to their stop flag",
                           len(self._parsing), timeout)

    @property
    def busy(self) -> bool:
        return self.current is not None or not self._queue.empty()

    # -- the reindex / delete barrier -------------------------------------
    def is_reindexing(self, kb_id: str) -> bool:
        return kb_id in self._reindexing

    def begin_reindex(self, kb_id: str) -> None:
        """Claim ``kb_id`` for a rebuild. Called from the request handler.

        Claimed at *submit* time rather than when the worker picks the job up:
        between the two, a delete or an upload would still slip in and the job
        would then rebuild a library it read the chunks of before that change.
        """
        self._reindexing.add(kb_id)

    def end_reindex(self, kb_id: str) -> None:
        self._reindexing.discard(kb_id)

    def request_stop(self, kb_id: str, doc_id: str) -> None:
        """Ask the in-flight parse of one document to stop at its next page.

        Called before the delete removes anything, so the check the parser makes
        is already true by the time the directory goes away. A job that is
        *queued* rather than running needs no flag: ``forget`` drops it.
        """
        self._cancelled.add((kb_id, doc_id))

    def _stopped(self, kb_id: str, doc_id: str) -> bool:
        key = (kb_id, doc_id)
        return self._stopping or key in self._cancelled or key in self._halted

    async def await_stop(self, kb_id: str, doc_id: str,
                         timeout: float = STOP_GRACE_S) -> bool:
        """Wait for a document's parse to confirm it has stopped. True if it did.

        The delete route calls this between ``request_stop`` and ``rmtree``. The
        flag alone was not enough: the parser notices it at the *next page*,
        which is a whole render plus OCR round trip away, and in that window it
        was still writing previews and ``meta.json`` into the directory the
        delete was removing -- an ``ENOTEMPTY`` 500 and a ``meta.json`` for a
        document that no longer existed. Waiting here makes the delete
        deterministic: afterwards nothing is writing there at all.

        A timeout is not a failure of the delete -- the store refuses writes to a
        document whose directory is gone, so removing it after the wait is still
        safe -- it only means the operator waits for a wedged NPU rather than
        for a page.
        """
        key = (kb_id, doc_id)
        deadline = time.monotonic() + max(0.0, timeout)
        while key in self._parsing and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        if key in self._parsing:
            logger.warning("%s/%s is still parsing after %.0f s; deleting anyway "
                           "(its writes are refused once the directory is gone)",
                           kb_id, doc_id, timeout)
            return False
        return True

    def submit(self, job: Job) -> None:
        """Queue ``job``. Never blocks: the caller is an HTTP handler.

        The store is pinned here rather than read from ``self.store`` when the
        worker gets to it: a data-directory move repoints ``self.store`` while a
        job is still in the queue, and a document's job must keep writing to the
        library it was queued against (the move's copy carries it; the retry the
        operator then presses creates a job against the new root).
        """
        if job.store is None:
            job.store = self.store
        self.start()
        self._queue.put_nowait(job)

    def forget(self, kb_id: str, doc_id: str | None = None) -> None:
        """Drop queued jobs for a deleted library or document.

        A queued job carries ids, not files, so it would fail at its first read
        with "not found" and mark a record that no longer exists. Dropping it
        here also stops a delete from racing a queue entry that would otherwise
        recreate the directory it is deleting.

        The job in flight is *not* stopped here: cancelling it mid-write of the
        aggregate index is how a half-spliced library happens. It reads its
        metadata at each step and fails cleanly once the document is gone.
        (``request_stop`` is the separate, page-boundary way to ask a parse to
        give up.)

        A dropped *reindex* job also releases its claim on the library: the
        claim is normally released by ``reindex``'s own ``finally``, but a job
        that never reaches the worker never runs it, and the library would be
        stuck answering 409 to every mutation for the rest of the process's life.
        """
        kept: list[Job] = []
        while not self._queue.empty():
            job = self._queue.get_nowait()
            if job.kb_id == kb_id and (doc_id is None or job.doc_id == doc_id):
                if job.is_reindex:
                    self.end_reindex(job.kb_id)
                self._queue.task_done()
                continue
            kept.append(job)
        for job in kept:
            self._queue.put_nowait(job)

    # -- the worker -------------------------------------------------------
    async def _run(self) -> None:
        # A readiness wait may consume cancellation as it completes. Do not
        # return to an empty queue after stop() has asked this worker to exit.
        while not self._stopping:
            job = await self._queue.get()
            self.current = job
            try:
                if job.is_reindex:
                    await self.reindex(job)
                else:
                    await self._process(job)
            except asyncio.CancelledError:
                raise
            except doc_parse.Stopped:
                # The document was deleted while it was being parsed. There is no
                # record to mark and no directory to write to; the delete route
                # has already removed both.
                logger.info("stopped indexing %s/%s: document deleted",
                            job.kb_id, job.doc_id)
            except Exception as exc:  # noqa: BLE001 - one document's failure
                logger.exception("indexing %s/%s failed", job.kb_id, job.doc_id)
                self._finish_failed(job, _describe(exc))
            finally:
                self.current = None
                self._cancelled.discard((job.kb_id, job.doc_id))
                self._queue.task_done()

    def _finish_failed(self, job: Job, message: str) -> None:
        store = self._store_for(job)
        if job.is_reindex:
            # A library-wide job marks every document it was about to redo, so
            # each one keeps a Retry (which re-runs the document, not the whole
            # library -- the partial state Reindex left behind is reported by
            # the search stage, not by a per-document error). Only the documents
            # this job actually claimed: `failed` and `queued` ones were not
            # touched by it and must keep the state they had.
            try:
                for meta in store.list_docs(job.kb_id):
                    if meta.get("status") != EMBEDDING:
                        continue
                    meta["status"] = FAILED
                    meta["progress"] = None
                    meta["error"] = message
                    store.write_doc_meta(job.kb_id, meta["id"], meta)
            except Exception:  # pragma: no cover
                logger.exception("could not record the reindex failure")
            return
        try:
            meta = store.read_doc_meta(job.kb_id, job.doc_id)
        except KbError:
            return  # the library or the document is gone; nothing to mark
        meta["status"] = FAILED
        meta["progress"] = None
        meta["error"] = message
        try:
            store.write_doc_meta(job.kb_id, job.doc_id, meta)
        except Exception:  # pragma: no cover
            logger.exception("could not record the failure for %s", job.doc_id)

    def _store_for(self, job: Job) -> KbStore:
        """The store this job writes to: pinned at submit, not ``self.store``."""
        return job.store if job.store is not None else self.store

    def _update(self, job: Job, **fields) -> dict:
        """Read-modify-write the document's ``meta.json``.

        Returns ``{}`` when the record is gone. That is a *normal* state, not a
        failure: a delete removes the document directory while its parse is
        still running, and the parser reports progress once per page. Raising
        there would turn the delete into a logged traceback and a ``failed``
        record for a document that no longer exists -- the loop's own stop flag
        is what ends the parse, one page later.
        """
        store = self._store_for(job)
        try:
            meta = store.read_doc_meta(job.kb_id, job.doc_id)
            meta.update(fields)
            if not store.write_doc_meta(job.kb_id, job.doc_id, meta):
                return {}
            return meta
        except KbError:
            return {}

    def _progress(self, job: Job, stage: str, done: int, total: int) -> None:
        """Publish progress.

        A reindex job has no document of its own (it spans the library), so it
        publishes progress to every document it is redoing. Dispatching here
        rather than at each call site means ``_embed_chunks`` is shared by both
        job shapes without knowing which one it is running for.
        """
        if job.is_reindex:
            self._library_progress(job, stage, done, total)
            return
        self._update(job, status=stage,
                     progress={"stage": stage, "done": done, "total": total})

    def _library_progress(self, job: Job, stage: str, done: int, total: int) -> None:
        """Progress for a library-wide job: every participating document moves together.

        Only the documents the job claimed (``EMBEDDING``) are updated. Writing
        to every in-flight record -- which is what this did before -- dragged a
        ``queued`` document into the ``embedding`` stage before it had been
        parsed, so its progress bar described work that had not started.
        """
        store = self._store_for(job)
        for meta in store.list_docs(job.kb_id):
            if meta.get("status") != EMBEDDING:
                continue
            meta["progress"] = {"stage": stage, "done": done, "total": total}
            store.write_doc_meta(job.kb_id, meta["id"], meta)

    # -- one document -----------------------------------------------------
    async def _process(self, job: Job) -> None:
        store = self._store_for(job)
        self._update(job, status=PARSING, error=None,
                     progress={"stage": PARSING, "done": 0, "total": 1})
        meta = store.read_doc_meta(job.kb_id, job.doc_id)
        # The file the upload POST already wrote. Read once, off the event loop,
        # and never copied a second time: the parse needs the bytes and 50 MiB
        # is 2% of this board's RAM.
        path = store.source_file(job.kb_id, job.doc_id)
        data = await asyncio.to_thread(path.read_bytes)

        # 1. Parse. OCR is resolved once and handed to the parser as a plain
        #    *synchronous* callable -- the parser runs in a worker thread, and an
        #    async callback there would never be awaited.
        #
        #    Resolved with on-demand loading: a scanned PDF cannot be built at all
        #    without OCR, and the operator who uploaded it has already said they
        #    want this document indexed. The await happens here, on the job's own
        #    coroutine, before the thread is started -- which is the only place in
        #    this path where an await is safe.
        ocr_model = (await model_resolve.resolve_or_load(job.request, "ocr")
                     if job.request else None)

        def run_ocr(png: bytes):
            return _ocr_lines_sync(job.request, ocr_model, png)

        def write_preview(number: int, png: bytes) -> None:
            # Written as each page is rendered: 300 A4 previews is a few hundred
            # MB of PNG, and this box has 2.6 GB in total. A no-op once the
            # document is gone: the delete removed the directory, and creating
            # it again here is what made ``rmtree`` fail with ENOTEMPTY.
            store.write_preview(job.kb_id, job.doc_id, number, png)

        doc = await self._parse(job, meta, data, run_ocr,
                                ocr_available=bool(ocr_model),
                                write_preview=write_preview)
        meta = self._update(job, pages=len(doc.pages), text_pages=doc.text_pages,
                            ocr_pages=doc.ocr_pages, warnings=list(doc.warnings))
        # The bytes are not needed past the parse; dropping the reference here
        # matters because the embedding pass below can run for minutes.
        del data

        if not doc.has_text:
            reason = "没有提取到任何文字"
            if doc.ocr_pages and not ocr_model:
                reason += "（OCR 模型未加载，扫描页与图片均被跳过）"
            await self._replace_rows(job, [], [], None)
            self._update(job, status=FAILED, progress=None, error=reason, chunks=0)
            return

        # 2. The embedding model, resolved before anything is written: building a
        #    library *requires* one (the design says so -- the vectors are the
        #    point), and failing here rather than half-way keeps the invariant
        #    that `vectors.npy` has exactly one chunk row per chunk.
        #
        #    A library already records the model it was built with, so that is
        #    the preference: adding a document to it must embed into the same
        #    vector space, and loading some other embedding model on demand would
        #    hit the mismatch check below and fail a build for no reason.
        #
        #    "The same space" is the *vector family*, not the file: the seq512 and
        #    seq2048 builds are separately compiled graphs of the same weights
        #    whose vectors agree to seven decimals, so either may append to a
        #    library the other built (MYS-2706). Passing the family makes the
        #    resolve bring up a sibling build when the recorded one is not loaded,
        #    instead of failing the document for a difference that is not one.
        #
        #    Read before the resolve (not after, where it used to be) because the
        #    preference has to be known before anything can be loaded. The raise
        #    for a library deleted mid-job stays where it was: ``load_kb`` throws
        #    the same ``KbError`` out of the same job either way.
        kb = store.load_kb(job.kb_id)
        family = model_resolve.vector_family_of(job.request, kb.embedding_model)
        embed = (await model_resolve.resolve_or_load(
            job.request, "embedding", preferred=kb.embedding_model,
            family=family or None)
            if job.request else None)
        if not embed:
            await self._replace_rows(job, [], [], None)
            self._update(
                job, status=FAILED, progress=None, chunks=0,
                error=f"{embed.reason if embed else '未加载 embedding 模型'}；"
                      "建库需要 embedding 模型来生成向量。加载后可用「重试」继续")
            return
        if kb.embedding_model and not model_resolve.same_space(family, embed):
            await self._replace_rows(job, [], [], None)
            self._update(
                job, status=FAILED, progress=None, chunks=0,
                error=f"该知识库的向量由 {kb.embedding_model} 建立，"
                      f"当前加载的是 {embed.model_id}；请换回原模型，"
                      "或对整库执行「重建索引」")
            return

        # 3. Chunk, and check the library cap *before* spending NPU time on it.
        chunks = _chunks_for(doc)
        async with self.lock:
            existing = store.load_chunks(job.kb_id)
            others = [c for c in existing if c.get("doc_id") != job.doc_id]
        if len(others) + len(chunks) > doc_parse.MAX_CHUNKS_PER_KB:
            await self._replace_rows(job, [], [], None)
            self._update(
                job, status=FAILED, progress=None, chunks=0,
                error=f"加入该文档后共有 {len(others) + len(chunks)} 个切片，"
                      f"超过单库上限 {doc_parse.MAX_CHUNKS_PER_KB} 个")
            return

        # 4. Embed.
        self._progress(job, EMBEDDING, 0, len(chunks))
        vectors = await self._embed_chunks(job, chunks, embed, total=len(chunks))

        # 5. Splice into the library's aggregate index.
        await self._replace_rows(job, chunks, vectors, embed.model_id)
        self._update(job, status=READY, progress=None, error=None,
                     chunks=len(chunks), embedded=True, indexed_at=time.time())
        logger.info("indexed %s/%s: %d chunk(s)", job.kb_id, job.doc_id, len(chunks))

    async def reindex(self, job: Job) -> None:
        """Re-embed the whole library with the currently loaded model.

        One job for the library rather than one per document, because
        ``vectors.npy`` is a single matrix over every chunk: rebuilding it
        document by document would leave the rows of the documents not yet
        redone pointing at the wrong chunks for as long as the job runs.

        **What it must not touch.** A document with no chunks in the file is
        left alone: there is nothing to re-embed, and its failure plus the Retry
        button it advertises is the operator's only way to fix it. Everything
        that *does* have chunks is claimed and ends ``ready`` -- which is what
        makes a rebuild the recovery path after a failed one, or after a restart
        in the middle of one (both leave the flag set and the documents
        ``failed``, and the rebuild endpoint would otherwise refuse with "没有可
        重建的文档" and leave deleting the library as the only exit).

        The library's chunk set is read under the lock and re-checked under it
        before the write, and document mutations are refused for the whole
        duration (``begin_reindex``), so the matrix it writes describes exactly
        the chunks it read.
        """
        store = self._store_for(job)
        try:
            # Reindex rebuilds *this library's* matrix, so it must use the model
            # the library already records when one is recorded. A library with no
            # recorded model yet (never embedded) takes whatever comes up.
            #
            # Read first and unguarded: a library deleted while the job was queued
            # should fail the job, not quietly rebuild somebody else's -- and it
            # would have thrown the same ``KbError`` from ``list_docs`` below
            # anyway, so this only moves the failure earlier (before any model is
            # loaded for a job that cannot succeed).
            kb = store.load_kb(job.kb_id)
            family = model_resolve.vector_family_of(job.request, kb.embedding_model)
            embed = (await model_resolve.resolve_or_load(
                job.request, "embedding", preferred=kb.embedding_model,
                family=family or None)
                if job.request else None)
            docs = store.list_docs(job.kb_id)
            if not embed:
                raise KbError(f"{embed.reason if embed else '未加载 embedding 模型'}；"
                              "无法重建向量索引")
            async with self.lock:
                chunks = store.load_chunks(job.kb_id)
            if not chunks:
                raise KbError("知识库还没有切片，无法重建索引")

            # Which documents end up `ready` afterwards is decided from the chunk
            # file, not from what state they were in when the job started. A
            # rebuild is also the recovery path for one that *failed* or was
            # interrupted by a restart: those leave every document `failed` and
            # the library flagged, and marking only `ready` documents here would
            # mean the job that was supposed to rescue them had nothing to
            # rescue. A document with no chunks in the file keeps its failure --
            # it has no vectors to rebuild, and its Retry must survive.
            per_doc: dict[str, int] = {}
            for chunk in chunks:
                per_doc[chunk.get("doc_id") or ""] = per_doc.get(
                    chunk.get("doc_id") or "", 0) + 1
            for meta in docs:
                if not per_doc.get(meta["id"]):
                    continue
                meta["status"] = EMBEDDING
                meta["progress"] = {"stage": EMBEDDING, "done": 0,
                                    "total": len(chunks)}
                meta["error"] = None
                store.write_doc_meta(job.kb_id, meta["id"], meta)

            # Each row is embedded from its stored text, in the same order the
            # chunk file lists them, so the new matrix aligns by construction.
            pseudo = [Chunk(page=c.get("page"), source=c.get("source") or "text",
                            text=c.get("text") or "", char_start=0, char_end=0)
                      for c in chunks]
            vectors = await self._embed_chunks(job, pseudo, embed, total=len(pseudo))

            import numpy as np

            async with self.lock:
                # Re-read under the lock: the embed above took minutes, and this
                # is the last word on whether the matrix may be written.
                current = store.load_chunks(job.kb_id)
                if [c.get("id") for c in current] != [c.get("id") for c in chunks]:
                    raise KbError(
                        "重建索引期间知识库的切片发生了变化，本次重建已放弃；请重试")
                store.save_vectors(job.kb_id, np.asarray(vectors, dtype="float32"))
                store.set_index_flag(
                    job.kb_id, needs_reindex=False,
                    embedding_model=embed.model_id,
                    dims=len(vectors[0]) if vectors else 0)
                for meta in docs:
                    # Only the documents this job claimed. One with no chunks in
                    # the file was not claimed above, so a `failed` document with
                    # nothing to rebuild keeps its failure and its Retry.
                    if meta.get("status") != EMBEDDING:
                        continue
                    if not per_doc.get(meta["id"]):
                        continue
                    meta["status"] = READY
                    meta["progress"] = None
                    meta["error"] = None
                    meta["embedded"] = True
                    meta["chunks"] = per_doc.get(meta["id"], 0)
                    store.write_doc_meta(job.kb_id, meta["id"], meta)
            logger.info("reindexed %s: %d chunk(s) with %s",
                        job.kb_id, len(chunks), embed.model_id)
        finally:
            self.end_reindex(job.kb_id)

    async def _parse(self, job: Job, meta: dict, data: bytes, run_ocr, *,
                     ocr_available: bool, write_preview):
        """Run the parser off the event loop (it renders pages and decodes images).

        A PDF reports per-page progress as it goes, and polls ``should_stop``
        between pages so a delete can cut a 300-page OCR pass short. The stage
        name only becomes ``ocr`` for a document that really needed it: a text
        PDF stays on ``parsing``, which is what the console shows.
        """
        kind = meta.get("type") or "txt"
        should_stop = lambda: self._stopped(job.kb_id, job.doc_id)  # noqa: E731
        key = (job.kb_id, job.doc_id)

        if kind == "pdf":
            def on_page(done: int, total: int, scanned: int) -> None:
                # `ocr` only once a page has actually needed it: a text PDF stays
                # on `parsing` the whole way, and a mixed one switches as soon as
                # the first scanned page appears.
                self._progress(job, OCR if scanned else PARSING, done, total)

            return await self._in_parse_thread(
                key, doc_parse.parse_pdf, data,
                ocr=run_ocr if ocr_available else None,
                write_preview=write_preview, on_page=on_page,
                should_stop=should_stop)
        if kind == "image":
            self._progress(job, OCR, 0, 1)
            if should_stop():
                raise doc_parse.Stopped("文档已被删除，处理中止")
            return await self._in_parse_thread(
                key, doc_parse.parse_image, data,
                ocr=run_ocr if ocr_available else None,
                write_preview=write_preview)
        return await self._in_parse_thread(
            key, doc_parse.parse_text_document, data, kind)

    async def _in_parse_thread(self, key: tuple[str, str], fn, *args, **kwargs):
        """Run a parser in a worker thread, tracked in ``_parsing`` until it returns.

        ``asyncio.to_thread`` returns when the *await* is cancelled, not when the
        thread is done: the thread runs on. ``_parsing`` is what lets ``stop()``
        and the delete route wait for the real end, and the key is dropped inside
        the thread's own ``finally`` so nothing has to guess.

        ``_halted`` is cleared in the same place, and *only* there. It is the
        shutdown's stop flag, and ``stop()`` must not clear it: cancelling the
        awaiting task runs the worker's ``finally`` at once, long before the
        thread reaches its next page.
        """
        self._parsing.add(key)

        def body():
            try:
                return fn(*args, **kwargs)
            finally:
                self._parsing.discard(key)
                self._halted.discard(key)

        return await asyncio.to_thread(body)

    async def _embed_chunks(self, job: Job, chunks: list[Chunk], embed, *,
                            total: int) -> list[list[float]]:
        """Encode ``chunks`` in batches of ``EMBED_BATCH``.

        Passages are encoded **without** the retrieval instruction: Qwen3-Embedding
        is asymmetric, and prefixing a passage with the query instruction moves it
        into the query's neighbourhood for the wrong reason.

        Each batch goes through :func:`retrieval.embed_passages`, the same code
        path ``/api/test/embeddings`` uses -- so a build writes one inference
        record per batch, with ``source`` = ``/api/apps/kb`` and actor ``kb``,
        and inherits the endpoint's batch cap instead of having its own.

        The stop flag is checked **between** batches, not only during the parse:
        embedding a 20 000-chunk library is minutes of NPU time, and a delete (or
        a shutdown) that had to wait for all of it would be the same wait the
        page-boundary check exists to avoid. A deleted document raises
        ``Stopped`` -- the delete route already removed the record, so there is
        nothing to write; a shutdown raises the same, and ``recover`` handles the
        record on the next start.
        """
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), EMBED_BATCH):
            if job.is_reindex and self._stopping:
                raise KbError("服务正在停止，本次重建已放弃")
            if not job.is_reindex and self._stopped(job.kb_id, job.doc_id):
                raise doc_parse.Stopped("文档已被删除，嵌入中止")
            batch = chunks[start:start + EMBED_BATCH]
            # A chunk can still be over the model's limit even after the
            # chunker's character ceiling: a character is not a token, and the
            # worst scripts cost three tokens each (CJK Extension B, private-use
            # codepoints), so MAX_CHUNK_CHARS characters can be 3000 tokens. The
            # worker refuses such an input instead of truncating it, and a
            # refusal used to fail the embedding of the *whole document*.
            #
            # The host has no tokenizer (it lives in the worker), so the
            # worker's refusal is the test: the batch goes as one request as
            # before -- ordinary text never takes another path -- and only a
            # refused batch is retried chunk by chunk, splitting just the chunk
            # the worker refuses (``_embed_fitted``).
            texts = [chunk.text for chunk in batch]
            try:
                got = await embed_passages(job.request, embed, texts)
            except InputRefused:
                got = [await self._embed_fitted(job, embed, text) for text in texts]
            if len(got) != len(batch):
                raise KbError(
                    f"embedding 返回 {len(got)} 个向量，请求了 {len(batch)} 条")
            vectors.extend([float(x) for x in v] for v in got)
            self._progress(job, EMBEDDING, min(start + len(batch), total), total)
        widths = {len(v) for v in vectors}
        if len(widths) > 1:
            raise KbError(f"embedding 返回的向量维度不一致：{sorted(widths)}")
        return vectors

    async def _embed_fitted(self, job: Job, embed, text: str,
                            depth: int = 0) -> list[float]:
        """One chunk's vector, splitting it until the worker accepts every piece.

        The worker's own tokenizer is the judge: a refused text is cut in half
        (by characters) and each half embedded the same way, then the halves are
        pooled (:func:`_pool_pieces`: mean, renormalised). A text that fits costs
        one request and comes back untouched. :data:`MAX_SPLIT_DEPTH` halvings
        take a 1000-character chunk down to 4 characters, far below any SEQLEN,
        so reaching it means the refusal is about something other than length,
        and it is re-raised as the error it was.
        """
        try:
            return (await embed_passages(job.request, embed, [text]))[0]
        except InputRefused as exc:
            if len(text) < 2 or depth >= MAX_SPLIT_DEPTH:
                raise
            refused = exc
        mid = len(text) // 2
        halves = [h for h in (text[:mid], text[mid:]) if h.strip()]
        if not halves:
            raise refused
        vectors = [await self._embed_fitted(job, embed, h, depth + 1) for h in halves]
        return _pool_pieces(vectors, [len(vectors)])[0]

    async def _replace_rows(self, job: Job, chunks: list[Chunk], vectors: list,
                            model_id: str | None = None) -> None:
        """Replace this document's rows in the library's aggregate index.

        The files are written in an order that keeps every crash state readable:
        vectors first, chunks last, so a reader that sees the new
        ``chunks.jsonl`` always finds vectors that already match it.

        **The invariant this maintains**: ``vectors.npy`` has exactly one row per
        line of ``chunks.jsonl``, in the same order, or it does not exist at all.
        Because of it, a document whose chunks could not be embedded is *refused*
        rather than spliced in without a vector -- a matrix with a hole in it can
        only be read by knowing which rows are missing, and nothing else in this
        app knows that.

        **A flagged library is not appended to.** If ``needs_reindex`` is set the
        matrix is known not to line up, so this writes the chunk rows and leaves
        the vectors to the rebuild: appending the new document's vectors to a
        matrix whose earlier rows are already wrong would make the break
        permanent and silent.
        """
        import numpy as np

        store = self._store_for(job)
        async with self.lock:
            existing = store.load_chunks(job.kb_id)
            kb = store.load_kb(job.kb_id)
            matrix = None if kb.needs_reindex else store.aligned_vectors(
                job.kb_id, existing)
            keep_idx = [i for i, c in enumerate(existing) if c.get("doc_id") != job.doc_id]
            kept = [existing[i] for i in keep_idx]
            if len(kept) + len(chunks) > doc_parse.MAX_CHUNKS_PER_KB:
                raise KbError(
                    f"加入该文档后共有 {len(kept) + len(chunks)} 个切片，超过单库上限 "
                    f"{doc_parse.MAX_CHUNKS_PER_KB} 个")

            meta = store.read_doc_meta(job.kb_id, job.doc_id)
            doc_meta = {"id": job.doc_id, "name": meta.get("name") or "",
                        "type": meta.get("type") or "txt"}
            new_rows = [{
                "id": f"{job.doc_id}:{i}",
                "doc_id": job.doc_id,
                "doc": doc_meta,
                "page": chunk.page,
                "source": chunk.source,
                "text": chunk.text,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "boxes": chunk.boxes,
            } for i, chunk in enumerate(chunks)]

            # The surviving rows of a matrix that is already aligned to `kept`.
            # An `numpy` array cannot be indexed with an empty list and still
            # keep its column count, so "no survivors" is handled explicitly.
            kept_matrix = None
            if matrix is not None and keep_idx:
                kept_matrix = matrix[keep_idx]
            elif matrix is not None and not matrix.shape[0]:
                kept_matrix = None

            final = kept_matrix
            if vectors:
                new_matrix = np.asarray(vectors, dtype="float32")
                final = new_matrix if final is None else np.vstack([final, new_matrix])

            if kb.needs_reindex:
                # No matrix may be written here at all. `final` would hold only
                # *this* document's rows, which is precisely the desync: a
                # matrix that lines up with nothing in particular, which the next
                # search would then have to detect and throw away again. The
                # chunk rows go in below and the rebuild embeds them.
                pass
            elif final is not None and len(final):
                store.save_vectors(job.kb_id, final)
            else:
                # Nothing is left to have been vectorised, so there is no matrix
                # to keep -- and the library's recorded model must go with it or
                # the next document would be refused as "a different model".
                store.delete_vectors(job.kb_id)

            store.save_chunks(job.kb_id, kept + new_rows,
                              doc_count=len(store.list_docs(job.kb_id)))

            if kb.needs_reindex:
                # The rebuild owns the model/dims from here; this document's
                # rows are in the chunk file and will be embedded by it.
                return
            kb = store.load_kb(job.kb_id)
            if final is not None and len(final) and model_id:
                if not kb.embedding_model:
                    kb.embedding_model = model_id
                    kb.dims = int(final.shape[1])
                    store.save_kb(kb)
            elif not (kept + new_rows) and kb.embedding_model:
                kb.embedding_model = None
                kb.dims = 0
                store.save_kb(kb)


# -- helpers ----------------------------------------------------------------
def _ocr_lines_sync(request, resolved, png: bytes) -> list[doc_parse.OcrLine]:
    """One rendered page through PP-OCR, called from the parser's worker thread.

    ``parse`` runs in a thread (it renders and decodes), so this bridges back to
    the event loop the worker client's socket lives on. Without the bridge the
    coroutine is created and never awaited -- the OCR pass silently produces
    nothing and every scanned page reads as blank.

    The bound is the client's own OCR timeout plus room for the hop: the client
    already refuses a wedged NPU, so a tighter number here would only ever fire
    for a call the client was about to give up on anyway.
    """
    import asyncio

    from ...core.client import OCR_TIMEOUT_S

    loop = getattr(request.app.state, "event_loop", None) or _current_loop()
    future = asyncio.run_coroutine_threadsafe(_ocr_lines(request, resolved, png), loop)
    return future.result(timeout=OCR_TIMEOUT_S + 30.0)


def _current_loop():
    import asyncio

    try:
        return asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - only from a non-async caller
        raise KbError("OCR 需要事件循环；请在服务进程内调用") from None


async def _ocr_lines(request, resolved, png: bytes) -> list[doc_parse.OcrLine]:
    """One rendered page through PP-OCR; boxes in the *rendered* image's pixels.

    ``parse`` scales them into the preview's coordinates: the two images are the
    same page at different sizes.

    Goes through :func:`retrieval.ocr_image` so the call is recorded like the
    console's own OCR test -- one row per page, ``source`` ``/api/apps/kb``,
    actor ``kb`` -- rather than reaching into the worker client directly.
    """
    from .retrieval import ocr_image

    reply = await ocr_image(request, resolved, png)
    out: list[doc_parse.OcrLine] = []
    for line in reply.get("lines") or []:
        box = line.get("box")
        if not box:
            continue
        out.append(doc_parse.OcrLine(
            text=line.get("text") or "",
            box=[[float(p[0]), float(p[1])] for p in box],
        ))
    return out


def _chunks_for(doc) -> list[Chunk]:
    """Split every page into chunks; per page, so a chunk never spans two.

    The box offsets are computed *against the page text the chunker measures*:
    ``page.text`` (which is the join of the OCR lines) is normalised first, and
    each line is located in that normalised string by
    :func:`_pair_offsets_with_boxes`. Deriving them from the raw OCR output --
    ``len(line.text) + 1`` per line -- is what made a chunk's boxes land on its
    neighbours: OCR returns trailing spaces and repeated rows, so raw lengths do
    not add up to the offsets in the cleaned text.
    """
    chunks: list[Chunk] = []
    for page in doc.pages:
        if not page.text.strip():
            continue
        line_boxes = None
        if page.lines:
            line_boxes = _pair_offsets_with_boxes(
                normalise(page.text),
                [line.text for line in page.lines],
                {i: line.box for i, line in enumerate(page.lines)},
            ) or None
        chunks.extend(chunk_text(
            page.text, page=page.number, source=page.source, line_boxes=line_boxes))
    return chunks


def _pair_offsets_with_boxes(page_text: str, line_texts: list[str],
                             boxes_by_index: dict[int, list]) -> list[tuple[int, list]]:
    """``[(offset, box)]`` for the lines that could be located, in reading order."""
    out: list[tuple[int, list]] = []
    cursor = 0
    for index, raw in enumerate(line_texts):
        cleaned = normalise(raw)
        if not cleaned:
            continue
        found = page_text.find(cleaned, cursor)
        box = boxes_by_index.get(index)
        if found < 0 or not box:
            break
        out.append((found, box))
        cursor = found + len(cleaned)
    return out


def _describe(exc: BaseException) -> str:
    """A one-line failure reason; the traceback goes to the log, not the API."""
    if isinstance(exc, (KbError, doc_parse.ParseError)):
        return str(exc)
    logger.debug("failure detail:\n%s", traceback.format_exc())
    return f"{type(exc).__name__}: {exc}"
