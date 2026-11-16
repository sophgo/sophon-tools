#!/usr/bin/env bash
# Build the offline release tarball for CV84X6 (aarch64, Python 3.10).
#
#   scripts/package.sh --lib <libcv84x6_llm.so> --config <qwen3.5 config dir> [--out dist/]
#   scripts/package.sh ... --stage <dir>     # unpacked tree only, no tarball
#
# The tarball is self-contained: the web stack ships in vendor/ and tokenising
# lives in lib/libcv84x6_llm.so, so the board needs only a Python 3.10
# interpreter -- no numpy/tokenizers/torch.
# Inputs:
#   --lib     the engine built ON the board (native/, cmake) -- it links the
#             board's libsophon, so it is not cross-built here.
#   --config  sophon-demo's Qwen3_5 config dir (config.zip), shipped as the
#             fallback tokenizer/processor config for bare .bmodel downloads.
#   --stage   write the release tree to <dir>/<name>/ and stop there. This is
#             what scripts/package_deb.sh wraps into a .deb; it is the same tree
#             the tarball contains, so the two cannot drift. The directory is
#             left in place for the caller to consume.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

LIB="" CONFIG="" OUT="$ROOT/dist" STAGE_OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --lib) LIB=$2; shift 2 ;;
    --config) CONFIG=$2; shift 2 ;;
    --out) OUT=$2; shift 2 ;;
    --stage) STAGE_OUT=$2; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -f "$LIB" ] || { echo "--lib <libcv84x6_llm.so> is required" >&2; exit 2; }
[ -f "$CONFIG/tokenizer.json" ] || { echo "--config must contain tokenizer.json" >&2; exit 2; }
[ -f web/dist/index.html ] || { echo "web/dist missing: run scripts/build_web.sh" >&2; exit 2; }
file "$LIB" | grep -q "aarch64" || { echo "$LIB is not an aarch64 library" >&2; exit 2; }

VERSION=$(python3 -c 'import re;print(re.search(r"__version__ = \"([^\"]+)\"", open("app/__init__.py").read()).group(1))')
NAME="cv84x6-llm-server-${VERSION}-aarch64"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
D="$STAGE/$NAME"
mkdir -p "$D"

# Application code, console, engine source (for rebuilding on another SDK).
# rsync is the upstream tool; the sophon-tools unified image does not ship it,
# so there is a `cp -a` fallback. cp cannot filter, so the fallback prunes the
# excluded paths AFTER the copy — the excluded sets are shared in one place
# (_TREE_EXCLUDES below) and the prune mirrors them exactly, so both paths
# produce the same tree even when the source has build residue (native/build/,
# stray .pyc) from a previous in-tree compile.
if command -v rsync >/dev/null 2>&1; then
  _tree_copy() { local ex=(); while [ "$1" = "--exclude" ]; do ex+=(--exclude "$2"); shift 2; done; rsync -a "${ex[@]}" "$@"; }
  _tree_prune() { :; }   # rsync already skipped the excluded paths
else
  _tree_copy() { while [ "$1" = "--exclude" ]; do shift 2; done; cp -a "$@"; }
  _tree_prune() {
    # Must mirror every --exclude passed above, per copied directory.
    find "$D/app" "$D/native" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    find "$D/app" "$D/native" -name '*.pyc' -delete 2>/dev/null || true
    rm -rf "$D/native/build" 2>/dev/null || true
  }
