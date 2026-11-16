"""Expose named intermediate tensors of a top-level MLIR as extra outputs.

    python3 add_outputs.py in.mlir out.mlir name1 name2 ...
Names are loc() strings; the op whose loc is that name (or a fused loc
containing it) becomes an output.
"""
import re
import sys

src, dst, *names = sys.argv[1:]
s = open(src).read()
locs = {}
for m in re.finditer(r'^#(loc\d+) = loc\("([^"]+)"\)', s, re.M):
    locs[m.group(2)] = m.group(1)
fused = {}
for m in re.finditer(r'^#(loc\d+) = loc\(fused\[([^\]]+)\]\)', s, re.M):
    for i, part in enumerate(x.strip()[1:] for x in m.group(2).split(",")):
        fused[part] = (m.group(1), i)
outs, types = [], []
for n in names:
    lid = locs[n]
    if lid in fused:
        lid, k = fused[lid]
    else:
        k = 0
    line = next(l for l in s.splitlines() if l.rstrip().endswith(f"loc(#{lid})") and "=" in l)
    lhs = line.split("=")[0].strip()
    vals = [v.strip() for v in lhs.split(",")]
    v = vals[k]
    if ":" in v:  # %values:2 style
        v = v.split(":")[0] + f"#{k}"
    rty = line.rsplit("->", 1)[1].rsplit("loc(", 1)[0].strip()
    rtys = [t.strip() for t in rty.strip("()").split("tensor") if t.strip()]
    rtys = ["tensor" + t.rstrip(", ") for t in rtys]
    outs.append(v)
    types.append(rtys[k] if len(rtys) > k else rtys[0])
lines = s.split("\n")
for i, l in enumerate(lines):
    if "func.func @main(" in l:
        head, tail = l.rsplit(") {", 1)
        lines[i] = head + ", " + ", ".join(types) + ") {" + tail
        break
s = "\n".join(lines)
ret = re.search(r"^(\s*return )([^:]+) : (.+?) (loc\(#loc\))$", s, re.M)
s = s[:ret.start()] + f"{ret.group(1)}{ret.group(2).strip()}, {', '.join(outs)} : {ret.group(3)}, {', '.join(types)} {ret.group(4)}" + s[ret.end():]
open(dst, "w").write(s)
print("added", list(zip(names, outs, types)))
