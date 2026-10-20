"""Local-only Chromium walkthrough. All service reads/writes are mocked; no public preview.

Run: python3 tests/alt_browser.py
Optional screenshot fixture: python3 tests/alt_browser.py --serve (127.0.0.1:5071).
"""
import os
import sys
import tempfile
import threading
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import requests
from test_alt_reviews import CONFIG, INFO, TEXT, response
from werkzeug.serving import make_server


@contextmanager
def fixture(port=0):
    with ExitStack() as stack:
        temp = stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.dict(os.environ, CONFIG, clear=True))
        stack.enter_context(patch.dict(app.app.config, {"ALT_REVIEW_DB": temp + "/browser.sqlite3"}))
        stack.enter_context(patch.object(app, "SCOUT", ""))
        def info(po):
            countries = {"US": "United States", "UK": "United Kingdom", "EU": "Ireland", "AU": "Australia"}
            return {**INFO, "order_number": po, "resolved_order_number": po,
                    "shipping_country": countries.get(po, "United States")}
        stack.enter_context(patch.object(app, "get_order_info_for_ticket", side_effect=info))
        stack.enter_context(patch.object(app, "fetch_full_order", side_effect=lambda po: {
            "order_number": po, "org_name": "Test Organization", "purchaser": {"name": "Test Buyer"},
            "status": "QUOTE_IN_PROGRESS", "status_checked_at": 1,
            "recipient": {"first_name": "Test", "last_name": "Recipient", "phone": "test-phone"},
            "order_items": [{"qty": 1, "name": "Apple MacBook Air", "mpn": "Z12345678"}],
        }))
        stack.enter_context(patch.object(app, "fetch_order_status", side_effect=lambda po: {
            "order_number": po, "status": "QUOTE_IN_PROGRESS", "status_checked_at": 1}))
        service = Mock()
        service.users.return_value.threads.return_value.list.return_value.execute.return_value = {"threads": [{"id": "threadTest"}]}
        service.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "threadTest", "historyId": "1", "messages": [{
                "id": "messageTest", "internalDate": "1", "labelIds": ["INBOX"],
                "payload": {"mimeType": "text/plain", "body": {},
                            "headers": [{"name": "From", "value": "vendor@example.test"},
                                        {"name": "Subject", "value": "Test quote"}],
                            "parts": [{"mimeType": "application/pdf", "filename": "quote.pdf",
                                       "body": {"attachmentId": "attTest"}}]},
            }],
        }
        service.users.return_value.drafts.return_value.list.return_value.execute.return_value = {"drafts": []}
        for action in ("create", "update", "send", "delete"):
            getattr(service.users.return_value.drafts.return_value, action).side_effect = AssertionError("Gmail write forbidden")
        stack.enter_context(patch.object(app, "gmail", return_value=service))
        stack.enter_context(patch.object(requests, "get", side_effect=AssertionError("External read forbidden")))
        mode = {"notification": 200, "creation": 201, "timeout": False}
        writes = []
        def post(url, **kwargs):
            writes.append((url, kwargs))
            if "api.airtable.com" in url:
                if mode["timeout"]:
                    raise requests.Timeout("mock timeout")
                return response({"id": "recBrowser", "fields": {"Status": "Open"}}, mode["creation"])
            if url == CONFIG["AUTOMATED_APPROVALS_WEBHOOK_URL"]:
                return response({}, mode["notification"])
            raise AssertionError("Unexpected external write")
        stack.enter_context(patch.object(requests, "post", side_effect=post))
        server = make_server("127.0.0.1", port, app.app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", mode, writes, service
        finally:
            server.shutdown()
            thread.join(5)


def walkthrough():
    from playwright.sync_api import sync_playwright, expect
    with fixture() as (base, mode, writes, gmail), sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/repl/tools/bin/chromium", headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        # Block every browser request outside the local fixture, including ticket links.
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base)
        page.locator("#add").fill("US")
        page.locator("#add").press("Enter")
        expect(page.locator("#bAlt")).to_be_visible()
        expect(page.locator("#bPr")).to_be_hidden()
        expect(page.locator("#bAr")).to_be_visible()
        page.locator("#rbody").fill("My unsaved vendor reply")
        page.locator("#bAlt").click()
        expect(page.locator("#apbox input[type=checkbox]")).to_have_count(2)
        page.locator("#apText").fill(TEXT)
        with context.expect_page() as opened:
            page.locator("#apGo").click()
        review = opened.value
        review.wait_for_load_state()
        expect(review.locator("#rv-submit-btn")).to_be_enabled()
        expect(review.locator("#rv-multi-skus")).to_be_checked()
        expect(review.locator("#rv-order")).to_have_text("US")
        expect(review.locator("#rv-notification-warning")).to_contain_text("customer notification")
        expect(page.locator("#rbody")).to_have_value("My unsaved vendor reply")
        assert not writes
        review.locator("#rv-model").fill("")
        review.locator("#rv-submit-btn").click()
        expect(review.locator("#rv-submit-status")).to_contain_text("required")
        assert not writes
        review.locator("#rv-model").fill("Edited MacBook Air")
        review.locator("#rv-requested-by").select_option("emma@allwhere.co")
        review.locator("#rv-price").fill("0")
        Path("generated-artifacts").mkdir(exist_ok=True)
        review.screenshot(path="generated-artifacts/alternative-review.jpg", full_page=True)
        review.locator("#rv-submit-btn").click()
        expect(review.locator("#rv-airtable-link")).to_be_visible()
        expect(review.locator("#rv-result-message")).to_contain_text("accepted")
        assert len(writes) == 2
        fields = writes[0][1]["json"]["fields"]
        assert fields["fldBoqiTT5plbMzvX"] == "Edited MacBook Air"
        assert fields["fldCDwjxPNuLMT0ub"] == [{"id": "usrEmma"}]
        review.reload()
        expect(review.locator("#rv-submit-btn")).to_be_disabled()
        expect(review.locator("#rv-airtable-link")).to_be_visible()
        assert len(writes) == 2

        # Regions with empty alternative text preserve source defaults without invented specs.
        for country, expected in (("UK", "UK"), ("EU", ""), ("AU", "UK")):
            page.locator("#add").fill(country)
            page.locator("#add").press("Enter")
            expect(page.locator("#po")).to_have_text(country)
            expect(page.locator("#bAlt")).to_be_visible()
            page.locator("#bAlt").click()
            with context.expect_page() as opened:
                page.locator("#apGo").click()
            regional = opened.value
            regional.wait_for_load_state()
            expect(regional.locator("#rv-submit-btn")).to_be_enabled()
            expect(regional.locator("#rv-country")).to_have_value(expected)
            expect(regional.locator("#rv-alt-type")).to_have_value("CTO device")
            expect(regional.locator("#rv-lead-time")).to_have_value("3-5 weeks")
            expect(regional.locator("#rv-model")).to_have_value("")
            regional.locator("#rv-alt-type").select_option("EOL device")
            expect(regional.locator("#rv-lead-time-row")).to_be_hidden()
            regional.locator("#rv-alt-type").select_option("CTO device")
            expect(regional.locator("#rv-lead-time")).to_have_value("3-5 weeks")
            regional.close()
        assert len(writes) == 2

        def new_filled_review():
            page.locator("#bAlt").click()
            page.locator("#apText").fill(TEXT)
            with context.expect_page() as opened:
                page.locator("#apGo").click()
            tab = opened.value
            tab.wait_for_load_state()
            expect(tab.locator("#rv-submit-btn")).to_be_enabled()
            return tab

        mode["notification"] = 500
        partial = new_filled_review()
        partial.locator("#rv-submit-btn").click()
        expect(partial.locator("#rv-airtable-link")).to_be_visible()
        expect(partial.locator("#rv-result-message")).to_contain_text("Do not create another ticket")
        expect(partial.locator("#rv-submit-btn")).to_be_disabled()
        mode["timeout"] = True
        uncertain = new_filled_review()
        uncertain.locator("#rv-submit-btn").click()
        expect(uncertain.locator("#rv-no-duplicate")).to_be_visible()
        expect(uncertain.locator("#rv-no-duplicate")).to_contain_text("Do not submit again")
        expect(uncertain.locator("#rv-submit-btn")).to_be_disabled()
        count = len(writes)
        uncertain.reload()
        expect(uncertain.locator("#rv-submit-btn")).to_be_disabled()
        assert len(writes) == count

        # Lost browser response after server success: one GET recovers the saved result, no second POST.
        mode.update(timeout=False, notification=200)
        lost = new_filled_review()
        def drop_after_write(route):
            route.fetch()
            route.abort()
        lost.route("**/submit", drop_after_write)
        lost.locator("#rv-submit-btn").click()
        expect(lost.locator("#rv-airtable-link")).to_be_visible()
        expect(lost.locator("#rv-submit-btn")).to_be_disabled()
        assert len(writes) == count + 2

        with patch.dict(os.environ, {"AIRTABLE_USER_IDS_JSON": "{}"}):
            missing = new_filled_review()
            expect(missing.locator("#rv-mapping-errors")).to_contain_text("unmapped")
            missing.locator("#rv-submit-btn").click()
            expect(missing.locator("#rv-submit-status")).to_contain_text("blocked")
            expect(missing.locator("#rv-submit-btn")).to_be_enabled()
        assert len(writes) == count + 2
        expired = context.new_page()
        expired.goto(base + "/alt-review?session=unknown")
        expect(expired.locator("#rv-state-message")).to_contain_text("check Airtable")
        expect(expired.locator("#rv-submit-btn")).to_be_disabled()
        for action in ("create", "update", "send", "delete"):
            getattr(gmail.users.return_value.drafts.return_value, action).assert_not_called()
        assert not errors, errors
        browser.close()
        print("Local browser checks passed: standalone regional flow, fields, edits, warning, no Gmail writes, success/reload, partial failure, ambiguity/recovery, configuration, expiry.")


if __name__ == "__main__":
    if "--serve" in sys.argv:
        with fixture(5071):
            print("Mock-only Quote Desk fixture listening on 127.0.0.1:5071", flush=True)
            threading.Event().wait()
    else:
        walkthrough()
