"""Loopback-only launch regressions; actual Flask session creation, mocked services."""
import sys
import os
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from alt_browser import fixture
from test_alt_reviews import TEXT
from playwright.sync_api import sync_playwright, expect
import app
import alt_reviews


def run():
    with fixture() as (base, mode, writes, gmail), sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/repl/tools/bin/chromium",
                                    args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        context.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base + "/") else r.abort())
        launches = []
        context.on("request", lambda r: launches.append(r.post_data_json)
                   if r.method == "POST" and r.url == base + "/api/alt-review" else None)
        page = context.new_page()
        page.goto(base + "/#US")
        page.locator("#rbody").fill("Keep this unsaved vendor edit")
        page.locator("#bAlt").click()
        page.locator('#apbox input[value="0"]').uncheck()
        page.locator("#apText").fill(TEXT)
        def missing_script(route):
            route.abort()
        context.route("**/alt-review-assets/alt-review.js", missing_script)
        with context.expect_page() as opened:
            page.locator("#apGo").click()
        tab = opened.value
        expect(tab.locator("#rv-load-help")).to_be_visible()
        expect(tab.locator("#rv-submit-btn")).to_be_disabled()
        # Before the repair this says "Review tab opened" despite a disabled empty form.
        expect(page.locator("#apStat")).to_contain_text("could not confirm", timeout=15000)
        expect(page.locator("#apRecover")).to_be_visible()
        saved_url = page.locator("#apRecover").get_attribute("href")
        assert len(launches) == 1
        context.unroute("**/alt-review-assets/alt-review.js", missing_script)
        with context.expect_page() as recovered:
            page.locator("#apGo").click()
        review = recovered.value
        expect(review.locator("#rv-order")).to_have_text("US")
        expect(review.locator("#rv-req-sku")).to_have_value("202")
        expect(review.locator("#rv-model")).to_have_value("MacBook Air")
        expect(review.locator("#rv-memory")).to_have_value("24 GB")
        expect(page.locator("#apStat")).to_contain_text("Review ready")
        assert review.url == saved_url
        assert len(launches) == 1
        expect(page.locator("#apText")).to_have_value(TEXT)
        expect(page.locator('#apbox input[value="0"]')).not_to_be_checked()
        expect(page.locator("#rbody")).to_have_value("Keep this unsaved vendor edit")
        assert not writes

        # Navigation is independently recoverable, even when the real window exists
        # but a browser restriction rejects the location assignment.
        page.locator("#apText").fill("")
        page.evaluate("""() => {
          window.realOpen = window.open;
          window.open = (...args) => {
            const tab = window.realOpen(...args);
            window.waitingTab = tab;
            return {
              set opener(value) {tab.opener=value},
              set location(value) {throw new DOMException('navigation blocked','SecurityError')},
              get location() {return tab.location},
              get document() {return tab.document},
              get closed() {return tab.closed},
              close() {tab.close()}
            };
          };
        }""")
        with context.expect_page() as waiting:
            page.locator("#apGo").click()
        expect(page.locator("#apStat")).to_contain_text("could not navigate")
        expect(waiting.value.locator("body")).to_contain_text("return to the original Quote Desk")
        count = len(launches)
        page.evaluate("() => { window.open=window.realOpen; }")
        assert page.locator("#apRecover").get_attribute("href").startswith(base + "/alt-review?session=")
        with context.expect_page() as manual:
            page.locator("#apRecover").click()
        expect(manual.value.locator("#rv-order")).to_have_text("US")
        expect(manual.value.locator("#rv-req-sku")).to_have_value("202")
        expect(manual.value.locator("#rv-model")).to_have_value("")
        assert len(launches) == count

        # The actual server saved a session but the response was lost. The retry
        # repeats the same launch ID and returns that session, not a duplicate.
        page.locator("#apText").fill(TEXT + " lost response")
        saved = []
        def lose_creation_response(route):
            saved.append(route.fetch().json()["url"])
            route.abort()
        page.route("**/api/alt-review", lose_creation_response)
        with context.expect_page():
            page.locator("#apGo").click()
        expect(page.locator("#apStat")).to_contain_text("Could not open")
        first_key = launches[-1]["launch_id"]
        page.unroute("**/api/alt-review", lose_creation_response)
        with context.expect_page() as retry:
            page.locator("#apGo").click()
        expect(retry.value.locator("#rv-model")).to_have_value("MacBook Air")
        expect(page.locator("#apStat")).to_contain_text("Review ready")
        assert retry.value.url == base + saved[0]
        assert launches[-1]["launch_id"] == first_key
        with app.app.app_context(), alt_reviews.database() as db:
            assert db.execute("SELECT count(*) FROM reviews").fetchone()[0] == 3
        expect(page.locator("#rbody")).to_have_value("Keep this unsaved vendor edit")
        assert not writes
        browser.close()
        print("Saved-session launch recovery passed.")


