"""A cancelled ingestion job must not leave shutdown waiting on an empty queue."""
import asyncio

from app.apps.kb.ingest import Ingestor, Job
from app.apps.kb.store import KbStore


async def test_stop_survives_a_job_consuming_cancellation(tmp_path, monkeypatch):
    ingestor = Ingestor(KbStore(tmp_path / "kb"))
    entered = asyncio.Event()

    async def consume_cancellation(job):
        entered.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            # A lower-level readiness wait can complete at the same time as
            # cancellation. Model the observed return to _run with cancelling=1.
            return

    monkeypatch.setattr(ingestor, "_process", consume_cancellation)
    ingestor.start()
    worker = ingestor._task
    ingestor.submit(Job(kb_id="kb", doc_id="doc"))
    await asyncio.wait_for(entered.wait(), 1)
    stop = asyncio.create_task(ingestor.stop())
    try:
        done, _ = await asyncio.wait({stop}, timeout=1)
        assert stop in done, "stop hung after the job returned to an empty queue"
        await stop
        assert worker.done()
        assert ingestor.current is None
        assert ingestor._queue.empty()
    finally:
        # Keep the regression's failing version from orphaning a worker.
        if not stop.done():
            stop.cancel()
        if not worker.done():
            worker.cancel()
        await asyncio.gather(stop, worker, return_exceptions=True)
