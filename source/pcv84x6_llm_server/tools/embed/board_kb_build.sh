#!/usr/bin/env bash
# Build a 200+ chunk knowledge base through the API and report the wall time.
#
# The seq2048 change is supposed to make a build ~9.7x faster (0.29 s per text
# instead of 2.81 s). This measures that end to end, through the same queue the
# console uses, rather than extrapolating from the forward-pass figure.
#
# One file at a time, and the clock starts just before the POST that queues the
# last document, so the number reported is "time from 'upload' to 'all chunks
# embedded'" for a library that already has its earlier documents -- which is
# what an operator waits for on a real upload.
set -uo pipefail
BASE=http://127.0.0.1:8099
COOKIE=/tmp/ck_kb
DOCS=${DOCS:-8}          # 8 x 30 chunks = 240

# Log in here rather than reusing a cookie from an earlier step: the session
# cookie expires, and an expired one turns every call into a 401 that looks like
# a bad route.
rm -f $COOKIE
curl -s -c $COOKIE -X POST "$BASE/api/login" -H 'Content-Type: application/json' \
  -d '{"password":"admin"}' > /dev/null

python3 - "$DOCS" <<'PY'
import sys
# ~340 characters per paragraph, so the 400-character target makes ~2 paragraphs
# a chunk; 60 paragraphs is ~30 chunks a file.
para = ("库房管理制度第{n}条：物料入库应当核对品名、规格、数量与送货单是否一致，"
        "发现短缺或破损应当在当日填写异常单并通知采购与质检；"
        "上架时按库位号顺序摆放，标识朝外，同类物料不得混放；"
        "每月末盘点一次，盘点结果由两人签字确认后归档保存三年；"
        "出库遵循先进先出，单据保留备查。")
for i in range(int(sys.argv[1])):
    with open(f"/tmp/kbdoc{i}.txt", "w") as f:
        f.write("\n".join(para.format(n=i * 60 + j) for j in range(60)))
PY

kb=$(curl -s -b $COOKIE -X POST "$BASE/api/apps/kb" -H 'Content-Type: application/json' \
     -d '{"name":"P1 建库计时 200+"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["kb"]["id"])')
echo "== kb $kb"
echo "$kb" > /tmp/kb_id.txt

start=$(date +%s.%N)
for i in $(seq 0 $((DOCS - 1))); do
  curl -s -b $COOKIE -X POST "$BASE/api/apps/kb/$kb/docs" \
    -F "file=@/tmp/kbdoc$i.txt" -o /tmp/up$i.json
done
echo "== all $DOCS documents queued"

for _ in $(seq 1 600); do
  s=$(curl -s -b $COOKIE "$BASE/api/apps/kb/$kb" | python3 -c "
import json,sys
d=json.load(sys.stdin)['kb']
docs=d.get('docs')
if isinstance(docs,int):
    print(docs, 0, d.get('chunks',0)); raise SystemExit
busy=[x for x in docs if x.get('status') in ('queued','parsing','embedding')]
print(len(docs), len(busy), d.get('chunks',0))
" 2>/dev/null)
  set -- $s
  if [ "${2:-1}" = "0" ] && [ "${1:-0}" != "0" ]; then
    end=$(date +%s.%N)
    python3 -c "print(f'== {int($1)} docs, {$3} chunks, built in {$end-$start:.1f} s')"
    python3 -c "print(f'   -> {$3} chunks in {$end-$start:.1f} s = {($end-$start)/max($3,1)*1000:.0f} ms per chunk')"
    break
  fi
  sleep 2
done

curl -s -b $COOKIE "$BASE/api/apps/kb/$kb/docs" | python3 -c "
import json,sys
d=json.load(sys.stdin)['docs']
print('  statuses:', sorted({x['status'] for x in d}))
print('  total chunks:', sum(x['chunks'] for x in d))
bad=[x for x in d if x['status']!='ready']
print('  not ready:', [(x['name'], x['status'], x.get('error')) for x in bad] or 'none')
"
