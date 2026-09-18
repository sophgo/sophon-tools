#!/usr/bin/env python3
"""从系统 Noto Sans CJK 里抽出 SC 字面并按字集裁剪，产出可内嵌的 OTF。

字集 = ASCII/拉丁 + 常用符号 + 中文标点 + 全角 + GB2312 汉字。
GB2312 覆盖 6763 个简体汉字，日常界面文案、盘型号、文件名、报错信息都够用；
再少就会出现豆腐块，再多（GBK/全 CJK）体积涨得不成比例。
"""
import sys
from fontTools.ttLib import TTCollection
from fontTools import subset

SRC = "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"
FACE = 2  # Noto Sans CJK SC
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/NotoSansSC-subset.otf"


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
    rng(0x25A0, 0x25FF)  # 几何图形（● ■ ▲ 等）
    rng(0x2600, 0x27BF)  # 杂项符号（✓ ✗ ⚠ 等）
    rng(0x2800, 0x28FF)  # 盲文点阵 —— 进度转圈用的就是这些
    rng(0x3000, 0x303F)  # 中文标点
    rng(0x3040, 0x30FF)  # 假名（盘型号/日文文件名）
    rng(0xFF00, 0xFFEF)  # 全角
    cs |= gb2312_chars()
    return cs


def main():
    cs = build_charset()
    print("charset size:", len(cs))
    coll = TTCollection(SRC, lazy=False)
    font = coll.fonts[FACE]
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
    import os
    print("saved:", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
