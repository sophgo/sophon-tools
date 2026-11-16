"""Area 3a: /v1/chat/completions on the 35B, through the official openai SDK where possible."""
import base64
import concurrent.futures as cf
import json
import time

import httpx
from openai import OpenAI

from e2e_common import BASE, INFER_KEY, admin, infer, load, models, record

A = "A3 /v1 对话"
MID = "qwen3.6-35b-a3b-128k"
cli = OpenAI(base_url=f"{BASE}/v1", api_key=INFER_KEY, timeout=600, max_retries=0)

if not models()[MID]["loaded"]:
    code, secs, body = load(MID)
    print("load", code, f"{secs:.1f}s")

# 1. SDK non-stream
r = cli.chat.completions.create(model=MID, max_tokens=64,
                                messages=[{"role": "user", "content": "1+1 等于几？只回答数字。"}])
record(A, "SDK 非流式", r.choices[0].finish_reason == "stop" and "2" in r.choices[0].message.content,
       f"{r.choices[0].message.content!r} finish={r.choices[0].finish_reason} usage={r.usage.prompt_tokens}/{r.usage.completion_tokens}")

# 2. SDK stream with usage
chunks, text, fin, usage = 0, "", None, None
for c in cli.chat.completions.create(model=MID, max_tokens=64, stream=True, stream_options={"include_usage": True},
                                     messages=[{"role": "user", "content": "用三个词形容秋天。"}]):
    chunks += 1
    if c.choices:
        text += c.choices[0].delta.content or ""
        fin = c.choices[0].finish_reason or fin
    if c.usage:
        usage = c.usage
record(A, "SDK 流式 + usage", chunks > 3 and fin == "stop" and usage is not None and len(text) > 0,
       f"chunks={chunks} finish={fin} usage={'%d/%d' % (usage.prompt_tokens, usage.completion_tokens) if usage else None} text={text[:40]!r}")

# 3. length limits
for field in ("max_tokens", "max_completion_tokens"):
    r = infer.post("/v1/chat/completions", json={"model": MID, field: 5,
                   "messages": [{"role": "user", "content": "写一首关于大海的长诗。"}]}).json()
    record(A, f"{field}=5 截断", r["choices"][0]["finish_reason"] == "length" and r["usage"]["completion_tokens"] <= 5,
           f"finish={r['choices'][0]['finish_reason']} completion={r['usage']['completion_tokens']}")

# 4. stop
r = cli.chat.completions.create(model=MID, max_tokens=64, stop=["3"],
                                messages=[{"role": "user", "content": "从 1 数到 5，用逗号分隔，只输出数字。"}])
c = r.choices[0].message.content
record(A, "stop 序列", "3" not in c and "1" in c and r.choices[0].finish_reason == "stop", f"{c!r}")

# 5. thinking on / off
r = infer.post("/v1/chat/completions", json={"model": MID, "max_tokens": 400,
               "chat_template_kwargs": {"enable_thinking": True},
               "messages": [{"role": "user", "content": "17*23 等于多少？"}]}).json()
msg = r["choices"][0]["message"]
rc = msg.get("reasoning_content") or ""
record(A, "思考开启", len(rc) > 0 and "391" in (msg.get("content") or "") + rc,
       f"reasoning={len(rc)} chars content={str(msg.get('content'))[:60]!r} finish={r['choices'][0]['finish_reason']}")
r = infer.post("/v1/chat/completions", json={"model": MID, "max_tokens": 64,
               "messages": [{"role": "user", "content": "17*23 等于多少？只给结果。"}]}).json()
msg = r["choices"][0]["message"]
record(A, "思考默认关闭", not msg.get("reasoning_content") and "391" in (msg.get("content") or ""),
       f"content={msg.get('content')!r}")

