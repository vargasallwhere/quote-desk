"""Mock-only loopback PDF tag walkthrough; never reads or writes live Gmail."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from attachment_browser import fixture


def tagged_pdf():
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R 5 0 R 7 0 R] /Count 3 >>"]
    for number in range(1, 4):
        # Deliberately split 32 and GB across distinct font sizes/text objects.
        content = (b'BT /F1 16 Tf 45 740 Td (MacBook Pro M5 - 14" - ) Tj '
                   b'(32) Tj /F1 15 Tf (GB) Tj /F1 16 Tf '
                   b'( - 1TB - Silver - US English - M3XE4X/A) Tj '
                   b'0 -40 Td (14 in; 10C CPU; 10-core GPU) Tj ET'
                   if number < 3 else b"")
        if number == 2:
            content = b"BT /F1 16 Tf 45 740 Td (32GB - Silver) Tj ET"
        rotation = " /Rotate 90" if number == 2 else ""
        objects.extend([
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 900 792]{rotation}"
             f" /Resources << /Font << /F1 9 0 R >> >> /Contents {len(objects)+2} 0 R >>").encode(),
            f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
        ])
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
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


def walkthrough():
    from playwright.sync_api import sync_playwright, expect
    with patch("attachment_browser.pdf", tagged_pdf), fixture() as (base, mode, writes, service), sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/repl/tools/bin/chromium",
                                    headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1600, "height": 1050})
        context.route("**/*", lambda route: route.continue_()
                      if route.request.url.startswith((base + "/", "blob:")) else route.abort())
        page = context.new_page()
        errors, calls = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: calls.append((request.method, request.url)))
        page.goto(base + "/#US")
        expect(page.locator("#rbody")).to_be_visible()
        page.locator("#rbody").fill("Keep this unsaved reply")
        page.evaluate("window.savedReply = document.getElementById('rbody')")
        page.locator('.legend button[data-k="ssd"]').click()
        page.locator('.att[data-name="quote.pdf"]').click()
        expect(page.locator("#av-page")).to_have_text("Page 1 of 3")
        expect(page.locator("#av-matches")).to_contain_text("Storage:")
        assert page.locator(".av-text .hl-ssd").inner_text() == "1TB"
        assert page.locator(".av-text .hl-mem").all_text_contents() == ["32", "GB"]
        assert page.locator(".av-text .hl-cpu").all_text_contents() == ["M5", "10C CPU", "10-core GPU"]
        assert page.locator(".av-text .hl-size").all_text_contents() == ['14"', "14 in"]
        # Each category is detected on the quote, and selected state is shared.
        for key in ("cpu", "mem", "ssd", "color", "kb", "size", "mpn"):
            button = page.locator(f'.legend button[data-k="{key}"]')
            if button.get_attribute("aria-pressed") != "true":
                button.click()
            expect(button).to_have_attribute("aria-pressed", "true")
            assert page.locator(f".av-text .hl-{key}").count()
            assert page.locator(f".av-text .hl-{key}").first.evaluate(
                "e=>getComputedStyle(e).backgroundColor") != "rgba(0, 0, 0, 0)"
            other = "mem" if key != "mem" else "ssd"
            assert page.locator(f".av-text .hl-{other}").first.evaluate(
                "e=>getComputedStyle(e).backgroundColor") == "rgba(0, 0, 0, 0)"
        # Toggling off restores the existing all-colors behavior.
        page.locator('.legend button[data-k="mpn"]').click()
        expect(page.locator("html")).not_to_have_attribute("data-focus", "mpn")
        page.locator('.legend button[data-k="mem"]').click()
        page.locator("#av-actual").click()
        page.locator("#av-in").click()
        expect(page.locator("#av-zoom")).to_have_text("125%")
        expect(page.locator("#av-feedback")).to_have_text("")
        mark = page.locator(".av-text .hl-mem").first.bounding_box()
        canvas = page.locator(".av-pdf").bounding_box()
        assert canvas["x"] < mark["x"] < canvas["x"] + canvas["width"]
        assert canvas["y"] < mark["y"] < canvas["y"] + canvas["height"]
        # Highlight boxes must align over actual printed (dark) canvas pixels.
        assert page.locator(".av-text .hl-mem").first.evaluate("""e=>{
          const r=e.getBoundingClientRect(), c=document.querySelector('.av-pdf');
          const b=c.getBoundingClientRect(), sx=c.width/b.width, sy=c.height/b.height;
          const data=c.getContext('2d').getImageData(
            Math.max(0,Math.floor((r.x-b.x)*sx)), Math.max(0,Math.floor((r.y-b.y)*sy)),
            Math.ceil(r.width*sx), Math.ceil(r.height*sy)).data;
          return data.some((v,i)=>i%4!==3 && v<100);
        }""")
        page.locator("#av-next").click()
        expect(page.locator("#av-page")).to_have_text("Page 2 of 3")
        expect(page.locator("#av-matches")).to_contain_text("Memory:")
        expect(page.locator(".av-text .hl-mem").first).to_be_visible()
        page.locator('.legend button[data-k="cpu"]').click()
        expect(page.locator("#av-matches")).to_have_text("No chip & cores matches found on this page.")
        page.locator('.legend button[data-k="mem"]').click()
        page.locator("#av-next").click()
        expect(page.locator("#av-page")).to_have_text("Page 3 of 3")
        expect(page.locator("#av-matches")).to_contain_text("No readable text")
        assert page.locator(".av-text .hl").count() == 0
        page.locator("#av-prev").click()
        page.locator("#av-prev").click()
        page.locator("#av-fit").click()
        expect(page.locator("#av-page")).to_have_text("Page 1 of 3")
        expect(page.locator("#av-feedback")).to_have_text("")
        page.locator("#av-actual").click()
        expect(page.locator("#av-feedback")).to_have_text("")
        expect(page.locator("#av-matches")).to_have_text("Memory: 1 highlighted match on this page.")
        page.locator("#av-fit").click()
        expect(page.locator("#av-feedback")).to_have_text("")
        Path("generated-artifacts").mkdir(exist_ok=True)
        page.screenshot(path="generated-artifacts/pdf-tag-highlights.jpg")
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator("#av-feedback")).to_have_text("")
        expect(page.locator(".av-text .hl-mem").first).to_be_visible()
        page.locator("#av-back").click()
        expect(page.locator("#rbody")).to_have_value("Keep this unsaved reply")
        assert page.evaluate("savedReply === document.getElementById('rbody')")
        assert page.locator(".av-text").count() == 0
        assert len(context.pages) == 1
        assert not [method for method, url in calls if method != "GET"]
        assert not writes
        assert not errors, errors
        browser.close()
        print("PDF tag checks passed: seven categories, split text, focus/toggle, zoom, rotation, pages, no text/no match, phone, Back, no writes.")


if __name__ == "__main__":
    walkthrough()
