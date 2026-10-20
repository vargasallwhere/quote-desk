"""Duplicate-free drafts, using only loopback and mocked services.

Run python3 tests/draft_browser.py. Only explicit saves may POST to Flask;
Gmail updates are mocked and their MIME content inspected. Screenshots are synthetic.
"""
import base64
import copy
import sys
import threading
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import Mock, patch

from attachment_browser import fixture, pdf


def message(ident, labels, text, attachments=None):
    return {
        "id": ident, "labels": labels, "text": text, "html": "",
        "from": "Vendor <vendor@example.test>", "to": "quotes@example.test",
        "cc": "copy@example.test", "reply_to": "", "subject": "164801-1-TEST",
        "date": "2026-10-20T12:00:00Z", "message_id": ident + "@example.test",
        "references": "", "attachments": attachments or [],
    }


PDF = {"id": "mock-pdf", "name": "quote.pdf", "type": "application/pdf"}
DRAFT_PDF = {"id": "draft-pdf", "name": "draft-spec.pdf", "type": "application/pdf"}
BODY = ("Hi Vendor,\n\nHope all is well!\n\nPlease quote:\n\nZ1M15P15164819W\n"
        'Apple 14" MacBook Pro M5 Pro - Space Black - 48 GB - 1 TB - UK English\n\n'
        "Enrolled in ABM: MOCK-ABM\n\nShipped to:\nTest Recipient\nLondon\nUnited Kingdom\n\nBest,\nSara")


def data():
    draft = message("request", ["DRAFT"], BODY, [DRAFT_PDF])
    reply = message("confirmation", ["DRAFT"], "Saved confirmation\n\nOn Monday vendor wrote:\nQuoted history", [DRAFT_PDF])
    vendor = message("vendor", ["INBOX"], "In stock. Quote attached.", [PDF])
    sent = message("sent", ["SENT"], "Earlier sent request")
    distinct = message("distinct", ["DRAFT"], "A distinct unsent request")
    threads = [
        {"id": "request-thread", "messages": [draft]},
        {"id": "confirmation-thread", "messages": [sent, vendor, reply]},
        {"id": "multiple-thread", "messages": [distinct, draft]},
        {"id": "waiting-thread", "messages": [draft, sent]},
        {"id": "noquote-thread", "messages": [message("noquote", ["INBOX"], "No quote yet"), reply]},
        {"id": "multiple-confirmation", "messages": [sent, vendor, distinct, reply]},
    ]
    return {"synced": 1, "threads": threads,
            "drafts": {"request": "gmail-request", "confirmation": "gmail-confirmation", "distinct": "gmail-distinct"}}