# 6. tools
tools = [{"type": "function", "function": {"name": "get_weather", "description": "查询城市天气",
          "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
r = cli.chat.completions.create(model=MID, max_tokens=200, tools=tools,
                                messages=[{"role": "user", "content": "北京今天天气怎么样？"}])
tc = r.choices[0].message.tool_calls
ok = bool(tc) and tc[0].function.name == "get_weather" and "北京" in json.loads(tc[0].function.arguments).get("city", "")
record(A, "函数调用 tools", ok, f"finish={r.choices[0].finish_reason} tool_calls={[(t.function.name, t.function.arguments) for t in (tc or [])]}")
if ok:
    r2 = cli.chat.completions.create(model=MID, max_tokens=120, tools=tools, messages=[
        {"role": "user", "content": "北京今天天气怎么样？"},
        {"role": "assistant", "content": None, "tool_calls": [t.model_dump() for t in tc]},
        {"role": "tool", "tool_call_id": tc[0].id, "content": json.dumps({"city": "北京", "weather": "晴", "temp_c": 18}, ensure_ascii=False)}])
    c = r2.choices[0].message.content or ""
    record(A, "函数调用 回填结果", "晴" in c or "18" in c, f"{c[:80]!r}")

# 7. vision
m = models()[MID]
img = base64.b64encode(open("/home/zzt/workspace/cv84x6-demo-ui/tests/data/ocr/img/table_stats.png", "rb").read()).decode()
r = infer.post("/v1/chat/completions", json={"model": MID, "max_tokens": 120, "messages": [{"role": "user", "content": [
    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}},
    {"type": "text", "text": "这张表格的标题是什么？哪条产线产量最高？"}]}]})
if m.get("supports_vision"):
    d = r.json()
    c = d["choices"][0]["message"]["content"] if r.status_code == 200 else r.text[:200]
    record(A, "视觉（图片输入）", r.status_code == 200 and ("一号线" in c or "生产" in c), f"{r.status_code} {c[:100]!r} prompt_tokens={d.get('usage',{}).get('prompt_tokens') if r.status_code==200 else None}")
else:
    record(A, "视觉（图片输入）", r.status_code == 400, f"model has no vision; {r.status_code} {r.text[:120]}")

# 8. concurrency x3
def one(i):
    t0 = time.time()
    rr = infer.post("/v1/chat/completions", json={"model": MID, "max_tokens": 48,
                    "messages": [{"role": "user", "content": f"第{i}个问题：中国的首都是哪里？"}]})
    return rr.status_code, time.time() - t0, rr.json()["choices"][0]["message"]["content"] if rr.status_code == 200 else rr.text[:80]
with cf.ThreadPoolExecutor(3) as ex:
    res = list(ex.map(one, range(3)))
record(A, "3 路并发", all(c == 200 and "北京" in t for c, _, t in res), "; ".join(f"{c} {s:.1f}s" for c, s, _ in res))

# 9. prefix cache
sysmsg = "你是一个严谨的设备运维助手。" + "以下是巡检规范：" + "每台服务器每周巡检一次，记录温度、风扇、电源和磁盘状态。" * 40
u = []
for q in ("一号机房多久巡检一次？", "巡检要记录哪些项目？"):
    d = infer.post("/v1/chat/completions", json={"model": MID, "max_tokens": 32,
                   "messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": q}]}).json()
    u.append(d["usage"])
cached = (u[1].get("prompt_tokens_details") or {}).get("cached_tokens", 0)
record(A, "前缀缓存命中", cached > 0, f"prompt={u[1]['prompt_tokens']} cached={cached}")

# 10. long prompt
long_text = ("设备编号 A{0:03d} 的巡检结论是正常，温度 {1} 度。".format(i, 40 + i % 9) for i in range(400))
d = infer.post("/v1/chat/completions", json={"model": MID, "max_tokens": 48, "messages": [
    {"role": "user", "content": "".join(long_text) + "\n\n设备 A123 的温度是多少度？只回答数字。"}]}, timeout=900)
dd = d.json()
c = dd["choices"][0]["message"]["content"] if d.status_code == 200 else d.text[:120]
record(A, "长提示（≥2048 token）", d.status_code == 200 and dd["usage"]["prompt_tokens"] >= 2048 and "46" in c,
       f"{d.status_code} prompt_tokens={dd.get('usage',{}).get('prompt_tokens')} answer={c[:30]!r}")

# 11. /v1/models + auth
ml = infer.get("/v1/models").json()
record(A, "/v1/models", any(x["id"] == MID for x in ml["data"]), f"{[x['id'] for x in ml['data']]}")
r1 = httpx.post(f"{BASE}/v1/chat/completions", json={"model": MID, "messages": []})
r2 = httpx.post(f"{BASE}/v1/chat/completions", headers={"Authorization": "Bearer sk-wrong"}, json={"model": MID, "messages": []})
record(A, "认证：无 key / 错 key", r1.status_code == 401 and r2.status_code == 401, f"{r1.status_code} {r2.status_code} {r2.text[:100]}")
