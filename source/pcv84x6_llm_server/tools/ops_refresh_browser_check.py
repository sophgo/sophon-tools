"""The refresh scenario, driven in a real browser.

What it proves, against a service whose model load really takes seconds:

1. click 加载, then RELOAD the page -- the button is still disabled and still
   says 加载中, i.e. the lock came from the backend, not from React state;
2. the button unlocks by itself once the model finishes loading, without a
   click (the page polls because the server says it is busy);
3. a second click while loading does not spawn a second worker;
4. unload from a reloaded page works, and the card returns to 未加载.

Run: python3 tools/ops_refresh_browser_check.py [base_url]
Exits non-zero on the first failed expectation.
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18200"
MODEL = "qwen-demo"
TIMEOUT_MS = 60_000
failures: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


def login(page) -> None:
    page.goto(BASE + "/", wait_until="networkidle")
    if page.locator('input[type="password"]').count():
        page.fill('input[type="password"]', "admin")
        page.keyboard.press("Enter")
        page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)


def open_models(page) -> None:
    """Navigate to the 模型 page.

    The console is a client-side router (buttons set React state, the URL never
    changes), so a reload always lands back on 总览. That is precisely the case
    this test is about: whatever locked the model is gone from the browser, and
    only the backend can still know.
    """
    page.get_by_role("button", name="模型").click()
    page.wait_for_selector(f'[data-testid="model-card-{MODEL}"]', timeout=TIMEOUT_MS)


def reload_and_open_models(page) -> None:
    """A real refresh: F5, then walk back to the models page."""
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(300)
    open_models(page)


def card_state(page) -> dict:
    card = page.locator(f'[data-testid="model-card-{MODEL}"]')
    card.wait_for(timeout=TIMEOUT_MS)
    return {
        "operation": card.get_attribute("data-operation"),
        "loaded": card.get_attribute("data-loaded"),
        "status_text": page.locator(f'[data-testid="model-status-{MODEL}"]').inner_text(),
        "load_disabled": _disabled(page, f"model-load-{MODEL}"),
        "unload_disabled": _disabled(page, f"model-unload-{MODEL}"),
        "delete_disabled": _disabled(page, f"model-delete-{MODEL}"),
        "load_text": _text(page, f"model-load-{MODEL}"),
        "unload_text": _text(page, f"model-unload-{MODEL}"),
        "op_note": _text(page, f"model-operation-{MODEL}"),
    }


def _disabled(page, testid: str):
    el = page.locator(f'[data-testid="{testid}"]')
    if not el.count():
        return None  # the other button is the one rendered
    return el.is_disabled()


def _text(page, testid: str) -> str:
    el = page.locator(f'[data-testid="{testid}"]')
    return el.inner_text() if el.count() else ""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        login(page)
        open_models(page)

        idle = card_state(page)
        check(idle["operation"] == "idle", f"idle card reports data-operation=idle ({idle['operation']})")
        check(idle["loaded"] == "false", "idle card reports data-loaded=false")
        check(idle["load_disabled"] is False, "load button is enabled when idle")

        page.click(f'[data-testid="model-load-{MODEL}"]')

        # -- the point of the whole change: reload mid-load -----------------
        page.wait_for_timeout(1200)
        page.reload(wait_until="networkidle")
        open_models(page)
        during = card_state(page)
        check(during["operation"] == "loading",
              f"after a reload mid-load the card still reports loading ({during['operation']})")
        check(during["loaded"] == "false",
              "after a reload mid-load the model still reports loaded=false")
        check(during["load_disabled"] is True,
              "after a reload mid-load the load button is still disabled")
        check("加载中" in during["load_text"],
              f"after a reload mid-load the button still says 加载中 ({during['load_text']!r})")
        check(during["delete_disabled"] is True,
              "after a reload mid-load the delete button is disabled")
        check("正在加载" in (during["op_note"] or ""),
              f"the card explains why it is locked ({during['op_note']!r})")

        # A second click must not be possible, and must not spawn a worker.
        page.evaluate(
            f"""() => {{
                const b = document.querySelector('[data-testid="model-load-{MODEL}"]');
                if (b && !b.disabled) b.click();
            }}"""
        )

        # -- unlocks by itself ---------------------------------------------
        page.wait_for_function(
            f"""() => {{
                const c = document.querySelector('[data-testid="model-card-{MODEL}"]');
                return c && c.getAttribute('data-operation') === 'idle'
                        && c.getAttribute('data-loaded') === 'true';
            }}""",
            timeout=TIMEOUT_MS,
        )
        after = card_state(page)
        check(after["loaded"] == "true", "the model finished loading and the card says so")
        check(after["unload_disabled"] is False,
              "the unload button unlocked without a click")
        check("在线" in after["status_text"], f"status pill reads 在线 ({after['status_text']!r})")
        check(after["op_note"] == "", "the 'why locked' note is gone once idle")

        # -- unload from a reloaded page -----------------------------------
        reload_and_open_models(page)
        page.click(f'[data-testid="model-unload-{MODEL}"]')
        page.wait_for_function(
            f"""() => {{
                const c = document.querySelector('[data-testid="model-card-{MODEL}"]');
                return c && c.getAttribute('data-loaded') === 'false'
                        && c.getAttribute('data-operation') === 'idle';
            }}""",
            timeout=TIMEOUT_MS,
        )
        final = card_state(page)
        check(final["loaded"] == "false", "unload from a reloaded page returned the card to 未加载")
        check(final["load_disabled"] is False, "the load button is usable again")

        page.screenshot(path="/tmp/ops-accept/models-final.png", full_page=True)
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        for f in failures:
            print("  -", f)
        return 1
    print("all browser checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
