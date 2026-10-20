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

Keep the file on ordinary restarts to preserve locks/results. A process interrupted during a write leaves the review locked in submitting state and must be reconciled manually. Deleting/replacing the file or moving to another host invalidates old reviews; it is not a retry mechanism. Multiple hosts with separate local files are not supported. Authentication and shared-host deployment remain out of scope: keep the existing localhost-only operation.

## Safe verification

```sh
python3 -m unittest discover -s tests
for f in tests/*.js; do node "$f" || exit 1; done
python3 tests/alt_browser.py
```

The last command requires the test-only Playwright dependency in `requirements.txt` and an installed Chromium. It uses `/repl/tools/bin/chromium` on Replit. The fixture binds loopback on an ephemeral port, uses a temporary session store, clears configuration to fictitious values, mocks all server services and blocks browser requests outside that local origin. It verifies selection, all four regional flows, empty text/CTO defaults, editable fields, warning, success links/reload locks, partial success, uncertain creation, lost browser responses, unmapped collaborators, expiry and unchanged unsaved vendor reply/no Gmail writes.

The local screenshot is written to ignored `generated-artifacts/alternative-review.jpg`. To inspect the mock-only app separately, `python3 tests/alt_browser.py --serve` binds 127.0.0.1:5071. Do not use a public preview, live Airtable/webhook calls or Gmail mutations for verification.
