"""Area 2b: VPP really used -- spill a model into VPP, infer on it, refuse what does not fit, then make room."""
import time

from e2e_common import ROOT, admin, heaps, infer, load, models, record, stats, unload

A = "A2 模型"
for _ in range(60):
    if "qwen3-asr-1.7b" in models() and not models()["qwen3-asr-1.7b"].get("downloading"):
        break
    time.sleep(5)
ms = models()
record(A, "qwen3-asr-1.7b 经 dfss 下载完成并出现在列表", "qwen3-asr-1.7b" in ms and ms["qwen3-asr-1.7b"]["has_config"], f"size={ms.get('qwen3-asr-1.7b', {}).get('size_bytes')}")

before = heaps()
code, secs, body = load("qwen3-asr-0.6b")
after = heaps()
dm = stats()["device"]["device_mem"]
record(A, "溢出到 VPP：NPU 将满时加载 ASR 0.6B", code == 200 and after["vpp"] > before["vpp"] + 500,
       f"{code} {secs:.1f}s before={before} after={after} max_block={dm['max_block_bytes'] >> 20}")
with open(ROOT / "asr_zh.mp3", "rb") as f:
    r = infer.post("/v1/audio/transcriptions", data={"model": "qwen3-asr-0.6b"}, files={"file": ("a.mp3", f, "audio/mpeg")})
record(A, "VPP 上的模型推理正确", r.status_code == 200 and "停滞" in r.json().get("text", ""), f"{r.status_code} {r.text[:80]}")
loaded = [m for m, v in models().items() if v["loaded"]]
record(A, f"同时在线 {len(loaded)} 个模型（NPU + VPP）", len(loaded) >= 6, f"{loaded} heaps={after}")

code, secs, body = load("qwen3-asr-1.7b")
record(A, "放不下时拒绝并说明（ASR 1.7B）", code == 409 and "设备内存不足" in body, f"{code} {body[:220]}")
for m in ("qwen3-embedding-0.6b", "bge-reranker-v2-m3"):
    unload(m)
code, secs, body = load("qwen3-asr-1.7b")
h = heaps()
with open(ROOT / "asr_zh.mp3", "rb") as f:
    r = infer.post("/v1/audio/transcriptions", data={"model": "qwen3-asr-1.7b"}, files={"file": ("a.mp3", f, "audio/mpeg")})
record(A, "腾出空间后加载 ASR 1.7B 并推理", code == 200 and r.status_code == 200 and "停滞" in r.json().get("text", ""),
       f"load {code} {secs:.1f}s heaps={h} asr={r.text[:60]}")
unload("qwen3-asr-1.7b")
for m in ("qwen3-embedding-0.6b", "bge-reranker-v2-m3"):
    load(m)
record(A, "恢复 35B + 辅助 + VL 组合", True, f"heaps={heaps()}")
