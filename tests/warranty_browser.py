"""Mock-only, loopback warranty display check; never connects to live services.

Run normally for Chromium assertions, or --serve for local screenshots on 5073.
"""
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
    warranty = {
        "name": "AppleCare+ - extended service agreement - 3 years",
        "sku": "MOCK-CARE-3", "qty": 1, "price": 55.70,
    }
    order = {
        "order_number": "WARRANTY-DEMO", "org_name": "Mock Organization",
        "purchaser": {"name": "Mock Buyer"}, "status": "QUOTE_IN_PROGRESS",
        "status_checked_at": 1, "recipient": {"first_name": "Mock", "last_name": "Recipient"},
        "order_items": [
            {"name": "Apple MacBook Air", "qty": 10, "mpn": "MOCK-MAC"},
            *[{"mpn": "MOCK-CARE", **copy.deepcopy(warranty)} for _ in range(10)],
        ],
        "warranty": {
            "devices": [
                {"name": "Apple MacBook Air", "plan": "Add protection plan", "qty": 10},
                {"name": "Dell Laptop", "plan": "Plan Alpha", "qty": 2},
            ],
            "lines": [copy.deepcopy(warranty) for _ in range(10)],
        },
    }
    before = copy.deepcopy(order)
    with order_fixture(port) as (base, mode, writes, gmail):
        with patch.object(app, "fetch_full_order", return_value=order), \
                patch("requests.sessions.Session.request", side_effect=AssertionError("Live network forbidden")):
            yield base
            assert order == before, "Display must not mutate source data"
            assert not writes, "Verification must not submit approvals"
            for action in ("create", "update", "send", "delete"):
                getattr(gmail.users.return_value.drafts.return_value, action).assert_not_called()
            gmail.users.return_value.messages.return_value.send.assert_not_called()


def walkthrough():
    from playwright.sync_api import sync_playwright, expect
    with fixture() as base, sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/repl/tools/bin/chromium", headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        context.route("**/*", lambda route: route.continue_()
                      if route.request.url.startswith(base + "/") else route.abort())
        page = context.new_page()
        errors, requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append((request.method, request.url)))
        page.goto(base + "/#WARRANTY-DEMO")
        section = page.locator("#order .facts > div").filter(
            has=page.locator("dt", has_text="Warranty")).locator("dd")
        expect(section.locator("b")).to_have_count(1)
        expect(section.locator("b")).to_have_text(
            "10x AppleCare+ - extended service agreement - 3 years")
        expect(section.locator("small")).to_have_text("SKU MOCK-CARE-3 · Unit price $55.70")
        expect(section.locator(".chip.ok")).to_have_text("Add protection plan")
        expect(section.locator(".chip.plain")).to_have_text("Plan Alpha")
        # Items now groups by SKU too, without changing the separate warranty rules.
        items = page.locator("#order .facts > div").filter(
            has=page.locator("dt", has_text="Items")).locator("dd")
        assert items.inner_text().count("AppleCare+") == 1
        expect(items).to_contain_text("10x AppleCare+")
        assert "qty 1" not in section.inner_text()
        Path("generated-artifacts").mkdir(exist_ok=True)
        page.screenshot(path="generated-artifacts/warranty-display.png", full_page=True)
        assert not errors, errors
        assert all(method == "GET" for method, _ in requests), requests
        browser.close()
    print("Warranty browser check passed: ten-unit display, badges, consolidated Items, no writes.")


if __name__ == "__main__":
    if "--serve" in sys.argv:
        with fixture(5073) as base:
            print(base + "/#WARRANTY-DEMO", flush=True)
            threading.Event().wait()
    else:
        walkthrough()
