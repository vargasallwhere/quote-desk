"""Mock-only failure and recovery checks. No external requests or writes."""
from attachment_browser import fixture
from pathlib import Path


def walkthrough():
    from playwright.sync_api import sync_playwright, expect
    cases = {
        "initializer": None,
        "transport": "request/transport",
        "interrupted-body": "body/failed",
        "http": "request/http/502",
        "module": "module/failed",
        "module-transport": "module/failed",
        "worker": "worker/failed",
        "worker-transport": "worker/failed",
        "parse": "document/failed",
        "retrieval-stall": "request/timeout",
        "body-stall": "body/timeout",
        "module-stall": "module/timeout",
        "worker-stall": "worker/timeout",
        "document-stall": "document/timeout",
        "page-stall": "page/timeout",
        "render-stall": "render/timeout",
        "render-error": "render/failed",
    }
    with fixture() as (base, mode, writes, service), sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/repl/tools/bin/chromium",
                                    headless=True, args=["--no-sandbox"])
        for case, expected_code in cases.items():
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
            broken = [True]
            mode["interrupt_body"] = case == "interrupted-body"
            def route(request):
                url = request.request.url
                if not url.startswith(base + "/"):
                    return request.abort()
                if broken[0]:
                    preview = "/api/attachment/" in url and request.request.headers.get("x-attachment-preview") == "1"
                    if preview and case == "transport":
                        return request.abort("connectionreset")
                    if preview and case == "http":
                        return request.fulfill(status=502, content_type="application/json",
                                               body='{"error":"PRIVATE https://private.test/customer?secret=123"}')
                    if case == "initializer" and "/static/attachment-preview.js" in url:
                        return request.abort()
                    if case == "module" and "/build/pdf.min.mjs" in url:
                        return request.fulfill(status=404, body="missing")
                    if case == "module-transport" and "/build/pdf.min.mjs" in url:
                        return request.abort("connectionreset")
                    if case == "worker" and "/build/pdf.worker.min.mjs" in url:
                        return request.fulfill(status=404, body="missing")
                    if case == "worker-transport" and "/build/pdf.worker.min.mjs" in url:
                        return request.abort("connectionreset")
                    if case == "parse" and preview:
                        return request.fulfill(content_type="application/pdf", body=b"%PDF-1.7\ninvalid")
                    if case == "module-stall" and "/build/pdf.min.mjs" in url:
                        return request.fulfill(content_type="text/javascript", body="await new Promise(()=>{});")
                    if case == "worker-stall" and "/build/pdf.worker.min.mjs" in url:
                        return request.fulfill(content_type="text/javascript", body="setInterval(()=>{},1000);")
                    if case in ("document-stall", "page-stall", "render-stall", "render-error") and "/build/pdf.min.mjs" in url:
                        page = ("new Promise(()=>{})" if case == "page-stall" else
                                "Promise.resolve({getViewport:()=>({width:612,height:792}),render:()=>({promise:" +
                                ("Promise.reject(new Error('PRIVATE https://private.test/customer'))" if case == "render-error" else "new Promise(()=>{})") +
                                ",cancel(){}})})")
                        document = "new Promise(()=>{})" if case == "document-stall" else f"Promise.resolve({{numPages:3,getPage:()=>{page}}})"
                        return request.fulfill(content_type="text/javascript", body=f"""
                          export class PDFWorker {{
                            promise=Promise.resolve();
                            destroy() {{}}
                          }}
                          export function getDocument() {{ return {{
                            destroy:()=>Promise.resolve(),
                            promise:{document}
                          }}; }}
                        """)
                request.continue_()
            context.route("**/*", route)
            context.add_init_script("""
              window.breakPreview = true;
              const fetchOriginal = window.fetch;
              window.fetch = async (...args) => {
                let response;
                try { response = await fetchOriginal(...args); }
                catch(error) {
                  window.networkFailure = {stage:"request", matchesReported:error.message==="Failed to fetch"};
                  throw error;
                }
                const read = response.arrayBuffer.bind(response);
                response.arrayBuffer = async () => {
                  try { return await read(); }
                  catch(error) {
                    window.networkFailure = {stage:"body", matchesReported:error.message==="Failed to fetch"};
                    throw error;
                  }
                };
                return response;
              };
              const NativeWorker = window.Worker;
              window.liveWorkers = new Set();
              window.Worker = class extends NativeWorker {
                constructor(...args) { super(...args); liveWorkers.add(this); }
                terminate() { liveWorkers.delete(this); super.terminate(); }
              };
              const timer = window.setTimeout;
              window.setTimeout = (fn, ms, ...args) => timer(fn, ms>19000&&ms<=30000 ? 1500 : ms, ...args);
            """ + ("""
              const original = window.fetch;
              window.fetch = (url, options) => window.breakPreview && String(url).includes('/api/attachment/')
                ? new Promise(()=>{}) : original(url, options);
            """ if case == "retrieval-stall" else """
              const original = window.fetch;
              window.fetch = async (url, options) => {
                const response = await original(url, options);
                if(window.breakPreview && String(url).includes('/api/attachment/'))
                  response.arrayBuffer = () => new Promise(()=>{});
                return response;
              };
            """ if case == "body-stall" else ""))
            page = context.new_page()
            errors, downloads, requests, diagnostics = [], [], [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("download", lambda d: downloads.append(d))
            page.on("request", lambda r: requests.append((r.method, r.url)))
            page.on("console", lambda m: diagnostics.append(m.args[1].json_value())
                    if m.text.startswith("Attachment preview") else None)
            page.goto(base + "/#US")
            expect(page.locator("#rbody")).to_be_visible()
            page.locator("#rbody").fill("Unsaved during failure")
            page.evaluate("window.originalReply = document.getElementById('rbody')")
            page.locator(".mh").first.click()
            page.locator('.att[data-name="quote ∙ sample.pdf"]').click()
            expect(page.locator("#av-retry")).to_be_visible(timeout=7000)
            expect(page.locator("#av-feedback")).not_to_have_text("")
            expect(page.locator("#av-download")).to_be_visible()
            feedback = page.locator("#av-feedback").inner_text()
            if expected_code:
                assert expected_code in feedback, (case, feedback)
                assert diagnostics and diagnostics[-1]["stage"] == expected_code.split("/")[0]
                assert set(diagnostics[-1]) <= {"stage", "reason", "release", "attempt", "status"}
                assert "PRIVATE" not in str(diagnostics) + feedback
                assert "http" not in str(diagnostics).replace("'http'", "") + feedback.replace("request/http", "")
                assert "ANGjdJ" not in str(diagnostics) + feedback
                assert "sample.pdf" not in str(diagnostics) + feedback
                assert page.evaluate("liveWorkers.size") == 0, case
            if case in ("transport", "interrupted-body"):
                evidence = page.evaluate("networkFailure")
                assert evidence == {"stage": "request" if case == "transport" else "body",
                                    "matchesReported": True}, evidence
            assert page.url == base + "/#US" and len(context.pages) == 1 and not downloads
            # The same attachment/URL can download while its fetch/import/worker
            # preview fails. A successful download is not evidence of rendering.
            with page.expect_download() as downloaded:
                page.locator("#av-download").click()
            assert Path(downloaded.value.path()).read_bytes().startswith(b"%PDF-")
            # This Chromium build can use the generic "download" for long opaque
            # paths. Unicode header encoding is asserted by endpoint tests;
            # here verify the UI preserves the name and the download has bytes.
            assert page.locator("#av-download").get_attribute("download") == "quote ∙ sample.pdf"
            assert not [url for method, url in requests if "/api/attachment/" in url and method != "GET"]
            reads = len([url for method, url in requests if "/api/threads/" in url])
            broken[0] = False
            mode["interrupt_body"] = False
            page.evaluate("window.breakPreview = false")
            page.locator("#av-retry").click()
            expect(page.locator("#av-page")).to_have_text("Page 1 of 3")
            expect(page.locator("#av-feedback")).to_have_text("")
            assert page.locator("canvas").evaluate("""e => {
              const d=e.getContext('2d').getImageData(0,0,e.width,e.height).data;
              let ink=0; for(let i=0;i<d.length;i+=4) if(d[i]<100 && d[i+3]>200) ink++;
              return ink>1000;
            }""")
            if case == "interrupted-body":
                Path("generated-artifacts").mkdir(exist_ok=True)
                page.screenshot(path="generated-artifacts/attachment-recovered.jpg")
            assert page.url == base + "/#US" and len(context.pages) == 1
            expect(page.locator(".split > .panel").first).to_be_visible()
            page.evaluate("refreshOrderStatus()")
            expect(page.locator("#av-feedback")).to_have_text("")
            page.locator("#av-back").click()
            assert page.evaluate("liveWorkers.size") == 0
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


def late_module_walkthrough():
    """A non-cancellable import may resolve after Back, thread or PO changes."""
    from playwright.sync_api import sync_playwright, expect
    with fixture() as (base, mode, writes, service), sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/repl/tools/bin/chromium",
                                    headless=True, args=["--no-sandbox"])
        for action in ("back", "thread", "po"):
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            def route(request):
                url = request.request.url
                if not url.startswith(base + "/"):
                    return request.abort()
                if "/build/pdf.min.mjs" in url and "delayed" not in url:
                    return request.fulfill(content_type="text/javascript", body=f"""
                      export * from "{base}/attachment-renderer/build/pdf.min.mjs?delayed=1";
                      await new Promise(resolve=>window.releaseModule=()=>{{
                        resolve(); setTimeout(()=>window.moduleReleased=true,0);
                      }});
                    """)
                request.continue_()
            context.route("**/*", route)
            page = context.new_page()
            errors, calls = [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("request", lambda r: calls.append((r.method, r.url)))
            page.goto(base + "/#US")
            expect(page.locator("#rbody")).to_be_visible()
            page.locator("#rbody").fill("Keep this unsaved reply")
            page.evaluate("window.savedReply=document.getElementById('rbody')")
            page.locator('.att[data-name="quote.pdf"]').click()
            page.wait_for_function("typeof releaseModule === 'function'")
            if action == "back":
                page.locator("#av-back").click()
            elif action == "thread":
                page.evaluate("document.getElementById('ts').value='1'; document.getElementById('ts').dispatchEvent(new Event('change'))")
            else:
                page.locator("#add").fill("NEXT")
                page.locator("#add").press("Enter")
                expect(page.locator("#po")).to_have_text("NEXT")
            page.evaluate("releaseModule()")
            page.wait_for_function("window.moduleReleased")
            expect(page.locator("#attachment-preview")).to_be_hidden()
            expect(page.locator("#av-stage > *")).to_have_count(0)
            assert not [url for _, url in calls if "/build/pdf.worker.min.mjs" in url]
            if action == "back":
                expect(page.locator("#rbody")).to_have_value("Keep this unsaved reply")
                assert page.evaluate("savedReply===document.getElementById('rbody')")
            assert not errors and not writes
            assert not [method for method, _ in calls if method != "GET"]
            context.close()
            print("Discarded late renderer after:", action)
        browser.close()


if __name__ == "__main__":
    walkthrough()
    late_module_walkthrough()
