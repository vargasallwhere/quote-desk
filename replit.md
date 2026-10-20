# Quote Desk

Small Flask application with its existing HTML frontend. Keep this structure and stack.

## Running on Replit

Dependencies are listed in `requirements.txt`.
The attachment reader also needs `npm ci --omit=dev` to install the locked PDF.js browser assets; Flask serves them locally. No Node server or build step is needed.
Run regression checks with `python3 -m unittest discover -s tests`.
Do not expose a public web workflow: the current app has no authentication and can access a connected Gmail mailbox and customer orders. Add sign-in and authorization before exposing a preview or publishing it. A local-only console workflow may run the existing entry point for verification.
The existing local development entry point remains `python3 app.py` (localhost port 5070).

## Service configuration

- `ALLWHERE_AUTH`: Authorization header (for example, a Basic or Bearer header), a `username:password` pair, or a serialized two-string list/tuple. Legacy `ALLWHERE_USER` and `ALLWHERE_PASS` are still supported when `ALLWHERE_AUTH` is absent.
- `ALLWHERE_BASE`: Allwhere service URL, either the root or ending in `/v1` or `/v2`. The existing production service URL remains the default when unset.
- `GMAIL_TOKEN_JSON`: Gmail authorized-user token JSON.
- `PS_USER` and `PS_PASS`: separate product-service Basic-auth credentials, required to verify current catalog MPNs. Missing credentials prevent catalog requests and produce actionable diagnostics; order-service authentication is not a substitute.
- Optional `SCOUT_URL`: enables desktop Price Approval and Autopilot. Alternative Approval Ticket runs independently and stays visible without it.

Never print credentials or put them in source control. Gmail drafts and sends are real actions; preserve the existing send confirmation and existing-thread/draft guard.

Catalog reads validate the returned variant ID and order-snapshot SKU. Successful explicit null MPNs override older snapshots. During failed catalog reads, structured snapshot MPNs are preserved and labeled as unverified against the current catalog; unresolved items remain visible. Credentials are read per request, so imported, stale authorization headers are not retained. Restart the local application after configuration/code changes before verifying it.

Read-only verification uses `generate_eu_email`, `generate_uk_email`, or `generate_us_email` and the order/ticket GET endpoints. **Do not call `generate_auto_quote_email` or POST `/api/quote-draft` against live Gmail during verification**: those create real drafts.

Vendor quote-request emails must not include product or warranty prices, currency/amount lines, price labels, or unavailable-price placeholders. Apply this to every regional template, including Australia and New Zealand. Keep quantities, MPNs, specifications, and warranty requests. Catalog prices may still be used internally; never insert them into the vendor request. Do not change existing Gmail drafts unless the user specifically asks to correct that draft.

Additional browser-side checks: `node tests/order_status_refresh.js`, `node tests/confirmation_load.js`, and `node tests/catalog_display.js`.

Warranty regression checks also include `node tests/warranty_display.js` and the Python warranty tests. All Gmail writes in these checks are mocked, and the tests decode the submitted MIME body.

Standalone warranty consolidation is display-only: match nonempty SKU, exact name, and unit price; preserve source order lines for all other workflows. `python3 tests/warranty_browser.py` checks the ten-unit scenario locally with mocked services and saves an ignored screenshot. `--serve` offers the mock fixture only on 127.0.0.1:5073.

Items separately consolidates exact nonempty SKUs in first-seen order, sums quantities, and shows `Nx` (including `1x`). Missing/blank SKUs remain separate. The first line supplies display metadata, but catalog-verification and unavailable-MPN caveats include every source line; original diagnostics and order data stay intact. Run `node tests/items_display.js` and `python3 tests/items_browser.py` for regression checks and an ignored mock-only local screenshot.

New quotes preserve the supplied plan wording beside the device, group only matching variant/plan selections, and exclude blank or explicit no-plan selections. Standalone warranty products and the existing enterprise-note heuristic stay separate. Do not invent coverage terms, duration, or price.

## Standalone alternative approvals

Alternative Approval Ticket opens a same-origin wide review tab for selected distinct SKUs. Opening/reviewing is read-only: never create tickets, notify customers, or write Gmail until explicit submission. The parser is the supplied Scout parser, not a catalog verifier. US defaults to US, UK/Australia use the source UK defaults, and EU/other regions stay blank for manual confirmation. Prices in this approval form are USD; do not infer currency conversion.