def reported_origin_recovery():
    """Real local TLS windows, synthetic published Origin/internal Host boundary."""
    with fixture(proxy=True) as (base, mode, writes, gmail), sync_playwright() as p:
        mode["reported_origin"] = "https://quote-desk-sara455.replit.app"
        app.app.config.update(ALT_REVIEW_EXTERNAL_ORIGIN=None, ALT_REVIEW_PUBLIC_ORIGIN=None)
        browser = p.chromium.launch(executable_path="/repl/tools/bin/chromium", args=["--no-sandbox"])
        context = browser.new_context(viewport={"width":1440,"height":1100}, ignore_https_errors=True)
        context.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base + "/") else r.abort())
        page = context.new_page()
        launches, errors = [], []
        context.on("page", lambda tab: tab.on("pageerror", lambda e: errors.append(str(e))))
        context.on("request", lambda r: launches.append(r.post_data_json)
                   if r.method=="POST" and r.url==base+"/api/alt-review" else None)
        page.goto(base + "/#US")
        page.locator("#rbody").fill("Unsaved reply during origin recovery")
        page.locator("#bAlt").click()
        page.locator('#apbox input[value="0"]').uncheck()
        page.locator("#apText").fill("test")
        with context.expect_page() as denied:
            page.locator("#apGo").click()
        expect(page.locator("#apStat")).to_contain_text("Address configuration failed (HTTP 403)")
        expect(page.locator("#apGo")).to_be_enabled()
        assert denied.value.is_closed()
        expect(page.locator('#apbox input[value="0"]')).not_to_be_checked()
        expect(page.locator("#apText")).to_have_value("test")
        with app.app.app_context(), alt_reviews.database() as db:
            assert db.execute("SELECT count(*) FROM reviews").fetchone()[0] == 0
        # Change independently controlled configuration, not forwarded/header trust.
        app.app.config["ALT_REVIEW_PUBLIC_ORIGIN"] = mode["reported_origin"]
        with patch.dict(os.environ, {"AIRTABLE_PAT":""}):
            with context.expect_page() as opened:
                page.locator("#apGo").click()
            review = opened.value
            expect(review.locator("#rv-order")).to_have_text("US")
            expect(review.locator("#rv-req-sku")).to_have_value("202")
            expect(review.locator("#rv-model")).to_have_value("")
            expect(review.locator("#rv-errors")).to_contain_text("AIRTABLE_PAT")
            expect(page.locator("#apStat")).to_contain_text("Review ready")
        assert launches[0] == launches[1]  # includes identical retry identity.
        assert launches[-1]["items"] == [2]
        assert launches[-1]["text"] == "test"
        page.locator("#apText").fill(TEXT)
        with context.expect_page() as pasted:
            page.locator("#apGo").click()
        expect(pasted.value.locator("#rv-model")).to_have_value("MacBook Air")
        expect(pasted.value.locator("#rv-memory")).to_have_value("24 GB")
        expect(page.locator("#apStat")).to_contain_text("Review ready")
        assert pasted.value.locator(".page-shell").bounding_box()["width"] >= 1100
        Path("generated-artifacts").mkdir(exist_ok=True)
        pasted.value.screenshot(path="generated-artifacts/alternative-origin-recovery.jpg", full_page=True)
        # Session GET failure reports load stage and retry opens the existing session.
        def failed_get(route):
            route.fulfill(status=503, body="unavailable")
        context.route("**/api/alt-review/*", failed_get)
        count = len(launches)
        with context.expect_page() as failed:
            page.locator("#apGo").click()
        expect(failed.value.locator("#rv-state-message")).to_contain_text("could not load")
        expect(page.locator("#apStat")).to_contain_text("saved review could not load")
        context.unroute("**/api/alt-review/*", failed_get)
        with context.expect_page() as fixed:
            page.locator("#apGo").click()
        expect(fixed.value.locator("#rv-model")).to_have_value("MacBook Air")
        expect(page.locator("#apStat")).to_contain_text("Review ready")
        assert len(launches) == count
        expect(page.locator("#rbody")).to_have_value("Unsaved reply during origin recovery")
        assert mode["proxy_facts"] == {"origin":mode["reported_origin"],"scheme":"http","host":"internal.test:5000"}
        assert not writes and not errors
        for action in ("create","update","send","delete"):
            getattr(gmail.users.return_value.drafts.return_value, action).assert_not_called()
        browser.close()
        print("Reported-origin rejection/recovery and populated review passed, loopback only.")


if __name__ == "__main__":
    reported_origin_recovery()
    run()
