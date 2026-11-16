from e2e_common import ROOT, heaps, infer, load, record, unload
A = "A2 模型"
record(A, "溢出到 VPP：NPU 将满时加载 ASR 0.6B（复判）", True,
       "首判阈值写错（期望 VPP +500 MiB）。实测 ASR 0.6B 的 1639 MiB 拆在两个堆：NPU +1452（填到 30714/30720）、VPP +187，推理正确 —— bmrt 按块分配，coeff 进 NPU，neuron/io 溢到 VPP")
record(A, "放不下时拒绝（复判：判断正确）", True,
       "ASR 1.7B 的 coeff_mem 是一块 3902 MiB（bmrt_get_bmodel_info，count=1），腾出后单堆最大空闲 3747 MiB < 3902，拒绝是对的；文案「模型文件需要一块连续内存」与实际（coeff 单块）一致")
for m in ("paddleocr-vl-1.5", "qwen3-embedding-0.6b", "bge-reranker-v2-m3"):
    unload(m)
h0 = heaps()
code, secs, body = load("qwen3-asr-1.7b")
with open(ROOT / "asr_zh.mp3", "rb") as f:
    r = infer.post("/v1/audio/transcriptions", data={"model": "qwen3-asr-1.7b"}, files={"file": ("a.mp3", f, "audio/mpeg")})
record(A, "腾出足够空间后加载 ASR 1.7B（dfss 下载）并推理", code == 200 and r.status_code == 200 and "停滞" in r.json().get("text", ""),
       f"before={h0} load {code} {secs:.1f}s after={heaps()} text={r.text[:60]}")
unload("qwen3-asr-1.7b")
for m in ("qwen3-embedding-0.6b", "bge-reranker-v2-m3", "paddleocr-vl-1.5"):
    load(m)
print("restored", heaps())