Server-side setup (see `ALTERNATIVE_APPROVALS.md`):
- `AIRTABLE_PAT`: scoped personal access token with record-write access to the target base.
- `AIRTABLE_BASE_ID` and `AIRTABLE_TABLE`: target `app...` and `tbl...` identifiers matching the supplied field mapping.
- `AUTOMATED_APPROVALS_WEBHOOK_URL` and `AUTOMATED_APPROVALS_WEBHOOK_SECRET`: HTTPS automation destination and shared secret.
- `AIRTABLE_USER_IDS_JSON`: JSON mapping procurement/order-manager email addresses to Airtable `usr...` collaborator IDs. Unmapped Requested By or Assigned To blocks submission, rather than silently omitting either.

Secrets must be entered using the workspace Secrets tool, never in chat, source, or test fixtures containing real values. Missing setup does not prevent reviewing; it blocks all external writes with actionable messages. No live notification delivery has been verified by the mocked tests.

Review sessions use an ignored, private local SQLite file, `.cache/alt-reviews.sqlite3`, for restart-safe submission locks and results; 2-hour lifetime, up to 500 sessions, expired entries cleaned on new review creation. Keep this file during ordinary process restarts. This is single-instance local operation, not a shared multi-host store. Do not delete it as a way to retry uncertain submissions. Do not share review URLs.

Only explicit submission sets Send Alt/Pricing Email and invokes the supplied webhook; Quote Desk never sends a separate Gmail notification. Downstream automation owns adding the order external link; do not add a second link here. Omit webhook `multipleSKU` until its accepted contract is verified; the Airtable multiple-SKU checkbox is retained. Checkpoint successful ticket creation before notifying. A webhook failure/unknown outcome must retain the ticket link and prohibit another creation. Ambiguous Airtable writes must remain locked with a check-Airtable warning, never automatically retried.

Run `node tests/alternative_picker.js` plus all existing Python/JS checks. Local Chromium walkthrough: `python3 tests/alt_browser.py` (requires the test-only `playwright` package and Chromium; the Replit path is `/repl/tools/bin/chromium`). It binds only loopback, mocks all external reads/writes, blocks browser requests outside its local fixture, and saves an ignored screenshot under `generated-artifacts/`. Never use a public preview or live writes to verify approvals.

## Attachment comparison

Attachments open inside Vendor email; Back retains the original email/composer DOM and never saves or reloads Gmail. PDF.js renders PDF pages to canvas only (no document scripts, annotations, forms, or links); raster images use temporary object URLs. HTML, SVG, Office files and other unsupported formats are download-only. Attachment responses always force download, use no-store/nosniff and validate supported MIME signatures. Keep this allowlist restrictive.

Run `python3 tests/attachment_browser.py` for the mock-only loopback walkthrough (PDF pixels/pages, image zoom/scroll, earlier messages, Back/reply/scroll restoration, download, failures/retry, active content, late responses after PO/thread/Back changes, status independence, keyboard and phone layout). Screenshots are ignored under `generated-artifacts/`. `python3 tests/attachment_browser.py --serve` offers only the mock fixture on 127.0.0.1:5072 for local screenshots.


### Inline PDF reliability and release diagnosis

The reported separate-tab screenshot matches the preceding attachment links, which explicitly used `target="_blank"`. Available deployment logs also record `UnicodeEncodeError` for U+2219 while serializing the attachment response header. The preceding endpoint embedded the raw filename in `Content-Disposition: inline`; a synthetic filename with this character reproduces that Latin-1 serialization failure. The already-merged safe ASCII fallback plus RFC 5987 encoded filename corrects that failure; endpoint and loopback browser checks now cover the character explicitly. The current merged code painted the mock PDF in local Chromium before these additional reliability fixes. No production request, customer attachment retrieval, or publication was used for verification, and the exact externally served release remains unverified.

Attachment activation now uses buttons, never raw download/navigation links. A missing viewer initializer leaves order/email loading intact and offers an in-panel retry that reloads only the viewer script. The HTML binds script/CSS URLs and renderer imports to a content fingerprint; HTML, viewer assets, and renderer responses are no-store. Module and worker responses explicitly use JavaScript MIME types. Retries use new module/worker URLs to avoid cached failed imports. Only allowlisted PDF.js assets are exposed; a missing runtime installation returns an actionable 503.

The publishing build runs `npm ci --omit=dev --omit=optional --no-audit --no-fund`, so PDF.js no longer depends solely on post-merge installation. This setting takes effect only on a future publication. These changes must be merged before an externally served version can receive them; an already-open old page must then be reloaded. No published-version fix has been verified and no publication was performed.

Loading (including renderer import/worker startup/parsing) has a 30-second deadline; page retrieval/rendering has a 20-second deadline. Back, Retry and order/thread changes cancel/invalidate old work. `python3 tests/attachment_failures_browser.py` checks missing initializer/module/worker, invalid PDF, stalled retrieval/import/worker/page/render, safe retries with painted pixels, unchanged URL/single tab and unchanged unsaved reply, with all external access blocked.
