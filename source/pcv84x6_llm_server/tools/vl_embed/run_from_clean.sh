#!/bin/bash
# MYS-2913 verification from a CLEAN checkout, on the board.
#
# Design decisions that matter for validity:
#   * Every trial runs in its OWN process. Re-creating an encoder inside a
#     process that already faulted can fail with "bmodel loading failed" /
#     "bm free gmem failed"; process isolation removes that confound.
#   * CV_VLE_TRACE is UNSET, not "=0". Both the shipped and the instrumented
#     engine test only for the variable's presence, so "=0" would ENABLE tracing,
#     and a trace readback per layer serialises the device and hides the race.
#   * Arms run in a different order each round, so slow drift cannot masquerade
#     as an arm effect.
#   * Only one CV_VLE_* factor differs between arms; everything else is fixed.
#
#   bash run_from_clean.sh [branch] [workroot]
set -u
BRANCH="${1:-diag/mys2293-wemm-repeat-zero}"
ROOT="${2:-/data/mys2913-clean}"
REPO=https://github.com/sophgo/sophon-tools.git
export PYTHONPATH=/opt/sophgo/cv84x6_llm_server/vendor
MODEL=/data/cv84x6_llm_server/models/wemm-embedding-2b/wemm-embedding-2b_w8bf16_seq2048_pixels1310720_cv84x6_4core_buckets_gdnmixed_20261114_091623.bmodel
CFG=/opt/sophgo/cv84x6_llm_server/model-config/wemm_embedding
SHIPPED=/opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so
CALLS="${CALLS:-6}"
TRIALS="${TRIALS:-3}"
ROUNDS="${ROUNDS:-2}"
TEXT_ARGS="${TEXT_ARGS:---long-text-repeats 20}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# The work directory must be new: this script never deletes a tree it did not
# create, so a mistyped path cannot destroy a caller's data.
if [ -e "$ROOT" ]; then
  echo "run_from_clean: refusing to reuse existing path $ROOT" >&2
  echo "run_from_clean: pass a path that does not exist yet" >&2
  exit 1
fi
mkdir -p "$ROOT/results"
cd "$ROOT"

echo "== clone $BRANCH"
if ! git clone --depth 1 --branch "$BRANCH" "$REPO" st >"$ROOT/clone.log" 2>&1; then
  echo "run_from_clean: clone failed" >&2
  tail -20 "$ROOT/clone.log" >&2
  exit 1
fi
PKG="$ROOT/st/source/pcv84x6_llm_server"
if [ ! -d "$PKG" ]; then
  echo "run_from_clean: package root missing after clone" >&2
  exit 1
fi

echo "== provenance"
echo "commit=$(git -C "$ROOT/st" rev-parse HEAD)"
echo "patch_sha256=$(sha256sum "$PKG/tools/vl_embed/MYS-2913-instrumentation.patch" | cut -d' ' -f1)"
echo "shipped_lib_sha256=$(sha256sum "$SHIPPED" | cut -d' ' -f1)"
echo "bmrt_sha256=$(sha256sum /opt/sophon/libsophon-current/lib/libbmrt.so.1.0 | cut -d' ' -f1)"
echo "bmlib_sha256=$(sha256sum /opt/sophon/libsophon-current/lib/libbmlib.so.0 | cut -d' ' -f1)"
echo "libsophon=$(dpkg-query -W -f='${Version}' sophon-soc-libsophon 2>/dev/null || echo unknown)"

echo "== build instrumented library from clean source"
if ! bash "$PKG/tools/vl_embed/MYS-2913-build-diag.sh" "$PKG" "$ROOT/build" \
        >"$ROOT/build.log" 2>&1; then
  echo "run_from_clean: diagnostic build FAILED" >&2
  tail -30 "$ROOT/build.log" >&2
  exit 1
fi
DIAG="$ROOT/build/libcv84x6_vl_diag.so"
if [ ! -f "$DIAG" ]; then
  echo "run_from_clean: build reported success but produced no library" >&2
  tail -30 "$ROOT/build.log" >&2
  exit 1
fi
echo "diag_lib_sha256=$(sha256sum "$DIAG" | cut -d' ' -f1)"

