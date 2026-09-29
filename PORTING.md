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
