"""Mock-only failure and recovery checks. No external requests or writes."""
from attachment_browser import fixture


def walkthrough():
    from playwright.sync_api import sync_playwright, expect
    cases = ("initializer", "module", "worker", "parse", "retrieval-stall",
             "module-stall", "worker-stall", "page-stall", "render-stall")
    with fixture() as (base, mode, writes, service), sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/repl/tools/bin/chromium",
                                    headless=True, args=["--no-sandbox"])
        for case in cases:
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            broken = [True]
            def route(request):
                url = request.request.url
                if not url.startswith(base + "/"):
                    return request.abort()
                if broken[0]:
                    if case == "initializer" and "/static/attachment-preview.js" in url:
                        return request.abort()
                    if case == "module" and "/build/pdf.min.mjs" in url:
                        return request.fulfill(status=404, body="missing")
                    if case == "worker" and "/build/pdf.worker.min.mjs" in url:
                        return request.fulfill(status=404, body="missing")
                    if case == "parse" and "/api/attachment/" in url:
                        return request.fulfill(content_type="application/pdf", body=b"%PDF-1.7\ninvalid")
                    if case == "module-stall" and "/build/pdf.min.mjs" in url:
                        return request.fulfill(content_type="text/javascript", body="await new Promise(()=>{});")
                    if case == "worker-stall" and "/build/pdf.worker.min.mjs" in url:
                        return request.fulfill(content_type="text/javascript", body="setInterval(()=>{},1000);")
                    if case in ("page-stall", "render-stall") and "/build/pdf.min.mjs" in url:
                        page = ("new Promise(()=>{})" if case == "page-stall" else
                                "Promise.resolve({getViewport:()=>({width:612,height:792}),render:()=>({promise:new Promise(()=>{}),cancel(){}})})")
                        return request.fulfill(content_type="text/javascript", body=f"""
                          export const GlobalWorkerOptions = {{}};
                          export function getDocument() {{ return {{
                            destroy:()=>Promise.resolve(),
                            promise:Promise.resolve({{numPages:3,getPage:()=>{page}}})
                          }}; }}
                        """)
                request.continue_()
            context.route("**/*", route)
            context.add_init_script("""
              window.breakPreview = true;
              const timer = window.setTimeout;
              window.setTimeout = (fn, ms, ...args) => timer(fn, ms===30000||ms===20000 ? 1500 : ms, ...args);
            """ + ("""
              const original = window.fetch;
              window.fetch = (url, options) => window.breakPreview && String(url).includes('/api/attachment/')
                ? new Promise(()=>{}) : original(url, options);
            """ if case == "retrieval-stall" else ""))
            page = context.new_page()
            errors, downloads, requests = [], [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("download", lambda d: downloads.append(d))
            page.on("request", lambda r: requests.append((r.method, r.url)))
            page.goto(base + "/#US")
            expect(page.locator("#rbody")).to_be_visible()
            page.locator("#rbody").fill("Unsaved during failure")
            page.evaluate("window.originalReply = document.getElementById('rbody')")
            page.locator(".att").filter(has_text="quote.pdf", has_not_text="earlier").click()
            expect(page.locator("#av-retry")).to_be_visible(timeout=7000)
            expect(page.locator("#av-feedback")).not_to_have_text("")
            expect(page.locator("#av-download")).to_be_visible()
            assert page.url == base + "/#US" and len(context.pages) == 1 and not downloads
            assert not [url for method, url in requests if "/api/attachment/" in url and method != "GET"]
            reads = len([url for method, url in requests if "/api/threads/" in url])
            broken[0] = False
            page.evaluate("window.breakPreview = false")
            page.locator("#av-retry").click()
            expect(page.locator("#av-page")).to_have_text("Page 1 of 3")
            expect(page.locator("#av-feedback")).to_have_text("")
            assert page.locator("canvas").evaluate("""e => {
              const d=e.getContext('2d').getImageData(0,0,e.width,e.height).data;
              let ink=0; for(let i=0;i<d.length;i+=4) if(d[i]<100 && d[i+3]>200) ink++;
              return ink>1000;
            }""")
            page.locator("#av-back").click()
            expect(page.locator("#rbody")).to_have_value("Unsaved during failure")
            assert page.evaluate("originalReply === document.getElementById('rbody')")
            assert len([url for method, url in requests if "/api/threads/" in url]) == reads
            assert not [method for method, url in requests if method != "GET"]
            assert not errors, (case, errors)
            context.close()
            print("Recovered safely:", case)
        assert not writes
        for action in ("create", "update", "send", "delete"):
            getattr(service.users.return_value.drafts.return_value, action).assert_not_called()
        browser.close()


if __name__ == "__main__":
    walkthrough()
