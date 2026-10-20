# Standalone Alternative Approval Tickets

Alternative Approval Ticket works without `SCOUT_URL` in Quote Desk's existing Approvals section, alongside Manual AR Ticket. Price Approval and Autopilot still depend on Scout.

## Workflow

1. Load an order, click Alternative Approval Ticket and select one or more distinct requested SKUs.
2. Optionally paste the vendor alternative, then open the review in a separate wide tab. Allow popups for Quote Desk if blocked. Your unsaved vendor reply stays unchanged.
3. Confirm Requested By, requested SKU/multiple-SKU checkbox, alternative reason, device specifications, USD price, region/keyboard and lead time. Parsed values are editable suggestions, not verified catalog data. Blank values need manual entry. CTO defaults to 3–5 weeks; CTO/backorder exposes lead time.
4. **Submit to Airtable** explicitly creates the ticket and triggers the customer notification workflow. Simply opening/reviewing never writes to Airtable, calls the webhook or changes Gmail.
5. Keep the resulting Airtable link. Notification acceptance is not proof of email delivery.

US gets US region/keyboard defaults. The supplied popup groups Australia with UK, so Australia initially gets UK defaults too; confirm/edit them before submission. EU and other regions intentionally stay blank. The parser retains the supplied supported patterns; it does not verify stock, price, lead time or catalog specifications.

## Secure setup

Use the workspace **Secrets** tool to enter credentials, destination identifiers and collaborator mapping. Do not paste secret values into chat or source files. No real configuration is needed to run the mocked checks.

| Key | Required value |
| --- | --- |
| `AIRTABLE_PAT` | Airtable PAT with `data.records:write` and access to the intended base only. |
| `AIRTABLE_BASE_ID` | Destination base ID (`app...`). |
| `AIRTABLE_TABLE` | ALLWHERE TICKETS destination table ID (`tbl...`), not a display name. |
| `AUTOMATED_APPROVALS_WEBHOOK_URL` | Supplied automation's HTTPS endpoint; no embedded username/password. |
| `AUTOMATED_APPROVALS_WEBHOOK_SECRET` | Shared secret sent only in `X-Webhook-Secret`. |
| `AIRTABLE_USER_IDS_JSON` | JSON object mapping staff email addresses to Airtable collaborator IDs (`usr...`). Include every selectable requester you use and each order manager. |

Example **shape only**, with fictitious values:

```json
{"buyer@example.test":"usrExampleBuyer","manager@example.test":"usrExampleManager"}
```

Do not copy that example as real setup. Obtain collaborator IDs from your Airtable administrator. The source's internal mapping was not supplied and is not guessed. Requested By includes the five supplied choices plus the order's procurement manager; an unknown manager is shown, not silently replaced with Sara. Both Requested By and Assigned To must map before submission. The assigned OM, order number, rush flag and organization come from the saved server-side order review, never arbitrary client headers.

The base/table must contain the field IDs in `alt_tickets.py`. These IDs preserve the supplied mapping; changing destination to an unrelated table will not work. Text fields with blank values are omitted. The Summary/Subject field is left to Airtable. Action Request Type is Alternate Approval; priority is Urgent for rush orders, otherwise High. Secondary alternative is No; Send Alt/Pricing Email is true. Both collaborator fields use arrays of `{"id":"usr..."}`.

Missing or malformed settings are listed by **key name**, without values. Reviews still open, but submitting is blocked before any write if required setup or mappings are missing. External rejection details and exception bodies are not returned or logged.

An Airtable connector may exist in the workspace, but this focused port follows the supplied server-side environment/PAT contract; it does not read a connector's token or change its permissions. Never extract OAuth credentials to populate the PAT setting. No live base access is required for local verification.

## Notification and failure handling

The port retains the supplied webhook contract, including `record_id`, `orderNumbers`, `requestedSKU`, `alternativeType`, first-alternative specs, blank second-alternative fields and `leadTime`. It omits `multipleSKU` because the source comment says the validator requires null/omitted while its code emitted a boolean. Airtable still receives the boolean checkbox. Verify a changed contract with the automation owner before adding that webhook field.

The Send Alt/Pricing Email flag and webhook are the supplied single notification workflow. Quote Desk adds no separate Gmail email and no order external link; downstream automation owns attaching that link.