arm_env() {
  case "$1" in
    shipped)    echo "SHIPPED" ;;
    nowait)     echo "CV_VLE_COPY_SYNC=0 CV_VLE_COPY_DELAY_US=0 CV_VLE_LAUNCH_SYNC=0 CV_VLE_MEMSET_SYNC=0" ;;
    copysync)   echo "CV_VLE_COPY_SYNC=1 CV_VLE_COPY_SYNC_SITE=all CV_VLE_COPY_DELAY_US=0 CV_VLE_LAUNCH_SYNC=0 CV_VLE_MEMSET_SYNC=0" ;;
    memsetsync) echo "CV_VLE_COPY_SYNC=0 CV_VLE_COPY_DELAY_US=0 CV_VLE_LAUNCH_SYNC=0 CV_VLE_MEMSET_SYNC=1" ;;
    bothsync)   echo "CV_VLE_COPY_SYNC=1 CV_VLE_COPY_SYNC_SITE=all CV_VLE_COPY_DELAY_US=0 CV_VLE_LAUNCH_SYNC=0 CV_VLE_MEMSET_SYNC=1" ;;
    launchsync) echo "CV_VLE_COPY_SYNC=0 CV_VLE_COPY_DELAY_US=0 CV_VLE_LAUNCH_SYNC=1 CV_VLE_MEMSET_SYNC=0" ;;
    delay)      echo "CV_VLE_COPY_SYNC=0 CV_VLE_COPY_SYNC_SITE=all CV_VLE_COPY_DELAY_US=2000 CV_VLE_LAUNCH_SYNC=0 CV_VLE_MEMSET_SYNC=0" ;;
  esac
}

run_arm() {
  local arm="$1" round="$2"
  local envs lib files=()
  envs="$(arm_env "$arm")"
  if [ "$envs" = "SHIPPED" ]; then lib="$SHIPPED"; envs=""
  else lib="$DIAG"; fi
  echo "--- arm=$arm round=$round"
  for t in $(seq 0 $((TRIALS - 1))); do
    local out="$ROOT/results/$arm-r$round-t$t.json"
    # One process per trial: a faulted handle must never be reused.
    if ! env -u CV_VLE_TRACE $envs python3 "$PKG/tools/vl_embed/repeat_compare.py" \
        --library "$lib" --model "$MODEL" --config "$CFG" \
        --calls "$CALLS" --trials 1 $TEXT_ARGS --output "$out" \
        >/dev/null 2>"$ROOT/results/$arm-r$round-t$t.err"; then
      echo "    trial $t FAILED (exit non-zero); see $out.err" >&2
      tail -5 "$ROOT/results/$arm-r$round-t$t.err" >&2
      FAILURES=$((FAILURES + 1))
    fi
    files+=("$out")
  done
  # A missing/corrupt trial JSON makes aggregate.py exit non-zero; propagate it
  # instead of continuing with a hole in the matrix.
  if ! python3 "$HERE/aggregate.py" "$arm-r$round" \
        "$ROOT/results/$arm-r$round.json" "${files[@]}"; then
    echo "    aggregate FAILED for arm=$arm round=$round" >&2
    FAILURES=$((FAILURES + 1))
  fi
}

FAILURES=0
for ROUND in $(seq 1 "$ROUNDS"); do
  # Different order each round.
  if [ $((ROUND % 2)) -eq 0 ]; then
    ORDER="delay launchsync bothsync memsetsync copysync nowait shipped"
  else
    ORDER="shipped nowait copysync memsetsync bothsync launchsync delay"
  fi
  for arm in $ORDER; do run_arm "$arm" "$ROUND"; done
done

echo
if [ "$FAILURES" -ne 0 ]; then
  echo "run_from_clean: $FAILURES step(s) failed; results are INCOMPLETE" >&2
fi

echo "== summary"
python3 - "$ROOT" <<'PY'
import glob, json, os, sys
root = sys.argv[1]
rows = []
for path in sorted(glob.glob(os.path.join(root, "results", "*.json"))):
    name = os.path.basename(path)[:-5]
    if "-t" in name:      # per-trial file, already folded into the arm row
        continue
    d = json.load(open(path))
    t = d["totals"]
    rows.append((name, t.get("zero", 0), t.get("nonfinite", 0), t.get("refused", 0),
                 t.get("ok", 0), d["forwards_executed"], d["trials_load_failed"],
                 str(d["distinct_per_trial"]), d["worst_cosine"]))
print(f"{'arm':<16}{'zero':<6}{'nonfin':<8}{'refus':<7}{'ok':<5}"
      f"{'fwd':<6}{'loadfail':<10}{'distinct/trial':<18}worst_cos")
for r in rows:
    print(f"{r[0]:<16}{r[1]:<6}{r[2]:<8}{r[3]:<7}{r[4]:<5}{r[5]:<6}{r[6]:<10}{r[7]:<18}{r[8]}")
PY

# The summary is informational; the exit status carries the verdict.
if [ "$FAILURES" -eq 0 ]; then
  exit 0
fi
exit 1
