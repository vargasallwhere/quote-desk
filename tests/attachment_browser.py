"""Loopback-only attachment walkthrough; all Gmail/order access mocked.

Run python3 tests/attachment_browser.py; --serve offers the same mock fixture
on 127.0.0.1:5072 for a local screenshot, never a public preview.
"""
import base64
import copy
import struct
import sys
import threading
import zlib
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alt_browser import fixture as order_fixture


def pdf():
    """A valid, three-page readable quote, without any generation dependency."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R /OpenAction 10 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R 5 0 R 7 0 R] /Count 3 >>"]
    for number in range(1, 4):
        content = (f"BT /F1 18 Tf 45 740 Td (MOCK VENDOR QUOTE - Page {number}) Tj "
                   "0 -40 Td (MacBook Air - 24 GB - 1 TB - Starlight) Tj "
                   "0 -40 Td (Requested keyboard: US English) Tj ET").encode()
        objects.extend([
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 9 0 R >> >> /Contents {len(objects)+2} 0 R >>".encode(),
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        ])
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /S /JavaScript /JS (parent.compromised=true) >>")
    result = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(result)
    result += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    result += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets[1:])
    return result + f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()


def png():
    def chunk(tag, data):
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data))
    width, height = 1200, 1800
    pixels = b"".join(b"\0" + bytes((230 if y % 100 < 5 else 255, 240, 245)) * width for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


@contextmanager
def fixture(port=0):
    with order_fixture(port) as (base, mode, writes, service):
        import app
        # Exercise a genuinely incomplete HTTP body, not just a mocked rejected
        # Response method. Navigational Download of the exact URL remains intact.
        original_wsgi = app.app.wsgi_app
        def interrupt_body(environ, start_response):
            if (mode.get("interrupt_body") and environ.get("PATH_INFO", "").startswith("/api/attachment/")
                    and environ.get("HTTP_X_ATTACHMENT_PREVIEW") == "1"):
                captured = {}
                def capture(status, headers, exc_info=None):
                    captured.update(status=status, headers=headers)
                result = original_wsgi(environ, capture)
                try:
                    data = b"".join(result)
                finally:
                    if hasattr(result, "close"):
                        result.close()
                start_response(captured["status"], captured["headers"])
                return [data[:20]]  # Leave the original, larger Content-Length.
            return original_wsgi(environ, start_response)
        app.app.wsgi_app = interrupt_body
        threads = service.users.return_value.threads.return_value
        original = threads.get.return_value.execute.return_value
        message = original["messages"][0]
        message["id"] = "18c921a6f52e4b0d"
        message["payload"]["parts"][0]["body"]["attachmentId"] = "ANGjdJ_" + "q7K2x-P9_" * 90
        earlier = copy.deepcopy(message)
        earlier["id"] = "18c921a6f52e4b0e"
        earlier["payload"]["parts"] = [
            {"mimeType": mime, "filename": name, "body": {"attachmentId": ident}}
            for ident, mime, name in [
                ("image", "image/png", "specification.png"),
                ("office", "application/msword", "vendor.doc"),
                ("html", "text/html", "active.html"),
                ("svg", "image/svg+xml", "active.svg"),
                ("fake", "application/pdf", "misleading.pdf"),
                ("broken", "image/png", "broken.png"),
                ("failure", "application/pdf", "unavailable.pdf"),
                ("slow", "application/pdf", "slow.pdf"),
                ("earlier-pdf", "application/pdf", "earlier-quote.pdf"),
                ("ANGjdJ_" + "m8K3z-Q6_" * 90, "application/pdf", "quote ∙ sample.pdf"),
            ]]
        original["messages"].insert(0, earlier)
        threads.list.return_value.execute.return_value = {"threads": [{"id": "threadTest"}, {"id": "second"}]}
        mode["release"] = threading.Event()
        mode["started"] = threading.Event()
        def get_attachment(**kwargs):
            def execute():
                ident = kwargs["id"]
                if ident == "failure" and not mode.get("recover"):
                    raise RuntimeError("mock failure")
                if ident == "slow":
                    mode["started"].set()
                    mode["release"].wait(10)
                data = {
                    "image": png(), "html": b"<script>parent.compromised=true</script>",
                    "svg": b'<svg xmlns="http://www.w3.org/2000/svg" onload="parent.compromised=true"/>',
                    "fake": b"<script>parent.compromised=true</script>",
                    "office": b"unsupported document", "broken": b"\x89PNG\r\n\x1a\ninvalid",
                }.get(ident, pdf())
                return {"data": base64.urlsafe_b64encode(data).decode()}
            return Mock(execute=execute)
        service.users.return_value.messages.return_value.attachments.return_value.get.side_effect = get_attachment
        try:
            yield base, mode, writes, service
        finally:
            mode["release"].set()
            app.app.wsgi_app = original_wsgi


def walkthrough():
    from playwright.sync_api import sync_playwright, expect
    with fixture() as (base, mode, writes, service), sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/repl/tools/bin/chromium", headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith((base + "/", "blob:")) else route.abort())
        context.add_init_script("""{
          const originalFetch = window.fetch;
          window.slowResponses = 0;
          window.fetch = async (url, options) => {
            const slow = String(url).includes('/slow?');
            const result = await originalFetch(url, slow ? {...options, signal: undefined} : options);
            if(slow) ++window.slowResponses;
            return result;
          };
          const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
          window.liveObjectURLs = new Set();
          URL.createObjectURL = blob => { const url=create(blob); liveObjectURLs.add(url); return url; };
          URL.revokeObjectURL = url => { liveObjectURLs.delete(url); revoke(url); };
        }""")
        page = context.new_page()
        errors, calls = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: calls.append((request.method, request.url)))
        page.goto(base + "/#US")
        expect(page.locator("#rbody")).to_be_visible()
        page.locator("#rbody").fill("My unsaved reply\nCompare all specifications.")
        page.locator("#rto").fill("edited@example.test")
        page.locator("#rcc").fill("copy@example.test")
        page.locator(".mh").first.click()
        original = page.locator("#thread").evaluate("(e) => { window.savedReply=document.getElementById('rbody'); return e.innerHTML; }")
        page.evaluate("window.scrollTo(0, 250)")
        previous_y = page.evaluate("scrollY")
        reads = len([url for method, url in calls if "/api/threads/" in url])
        page.locator('.att[data-name="quote.pdf"]').click()
        expect(page.locator(".av-pdf")).to_be_visible()
        expect(page.locator("#av-page")).to_have_text("Page 1 of 3")
        expect(page.locator("#av-feedback")).to_have_text("")
        assert not page.evaluate("window.compromised || false")
        assert page.locator(".av-pdf").evaluate("""e=>{
          const pixels=e.getContext('2d').getImageData(0,0,e.width,e.height).data;
          return pixels.some((v,i)=>i%4!==3 && v<100);
        }"""), "PDF must actually paint readable content, not merely mount a viewer"
        expect(page.locator("#av-name")).to_have_text("quote.pdf")
        assert len(context.pages) == 1
        assert page.url == base + "/#US"
        order = page.locator(".split > .panel").first.bounding_box()
        viewer = page.locator("#vendor-panel").bounding_box()
        stage = page.locator("#av-stage").bounding_box()
        assert viewer["x"] > order["x"] + order["width"]
        assert stage["width"] > 800 and stage["height"] > 500
        assert order["y"] < 150
        page.locator("#av-next").click()
        expect(page.locator("#av-page")).to_have_text("Page 2 of 3")
        page.locator("#av-prev").click()
        expect(page.locator("#av-page")).to_have_text("Page 1 of 3")
        page.locator("#av-actual").click()
        page.locator("#av-in").click()
        expect(page.locator("#av-zoom")).to_have_text("125%")
        page.locator("#av-fit").click()
        expect(page.locator("#av-zoom")).to_have_text("Fit width")
        expect(page.locator("#av-feedback")).to_have_text("")
        Path("generated-artifacts").mkdir(exist_ok=True)
        page.screenshot(path="generated-artifacts/attachment-pdf.jpg")
        # Explicit refresh changes the badge only; viewer and hidden composer remain intact.
        page.evaluate("refreshOrderStatus()")
        expect(page.locator(".av-pdf")).to_be_visible()
        page.locator("#av-back").click()
        assert page.evaluate("liveObjectURLs.size") == 0
        expect(page.locator("#rbody")).to_have_value("My unsaved reply\nCompare all specifications.")
        expect(page.locator("#rto")).to_have_value("edited@example.test")
        expect(page.locator("#rcc")).to_have_value("copy@example.test")
        assert page.evaluate("savedReply === document.getElementById('rbody')")
        restored = page.locator("#thread").evaluate("(e)=>e.innerHTML")
        # Playwright's fill helper can leave an empty inline style after cleanup.
        assert restored.replace(' style=""', "") == original.replace(' style=""', "")
        assert abs(page.evaluate("scrollY") - previous_y) < 3
        assert len([url for method, url in calls if "/api/threads/" in url]) == reads
        # Keyboard activation of a PDF in an earlier message stays in the same app.
        page.locator(".att").filter(has_text="earlier-quote.pdf").focus()
        page.keyboard.press("Enter")
        expect(page.locator("#av-page")).to_have_text("Page 1 of 3")
        assert page.url == base + "/#US" and len(context.pages) == 1
        page.locator("#av-back").click()
        page.locator('.att[data-name="quote ∙ sample.pdf"]').click()
        expect(page.locator("#av-page")).to_have_text("Page 1 of 3")
        expect(page.locator("#av-feedback")).to_have_text("")
        page.locator("#av-back").click()
        # Earlier-message image, real image scrolling and fit/zoom.
        page.locator(".att").filter(has_text="specification.png").click()
        expect(page.locator(".av-image")).to_be_visible()
        expect(page.locator("#av-pages")).to_be_hidden()
        expect(page.locator("#av-feedback")).to_have_text("")
        page.locator("#av-actual").click()
        assert page.locator(".av-image").evaluate("(e)=>e.clientWidth") == 1200
        assert page.locator("#av-stage").evaluate("(e)=>e.scrollHeight>e.clientHeight")
        page.locator("#av-stage").evaluate("(e)=>e.scrollTop=500")
        assert page.locator("#av-stage").evaluate("(e)=>e.scrollTop") == 500
        assert page.locator(".split > .panel").first.bounding_box()["y"] < 100
        page.locator("#av-fit").click()
        page.screenshot(path="generated-artifacts/attachment-image.jpg")
        with page.expect_download() as downloaded:
            page.locator("#av-download").click()
        assert downloaded.value.suggested_filename == "specification.png"
        for name in ("vendor.doc", "active.html", "active.svg", "misleading.pdf"):
            page.locator("#av-back").click()
            page.locator(".att").filter(has_text=name).click()
            expect(page.locator("#av-feedback")).to_contain_text("not available for this file format")
            expect(page.locator("#av-stage > *")).to_have_count(0)
            assert not page.evaluate("window.compromised || false")
        page.locator("#av-back").click()
        page.locator(".att").filter(has_text="broken.png").click()
        expect(page.locator("#av-feedback")).to_contain_text("could not be displayed")
        expect(page.locator("#av-retry")).to_be_visible()
        page.locator("#av-back").click()
        page.locator(".att").filter(has_text="unavailable.pdf").click()
        expect(page.locator("#av-feedback")).to_contain_text("Could not retrieve")
        mode["recover"] = True
        page.locator("#av-retry").click()
        expect(page.locator(".av-pdf")).to_be_visible()
        # Back while a response is pending; thread and PO switching clear it too.
        for action in ("back", "thread", "po"):
            page.locator("#av-back").click()
            if page.locator(".msg").first.get_attribute("data-open") != "true":
                page.locator(".mh").first.click()
            mode["started"].clear()
            mode["release"].clear()
            previous_responses = page.evaluate("slowResponses")
            page.locator(".att").filter(has_text="slow.pdf").click()
            expect(page.locator("#av-feedback")).to_contain_text("Loading")
            assert mode["started"].wait(2)
            if action == "back":
                page.locator("#av-back").click()
            elif action == "thread":
                page.evaluate("document.getElementById('ts').value='1'; document.getElementById('ts').dispatchEvent(new Event('change'))")
            else:
                page.locator("#add").fill("NEXT")
                page.locator("#add").press("Enter")
                expect(page.locator("#po")).to_have_text("NEXT")
            mode["release"].set()
            page.wait_for_function(f"slowResponses > {previous_responses}")
            expect(page.locator("#attachment-preview")).to_be_hidden()
            expect(page.locator("#av-stage > *")).to_have_count(0)
            # Re-open a fast attachment to set up the next iteration.
            page.locator(".att").filter(has_text="quote.pdf", has_not_text="earlier-quote.pdf").click()
            expect(page.locator(".av-pdf")).to_be_visible()
        page.locator("#av-back").click()
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator(".mh").first.click()
        page.locator(".att").filter(has_text="specification.png").click()
        expect(page.locator(".av-image")).to_be_visible()
        page.locator("#av-actual").click()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator("#av-stage").evaluate("(e)=>e.scrollWidth>e.clientWidth")
        page.locator("#av-stage").evaluate("(e)=>e.scrollLeft=0")
        assert page.locator(".av-image").bounding_box()["x"] >= page.locator("#av-stage").bounding_box()["x"]
        page.screenshot(path="generated-artifacts/attachment-mobile.jpg")
        page.locator("#av-back").focus()
        page.keyboard.press("Enter")
        expect(page.locator("#attachment-preview")).to_be_hidden()
        assert page.evaluate("liveObjectURLs.size") == 0
        assert page.evaluate("document.activeElement.classList.contains('att')")
        # Draft-only threads retain message attachments as well as the editable composer.
        full = service.users.return_value.threads.return_value.get.return_value.execute.return_value
        for message in full["messages"]:
            message["labelIds"] = ["DRAFT"]
        page.locator("#add").fill("DRAFT")
        page.locator("#add").press("Enter")
        expect(page.locator("#rsub")).to_be_visible()
        page.locator(".att").filter(has_text="quote.pdf", has_not_text="earlier-quote.pdf").click()
        expect(page.locator("#av-page")).to_have_text("Page 1 of 3")
        page.locator("#av-back").click()
        expect(page.locator("#rsub")).to_be_visible()
        assert not writes
        assert not [method for method, url in calls if method != "GET"]
        for action in ("create", "update", "send", "delete"):
            getattr(service.users.return_value.drafts.return_value, action).assert_not_called()
        assert not errors, errors
        browser.close()
        print("Attachment browser checks passed: PDF, image, comparison layout, scrolling, zoom, download, earlier message, Back DOM/reply/scroll restoration, unsupported/active formats, errors/retry, stale loads, PO/thread switching, status refresh, keyboard, mobile, no writes.")


if __name__ == "__main__":
    if "--serve" in sys.argv:
        with fixture(5072):
            print("Mock-only attachment fixture on 127.0.0.1:5072", flush=True)
            threading.Event().wait()
    else:
        walkthrough()