- **Validation/configuration failure:** no external write; fix fields/setup and submit explicitly.
- **Definite Airtable rejection (e.g. 401/403/422/429):** sanitized HTTP code, no confirmed creation; fix access/schema or rate limits before explicitly trying again.
- **Timeout, connection loss, malformed success, 5xx or unexpected redirect:** the creation outcome may be unknown. The review stays locked. **Check Airtable for this order; never automatically retry or open a replacement review to bypass the lock.**
- **Created ticket, failed/uncertain webhook:** partial success with the ticket link. Do not create another ticket. Check the automation/customer-notification logs; coordinate any recovery with its owner to avoid duplicate emails.
- **Browser loses submission response:** one read-only GET checks the saved session. There is no second POST. If unresolved, the page warns and locks.

Double clicks/concurrent POSTs and completed-session reuse cannot create additional records. The server commits its submission lock before the write and checkpoints the returned record/link before attempting the webhook. No external write is automatically retried.

## Local session storage and limits

Reviews use random 256-bit identifiers and private SQLite storage (`.cache/alt-reviews.sqlite3`, mode 0600), ignored by Git and deployment uploads. The file stores review metadata and submitted results, **not credentials**. Its path can be overridden with Flask's `ALT_REVIEW_DB` configuration for tests. This does not replace the project's order service or any existing database.

Lifetime is two hours from creation; new-review requests delete expired entries. At most 500 active reviews are allowed; capacity errors do not evict an active review. Closing a tab does not delete its session. Successful/uncertain sessions cannot be reopened for writes after expiry; expired links say to check Airtable if previously submitted.

Keep the file on ordinary restarts to preserve locks/results. A process interrupted during a write leaves the review locked in submitting state and must be reconciled manually. Deleting/replacing the file or moving to another host invalidates old reviews; it is not a retry mechanism. Multiple hosts with separate local files are not supported. Authentication and shared-host deployment remain out of scope; this origin repair is not permission to share an unauthenticated app publicly.

## Review write origins and the Replit proxy

Both creation and submission use the same guard, before lookup, session storage or external writes. Previously it compared `Origin` directly with Flask's `request.host_url`. In a synthetic reproduction, `Origin: https://quote-test.replit.dev` and backend `http://internal.test:5000` fail that comparison even with forwarding headers present. This reproduces the reported error path; no request metadata from the original browser was available, so its precise host/scheme mismatch is not proven.

At application startup, `REPLIT_DEV_DOMAIN` pins one exact HTTPS origin in Flask configuration (`ALT_REVIEW_EXTERNAL_ORIGIN`). Only a valid bare hostname under `.replit.dev`, with no URL components or port, is accepted from that runtime setting. This is **not** a wildcard permission for other Replit apps. The request's backend scheme/host may differ behind TLS termination and host rewriting; they do not redefine the pinned origin. A missing/invalid runtime hostname adds no external origin. This setting supports the runtime's development address, not arbitrary aliases or a published/custom domain. Those require an independently verified, operator-controlled origin configuration; never derive them from a request.

Direct localhost, IPv4 loopback and IPv6 loopback operation retains exact request scheme/host/port matching. `localhost` and `127.0.0.1`, different ports, HTTP and HTTPS are not interchangeable. A browser `Origin` must be one valid serialized origin: foreign hosts, deceptive suffixes, userinfo, paths, trailing slashes, lists, `null`, empty and malformed values are rejected. An explicitly absent Origin remains supported for existing non-browser JSON clients. Both endpoints still reject form/text writes through their JSON validation. This is CSRF protection, not authentication.

**Trust boundary:** no `ProxyFix` is installed and no forwarded-header hop count or peer IP is trusted. Replit documentation describes HTTPS proxying but did not establish which client-supplied forwarding headers are stripped/replaced or a stable trusted-peer boundary. Public-preview probing was intentionally excluded. The safe assumption is that clients can supply these headers. `Forwarded`, `X-Forwarded-Host`, `X-Forwarded-Proto` and their chains are ignored, whether plausible, malformed or spoofed. The local WSGI reproduction confirms these headers can reach the app unchanged; it does not claim to measure Replit's real edge. The independent runtime hostname means no such header sanitization guarantee is needed. Do not add `ProxyFix` or infer authority from Origin to repair a future proxy issue.

`tests/test_alt_origin.py` covers both write gates, direct local origins, pinned HTTPS origins over internal HTTP and different hosts, header chains/spoofing, invalid origins blocked before storage, missing-Origin compatibility, JSON-only writes, validation/configuration failures and duplicate locks. `tests/alt_browser.py` runs the full walkthrough twice: direct HTTP and loopback TLS termination with a deliberately rewritten internal HTTP host and attacker-prefixed forwarding chains. It asserts the actual populated wide review, current PO, original picker indices, blank/pasted text, unchanged unsaved vendor reply, missing credentials/mappings, no writes on open, and explicit mocked submission/reload locking.

