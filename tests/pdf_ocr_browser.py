"""Image-only PDF regression with real, local OCR and synthetic quote pixels.

No customer files, network services, Gmail writes or external browser requests.
"""
import base64
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from attachment_browser import fixture


def scanned_pdf(jpeg):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
    ]
    for _ in range(2):
        content = b"q 600 0 0 300 0 0 cm /Scan Do Q"
        objects.extend([
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 300] "
             f"/Resources << /XObject << /Scan 7 0 R >> >> /Contents {len(objects)+2} 0 R >>").encode(),
            f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
        ])
    objects.append(
        f"<< /Type /XObject /Subtype /Image /Width 1200 /Height 600 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg)} >>\nstream\n".encode()
        + jpeg + b"\nendstream")
    result = b"%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(result)
    result += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    result += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return result + (f"trailer << /Size {len(offsets)} /Root 1 0 R >>\n"
                     f"startxref\n{xref}\n%%EOF\n").encode()


def walkthrough(serve=False):
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/repl/tools/bin/chromium",
                                    headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1600, "height": 1050})
        page = context.new_page()
        # Rasterize synthetic text, then embed only the JPEG (no PDF text/font).
        image = page.evaluate("""() => {
          const c=document.createElement('canvas'); c.width=1200; c.height=600;
          const x=c.getContext('2d'); x.fillStyle='white'; x.fillRect(0,0,1200,600);
          x.fillStyle='black'; x.font='36px Arial';
          ['MOCK SCANNED VENDOR QUOTE', 'MacBook Pro M5',
           '32GB RAM - 1TB SSD - Silver', 'US English keyboard - 14 in',
           'M3XE4X/A'].forEach((s,i)=>x.fillText(s,60,80+i*85));
          return c.toDataURL('image/jpeg', 0.98).split(',')[1];
        }""")
        scan = scanned_pdf(base64.b64decode(image))
        with patch("attachment_browser.pdf", lambda: scan), fixture(5077 if serve else 0) as (base, mode, writes, service):
            external, calls, errors = [], [], []
            def route_request(route):
                if route.request.url.startswith((base + "/", "blob:")):
                    route.continue_()
                else:
                    external.append(route.request.url)
                    route.abort()
            context.route("**/*", route_request)
            context.on("request", lambda request: calls.append((request.method, request.url)))
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/#US")
            expect(page.locator("#rbody")).to_be_visible()
            page.locator("#rbody").fill("Unsaved reply survives OCR")
            page.evaluate("window.savedReply=document.getElementById('rbody')")
            page.locator('.att[data-name="quote.pdf"]').click()
            expect(page.locator("#av-page")).to_have_text("Page 1 of 2")
            expect(page.locator("#av-matches")).to_contain_text("No readable text")
            expect(page.locator("#av-ocr")).to_be_visible()
            assert not [url for _, url in calls if "/attachment-ocr/" in url]
            page.locator("#av-ocr").click()
            expect(page.locator("#av-matches")).to_contain_text("Local OCR", timeout=90000)
            assert [url for _, url in calls if "/eng.traineddata.gz" in url]
            for key in ("cpu", "mem", "ssd", "color", "kb", "size", "mpn"):
                assert page.locator(f".av-ocr-mark.hl-{key}").count(), key
                button = page.locator(f'.legend button[data-k="{key}"]')
                if button.get_attribute("aria-pressed") != "true":
                    button.click()
                expect(page.locator("#av-matches")).to_contain_text("highlighted match")
                assert page.locator(f".av-ocr-mark.hl-{key}").first.evaluate(
                    "e=>getComputedStyle(e).backgroundColor") != "rgba(0, 0, 0, 0)"
            page.locator('.legend button[data-k="mem"]').click()
            expect(page.locator("#av-matches")).to_contain_text("Memory: 1 highlighted match")
            ocr_requests = len([url for _, url in calls if "/attachment-ocr/" in url])
            for control in ("#av-actual", "#av-in", "#av-fit"):
                page.locator(control).click()
                expect(page.locator("#av-feedback")).to_have_text("")
                expect(page.locator("#av-matches")).to_contain_text("Local OCR")
                # Accurate bbox over printed pixels after zoom, not just in-page.
                assert page.locator(".av-ocr-mark.hl-mem").first.evaluate("""e=>{
                  const r=e.getBoundingClientRect(), c=document.querySelector('.av-pdf');
                  const b=c.getBoundingClientRect(), sx=c.width/b.width, sy=c.height/b.height;
                  const data=c.getContext('2d').getImageData(
                    Math.floor((r.x-b.x)*sx), Math.floor((r.y-b.y)*sy),
                    Math.ceil(r.width*sx), Math.ceil(r.height*sy)).data;
                  return data.some((v,i)=>i%4!==3 && v<100);
                }""")
            assert len([url for _, url in calls if "/attachment-ocr/" in url]) == ocr_requests
            Path("generated-artifacts").mkdir(exist_ok=True)
            page.screenshot(path="generated-artifacts/pdf-ocr.jpg")
            page.locator("#av-next").click()
            expect(page.locator("#av-page")).to_have_text("Page 2 of 2")
            expect(page.locator("#av-ocr")).to_be_visible()
            assert not page.locator(".av-ocr-mark").count()
            page.locator("#av-prev").click()
            expect(page.locator("#av-matches")).to_contain_text("Local OCR")
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.locator(".av-ocr-mark.hl-mem").first).to_be_visible()
            expect(page.locator("#av-feedback")).to_have_text("")
            if serve:
                print(f"Mock scanned quote ready at {base}", flush=True)
                import threading
                threading.Event().wait()
            page.locator("#av-back").click()
            expect(page.locator("#rbody")).to_have_value("Unsaved reply survives OCR")
            assert page.evaluate("savedReply===document.getElementById('rbody')")

            # Controlled slow/error/empty OCR jobs exercise lifecycle without
            # depending on CPU timing. The actual recognition above is unmocked.
            context.route("**/static/pdf-ocr-worker.js", lambda route: route.fulfill(
                content_type="text/javascript", body="""
                self.onmessage=({data})=>{
                  if(data.cancel){ self.close(); return; }
                  self.postMessage({progress:1});
                  setTimeout(()=>self.postMessage({blocks:[]}),60000);
                };"""))
            for action in ("back", "thread", "po", "page", "zoom"):
                page.locator('.att[data-name="quote.pdf"]').click()
                expect(page.locator("#av-ocr")).to_be_visible()
                workers = []
                def track_worker(worker):
                    workers.append(worker)
                page.on("worker", track_worker)
                page.locator("#av-ocr").click()
                try:
                    expect(page.locator("#av-matches")).to_contain_text("1%", timeout=15000)
                except AssertionError:
                    print("OCR cancellation fixture:", action, "workers:", len(workers), "errors:", errors)
                    raise
                assert workers
                with workers[-1].expect_event("close"):
                    if action == "back":
                        page.locator("#av-back").click()
                    elif action == "thread":
                        page.evaluate("document.getElementById('ts').value='1'; document.getElementById('ts').dispatchEvent(new Event('change'))")
                    elif action == "po":
                        page.locator("#add").fill("NEXT")
                        page.locator("#add").press("Enter")
                        expect(page.locator("#po")).to_have_text("NEXT")
                    elif action == "page":
                        page.locator("#av-next").click()
                    else:
                        page.locator("#av-in").click()
                page.remove_listener("worker", track_worker)
                if action in ("page", "zoom"):
                    expect(page.locator("#av-ocr")).to_be_visible()
                    page.locator("#av-back").click()
                expect(page.locator("#attachment-preview")).to_be_hidden()
                assert page.locator(".av-ocr-mark").count() == 0
                expect(page.locator("#rbody")).to_be_visible()
            for response, message in (("{error:true}", "could not finish"),
                                      ("{blocks:[]}", "No readable text found by local OCR")):
                context.route("**/static/pdf-ocr-worker.js", lambda route, request, r=response: route.fulfill(
                    content_type="text/javascript",
                    body="self.onmessage=()=>{self.postMessage(" + r + ");self.close();};"))
                page.locator('.att[data-name="quote.pdf"]').click()
                expect(page.locator("#av-ocr")).to_be_visible()
                page.locator("#av-ocr").click()
                expect(page.locator("#av-matches")).to_contain_text(message)
                expect(page.locator(".av-pdf")).to_be_visible()
                expect(page.locator("#av-download")).to_be_visible()
                if response == "{error:true}":
                    expect(page.locator("#av-ocr")).to_be_visible()
                page.locator("#av-back").click()
            assert not [method for method, _ in calls if method != "GET"]
            assert not external, external
            assert not errors, errors
            assert not writes
        browser.close()
        print("Scanned PDF checks passed: real local OCR, seven categories, boxes/zoom/cache, pages/phone, cancellation, failure/empty, privacy, no writes.")


if __name__ == "__main__":
    walkthrough("--serve" in sys.argv)
