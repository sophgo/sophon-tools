#!/bin/sh
# Regenerate the static evidence for the BMRT queue-depth report (MYS-2469).
#
#   ./analysis/extract_driver_evidence.sh [--board linaro@10.42.0.242]
#
# Reads (never writes) the board's own libsophon artefacts and prints the
# extracts that back docs/bmrt-queue-depth.md section 1.3:
#
#   * tsh_cfg_default, the compile-time config whose first field is the TSH mode
#   * tsh_init called with cfg = NULL, i.e. the built-in default is used
#   * the mode-1 depth check (0x10101010 = 16 slots per HWQ)
#   * the mode-2 depth check (0x40404040 = 64 slots per HWQ)
#   * the 16/64 csel in bm84x6_task_init that sizes the kfifo
#   * every depth-register access, all of them reads
#   * the device-tree property names the driver actually consumes
#
# Nothing here modifies the board: it only tars a file out and disassembles it
# locally with the aarch64 cross binutils. Needs aarch64-linux-gnu-objdump,
# aarch64-linux-gnu-objcopy, aarch64-linux-gnu-nm, and ssh access to the board.
set -eu

BOARD="${BOARD:-linaro@10.42.0.242}"
LIBDIR=/opt/sophon/libsophon-0.4.15

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

echo "# Fetching bmtpu.ko from $BOARD (read-only)"
ssh "$BOARD" "tar czf - -C $LIBDIR/data bmtpu.ko" > "$TMP/ko.tgz"
tar xzf "$TMP/ko.tgz" -C "$TMP"
KO="$TMP/bmtpu.ko"

OBJDUMP=aarch64-linux-gnu-objdump
OBJCOPY=aarch64-linux-gnu-objcopy

$OBJDUMP -dr -d "$KO" > "$TMP/ko.dis" 2>/dev/null
$OBJCOPY -O binary --only-section=.rodata.str1.8 "$KO" "$TMP/str18.bin"

cstr() {  # cstr <offset>  -- print the NUL-terminated string at a .rodata offset
  python3 - "$TMP/str18.bin" "$1" <<'PY'
import sys
d = open(sys.argv[1], 'rb').read()
off = int(sys.argv[2], 16)
print(d[off:d.index(b'\0', off)].decode('utf-8', 'replace'))
PY
}

echo
echo "## 1. tsh_cfg_default: compile-time config; field 0 is 'mode'"
$OBJDUMP -s -j .data.tsh_cfg_default "$KO" | sed -n '1,10p'
python3 - "$KO" <<'PY'
import struct, subprocess, sys
raw = subprocess.run(['aarch64-linux-gnu-objcopy', '-O', 'binary',
                      '--only-section=.data.tsh_cfg_default', sys.argv[1], '/dev/stdout'],
                     capture_output=True).stdout
# tsh_init uses default+0x68 when its cfg argument is NULL
print("\n  mode at default+0x68 = %d" % struct.unpack_from('<I', raw, 0x68)[0])
print("  tsh_cfg_default size = %d bytes, mode at +0x00 = %d"
      % (len(raw), struct.unpack_from('<I', raw, 0)[0]))
PY

echo
echo "## 2. bmdrv_probe calls tsh_init(handle, NULL): the default is used,"
echo "##    so the mode -- and therefore the depth -- is not read from DT or a param"
PROBE_ADDR=$($OBJDUMP -t "$KO" | awk '$NF=="bmdrv_probe"{print $1; exit}')
sed -n "/^00000000000000*${PROBE_ADDR#000000000000000} <bmdrv_probe>:/,/^\$/p" "$TMP/ko.dis" \
  | grep -B4 -A3 'tsh_init' \
  || grep -B4 -A3 'bl.*tsh_init' "$TMP/ko.dis"

echo
echo "## 3. tsh_init: cfg selection (NULL -> default+0x68)"
sed -n '/<tsh_init>:/,/^0000000/p' "$TMP/ko.dis" | sed -n '1,16p'

echo
echo "## 4. mode 1 depth check: regs 0x6024/0x6028 must read 0x10101010"
echo "##    0x10101010 -> four bytes of 0x10 = 16 slots per HWQ"
sed -n '/<tsh_init>:/,/^0000000/p' "$TMP/ko.dis" | sed -n '/2dd28:/,/2ddb0:/p'

echo
echo "## 5. mode 2 depth check: regs 0x6050/0x6054 must read 0x40404040"
echo "##    0x40404040 -> four bytes of 0x40 = 64 slots per HWQ"
sed -n '/<tsh_init>:/,/^0000000/p' "$TMP/ko.dis" | sed -n '/2dc58:/,/2dc98:/p'

echo
echo "## 6. bm84x6_task_init: kfifo depth is 16 or 64, chosen on (mode == 2)"
sed -n '/<bm84x6_task_init>:/,/^0000000/p' "$TMP/ko.dis" | sed -n '/29de8:/,/29e18:/p'

echo
echo "## 7. tsh_get_hwq_free_slots: reg holds 4 HWQs, 8 bits each => hw max 255"
sed -n '/<tsh_get_hwq_free_slots>:/,/^0000000/p' "$TMP/ko.dis"

echo
echo "## 8. every depth-register address load, and its callee:"
echo "##    all tpu_reg_read -- the driver never writes the depth"
python3 - "$TMP/ko.dis" <<'PY'
import re, sys
lines = open(sys.argv[1]).read().splitlines()
n = 0
for i, l in enumerate(lines):
    if re.search(r'mov\s+w1, #0x60(24|28|50|54)\b', l):
        n += 1
        for j in range(i + 1, min(i + 22, len(lines))):
            m = re.search(r'bl\s+\S+\s+<(\w+)>', lines[j])
            if m:
                print("  %-56s -> %s" % (l.strip(), m.group(1)))
                break
print("  total depth-register address loads: %d" % n)
PY

echo
echo "## 9. device-tree properties the driver reads (never a queue depth)"
echo "##    .rodata.str1.8+0x4e0 / +0x4f8 are the only of_property name arguments"
printf '  0x4e0 -> %s\n' "$(cstr 4e0)"
printf '  0x4f8 -> %s\n' "$(cstr 4f8)"

echo
echo "## 10. boot-log corroboration: 8 HWQ x 16 slots x 128-byte entries = 16384"
ssh "$BOARD" 'dmesg | grep -E "kfifo init|Global max_depth|NUM_HWQS" | head -3' || true
