"""Verify native session growth with the real scheduler, then cancel live requests.

Run on an otherwise idle authorized board with --model, --tokenizer, --lib and
--out. Samples and native session lifetimes are written to JSON. A diagnostic
library can additionally log ensure_park's old/new capacities to stderr; keep
that trace with the report. Never replace this with two HTTP requests: the
service closes the native session at the end of each request.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import time

from app.core.monitor import parse_bm_smi
from app.engine.base import GenerateParams
from app.engine.native import NativeBackend
from app.engine.prefix_cache import PrefixCache
from app.engine.scheduler import Scheduler
from app.engine.worker import configure

MIB = 1 << 20


def reading():
    p = subprocess.run(['/opt/sophon/libsophon-current/bin/bm-smi', '-noloop'],
                       capture_output=True, timeout=10, check=True)
    r = parse_bm_smi(p.stdout)
    assert r.get('mem_used_bytes') is not None and r.get('mem_total_bytes')
    return r


async def run(a):
    before = reading()
    assert before['mem_used_bytes'] == 0, 'device must have no loaded models'
    backend = NativeBackend(a.model, a.tokenizer, 'review-9b', lib_path=a.lib)
    static = reading()['mem_used_bytes']
    budget = 1024 * MIB
    limit = static + budget
    assert before['mem_total_bytes'] - limit >= 1024 * MIB
    cache = PrefixCache(max_entries=64, max_bytes=budget, store=backend.snapshot_store)
    sched = Scheduler(backend, prefix_cache=cache, max_concurrent=2, max_queue=32)
    sched.kv_budget_bytes = budget
    sched.model_budget_bytes = budget
    samples, events, results = [], [], []
    phase = 'fill'
    finished = asyncio.Event()
    original_new = backend.new_session

    async def new():
        s = await original_new()
        handle = hex(s._handle)
        events.append({'event': 'new', 'handle': handle, 't': time.time(), 'phase': phase})
        feed, close = s.feed_prompt, s.close

        async def traced_feed(tokens):
            old = s.token_len
            await feed(tokens)
            events.append({'event': 'feed', 'handle': handle, 'old_len': old,
                           'new_len': s.token_len, 't': time.time(), 'phase': phase})

        async def traced_close():
            events.append({'event': 'close', 'handle': handle, 't': time.time(), 'phase': phase})
            await close()
        s.feed_prompt, s.close = traced_feed, traced_close
        return s
    backend.new_session = new

    async def sample():
        while not finished.is_set():
            try:
                r = await asyncio.to_thread(reading)
                samples.append({'t': time.time(), 'phase': phase,
                                'npu': r['mem_used_bytes'], 'total': r['mem_total_bytes'],
                                'stats': sched.stats()})
            except Exception as exc:
                samples.append({'t': time.time(), 'error': repr(exc)})
            try:
                await asyncio.wait_for(finished.wait(), timeout=.5)
            except asyncio.TimeoutError:
                pass

    async def sink(_):
        pass

    async def request(rid, length, output=8, cancel=False):
        head = backend.tokenizer_encode(f'<|im_start|>system\nArchive record {rid}. ')
        tail = backend.tokenizer_encode('<|im_end|>\n<|im_start|>user\nSummarise the record.<|im_end|>\n<|im_start|>assistant\n')
        body = backend.tokenizer_encode('The maintenance team inspected the equipment and recorded the findings. ' * 2000)
        tokens = head + body[:length - len(head) - len(tail)] + tail
        assert len(tokens) == length
        req = sched.enqueue(rid, tokens, GenerateParams(max_tokens=output), sink)
        if cancel:
            while req.state not in ('decode', 'done', 'error'):
                await asyncio.sleep(.01)
            if req.state == 'decode':
                sched.cancel(rid)
        await sched.wait(req)
        result = {'id': rid, 'phase': phase, 'prompt_len': req.prompt_len,
                  'reason': req.finish_reason, 'completion': len(req.generated),
                  'error': req.error}
        results.append(result)
        return req

    await sched.start()
    sampler = asyncio.create_task(sample())
    failure = None
    try:
        for i in range(22):
            await request(f'fill-{i}', 1024)
        fill = sched.stats()
        assert fill['cache']['bytes'] >= budget * .65, 'cache was not filled'
        assert fill['cache']['evictions'] > 0, 'cache did not reach eviction pressure'
        phase = 'cross'
        # Each request stays alive during chunked prefill. Switching residents
        # parks each native handle before it is extended past 4096.
        long_requests = asyncio.gather(request('long-a', 6144), request('long-b', 6144))
        while len(sched._active) < 2 and not long_requests.done():
            await asyncio.sleep(.01)
        assert len(sched._active) == 2
        refused = configure(sched, backend, {'mem_limit_mb': (static >> 20) + 512,
                                             'mem_static_mb': static >> 20})
        assert 'error' in refused and sched.kv_budget_bytes == budget
        await long_requests
        phase = 'pressure'
        deadline = time.monotonic() + a.seconds
        wave = 0
        while time.monotonic() < deadline:
            await asyncio.gather(*(request(f'w{wave}-{i}', 512, 24, cancel=i % 2 == 0)
                                   for i in range(6)))
            wave += 1
        final = sched.stats()
        assert final['cancelled_requests'] > 0
        assert not final['failed_requests'] and not backend.fault
        phase = 'cache-off'
        # Same runtime flag recorded by --no-prefix-cache / legacy CLI 0.
        sched.cache_cli_cap_bytes = 0
        assert configure(sched, backend, {})['cache_max_bytes'] == 0
        await request('cache-off', 1024)
        off = sched.stats()
        assert off['cache']['bytes'] == 0 and off['cache']['max_bytes'] == 0
    except Exception as exc:
        failure = repr(exc)
        fill = locals().get('fill')
        final = sched.stats()
    finally:
        finished.set()
        await sampler
        await sched.stop()
        cache.clear()
        await backend.close()
    valid = [s for s in samples if 'npu' in s]
    peak = max((s['npu'] for s in valid), default=0)
    crossed = [e for e in events if e['event'] == 'feed' and e['phase'] == 'cross'
               and 0 < e['old_len'] <= 4096 < e['new_len']]
    bad = [r for r in results if r['reason'] not in ('stop', 'length', 'cancelled')]
    ok = (not failure and not bad and len(valid) == len(samples) and len(valid) >= 20
          and peak <= limit and bool(crossed)
          and max(s['stats']['inflight'] for s in valid if s['phase'] == 'cross') == 2)
    result = {'result': 'PASS' if ok else 'FAIL', 'failure': failure, 'static': static,
              'limit': limit, 'peak': peak, 'min_free': before['mem_total_bytes'] - peak,
              'lib_sha256': hashlib.sha256(Path(a.lib).read_bytes()).hexdigest(),
              'fill': fill, 'final': final, 'requests': results,
              'live_reduction': locals().get('refused'), 'cache_off': locals().get('off'),
              'session_events': events, 'crossings': crossed, 'samples': samples,
              'after': reading()}
    Path(a.out).write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in ('result', 'failure', 'static', 'limit', 'peak', 'min_free')}), flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True)
    p.add_argument('--tokenizer', required=True)
    p.add_argument('--lib', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--seconds', type=int, default=120)
    raise SystemExit(asyncio.run(run(p.parse_args())))
