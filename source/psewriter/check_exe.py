#!/usr/bin/env python3
"""校验 Windows 产物的平台底线 (MYS-1062 十四轮)。

三条硬要求都要能从文件本身验出来, 而不是靠文档里写一句:

  1. 位宽      —— PE32 = 32 位 (i386) / PE32+ = 64 位 (x86-64)
  2. Win7 可跑 —— PE 可选头里的 MajorSubsystemVersion.MinorSubsystemVersion 必须是 6.0x。
                  Go 1.21 起这个值变成 10.0, 这种 exe 在 Windows 7 上会被加载器直接拒绝
                  (「不是有效的 Win32 应用程序」), 所以它是"能不能在 Win7 上跑"的硬指标。
  3. 管理员权限 —— PE 资源目录里的 RT_MANIFEST (24) 必须含
                  requestedExecutionLevel level="requireAdministrator";
                  同时必须含 comctl32 v6 依赖 (lxn/walk 的硬要求, 缺了启动即报
                  TTM_ADDTOOL failed)。

用法: python3 check_exe.py <exe> [<exe> ...]
      python3 check_exe.py --want arch=386,subsys=6.0,admin <exe>
退出码 0 = 全部通过, 1 = 有不合格项。
"""
import pathlib
import struct
import sys

RT_MANIFEST = 24

# PE 可选头里数据目录的起始偏移: PE32 (0x10b) 与 PE32+ (0x20b) 不同
DDIR_OFF = {0x10B: 96, 0x20B: 112}
MACHINE = {0x014C: "i386(32位)", 0x8664: "x86-64(64位)", 0xAA64: "ARM64"}


class PE:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.b = self.path.read_bytes()
        e = struct.unpack_from("<I", self.b, 0x3C)[0]
        if self.b[e:e + 4] != b"PE\0\0":
            raise ValueError("不是 PE 文件")
        coff = e + 4
        self.machine = struct.unpack_from("<H", self.b, coff)[0]
        nsec = struct.unpack_from("<H", self.b, coff + 2)[0]
        optsz = struct.unpack_from("<H", self.b, coff + 16)[0]
        opt = coff + 20
        self.magic = struct.unpack_from("<H", self.b, opt)[0]
        self.subsys_major, self.subsys_minor = struct.unpack_from("<HH", self.b, opt + 48)
        self.subsystem = struct.unpack_from("<H", self.b, opt + 68)[0]
        ddir = opt + DDIR_OFF[self.magic]
        self.res_rva, _ = struct.unpack_from("<II", self.b, ddir + 2 * 8)
        self.secs = []
        so = opt + optsz
        for i in range(nsec):
            s = so + i * 40
            vsz, va, rawsz, praw = struct.unpack_from("<IIII", self.b, s + 8)
            self.secs.append((va, max(vsz, rawsz), praw))

    def _r2o(self, rva):
        for va, vsz, praw in self.secs:
            if va <= rva < va + vsz:
                return praw + (rva - va)
        return None

    def resources(self):
        """遍历资源目录 → [(类型, 名字, 语言, 文件偏移, 长度)]"""
        base = self._r2o(self.res_rva)
        if base is None:
            return []
        out = []

        def walk(off, path):
            nn, ni = struct.unpack_from("<HH", self.b, off + 12)
            for i in range(nn + ni):
                eo = off + 16 + i * 8
                nameid, offv = struct.unpack_from("<II", self.b, eo)
                # NameId 高位=1 表示"名字字符串"(相对 base), 否则是整数 ID
                ident = ("name", base + (nameid & 0x7FFFFFFF)) if nameid & 0x80000000 else ("id", nameid)
                # Offset 高位=1 表示指向下一级目录, 偏移同样是**相对资源根**的
                nxt = base + (offv & 0x7FFFFFFF)
                if offv & 0x80000000:
                    walk(nxt, path + [ident])
                else:
                    rva, size = struct.unpack_from("<II", self.b, nxt)
                    off2 = self._r2o(rva)
                    out.append((path + [ident], size, off2))

        walk(base, [])
        return out

    def manifest(self):
        """取 RT_MANIFEST 的内容 (无则 None)"""
        for path, size, off in self.resources():
            if path and path[0] == ("id", RT_MANIFEST) and off is not None:
                return self.b[off:off + size]
        return None


def check(path, want_arch=None):
    """返回 (问题列表, 信息字典)"""
    problems = []
    p = PE(path)
    mb = p.path.stat().st_size / (1 << 20)
    bits = 32 if p.magic == 0x10B else 64
    info = {
        "file": p.path.name,
        "machine": MACHINE.get(p.machine, "0x%04x" % p.machine),
        "bits": bits,
        "subsys": "%d.%02d" % (p.subsys_major, p.subsys_minor),
        "size_mb": mb,
    }

    if want_arch and want_arch != bits:
        problems.append("位宽应为 %d 位, 实为 %d 位" % (want_arch, bits))

    # Win7 = 6.1; 子系统版本高于 6.1 的 exe 在 Win7 上直接加载失败
    if (p.subsys_major, p.subsys_minor) > (6, 1):
        problems.append("PE 子系统版本 %s 高于 6.01, Windows 7 无法加载 (Go 1.21+ 的默认值就是 10.0)"
                        % info["subsys"])

    man = p.manifest()
    info["manifest"] = len(man) if man else 0
    if not man:
        problems.append("PE 资源里没有 RT_MANIFEST(24) — lxn/walk 会因 comctl32 v5 启动即报 TTM_ADDTOOL failed")
    else:
        info["admin"] = b'level="requireAdministrator"' in man
        info["comctl"] = b"Common-Controls" in man and b"6.0.0.0" in man
        info["permonitor"] = b"PerMonitorV2" in man
        if not info["admin"]:
            problems.append('manifest 里没有 requestedExecutionLevel level="requireAdministrator"')
        if not info["comctl"]:
            problems.append("manifest 里没有 comctl32 v6 依赖")
    return problems, info


def main(argv):
    want_bits = None
    args = []
    for a in argv:
        if a.startswith("--want"):
            continue
        if a.startswith("arch="):
            want_bits = int(a.split("=", 1)[1])
        elif a.startswith("subsys=") or a.startswith("admin"):
            continue
        else:
            args.append(a)
    if not args:
        print(__doc__)
        return 2
    bad = 0
    for f in args:
        try:
            problems, info = check(f, want_bits)
        except Exception as ex:  # noqa: BLE001
            print("✗ %s: 解析失败: %s" % (f, ex))
            bad += 1
            continue
        mark = "✓" if not problems else "✗"
        print("%s %-24s %-12s %s  %6.1f MiB  manifest=%d 管理员=%s comctl32v6=%s PerMonitor=%s" % (
            mark, info["file"], info["machine"], info["subsys"], info["size_mb"],
            info["manifest"], info.get("admin", "-"), info.get("comctl", "-"), info.get("permonitor", "-")))
        for pr in problems:
            print("    - " + pr)
        bad += len(problems)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
