#!/usr/bin/env python3
"""生成 / 校验 SE写卡工具内置的中文字体子集。

    python3 mkfont.py                      # 重新生成 NotoSansSC-Regular-subset.otf
    python3 mkfont.py --check              # 只检查：界面源码里有没有字不在子集字体里

字集 = ASCII/拉丁 + 常用符号 + 中文标点 + 全角 + 假名 + GB2312 全部汉字。
GB2312 覆盖 6763 个简体汉字，日常界面文案、盘型号、文件名、报错信息都够用；
再少就会出现豆腐块，再多（GBK / 全 CJK）体积涨得不成比例。

为什么要 --check: 界面统一用这份内置字体画，而它不在系统的字体链接表里 ——
GDI 不会替它回退到别的字体，界面上出现字体里没有的字就是豆腐块。
**加新图标/符号时先跑一遍 --check。**

依赖: fonttools (pip install fonttools)；源字体用系统装的 Noto Sans CJK。
"""
import glob
import os
import re
import sys

from fontTools.ttLib import TTCollection
from fontTools import subset

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"
FACE = 2  # Noto Sans CJK SC
OUT = os.path.join(HERE, "NotoSansSC-Regular-subset.otf")
SRC_GLOB = os.path.join(HERE, "..", "*.go")


def gb2312_chars():
    out = set()
    for hi in range(0xA1, 0xF8):
        for lo in range(0xA1, 0xFF):
            try:
                out.add(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    return out


def build_charset():
    cs = set()

    def rng(a, b):
        cs.update(chr(c) for c in range(a, b + 1))

    rng(0x20, 0x7E)      # ASCII 可打印
    rng(0xA0, 0xFF)      # 拉丁补充
    rng(0x2010, 0x203A)  # 常用标点（– — ‘ ’ “ ” … 等）
    rng(0x20A0, 0x20BF)  # 货币
    rng(0x2190, 0x21FF)  # 箭头
    rng(0x2200, 0x22FF)  # 数学运算符（≤ ≥ ≠ 等）
    rng(0x2460, 0x24FF)  # ①②③ …
    rng(0x2500, 0x257F)  # 制表符
    rng(0x25A0, 0x25FF)  # 几何图形（● ■ ◐◓◑◒ 等，进度转圈用的就是这些）
    rng(0x2600, 0x27BF)  # 杂项符号（✓ ⚠ 等）
    rng(0x3000, 0x303F)  # 中文标点
    rng(0x3040, 0x30FF)  # 假名（盘型号 / 日文文件名）
    rng(0xFF00, 0xFFEF)  # 全角
    cs |= gb2312_chars()
    return cs


def load_source_face():
    coll = TTCollection(SRC, lazy=False)
    font = coll.fonts[FACE]
    return font


def generate():
    cs = build_charset()
    print("charset size:", len(cs))
    font = load_source_face()
    print("face:", font["name"].getDebugName(1))

    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.name_legacy = True
    opts.name_languages = ["*"]
    opts.notdef_outline = True
    opts.recalc_bounds = True
    opts.drop_tables += ["DSIG"]
    opts.glyph_names = False

    sub = subset.Subsetter(options=opts)
    sub.populate(text="".join(sorted(cs)))
    sub.subset(font)

    font.save(OUT)
    print("saved:", OUT, os.path.getsize(OUT), "bytes")


# 源码里的字符串 / 反引号串 / 字符字面量（行注释先去掉，免得把注释里的字算进来）
LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"' + r'|`([^`]*)`' + r"|'((?:[^'\\]|\\.)*)'")


def check():
    from fontTools.ttLib import TTFont

    if not os.path.exists(OUT):
        sys.exit("找不到 %s，先跑一次 python3 mkfont.py" % OUT)
    cmap = set(TTFont(OUT, lazy=True).getBestCmap().keys())

    missing = {}
    for path in sorted(glob.glob(SRC_GLOB)):
        if path.endswith("_test.go"):
            continue
        src = re.sub(r"//[^\n]*", "", open(path, encoding="utf-8").read())
        for m in LITERAL.finditer(src):
            for ch in m.group(1) or m.group(2) or m.group(3) or "":
                if ord(ch) > 0x7F and ord(ch) not in cmap:
                    missing.setdefault(ch, set()).add(os.path.basename(path))

    if not missing:
        print("OK: 界面源码里用到的字都在内置字体里")
        return 0
    print("以下字符不在内置字体里，界面上会画成豆腐块：")
    for ch, files in sorted(missing.items(), key=lambda kv: ord(kv[0])):
        print("  U+%04X %r  %s" % (ord(ch), ch, ",".join(sorted(files))))
    return 1


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        sys.exit(check())
    generate()