def walkthrough():
    from playwright.sync_api import sync_playwright, expect
    with fixture() as (base, mode, writes, service), sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/repl/tools/bin/chromium", headless=True,
                                    args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1050})
        original = data()
        posts, calls, errors, saved_messages = [], [], [], []
        stored = {}
        for ident, thread in (("gmail-request", "request-thread"),
                              ("gmail-confirmation", "confirmation-thread")):
            message_mime = EmailMessage()
            message_mime.set_content("Original saved draft")
            message_mime.add_attachment(pdf(), maintype="application", subtype="pdf",
                                        filename="draft-spec.pdf")
            stored[ident] = {"message": {"threadId": thread, "raw":
                            base64.urlsafe_b64encode(message_mime.as_bytes()).decode()}}
        drafts = service.users.return_value.drafts.return_value
        drafts.get.side_effect = lambda **kw: Mock(execute=lambda: stored[kw["id"]])

        def update(**kw):
            def execute():
                saved = kw["body"]["message"]
                parsed = BytesParser(policy=policy.default).parsebytes(
                    base64.urlsafe_b64decode(saved["raw"]))
                files = list(parsed.iter_attachments())
                assert len(files) == 1 and files[0].get_filename() == "draft-spec.pdf"
                assert files[0].get_payload(decode=True) == pdf(), "Saving must retain exact attachment bytes"
                saved_messages.append(parsed)
                stored[kw["id"]] = {"message": saved}
                return {"id": kw["id"]}
            return Mock(execute=execute)

        drafts.update.side_effect = update

        def route(r):
            url = r.request.url
            if not url.startswith(base + "/"):
                return r.abort()
            if r.request.method != "GET":
                assert url == base + "/api/draft", "Only explicit mocked saves are allowed"
                posts.append(r.request.post_data_json)
                return r.continue_()
            if "/api/threads/" in url:
                payload = copy.deepcopy(original)
                if url.endswith("/NEXT"):
                    payload["threads"] = [{"id": "next-thread", "messages": [
                        message("next", ["DRAFT"], "Next order draft")]}]
                    payload["drafts"] = {"next": "gmail-next"}
                return r.fulfill(json=payload)
            r.continue_()

        context.route("**/*", route)
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: calls.append((r.method, r.url)))
        page.goto(base + "/#UK")
        expect(page.locator("#rbody")).to_have_value(BODY)
        expect(page.locator("#msgs .msg")).to_have_count(0)
        assert page.locator("#msgs").bounding_box()["height"] == 0
        assert page.locator("#reply").evaluate("e=>getComputedStyle(e).borderTopWidth") == "0px"
        expect(page.locator("#reply")).to_contain_text("has not been sent")
        expect(page.locator("#rto")).to_have_value("quotes@example.test")
        expect(page.locator("#rcc")).to_have_value("copy@example.test")
        expect(page.locator("#rsub")).to_have_value("164801-1-TEST")
        expect(page.locator("#rsave")).to_be_visible()
        expect(page.locator("#rsend")).to_be_visible()
        Path("generated-artifacts").mkdir(exist_ok=True)
        page.screenshot(path="generated-artifacts/draft-only.jpg", full_page=True)

        def preserve_edits(body):
            page.locator("#rbody").fill(body)
            page.locator("#rto").fill("edited@example.test")
            page.locator("#rcc").fill("edited-copy@example.test")
            if page.locator("#rsub").count():
                page.locator("#rsub").fill("Edited subject")
            page.evaluate("window.savedEditor=document.getElementById('rbody')")
            reads = len([url for _, url in calls if "/api/threads/" in url])
            page.locator('#reply .att[data-name="draft-spec.pdf"]').click()
            expect(page.locator("#av-page")).to_have_text("Page 1 of 3")
            assert page.locator("canvas").evaluate("""e=>{
                const d=e.getContext('2d').getImageData(0,0,e.width,e.height).data;
                return d.some((v,i)=>i%4!==3&&v<100);
            }""")
            page.evaluate("refreshOrderStatus()")
            expect(page.locator("#order-status")).to_have_text("Quote In Progress")
            page.locator("#av-back").click()
            expect(page.locator("#rbody")).to_have_value(body)
            expect(page.locator("#rto")).to_have_value("edited@example.test")
            expect(page.locator("#rcc")).to_have_value("edited-copy@example.test")
            if page.locator("#rsub").count():
                expect(page.locator("#rsub")).to_have_value("Edited subject")
            assert page.evaluate("savedEditor===document.getElementById('rbody')")
            assert len([url for _, url in calls if "/api/threads/" in url]) == reads

        def arm_without_send():
            count = len(posts)
            page.locator("#rsend").click()
            expect(page.locator("#rsend")).to_have_text("Yes, send now")
            expect(page.locator("#rstat")).to_contain_text("edited@example.test")
            assert len(posts) == count

        preserve_edits("Unsaved request")
        assert not posts, "Loading, editing, preview and status checks must be read-only"
        arm_without_send()
        page.locator("#rsave").click()
        expect(page.locator("#rstat")).to_contain_text("Saved in Gmail")
        assert posts[-1] == {
            "threadId": "request-thread", "draftId": "gmail-request",
            "to": "edited@example.test", "cc": "edited-copy@example.test",
            "subject": "Edited subject", "body": "Unsaved request",
        }
        page.locator("#ts").select_option("1")
        expect(page.locator("#rbody")).to_have_value("Saved confirmation")
        expect(page.locator("#msgs .msg")).to_have_count(2)
        expect(page.locator("#msgs")).not_to_contain_text("Saved confirmation")
        expect(page.locator("#msgs .msg").last).to_have_attribute("data-open", "true")
        expect(page.locator("#msgs .msg").first).to_have_attribute("data-open", "false")
        expect(page.locator("#reply")).to_contain_text("UNSENT")
        expect(page.locator('#msgs .att[data-name="quote.pdf"]')).to_be_visible()
        page.locator('#msgs .att[data-name="quote.pdf"]').click()
        expect(page.locator("#av-page")).to_have_text("Page 1 of 3")
        page.locator("#av-back").click()
        page.locator("#msgs .mh").first.click()
        expect(page.locator("#msgs .msg").first.locator("pre")).to_be_visible()
        preserve_edits("Unsaved confirmation")
        arm_without_send()
        page.locator("#rsave").click()
        expect(page.locator("#rstat")).to_contain_text("Saved as a draft")
        saved = posts[-1]
        assert saved["draftId"] == "gmail-confirmation"
        assert saved["threadId"] == "confirmation-thread"
        assert saved["inReplyTo"] == "vendor@example.test"
        assert saved["body"].startswith("Unsaved confirmation\n\nOn ")

        for index in ("2", "5"):
            page.locator("#ts").select_option(index)
            expect(page.locator("#msgs")).to_contain_text("A distinct unsent request")
            expect(page.locator("#msgs .msg")).to_have_count(1 if index == "2" else 3)
            expect(page.locator("#msgs .msg").last).to_have_attribute("data-open", "true")
            expect(page.locator("#rbody")).to_have_value(BODY if index == "2" else "Saved confirmation")
        for index, note, body in (
            ("3", "Waiting on the vendor", BODY),
            ("4", "no confirmation is due yet", "Saved confirmation"),
        ):
            page.locator("#ts").select_option(index)
            expect(page.locator("#rbody")).to_have_count(0)
            expect(page.locator("#reply")).to_contain_text(note)
            expect(page.locator("#msgs")).to_contain_text(body)
            expect(page.locator("#msgs .msg")).to_have_count(2)
            draft_card = page.locator("#msgs .msg").filter(has_text=body)
            if draft_card.get_attribute("data-open") != "true":
                draft_card.locator(".mh").click()
            expect(draft_card.locator(".att")).to_be_visible()

        page.locator("#ts").select_option("0")
        expect(page.locator("#rbody")).to_have_value(BODY)
        page.locator("#rbody").fill("Must not leak to next order")
        page.locator("#add").fill("NEXT")
        page.locator("#add").press("Enter")
        expect(page.locator("#rbody")).to_have_value("Next order draft")
        expect(page.locator("#msgs .msg")).to_have_count(0)
        expect(page.locator("#rsend")).to_have_text("Send…")
        assert len(posts) == 2, "Only the two explicit mocked saves may write"
        assert len(saved_messages) == 2
        assert drafts.update.call_count == 2
        assert not writes and not errors, errors
        for action in ("create", "send", "delete"):
            getattr(service.users.return_value.drafts.return_value, action).assert_not_called()
        assert data() == original, "Fixtures and original thread data stay intact"
        browser.close()
        print("Draft browser checks passed: single bodies, distinct/noneditable drafts, sent/vendor history, "
              "attachments, expansion, exact save targets, explicit send confirmation, unsaved edits, switching, no live writes.")


if __name__ == "__main__":
    if "--serve" in sys.argv:
        import app
        from flask import jsonify
        # The screenshot fixture uses the same synthetic draft, server-side.
        # Real Gmail and order access remain blocked by the underlying fixture.
        payload = data()
        payload["threads"] = payload["threads"][:1]
        with fixture(5076), patch.dict(app.app.view_functions, {
            "threads": lambda po: jsonify(payload),
        }):
            print("Mock-only draft fixture on 127.0.0.1:5076", flush=True)
            threading.Event().wait()
    else:
        walkthrough()
