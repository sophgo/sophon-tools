import base64, time, httpx
from e2e_common import BASE, INFER_KEY, board, load, record, unload
P = "__SUDO_PW__"
t0 = board("date '+%Y-%m-%d %H:%M:%S'").strip().splitlines()[-1]
b64 = base64.b64encode(open("/home/zzt/workspace/cv84x6-demo-ui/tests/data/ocr/img/table_stats.png", "rb").read()).decode()
for i in range(5):
    load("ppocrv6-medium")
    httpx.post(f"{BASE}/v1/ocr", headers={"Authorization": f"Bearer {INFER_KEY}"}, json={"model": "ppocrv6-medium", "image": b64, "mode": "layout"}, timeout=120)
    unload("ppocrv6-medium"); time.sleep(1)
out = board(f"echo {P} | sudo -S journalctl -u cv84x6-llm --since '{t0}' --no-pager 2>/dev/null | grep -c -E 'terminate called|bmlib_memory\\]\\[error|bmlib_runtime\\]\\[error|BM_CHECK'; "
            f"echo {P} | sudo -S journalctl -u cv84x6-llm --since '{t0}' --no-pager 2>/dev/null | grep -c 'worker stopped cleanly'; echo {P} | sudo -S dmesg 2>/dev/null | grep -c 'wait api timeout'")
nums = [l.strip() for l in out.splitlines() if l.strip().isdigit()]
record("RC2 复测", "D5 OCR 加载/卸载 5 次（含 layout 引擎）", nums[:1] == ["0"],
       f"自 {t0}（板上时间）起：terminate/bmlib error 行数={nums[0] if nums else '?'}；dmesg wait api timeout={nums[2] if len(nums)>2 else '?'}。首判 86 行是脚本用 13.24 的 PST 时间作 --since，板子按 CST 解析，窗口包含了 RC1 的旧错误")
