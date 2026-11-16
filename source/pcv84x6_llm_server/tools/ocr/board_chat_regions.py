#!/usr/bin/env python3
"""Board acceptance for MYS-2681: the *chat* path on region crops.

The card's criterion 4: drive `/v1/chat/completions` with the `openai` client --
what the official PaddleOCR client uses -- and post the crops the official
pipeline actually sends: `table_stats`'s 706x47 title and 537x29 footnote, plus
the three table crops. Titles and footnotes have to read correctly, and the
table OTSL has to match MYS-2663's.

The three text regions are cut with the boxes MYS-2660's layout run produced
(``boxes.json``), which is why the sizes here are the ones the card quotes --
these are not hand-picked crops that happen to be awkward, they are the regions
the pipeline sends.

    python3 tools/ocr/board_chat_regions.py --base http://<board>:8010 \\
        --key KEY --img-dir tests/data/ocr/img --out /tmp/chat_regions.json
"""
from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path

#: label -> (image, box or None for the whole image, prompt). The boxes are
#: ``/data/mys2660/pg1/boxes.json`` for table_stats; the two other tables were
#: aligned as whole images by MYS-2660 and are posted the same way here.
REGIONS = [
    ("title", "table_stats.png", (120, 104, 826, 151), "OCR:"),
    ("footnote", "table_stats.png", (114, 801, 651, 830), "OCR:"),
    ("table_table_stats", "table_stats.png", (123, 198, 1160, 738),
     "Table Recognition:"),
    ("table_merged", "cn_table_merged.png", None, "Table Recognition:"),
    ("table_simple", "cn_table_simple.png", None, "Table Recognition:"),
]

#: What the page really says, for the two regions the stretch used to invent
#: (``docs/ocr-vl.md`` §11.9's table). Compared with whitespace removed: the
#: model writes ``2026 年`` where the page has ``2026年``, and that is a
#: tokenisation difference, not a reading error.
TRUTH = {
    "title": "2026年第三季度生产数据统计表",
    "footnote": "注：合格率按抽检样本计算，抽检比例 5%。",
}


def crop_png(cv2, path: Path, box) -> bytes:
    bgr = cv2.imread(str(path))
    if box is not None:
        x1, y1, x2, y2 = box
        bgr = bgr[y1:y2, x1:x2]
    ok, buf = cv2.imencode(".png", bgr)
    if not ok:
        raise SystemExit(f"cannot encode {path}")
    return buf.tobytes()


def data_url(blob: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(blob).decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--model", default="vl-2681")
    ap.add_argument("--img-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    import cv2
    from openai import OpenAI

    client = OpenAI(base_url=args.base.rstrip("/") + "/v1", api_key=args.key)
    results = {}
    for name, image, box, prompt in REGIONS:
        blob = crop_png(cv2, args.img_dir / image, box)
        h, w = (box[3] - box[1], box[2] - box[0]) if box else (0, 0)
        started = time.time()
        response = client.chat.completions.create(
            model=args.model,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_url(blob)}},
                {"type": "text", "text": prompt},
            ]}],
            max_completion_tokens=2048,
            temperature=0,
            extra_body={"skip_special_tokens": True},
        )
        seconds = time.time() - started
        message = response.choices[0].message.content or ""
        entry = {
            "image": image,
            "crop": [w, h] if box else list(cv2.imread(
                str(args.img_dir / image)).shape[1::-1]),
            "prompt": prompt,
            "seconds": round(seconds, 2),
            "finish_reason": response.choices[0].finish_reason,
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "text": message,
        }
        if name in TRUTH:
            entry["truth"] = TRUTH[name]
            entry["correct"] = TRUTH[name].replace(" ", "") in message.replace(" ", "")
        results[name] = entry
        print(f"{name:20s} {entry['crop']} {seconds:5.2f}s "
              f"{len(message):4d} chars  {message[:50]!r}", flush=True)

    args.out.write_text(json.dumps(results, indent=1, ensure_ascii=False),
                        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