Only local synthetic requests/services were used: no live Airtable records, notifications, Gmail changes, public-preview tests or publication. The original reporting browser and real edge path still need confirmation after these changes reach that app. Local success alone does not prove that browser is fixed.

## Safe verification

### Inert opening diagnosis and recovery (2026-10-20)

The supplied original popup selects requested items, accepts optional alternative
text and opens the dedicated `review-v2` page with order context and editable
specifications. Quote Desk keeps the equivalent two-click selection/optional-text
flow and existing wide standalone review, not an embedded small form.

**Reproduced local cause:** with a ticket-info response containing `items: null`,
the old initial button called `uniq(tinfo.items)` and threw
`Cannot read properties of null (reading 'forEach')` before adding any picker
content. The local browser recorded that uncaught error, zero picker textareas,
and zero external writes. Missing/null ticket info and malformed item entries
were similarly unguarded. The original mock checks always supplied a valid item
array, so they did not detect this path. This proves a real inert-click defect,
**not that the reporting browser received this response**.

The picker now validates availability and renders an accessible error with
**Retry order details**. Retry requests only approval metadata, never reloads
the order/thread or replaces the vendor composer. A loaded order keeps the
approval entry point available even when its separate ticket-info read fails.
Grouping still submits the first original index per distinct exact SKU.

Popup creation, opener detachment, initial document access, the request, response
validation and navigation are now inside the guarded launch. A real local
sandboxed iframe without popup permission reproduces the restricted-context
path; blocked windows and thrown browser restrictions show recovery instructions.
Pending tabs paint a constant opening message rather than staying blank.
The opening request times out after 30 seconds, errors retain selection/text, and
the Open button is reusable. The launch captures the initiating PO and order
generation; selecting another order aborts it and closes the waiting tab.
Same-origin alternative review links are validated before navigation. Origin
authority and explicit submission/duplicate locks are unchanged.

The review HTML contains a script-independent loading/retry notice, so a missing
review script is not an unexplained disabled form. Session-read errors/timeouts
retain that notice with visible instructions; retry loads the same saved review.
These retries do not submit a ticket.

**Verified locally:** the isolated browser asserts the first click's visible
effect, real populated review fields after the second, blank/pasted descriptions,
source indices, regional defaults, editable fields, missing ticket configuration,
malformed HTTP item data/recovery, popup restrictions, HTTP/non-JSON/network
failures, missing JS/session responses and retry, order switching and unchanged
unsaved replies. The existing direct and synthetic TLS-proxy walkthroughs and
grouped-SKU browser checks also pass; all external writes are mocked/denied.
Python approval/origin/submission tests and browser-side unit checks pass.
The local populated review screenshot was saved and visually inspected at
`generated-artifacts/alternative-review-verified.jpg` (synthetic data only).

**Remaining evidence gap:** the reporting browser, address and embedded context
were not probed; no permission was granted for that. Neither this local malformed
item reproduction nor the earlier local origin-mismatch reproduction establishes
the user's original cause. If further diagnosis is authorized, first request only
browser name/version, whether Quote Desk is embedded or a separate tab, and the
address's scheme/hostname/port (no path, PO, session token, query or credentials).
Confirm the read-only two-click opening at that address only with explicit
permission. No public probing, live submissions, notifications or Gmail changes
were performed here.

```sh
python3 -m unittest discover -s tests
for f in tests/*.js; do node "$f" || exit 1; done
python3 tests/alt_browser.py
```

The last command requires the test-only Playwright dependency in `requirements.txt` and an installed Chromium. It uses `/repl/tools/bin/chromium` on Replit. The fixture binds loopback on an ephemeral port, uses a temporary session store, clears configuration to fictitious values, mocks all server services and blocks browser requests outside that local origin. It verifies selection, all four regional flows, empty text/CTO defaults, editable fields, warning, success links/reload locks, partial success, uncertain creation, lost browser responses, unmapped collaborators, expiry and unchanged unsaved vendor reply/no Gmail writes.

Local screenshots are written to ignored `generated-artifacts/alternative-review.jpg` and `generated-artifacts/alternative-review-proxy.jpg`. To inspect the mock-only app separately, `python3 tests/alt_browser.py --serve` binds 127.0.0.1:5071 and prints a synthetic populated review link. The TLS fixture uses Werkzeug's test-only ephemeral certificate and Chromium ignores its certificate error only in the local test context. Do not use a public preview, live Airtable/webhook calls or Gmail mutations for verification.
