"""Loopback-only depot walkthrough using real handlers and synthetic Gmail MIME."""
import copy
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import scout_port
from depot_notification import eligibility
from test_depot_notification import DepotTests, order, item, PO
from werkzeug.serving import make_server


@contextmanager
def fixture(port=0):
    case = DepotTests()
    case.setUp()
    try:
        orders = {po: order(po) for po in (PO, "SECOND-1-TEST", "FAIL-1-TEST", "REJECT-1-TEST", "DELAY-1-TEST")}
        orders["SECOND-1-TEST"]["orderItems"] = [item("SECOND", 3, "Synthetic Dell laptop", Memory="32GB")]
        def lookup(po):
            return copy.deepcopy(orders.get(po, order(po)))
        def catalog(variant, sku):
            snap = next((line["productVariantSnapshot"] for o in orders.values() for line in o["orderItems"]
                         if line["productVariantId"] == variant), item()["productVariantSnapshot"])
            return {"found": True, "status": "ok", "sku": snap["sku"], "mpn": snap["mpn"],
                    "product_name": snap["title"], "attributes": snap["attributes"],
                    "price_charged": 912.34, "is_build_to_order": False}
        case.stack.enter_context(patch.object(scout_port, "fetch_allwhere_order", side_effect=lookup))
        case.stack.enter_context(patch.object(scout_port, "_ps_variant", side_effect=catalog))
        case.stack.enter_context(patch.object(app, "get_order_info_for_ticket", return_value={}))
        case.stack.enter_context(patch.object(app, "fetch_order_status", side_effect=lambda po: {
            "order_number": po, "status": "SHIPPED", "status_checked_at": 2}))
        vendor = {"id": "vendor-thread", "messages": [{
            "id": "vendor-message", "internalDate": "1", "labelIds": ["INBOX"],
            "payload": {"mimeType": "text/plain", "body": {}, "headers": [
                {"name": "From", "value": "vendor@example.test"}, {"name": "Subject", "value": "Synthetic quote"}],
                "parts": [{"mimeType": "application/pdf", "filename": "mock.pdf", "body": {"attachmentId": "file"}}]}}]}
        original_list = case.fake.list_threads
        original_get = case.fake.get_thread
        case.fake.threads.list.return_value.execute.side_effect = lambda: {
            "threads": [{"id": "vendor-thread"}, *original_list()["threads"]]}
        case.fake.threads.get.return_value.execute.side_effect = lambda: (
            copy.deepcopy(vendor) if case.fake.threads.get.call_args.kwargs["id"] == "vendor-thread" else original_get())
        server = make_server("127.0.0.1", port, app.app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", case, orders
        finally:
            server.shutdown()
            thread.join(5)
    finally:
        case.stack.close()


def walkthrough():
    from playwright.sync_api import sync_playwright, expect
    with fixture() as (base, case, orders), sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/repl/tools/bin/chromium", headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        context.route("**/*", lambda route: route.continue_()
                      if route.request.url.startswith(base + "/") else route.abort())
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        def select(po):
            page.locator("#add").fill(po)
            page.locator("#add").press("Enter")
            expect(page.locator("#po")).to_have_text(po)
            expect(page.locator("#depot-open")).to_be_visible()
            expect(page.locator("#rbody")).to_be_visible()
        def review():
            page.locator("#depot-open").click()
            expect(page.locator("#depot-body")).to_be_enabled()
        page.goto(base + "/#" + PO)
        expect(page.locator("#depot-order-banner")).to_contain_text("Destination: allwhere storage Australia")
        expect(page.locator("#rbody")).to_be_visible()
        page.locator("#rbody").fill("Unsaved vendor reply — keep exactly")
        page.locator("#depot-open").focus()
        page.keyboard.press("Enter")
        expect(page.locator("#depot-body")).to_be_enabled()
        expect(page.locator("#depot-back")).to_be_focused()
        assert page.locator("#depot-review").bounding_box()["width"] >= 1100
        expect(page.locator("#depot-subject")).to_have_value(PO + " - Order coming to warehouse")
        expect(page.locator("#depot-to")).to_have_value(__import__("depot_notification").TO)
        assert page.locator("#depot-to").get_attribute("readonly") is not None
        assert case.fake.drafts.create.call_count == case.fake.drafts.send.call_count == 0
        page.locator("#depot-body").fill("My reviewed physical devices\n\nBest,\nSara")
        page.locator("#depot-back").click()
        expect(page.locator("#depot-open")).to_be_focused()
        expect(page.locator("#rbody")).to_have_value("Unsaved vendor reply — keep exactly")
        review()
        expect(page.locator("#depot-body")).to_have_value("My reviewed physical devices\n\nBest,\nSara")
        page.evaluate("refreshOrderStatus()")
        expect(page.locator("#depot-body")).to_have_value("My reviewed physical devices\n\nBest,\nSara")
        page.locator("#depot-save").evaluate("(b) => { b.click(); b.click(); }")
        expect(page.locator("#depot-state-badge")).to_have_text("DRAFT SAVED")
        assert case.fake.drafts.create.call_count == 1
        page.locator("#depot-back").click()
        review()
        assert case.fake.drafts.create.call_count == 1
        page.locator("#depot-send").click()
        expect(page.locator("#depot-confirm")).to_be_visible()
        assert case.fake.drafts.send.call_count == 0
        page.locator("#depot-subject").fill("Edited exact subject")
        expect(page.locator("#depot-confirm")).to_be_hidden()
        page.locator("#depot-send").click()
        Path("generated-artifacts").mkdir(exist_ok=True)
        page.screenshot(path="generated-artifacts/depot-review-desktop.jpg", full_page=True)
        page.locator("#depot-confirm-send").evaluate("(b) => { b.click(); b.click(); }")
        expect(page.locator("#depot-state-badge")).to_have_text("SENT")
        assert case.fake.drafts.send.call_count == 1
        page.locator("#depot-back").click()
        select("SECOND-1-TEST")
        review()
        expect(page.locator("#depot-body")).to_have_value(re.compile("3X TEST-MPN"))
        expect(page.locator("#depot-body")).to_have_value(re.compile("Synthetic Dell laptop"))
        expect(page.locator("#depot-subject")).to_have_value("SECOND-1-TEST - Order coming to warehouse")
        page.locator("#depot-body").fill("SECOND unsaved")
        page.locator("#depot-back").click()
        select(PO)
        expect(page.locator("#rbody")).to_have_value("Unsaved vendor reply — keep exactly")
        page.locator("#depot-open").click()
        expect(page.locator("#depot-state-badge")).to_have_text("SENT")
        expect(page.locator("#depot-send")).to_be_disabled()
        page.locator("#depot-back").click()
        select("SECOND-1-TEST")
        review()
        expect(page.locator("#depot-body")).to_have_value("SECOND unsaved")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        expect(page.locator("#depot-to")).to_be_visible()
        page.screenshot(path="generated-artifacts/depot-review-phone.jpg", full_page=True)
        page.locator("#depot-back").click()
        page.set_viewport_size({"width": 1440, "height": 1100})
        select("FAIL-1-TEST")
        review()
        case.fake.mode = "send-timeout"
        page.locator("#depot-send").click()
        page.locator("#depot-confirm-send").click()
        expect(page.locator("#depot-state-badge")).to_have_text("CHECK GMAIL")
        expect(page.locator("#depot-status")).to_contain_text("uncertain")
        expect(page.locator("#depot-send")).to_be_disabled()
        sent_count = case.fake.drafts.send.call_count
        page.locator("#depot-back").click()
        page.locator("#depot-open").click()
        expect(page.locator("#depot-send")).to_be_disabled()
        assert case.fake.drafts.send.call_count == sent_count
        page.locator("#depot-back").click()
        select("REJECT-1-TEST")
        review()
        case.fake.mode = "send-rejected"
        page.locator("#depot-send").click()
        page.locator("#depot-confirm-send").click()
        expect(page.locator("#depot-status")).to_contain_text("failed")
        expect(page.locator("#depot-state-badge")).to_have_text("DRAFT SAVED")
        expect(page.locator("#depot-send")).to_be_enabled()
        case.fake.mode = ""
        # Preview failure, close/reopen while a preview is delayed, and order switching.
        page.locator("#depot-back").click()
        select("DELAY-1-TEST")
        held = []
        page.route("**/api/depot-preview/DELAY-1-TEST", lambda route: held.append(route))
        page.locator("#depot-open").click()
        expect(page.locator("#depot-save")).to_be_disabled()
        page.wait_for_function("document.getElementById('depot-status').textContent.includes('Loading')")
        page.locator("#depot-back").click()
        page.locator("#depot-open").click()
        select("SECOND-1-TEST")
        held[0].continue_()
        review()
        expect(page.locator("#depot-body")).to_have_value("SECOND unsaved")
        page.locator("#depot-back").click()
        select("DELAY-1-TEST")
        page.locator("#depot-open").click()
        expect(page.locator("#depot-body")).to_be_enabled()
        expect(page.locator("#depot-subject")).to_have_value("DELAY-1-TEST - Order coming to warehouse")
        # A new page reopens a saved draft from Gmail, not a new draft.
        reopened = context.new_page()
        reopened.goto(base + "/#REJECT-1-TEST")
        reopened.locator("#depot-open").click()
        expect(reopened.locator("#depot-state-badge")).to_have_text("DRAFT SAVED")
        expect(reopened.locator("#depot-body")).to_be_enabled()
        page.locator("#depot-back").click()
        select("WRITE-1-TEST")
        review()
        pending = []
        page.route("**/api/depot-save", lambda route: pending.append(route))
        page.locator("#depot-save").click()
        expect(page.locator("#depot-save")).to_be_disabled()
        page.locator("#depot-back").click()
        select("SECOND-1-TEST")
        pending[0].continue_()
        review()
        expect(page.locator("#depot-body")).to_have_value("SECOND unsaved")
        page.unroute("**/api/depot-save")
        page.locator("#depot-back").click()
        select("WRITE-1-TEST")
        page.locator("#depot-open").click()
        expect(page.locator("#depot-state-badge")).to_have_text("DRAFT SAVED")
        expect(page.locator("#depot-send")).to_be_enabled()
        page.locator("#depot-back").click()
        select("BROKEN-1-TEST")
        page.route("**/api/depot-preview/BROKEN-1-TEST", lambda route: route.fulfill(
            status=502, content_type="application/json", body='{"error":"Mock preview unavailable"}'))
        page.locator("#depot-open").click()
        expect(page.locator("#depot-status")).to_contain_text("Mock preview unavailable")
        expect(page.locator("#depot-send")).to_be_disabled()
        page.unroute("**/api/depot-preview/BROKEN-1-TEST")
        page.get_by_role("button", name="Retry preview", exact=True).click()
        expect(page.locator("#depot-body")).to_be_enabled()
        before_confirm_failure = case.fake.drafts.send.call_count
        page.route("**/api/depot-confirm", lambda route: route.abort())
        page.locator("#depot-send").click()
        page.locator("#depot-confirm-send").click()
        expect(page.locator("#depot-status")).to_contain_text("Nothing was sent")
        expect(page.locator("#depot-send")).to_be_enabled()
        assert case.fake.drafts.send.call_count == before_confirm_failure
        assert not errors, errors
        browser.close()
    print("Depot browser passed: exact review, keyboard/phone, mocked save/send, reuse, failure/uncertainty, late responses, order isolation and retained vendor reply.")


if __name__ == "__main__":
    if "--serve" in sys.argv:
        with fixture(5078) as (base, case, orders):
            print(base + "/#" + PO, flush=True)
            threading.Event().wait()
    else:
        walkthrough()
