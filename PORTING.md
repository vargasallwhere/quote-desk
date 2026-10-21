# STATUS 2026-09-29: ported. Runs standalone (tested locally with env logins, no Scout Dev).
`app.py` now uses `scout_port.py` (functions copied from Scout Dev, logins from env) and `gmail_auth.py` (env token).
<<<<<<< HEAD
Alternative Approval Ticket now runs standalone; only Price Approval and Autopilot remain hidden without `SCOUT_URL`. See `ALTERNATIVE_APPROVALS.md` for configuration and safe verification.

## Standalone Alternative Approval — 2026-10-20

The supplied focused device parser, alternative enrichment, review fields, Airtable mapping and automated-approvals webhook contract are ported into the existing Flask/HTML app. Scout's startup jobs, desktop paths and unrelated workflows are not imported. Same-origin reviews are isolated, expire after two hours and retain submission locks/results across process restarts. The source UI is adapted to a wide dedicated tab.

Only explicit submission can create a ticket and trigger notification. Missing settings and unmapped collaborators block writes. Successful creation survives webhook failures as partial success with its ticket link. Unknown write outcomes are locked with a check-Airtable warning. No automatic write retries, order external links, or Gmail notification path were added. The contradictory webhook `multipleSKU` field is omitted, while the Airtable checkbox remains.

Regression and local Chromium verification use mocked order, Airtable, webhook and Gmail services only. No live records, notifications, Gmail writes, public preview or deployment are used. Historical notes below describe earlier states, not current behavior; in particular, the vendor-email price experiment below was superseded by the current no-price rules in `replit.md`.

## Catalog verification — 2026-10-07

Valid product-service credentials were supplied through Replit Secrets. Read-only authenticated requests to `https://product.allwhere.co/v1/product-variants/{id}` succeeded with HTTP 200 using Basic authentication in this workspace. Returned variant IDs and SKUs matched the exact orders:

| Order | Variant ID | SKU | Catalog MPN |
|---|---|---|---|
| 161876-1-JUST | 686df253-3798-40b6-aec1-c776c6091323 | 16699 | KM3322W-R-UK |
| 161876-1-JUST | bd389f4e-97d9-4c80-8188-7ae0b7ba9d64 | 16702 | KM555-BLK-UK |
| 161880-1-JUST | 690b978a-a4f2-441b-a6fe-714369436176 | 10237 | LS24D310EAUXXU |

All three have non-null structured catalog MPNs. Samsung's snapshot has null MPN, but no description parsing is needed: its part number was independently verified in the authenticated catalog. Earlier legacy endpoint 404s do not prove deletion or migration.

After the client changes, the read-only EU email builder and GET `/api/order/{po}` and `/api/ticket-info/{po}` were exercised for both orders against the live services. Both endpoints returned HTTP 200 and the expected SKU-to-MPN mappings without catalog warnings. Gmail was disabled for these checks; no live drafts were inspected, created, edited, sent, or deleted.

This verifies the workspace used for these checks, not a separate peer's desktop environment or a published deployment. Neither was accessed or changed. The application loads catalog credentials per request rather than retaining an import-time empty authorization header. For local UI verification, run the local-only console workflow, not a public preview.

### Vendor auto-quote prices

The regional templates now explicitly include product-service catalog unit prices. Live read-only EU quote checks verified USD 27.85 for SKU 16699, USD 55.70 for SKU 16702, and USD 129.18 for SKU 10237 under their respective verified MPNs. These are unit prices, not quantity-multiplied totals. Unavailable catalog prices are labeled unavailable rather than replaced with order-snapshot prices.

All 34 Python tests and the three browser-side scripts passed after this change, including coverage for warranty prices, duplicate quantities, missing pricing, and explicit zero. The auto-draft wrapper was tested only with mocked Gmail; existing live Gmail drafts remain unchanged.
=======
Order Notes, Price Approval and Generate Autopilot Form now run inside Quote Desk (`scout_port_buttons.py`, `panel/`), no Scout Dev needed. Only Alternative Approval still hides itself unless `SCOUT_URL` is set.
`python3 check_port.py` proves the copied functions match Scout Dev (expected differences: env-based logins, AIRTABLE_PAT, autopilot's imports).
>>>>>>> c175c91b4b8d7748a99529b2127e7ae5ca6ee043

## Replit secrets to add (names only)
`GMAIL_TOKEN_JSON` (contents of gmail_token.json), `ALLWHERE_USER`, `ALLWHERE_PASS`, `PS_USER`, `PS_PASS`, plus for the new buttons `AIRTABLE_PAT` (Price Approval) and `GOOGLE_SHEETS_TOKEN_JSON` (contents of sheets_token.json, Drive+Sheets scope; Autopilot).

---
Original notes:

# Porting Quote Desk to Replit

Quote Desk runs today only on Sara's Mac. `app.py` borrows three things from Scout Dev that do not exist on Replit.

## What must be replaced

| Borrowed from Scout Dev | Used for | Replit plan |
|---|---|---|
| `gmail_auth.get_gmail_service()` (reads `~/Claude_projects/gmail_token.json`) | Every Gmail read, draft and send | Read the token JSON from the Replit secret `GMAIL_TOKEN_JSON`. Same scopes: gmail.compose + gmail.readonly. |
| `order_confirm_engine.fetch_full_order`, `build_confirmation_email` | Order details, US confirmation text | Copy these two functions (and the helpers they call) into this repo. Do NOT copy `scout_engine.py`. |
| `scout_engine.ALLWHERE_AUTH` | Allwhere order API login | Replit secrets `ALLWHERE_USER`, `ALLWHERE_PASS` |
| `scout_engine.generate_auto_quote_email` and the UK/EU/US email builders | "Draft quote request email" button | Port the routing table and email text builders. Routing (AU goes to John + Uyen) lives in `generate_auto_quote_email`. |
| Scout Dev on `localhost:5002`: `/order-info` (CTO, warranty flags, approvals), `/parse-alt-description`, `/review-session`, `/review-v2`, `/review-pricing`, `/autopilot-sheet`, `/daily-card` | Banners, Alternative Approval, Price Approval, Autopilot, TD confirmation card | `/order-info` must be ported (banners + Manual AR depend on it). The review pages, Autopilot and daily card can stay out of the first Replit version. Hide those buttons there. |

## Warning: hardcoded credentials
`sourcing-scout-dev/backend/scout_engine.py` contains hardcoded logins and keys (Allwhere, product service, TD Synnex, Ingram, Airtable). Never copy that file into this repo. Read every credential from Replit secrets instead.

## Secrets Sara enters in Replit (names only)
`GMAIL_TOKEN_JSON`, `ALLWHERE_USER`, `ALLWHERE_PASS`, plus product-service login if `/order-info` needs it.
Do not paste secret values into a chat.

## Also change
- Port: `app.run(port=5070)` becomes the port Replit provides (`0.0.0.0`, from `PORT`).
- Replit has no `localhost:5002`. Remove the `SCOUT` constant and the Scout-proxy routes for the first version.
- Sends are real emails. Keep the two-click send and the "already has a thread/draft" guard.
