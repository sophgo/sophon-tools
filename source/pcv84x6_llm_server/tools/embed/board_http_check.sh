#!/usr/bin/env bash
# HTTP-level check of the shipped seq2048 build, run on .157 against the
# side-by-side 0.6.29 instance on :8099.
set -uo pipefail
BASE=http://127.0.0.1:8099
K=$(python3 -c "import json;print(json.load(open('/tmp/key.json'))['key'])")
AUTH="Authorization: Bearer $K"

echo "== single embedding, timing"
for i in 1 2 3; do
  code=$(curl -s -o /tmp/emb.json -w '%{http_code}' -X POST "$BASE/v1/embeddings" \
    -H "$AUTH" -H 'Content-Type: application/json' \
    --data-binary '{"model":"qwen3-embedding-0.6b","input":"深度学习是机器学习的一个分支。"}')
  python3 - "$code" <<'PY'
import json, sys
d = json.load(open('/tmp/emb.json'))
print(f"  http={sys.argv[1]} dims={len(d['data'][0]['embedding'])} usage={d.get('usage')}")
PY
done

echo "== token-count timing (10 sequential calls)"
python3 - <<'PY'
import json, time, urllib.request
key = json.load(open('/tmp/key.json'))['key']
text = "深度学习是机器学习的一个分支。"
body = json.dumps({"model": "qwen3-embedding-0.6b", "input": text}).encode()
times = []
for _ in range(10):
    req = urllib.request.Request("http://127.0.0.1:8099/v1/embeddings", data=body,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        r.read()
    times.append((time.perf_counter() - t0) * 1000)
times.sort()
print(f"  median {times[len(times)//2]:.0f} ms, min {times[0]:.0f} ms")
PY

echo "== over the 2048 limit must be a 400 that names 2048"
# CJK Extension B, not repeated ordinary CJK: the tokenizer merges runs of a
# repeated character, so "深" * 3000 is only ~1500 tokens and would (correctly)
# be accepted. Extension B costs three tokens a character, so 900 characters is
# ~2700 tokens -- genuinely over the limit.
python3 - <<'PY'
import json
open('/tmp/req.json', 'w').write(json.dumps(
    {"model": "qwen3-embedding-0.6b", "input": "\U00020000" * 900}))
PY
code=$(curl -s -o /tmp/e2.json -w '%{http_code}' -X POST "$BASE/v1/embeddings" \
  -H "$AUTH" -H 'Content-Type: application/json' --data-binary @/tmp/req.json)
echo "  http=$code  $(head -c 200 /tmp/e2.json)"
case "$code" in
  400) grep -q 2048 /tmp/e2.json && echo "  OK: refused and names 2048" ;;
  *)   echo "  FAIL: expected 400" ;;
esac

echo "== a 1000-character chunk (the new ceiling) must be accepted"
python3 - <<'PY'
import json
open('/tmp/req2.json', 'w').write(json.dumps(
    {"model": "qwen3-embedding-0.6b", "input": "中国科学院" * 200}))
PY
code=$(curl -s -o /tmp/e3.json -w '%{http_code}' -X POST "$BASE/v1/embeddings" \
  -H "$AUTH" -H 'Content-Type: application/json' --data-binary @/tmp/req2.json)
python3 - "$code" <<'PY'
import json, sys
d = json.load(open('/tmp/e3.json'))
print(f"  http={sys.argv[1]} dims={len(d['data'][0]['embedding'])}" if 'data' in d
      else f"  http={sys.argv[1]} {d}")
PY
