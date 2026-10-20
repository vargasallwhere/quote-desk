"""App-wide SKU fixture: loopback only, mock services, never external writes."""
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
    device = {"sku": "137", "qty": 1, "name": "Apple MacBook Test",
              "mpn": "", "mpn_source": "unavailable", "price": 100}
    warning = {"sku": "137", "status": "invalid_data", "quantity": 1,
               "mpn_source": "unavailable", "message": "The catalog returned invalid product data."}
    warranty = {"sku": "CARE", "qty": 2, "name": "Standalone warranty", "price": 55.7}
    order = {
        "order_number": "SKU-DEMO", "org_name": "Mock Organization",
        "purchaser": {"name": "Mock Buyer"}, "status": "QUOTE_IN_PROGRESS",
        "recipient": {"first_name": "Mock", "last_name": "Recipient"},
        "order_items": [copy.deepcopy(device) for _ in range(5)],
        "catalog_warnings": [copy.deepcopy(warning) for _ in range(5)],
        "warranty": {
            "devices": [{"sku": "137", "name": device["name"], "qty": 2, "plan": "Plan Alpha exact"},
                        {"sku": "137", "name": device["name"], "qty": 3, "plan": "Plan Beta exact"}],
            "lines": [warranty, {**warranty, "qty": 3}, {**warranty, "qty": 4, "price": 99}],
        },
    }
    info = {"order_number": "SKU-DEMO", "shipping_country": "United States",
            "items": [{"sku": "137", "product_name": device["name"], "quantity": q,
                       "protection_plan": plan, "price": 100, "mpn": ""}
                      for q, plan in [(2, "Plan Alpha exact"), (3, "Plan Beta exact")]] +
                     [{"sku": "", "product_name": "Unknown <product>", "quantity": 1},
                      {"sku": "", "product_name": "Unknown <product>", "quantity": 2}],
            "catalog_warnings": [{**warning, "quantity": 2}, {**warning, "quantity": 3}]}
    before = copy.deepcopy((order, info))
    with order_fixture(port) as (base, mode, writes, gmail):
        with patch.object(app, "fetch_full_order", return_value=order), \
                patch.object(app, "get_order_info_for_ticket", return_value=info), \
                patch("requests.sessions.Session.request", side_effect=AssertionError("Live network forbidden")):
            yield base
            assert (order, info) == before, "Display changed source data"
            assert not writes, "Approval writes forbidden"
            for action in ("create", "update", "send", "delete"):
                getattr(gmail.users.return_value.drafts.return_value, action).assert_not_called()
            gmail.users.return_value.messages.return_value.send.assert_not_called()


def walkthrough():
    from playwright.sync_api import sync_playwright, expect
    with fixture() as base, sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/repl/tools/bin/chromium",
                                    headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1150})
        context.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base + "/") else r.abort())
        page = context.new_page()
        errors, requests = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: requests.append((r.method, r.url)))
        page.goto(base + "/#SKU-DEMO")
        expect(page.locator("#rbody")).to_be_visible()
        page.locator("#rbody").fill("Keep my unsaved reply exactly")
        items = page.locator("#order .facts > div").filter(has=page.locator("dt", has_text="Items")).locator("dd")
        expect(items).to_contain_text("5x Apple MacBook Test")
        expect(items.locator(".err small")).to_have_count(1)
        expect(items.locator(".err")).to_have_text(
            "5x SKU 137: The catalog returned invalid product data.")
        warranty = page.locator("#order .facts > div").filter(has=page.locator("dt", has_text="Warranty")).locator("dd")
        for text in ("5x SKU 137", "2 × Apple MacBook Test", "Plan Alpha exact",
                     "3 × Apple MacBook Test", "Plan Beta exact", "9x SKU CARE",
                     "5x Standalone warranty", "$55.70", "4x Standalone warranty", "$99.00"):
            expect(warranty).to_contain_text(text)
        page.locator("#bAlt").click()
        expect(page.locator("#apbox input")).to_have_count(3)
        assert page.locator("#apbox input").evaluate_all("(nodes)=>nodes.map(n=>n.value)") == ["0", "2", "3"]
        expect(page.locator("#apbox")).to_contain_text("5x Apple MacBook Test")
        expect(page.locator("#apbox")).to_contain_text("2x Apple MacBook Test · Unit price $100 · Plan Alpha exact")
        expect(page.locator("#apbox")).to_contain_text("3x Apple MacBook Test · Unit price $100 · Plan Beta exact")
        expect(page.locator("#apbox .err")).to_have_text(
            "5x SKU 137: The catalog returned invalid product data.")
        assert page.locator("#apbox script").count() == 0
        expect(page.locator("#rbody")).to_have_value("Keep my unsaved reply exactly")
        assert page.evaluate("order.order_items.map(i=>i.qty)") == [1] * 5
        assert page.evaluate("tinfo.items.map(i=>i.quantity)") == [2, 3, 1, 2]
        # Quote-generation evidence remains separate and does not rerender the reply.
        page.evaluate("""showOrder(order, [{sku:"137", quantity:7, message:"Earlier quote lookup failed."}])""")
        expect(items).to_contain_text("Current-order catalog diagnostics:")
        expect(items).to_contain_text("Catalog diagnostics when the quote was generated:")
        expect(items).to_contain_text("7x SKU 137: Earlier quote lookup failed.")
        expect(page.locator("#rbody")).to_have_value("Keep my unsaved reply exactly")
        Path("generated-artifacts").mkdir(exist_ok=True)
        page.screenshot(path="generated-artifacts/sku-consolidation.png", full_page=True)
        assert not errors, errors
        assert all(method == "GET" for method, _ in requests), requests
        browser.close()
    print("SKU browser checks passed: five catalog failures, mixed quantities/plans/prices, original picker indices, escaping, immutable order, unsaved reply, no writes.")


if __name__ == "__main__":
    if "--serve" in sys.argv:
        with fixture(5075) as base:
            print(base + "/#SKU-DEMO", flush=True)
            threading.Event().wait()
    else:
        walkthrough()
