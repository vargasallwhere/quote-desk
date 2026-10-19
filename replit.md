# Quote Desk

Small Flask application with its existing HTML frontend. Keep this structure and stack.

## Running on Replit

Dependencies are listed in `requirements.txt`.
Run regression checks with `python3 -m unittest discover -s tests`.
Do not expose a public web workflow: the current app has no authentication and can access a connected Gmail mailbox and customer orders. Add sign-in and authorization before exposing a preview or publishing it. A local-only console workflow may run the existing entry point for verification.
The existing local development entry point remains `python3 app.py` (localhost port 5070).

## Service configuration

- `ALLWHERE_AUTH`: Authorization header (for example, a Basic or Bearer header), a `username:password` pair, or a serialized two-string list/tuple. Legacy `ALLWHERE_USER` and `ALLWHERE_PASS` are still supported when `ALLWHERE_AUTH` is absent.
- `ALLWHERE_BASE`: Allwhere service URL, either the root or ending in `/v1` or `/v2`. The existing production service URL remains the default when unset.
- `GMAIL_TOKEN_JSON`: Gmail authorized-user token JSON.
- `PS_USER` and `PS_PASS`: separate product-service Basic-auth credentials, required to verify current catalog MPNs. Missing credentials prevent catalog requests and produce actionable diagnostics; order-service authentication is not a substitute.
- Optional `SCOUT_URL`: enables the desktop Scout-only features. Those buttons stay hidden when unset.

Never print credentials or put them in source control. Gmail drafts and sends are real actions; preserve the existing send confirmation and existing-thread/draft guard.

Catalog reads validate the returned variant ID and order-snapshot SKU. Successful explicit null MPNs override older snapshots. During failed catalog reads, structured snapshot MPNs are preserved and labeled as unverified against the current catalog; unresolved items remain visible. Credentials are read per request, so imported, stale authorization headers are not retained. Restart the local application after configuration/code changes before verifying it.

Read-only verification uses `generate_eu_email`, `generate_uk_email`, or `generate_us_email` and the order/ticket GET endpoints. **Do not call `generate_auto_quote_email` or POST `/api/quote-draft` against live Gmail during verification**: those create real drafts.

Vendor quote-request emails must not include product or warranty prices, currency/amount lines, price labels, or unavailable-price placeholders. Apply this to every regional template, including Australia and New Zealand. Keep quantities, MPNs, specifications, and warranty requests. Catalog prices may still be used internally; never insert them into the vendor request. Do not change existing Gmail drafts unless the user specifically asks to correct that draft.

Additional browser-side checks: `node tests/order_status_refresh.js`, `node tests/confirmation_load.js`, and `node tests/catalog_display.js`.

Warranty regression checks also include `node tests/warranty_display.js` and the Python warranty tests. All Gmail writes in these checks are mocked, and the tests decode the submitted MIME body.

New quotes preserve the supplied plan wording beside the device, group only matching variant/plan selections, and exclude blank or explicit no-plan selections. Standalone warranty products and the existing enterprise-note heuristic stay separate. Do not invent coverage terms, duration, or price.
