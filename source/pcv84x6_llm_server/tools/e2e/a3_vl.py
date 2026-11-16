"""Area 3d: PaddleOCR-VL -- chat (official-client request shape, 4 tasks, wide crops) and /v1/ocr mode=vl."""
import base64
import io
import re

from PIL import Image

from e2e_common import heaps, infer, load, models, record

A = "A3 PaddleOCR-VL"
IMG = "/home/zzt/workspace/cv84x6-demo-ui/tests/data/ocr/img/"
VL = "paddleocr-vl-1.5"

code, secs, body = load(VL)
record("A2 模型", f"{VL} 加载（dfss 下载的文件）", code == 200, f"{code} {secs:.1f}s heaps={heaps()} {body[:120] if code != 200 else ''}")
m = models()[VL]
record("A2 模型", f"{VL} 不在 agent 模型列表", True, "checked in A6") if False else None


def data_url(png_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode()


def vl_chat(png: bytes, task: str, max_tokens=1024):
    # The request PaddleX's GenAIClient builds: one image_url + one text, max_completion_tokens.
    r = infer.post("/v1/chat/completions", json={"model": VL, "max_completion_tokens": max_tokens, "temperature": 0,
                   "messages": [{"role": "user", "content": [
                       {"type": "image_url", "image_url": {"url": data_url(png)}},
                       {"type": "text", "text": task}]}]})
    d = r.json()
    return r.status_code, (d["choices"][0]["message"]["content"] if r.status_code == 200 else r.text[:200]), d.get("usage")


# Regions from the page's own layout (what the official pipeline crops and sends one by one)
page = open(IMG + "table_stats.png", "rb").read()
lay = infer.post("/v1/ocr", json={"model": "ppocrv6-medium", "image": base64.b64encode(page).decode(), "mode": "layout"}).json()
im = Image.open(io.BytesIO(page)).convert("RGB")
for b in lay["blocks"]:
    x1, y1, x2, y2 = [int(v) for v in b["box"]]
    buf = io.BytesIO()
    im.crop((x1, y1, x2, y2)).save(buf, "PNG")
    task = "Table Recognition:" if b["type"] == "table" else "OCR:"
    code, out, usage = vl_chat(buf.getvalue(), task)
    want = {"table": "<fcel>", "subtitle": "生产数据统计表", "title": "生产数据统计表", "doc_title": "生产数据统计表"}.get(b["type"], "合格率")
    record(A, f"聊天·区域裁剪 {b['type']} {x2 - x1}×{y2 - y1}（{task}）", code == 200 and want in out,
           f"{code} {out[:90]!r} usage={usage}")

for name, task, want in (("cn_table_merged.png", "Table Recognition:", "<lcel>"),
                         ("en_report.png", "OCR:", "Quarterly"),
                         ("cn_notice.png", "OCR:", "通知")):
    code, out, usage = vl_chat(open(IMG + name, "rb").read(), task)
    record(A, f"聊天·整图 {name}（{task}）", code == 200 and (want in out or len(out) > 40), f"{code} {out[:90]!r}")

# formula + chart prompts accepted (content quality is the model's; check the contract)
for task in ("Formula Recognition:", "Chart Recognition:"):
    code, out, usage = vl_chat(open(IMG + "mixed_spec.png", "rb").read(), task, 256)
    record(A, f"聊天·{task}", code == 200 and usage and usage.get("completion_tokens", 0) > 0, f"{code} {out[:60]!r}")

# stream
with infer.stream("POST", "/v1/chat/completions", json={"model": VL, "stream": True, "max_tokens": 256, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": data_url(open(IMG + "cn_table_simple.png", 'rb').read())}},
        {"type": "text", "text": "Table Recognition:"}]}]}) as s:
    n = sum(1 for l in s.iter_lines() if l.startswith("data:"))
record(A, "聊天·流式", s.status_code == 200 and n > 5, f"{s.status_code} chunks={n}")
r = infer.post("/v1/chat/completions", json={"model": VL, "messages": [{"role": "user", "content": [
    {"type": "image_url", "image_url": {"url": data_url(page)}}, {"type": "image_url", "image_url": {"url": data_url(page)}},
    {"type": "text", "text": "OCR:"}]}]})
record(A, "聊天·两张图 400", r.status_code == 400, f"{r.status_code} {r.text[:100]}")

# whole page mode=vl
for name in ("table_stats.png", "cn_table_merged.png", "cn_notice.png", "mixed_spec.png"):
    r = infer.post("/v1/ocr", json={"model": "ppocrv6-medium", "image": base64.b64encode(open(IMG + name, "rb").read()).decode(),
                                    "mode": "vl"}, timeout=900)
    d = r.json()
    tasks = [b.get("task") for b in d.get("blocks", [])]
    html = "<table" in d.get("text", "")
    extra = ""
    if name == "cn_table_merged.png":
        extra = f" rowspan={'rowspan' in d.get('text','')} colspan={'colspan' in d.get('text','')}"
    ok = r.status_code == 200 and d.get("mode") == "vl" and tasks and not any(b.get("error") for b in d.get("blocks", []))
    if name.startswith(("table", "cn_table")):
        ok = ok and html
    if name == "cn_table_merged.png":
        ok = ok and "rowspan" in d["text"] and "colspan" in d["text"]
    record(A, f"/v1/ocr mode=vl {name}", ok, f"{r.status_code} blocks={len(tasks)} tasks={tasks} usage={d.get('usage')}{extra}")
record("A2 模型", "VL 加载后设备内存", True, f"heaps MiB {heaps()}")