fi
_tree_copy --exclude '__pycache__' --exclude '*.pyc' app "$D/"
mkdir -p "$D/web"
_tree_copy web/dist "$D/web/"
_tree_copy --exclude build native "$D/"
_tree_prune
mkdir -p "$D/lib"
cp "$LIB" "$D/lib/libcv84x6_llm.so"
# Tokenizer/processor configs. `--config` is the Qwen3.5 chat config (the
# caller passes sophon-demo's config.zip for it); the auxiliary models' configs
# come from the repository, because there is nothing on the board to copy them
# from -- a dfss download of an embedding bmodel brings only the .bmodel.
mkdir -p "$D/model-config"
_tree_copy "$CONFIG/" "$D/model-config/qwen3_5/"
if [ -d model-config ]; then
  for src in model-config/*; do
    [ -d "$src" ] || continue
    name=$(basename "$src")
    # qwen3_5 came from --config above; everything else is repository data.
    [ "$name" = "qwen3_5" ] && continue
    _tree_copy "$src/" "$D/model-config/$name/"
  done
fi
# (the cp -a fallback's prune ran right after the copy; this later sweep is a
# final guarantee for BOTH paths: the package must never ship native build
# output or caches, whatever the source tree looked like.)
find "$D/app" "$D/native" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
find "$D/app" "$D/native" -name '*.pyc' -delete 2>/dev/null || true
rm -rf "$D/native/build" 2>/dev/null || true
for required in qwen3_embedding/tokenizer.json bge_reranker_v2_m3/tokenizer.json \
                qwen3_asr/tokenizer.json wemm_embedding/tokenizer.json \
                wemm_embedding/embedding_config.json ppocr_v6/ppocr.json \
                ppocr_v6/ppocr_keys_v1.txt; do
  [ -f "$D/model-config/$required" ] || {
    echo "release tree is missing model-config/$required" >&2; exit 2; }
done
cp -a deploy README.md "$D/"
# The MCP stdio bridge (`bin/cv84x6-mcp-stdio`). Shipped even though none of the
# three bundled agents needs it -- all of them speak Streamable HTTP to /mcp
# directly (docs/mcp.md has the evidence) -- because it is the documented way to
# point a stdio-only client at this service, and a bridge an operator has to
# write themselves is a bridge that will be written wrong. Standard library only,
# so it adds one small file and no wheel.
mkdir -p "$D/bin"
cp -a bin/cv84x6-mcp-stdio "$D/bin/"
chmod 0755 "$D/bin/cv84x6-mcp-stdio"
mkdir -p "$D/scripts" "$D/tools"
cp scripts/install.sh scripts/uninstall.sh "$D/scripts/"
cp tools/engine_check.py tools/e2e_check.py tools/cache_check.py tools/cache_e2e.py tools/stress_check.py "$D/tools/"
mkdir -p "$D/tools/vl_embed"
cp tools/vl_embed/service_check.py "$D/tools/vl_embed/"

# Vendor wheels target the BOARD's interpreter (cp310/aarch64), never the build
# host's. The unified sophon-tools image ships python3.8 + pip 20.0.2, which
# mis-filters manylinux platform tags under --platform/--python-version and
# refuses cp310 wheels with a host-side requires-python error. Detect that
# host once: build a private pip >= 24 inside the staging area (never the
# caller's user-level pip) and pin --abi cp310 --ignore-requires-python so the
# wheel selection follows the --python-version 3.10 target instead of the 3.8
# host. On a cp310 host the original upstream invocation is used unchanged.
_vendor_pip_host=$(python3 -c 'import sys; print("cp%d%d" % sys.version_info[:2])')
_vendor_pip_flags=()
_vendor_pip_cmd=(python3 -m pip)
if [ "$_vendor_pip_host" != "cp310" ]; then
  _vendor_pip_ver=$(python3 -m pip --version | awk '{print $2}')
  _vendor_pip_major=${_vendor_pip_ver%%.*}
  if [ "${_vendor_pip_major:-0}" -lt 24 ]; then
    # Isolated target, not --user: the caller's site-packages stay untouched.
    python3 -m pip install -q --disable-pip-version-check \
      --target "$STAGE/pip-host" "pip==24.0"
    PYTHONPATH="$STAGE/pip-host" _vendor_pip_cmd=(python3 -m pip)
  fi
  _vendor_pip_flags=(--abi cp310 --ignore-requires-python)
fi
_vendor_pip() {
  env PYTHONPATH="$STAGE/pip-host${PYTHONPATH:+:$PYTHONPATH}" \
    "${_vendor_pip_cmd[@]}" install -q --disable-pip-version-check \
    --target "$D/vendor" \
    --platform manylinux2014_aarch64 --python-version 3.10 --implementation cp \
    --only-binary=:all: "${_vendor_pip_flags[@]}" "$@"
}

# Web stack for the board's Python (cp310 / aarch64), installed nowhere: the
# service puts vendor/ first on PYTHONPATH.
# sophon-tools adaptation: the vendored stack is resolved from
# requirements-vendor-lock.txt -- the exact versions shipped in the official
# v0.6.37 release (its vendor/VENDORED.txt). The upstream flow resolved the
# `>=` ranges in requirements-vendor.txt at build time, which is fine for the
# one machine that built each release but would make two builds of this tree
# ship different binaries. The lockfile is generated with
# `pip freeze --path vendor` from a release tree; bump it together with a real
# upgrade of the vendored stack, not routinely. tokenizers is excluded here and
# re-installed with --no-deps below (the release VENDORED.txt records it, but
# a plain -r would pull its huggingface-hub dependency tree, which the official
# package deliberately does not carry).
# The lockfile is the full VENDORED.txt of the release; the wheels that are
# re-installed below with --no-deps (tokenizers, pyclipper, numpy, pypdfium2,
# pillow) are excluded from this pass so they are fetched exactly once, with
# the same locked versions as upstream's separate --no-deps installs.
grep -vE '^(tokenizers|pyclipper|numpy|pypdfium2|pillow)==' requirements-vendor-lock.txt > "$STAGE/vendor-lock-no-tok.txt"
_vendor_pip -r "$STAGE/vendor-lock-no-tok.txt"
# HF `tokenizers` (Rust) separately, and with --no-deps, for two reasons: it is
# only needed for the auxiliary models (embedding/rerank), so a chat-only install
# would carry it for nothing, and its dependency set (huggingface-hub, etc.) is
# a tree the board does not need — the tokenizer.json is read straight from the
# model config directory. The version comes from the one lockfile (--no-deps
# skips dependency resolution, not version selection): an unpinned name here
# would let the newest release drift in while everything else stays locked.
VENDORIZERS_SPEC="$(grep -oE '^tokenizers==[^#[:space:]]+' requirements-vendor-lock.txt)"
[ -n "$VENDORIZERS_SPEC" ] || {
  echo "requirements-vendor-lock.txt must pin tokenizers==<version>" >&2; exit 2; }
_vendor_pip --no-deps "$VENDORIZERS_SPEC"
# pyclipper, same treatment: PP-OCR's DB postprocess offsets each text polygon
# outwards with it, and it is a 100 KB native wheel with no dependencies to
# speak of. Vendored rather than left to the device because nothing in the SDK
# ships it -- unlike OpenCV, which does and is used from there (the OCR
# pre/post-processing imports the device's sophon-opencv; see
# app/engine/ocr_ppocr.py and docs/aux-models.md). numpy is a runtime
# dependency of the OCR path only; it goes in from requirements.txt's aarch64
# wheel list below.
_vendor_pip --no-deps "$(grep -oE '^pyclipper==[^#[:space:]]+' requirements-vendor-lock.txt)"
# numpy: the OCR backend's arithmetic is numpy (resize/contour results, the
# softmax map, CTC). Everything else in this service avoids it on purpose, so it
# is installed here explicitly rather than added to requirements-vendor.txt --
# and `scipy`/`sklearn` are deliberately not pulled in by anything, which is why
# this uses --no-deps and the pure numpy wheel.
# Pinned to 1.x: the device's sophon-opencv cv2.so is built against the numpy 1
# C ABI, and under numpy 2 `import cv2` fails ("_ARRAY_API not found"), which
# leaves every OCR model unloadable (v0.6.22 shipped 2.2.6). 1.26.4 is the last
# 1.x with a cp310 aarch64 wheel; verified with cv2 4.8.0 on the CV84X6 board.
# The pin is asserted against the lockfile below, so the two cannot drift:
# lockfile is the single version source; the literal here is the assertion.
NUMPY_SPEC="$(grep -oE '^numpy==[^#[:space:]]+' requirements-vendor-lock.txt)"
[ -n "$NUMPY_SPEC" ] || { echo "lockfile must pin numpy==" >&2; exit 2; }
_vendor_pip --no-deps "$NUMPY_SPEC"
compgen -G "$D/vendor/numpy-1.*.dist-info" > /dev/null || {
  echo "vendor/numpy must be 1.x for the device's sophon-opencv" >&2; exit 2; }
# pypdfium2 and Pillow: the knowledge-base app (app/apps/kb/parse.py) reads PDF
# text layers, rasterises scanned pages for the OCR pass, and decodes the images
# it is asked to OCR. Both ship aarch64 wheels; both are --no-deps because
# pypdfium2 bundles libpdfium in its own wheel and Pillow has none. A deployment
# that never opens the app still carries them: the alternative is an install-time
# prerequisite, and a demo that fails to start because a wheel is missing is a
# worse trade than ~10 MB of disk on a device with gigabytes of it.
#
# Versions are pinned, not floating. An unpinned `pip install pillow` resolves to
# whatever is newest at build time, so two builds of the same commit ship
# different binaries -- and the board has no compiler to fall back on if a new
# release drops the aarch64/cp310 wheel. `12.2.0` is the Pillow measured on
# `.151`; `pypdfium2` 5.14.0 bundles the libpdfium the PDF path was verified
# against. Bump both together with a real-device run (docs/kb-app.md §12).
#
# These are *package* versions, not this service's: the service's own version
# comes from app/__init__.py and nowhere else (tests/test_packaging.py enforces
# that), which is why the names below do not start with `VERSION`.
KB_PDFIUM_PKG="$(grep -oE '^pypdfium2==[^#[:space:]]+' requirements-vendor-lock.txt)"
KB_IMAGE_PKG="$(grep -oE '^pillow==[^#[:space:]]+' requirements-vendor-lock.txt)"
[ -n "$KB_PDFIUM_PKG" ] && [ -n "$KB_IMAGE_PKG" ] || {
  echo "lockfile must pin pypdfium2== and pillow==" >&2; exit 2; }
_vendor_pip --no-deps "$KB_PDFIUM_PKG"
_vendor_pip --no-deps "$KB_IMAGE_PKG"
for required_pkg in tokenizers pyclipper numpy pypdfium2 PIL; do
  compgen -G "$D/vendor/$required_pkg*" > /dev/null || {
    echo "release tree is missing vendor/$required_pkg" >&2; exit 2; }
done
rm -rf "$D/vendor/bin"
find "$D/vendor" -name '__pycache__' -prune -exec rm -rf {} +
python3 -m pip freeze --path "$D/vendor" > "$D/vendor/VENDORED.txt" 2>/dev/null || true

echo "$VERSION" > "$D/VERSION"
# COMMIT records the SERVICE source commit the engine and service code came
# from. Since v0.6.38 that source lives in this repository
# (sophgo/sophon-tools, source/pcv84x6_llm_server), so the file names that
# repository explicitly rather than resolving the outer HEAD blindly: a caller
# building from a subdirectory or a detached worktree must still get the truth
# instead of an unrelated commit.
SOURCE_FILE="$ROOT/build/source-commit.txt"
if [ -f "$SOURCE_FILE" ]; then
  # format: <service commit> <repo> [<path within that repo>]
  SRC_COMMIT="$(cut -d' ' -f1 "$SOURCE_FILE")"
  SRC_REPO="$(cut -d' ' -f2 "$SOURCE_FILE")"
  SRC_PATH="$(cut -d' ' -f3 "$SOURCE_FILE")"
  echo "$SRC_COMMIT" > "$D/COMMIT"
  {
    echo "service-repo: ${SRC_REPO:-unknown}"
    [ -n "${SRC_PATH:-}" ] && echo "service-path: $SRC_PATH"
  } > "$D/COMMIT.provenance"
else
  git rev-parse HEAD > "$D/COMMIT" 2>/dev/null || true
fi
(cd "$D" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)

# --stage: hand the tree to the caller instead of tarring it.
if [ -n "$STAGE_OUT" ]; then
  mkdir -p "$STAGE_OUT"
  rm -rf "$STAGE_OUT/$NAME"
  mv "$D" "$STAGE_OUT/$NAME"
  trap - EXIT
  echo "staged $STAGE_OUT/$NAME"
  exit 0
fi

mkdir -p "$OUT"
tar -C "$STAGE" -czf "$OUT/$NAME.tar.gz" "$NAME"
(cd "$OUT" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
echo "built $OUT/$NAME.tar.gz ($(du -h "$OUT/$NAME.tar.gz" | cut -f1))"
