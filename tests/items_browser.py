"""Mock-only loopback check of eight repeated MacBooks; no live reads or writes."""
import copy
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from alt_browser import fixture as order_fixture


@contextmanager
def fixture(port=0):
    device = {
        "sku": "MOCK-MAC", "qty": 1,
        "name": "Apple MacBook Pro 14-inch M4 Pro 24GB 512GB Space Black US English",
        "mpn": "MC123LL/A", "mpn_source": "catalog",
    }
    order = {
        "order_number": "ITEMS-DEMO", "org_name": "Mock Organization",
        "purchaser": {"name": "Mock Buyer"}, "status": "QUOTE_IN_PROGRESS",
        "status_checked_at": 1, "recipient": {"first_name": "Mock", "last_name": "Recipient"},
        "order_items": [copy.deepcopy(device) for _ in range(8)],
        "warranty": {"devices": [{"name": device["name"], "plan": "Add protection plan", "qty": 8}],
                     "lines": []},
    }
    before = copy.deepcopy(order)
    with order_fixture(port) as (base, mode, writes, gmail):
        with patch.object(app, "fetch_full_order", return_value=order), \
                patch("requests.sessions.Session.request", side_effect=AssertionError("Live network forbidden")):
            yield base, order
            assert order == before, "Display must not mutate source data"
            assert not writes, "Verification must not submit approvals"
            for action in ("create", "update", "send", "delete"):
                getattr(gmail.users.return_value.drafts.return_value, action).assert_not_called()
            gmail.users.return_value.messages.return_value.send.assert_not_called()


def walkthrough():
    from playwright.sync_api import sync_playwright, expect
    with fixture() as (base, order), sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/repl/tools/bin/chromium", headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        context.route("**/*", lambda route: route.continue_()
                      if route.request.url.startswith(base + "/") else route.abort())
        page = context.new_page()
        errors, requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append((request.method, request.url)))
        page.goto(base + "/#ITEMS-DEMO")
        items = page.locator("#order .facts > div").filter(
            has=page.locator("dt", has_text="Items")).locator("dd")
        expect(items).to_contain_text("8x Apple MacBook Pro")
        expect(items.locator("small")).to_have_count(1)
        expect(items.locator("small")).to_have_text("MC123LL/A")
        assert items.inner_text().count("Apple MacBook Pro") == 1
        for spec in ("M4 Pro", "24GB", "512GB", "Space Black", "US English", "14-inch"):
            expect(items).to_contain_text(spec)
        page.get_by_role("button", name="Memory", exact=True).click()
        expect(items.locator(".hl-mem")).to_have_css("background-color", "rgb(230, 217, 255)")
        expect(items.locator(".hl-mem")).to_be_visible()
        warranty = page.locator("#order .facts > div").filter(
            has=page.locator("dt", has_text="Warranty")).locator("dd")
        expect(warranty).to_contain_text("8 × Apple MacBook")
        expect(warranty.locator(".chip.ok")).to_have_text("Add protection plan")
        # The global order used by composer/approvals still contains all eight lines.
        assert page.evaluate("order.order_items.length") == 8
        assert page.evaluate("order.order_items.map(i => i.qty)") == [1] * 8
        expect(page.locator("#rbody")).to_be_visible()
        page.locator("#rbody").fill("Unsaved mock reply")
        page.get_by_role("button", name="MPN", exact=True).click()
        expect(page.locator("#rbody")).to_have_value("Unsaved mock reply")
        expect(items.locator(".hl-mpn")).to_be_visible()
        Path("generated-artifacts").mkdir(exist_ok=True)
        page.screenshot(path="generated-artifacts/items-display.png", full_page=True)
        assert not errors, errors
        assert all(method == "GET" for method, _ in requests), requests
        browser.close()
    print("Items browser check passed: one 8x MacBook, readable highlighted specs/MPN, unchanged warranty/source/reply, no writes.")


if __name__ == "__main__":
    if "--serve" in sys.argv:
        with fixture(5074) as (base, order):
            print(base + "/#ITEMS-DEMO", flush=True)
            threading.Event().wait()
    else:
        walkthrough()
