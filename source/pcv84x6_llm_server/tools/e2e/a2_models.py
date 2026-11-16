"""Area 2a: each model alone -- load, heap delta, one real inference, unload, back to baseline."""
import base64
import sys
import time

from e2e_common import ROOT, admin, heaps, infer, load, models, record, unload

IMG = "/home/zzt/workspace/cv84x6-demo-ui/tests/data/ocr/img/"
ids = sys.argv[1:] or ["qwen3-embedding-0.6b", "bge-reranker-v2-m3", "qwen3-asr-0.6b",
                       "ppocrv6-medium", "qwen3.6-35b-a3b-128k"]


def infer_once(mid: str, kind: str) -> tuple[bool, str]:
    if kind == "embedding":
        r = infer.post("/v1/embeddings", json={"model": mid, "input": ["设备巡检记录", "合格率统计"]})
        d = r.json()
        dims = len(d["data"][0]["embedding"]) if r.status_code == 200 else None
        return r.status_code == 200 and dims == 1024, f"{r.status_code} dims={dims}"
    if kind == "rerank":
        r = infer.post("/v1/rerank", json={"model": mid, "query": "合格率是多少",
                                           "documents": ["二号线合格率 99.1%", "今天天气晴"]})
        d = r.json()
        res = d.get("results", [])
        ok = r.status_code == 200 and res and res[0]["index"] == 0
        return bool(ok), f"{r.status_code} top={res[0] if res else None}"
    if kind == "asr":
        with open(ROOT / "asr_zh.mp3", "rb") as f:
            r = infer.post("/v1/audio/transcriptions", data={"model": mid},
                           files={"file": ("asr_zh.mp3", f, "audio/mpeg")})
        text = r.json().get("text", "") if r.status_code == 200 else r.text[:120]
        return r.status_code == 200 and "交易" in text and "停滞" in text, f"{r.status_code} {text!r}"
    if kind == "ocr":
        b64 = base64.b64encode(open(IMG + "table_stats.png", "rb").read()).decode()
        r = infer.post("/v1/ocr", json={"model": mid, "image": b64})
        d = r.json()
        text = d.get("text", "")
        return r.status_code == 200 and "合格率" in text, f"{r.status_code} lines={len(d.get('lines', []))}"
    if kind == "chat":
        r = infer.post("/v1/chat/completions", json={
            "model": mid, "max_tokens": 32,
            "messages": [{"role": "user", "content": "用一句话介绍你自己。"}]})
        d = r.json()
        text = d["choices"][0]["message"]["content"] if r.status_code == 200 else r.text[:120]
        return r.status_code == 200 and len(text) > 0, f"{r.status_code} {text[:60]!r} usage={d.get('usage')}"
    return False, f"unknown kind {kind}"


ms = models()
base = heaps()
print("baseline heaps MiB", base)
for mid in ids:
    m = ms.get(mid)
    if not m:
        record("A2 模型", f"{mid} 存在", False, "not on disk")
        continue
    kind = m["kind"]
    code, secs, body = load(mid)
    after = heaps()
    delta = {k: after[k] - base.get(k, 0) for k in after}
    if code != 200:
        record("A2 模型", f"{mid} 加载", False, f"HTTP {code} {body}")
        continue
    record("A2 模型", f"{mid} 加载", True, f"{secs:.1f}s heapΔ MiB {delta}")
    m2 = models()[mid]
    record("A2 模型", f"{mid} 内存字段", m2.get("mem_used_bytes") is not None and m2.get("effective") is not None,
           f"static={(m2.get('mem_static_bytes') or 0) >> 20} used={(m2.get('mem_used_bytes') or 0) >> 20} "
           f"limit={(m2.get('effective') or {}).get('mem_limit_bytes', 0) >> 20} MiB")
    ok, ev = infer_once(mid, kind)
    record("A2 模型", f"{mid} 推理", ok, ev)
    code, body = unload(mid)
    time.sleep(1)
    back = heaps()
    leak = {k: back[k] - base.get(k, 0) for k in back}
    record("A2 模型", f"{mid} 卸载回基线", code == 200 and all(abs(v) <= 2 for v in leak.values()),
           f"HTTP {code} residual MiB {leak}")
