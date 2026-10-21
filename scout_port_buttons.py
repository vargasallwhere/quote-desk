"""Order Notes, Price Approval and Autopilot Form: copied from Scout Dev (scout_engine.py / order_confirm_engine.py).
Function bodies are verbatim copies; check_port.py proves it. Only the Airtable token now comes from the environment.
Needs env: AIRTABLE_PAT, GOOGLE_SHEETS_TOKEN_JSON (or a local sheets_token.json), plus the logins scout_port.py already uses."""
import os, re, datetime as _dtmod
from datetime import datetime
import requests

from scout_port import (clean_po, get_order_header, get_order_info_for_ticket, _item_is_cto,
                        UK_COUNTRIES, EU_COUNTRIES, ALLWHERE_AUTH, ALLWHERE_BASE)


AIRTABLE_PAT     = os.environ.get("AIRTABLE_PAT", "")

AIRTABLE_BASE_ID = "appnu2ZO4IDLIErUO"

AIRTABLE_TABLE   = "tblX3ICcWUDuwVsK6"

CURRENCY_SYMBOLS = {"USD": "$", "GBP": "£", "EUR": "€"}

COLOR_MAP = {
    "MacBook Air 13": ["Silver", "Starlight", "Midnight", "Sky Blue", "Teal"],
    "MacBook Air 15": ["Silver", "Starlight", "Midnight", "Sky Blue", "Teal"],
    "MacBook Pro 14": ["Silver", "Space Black"],
    "MacBook Pro 16": ["Silver", "Space Black"],
    "Mac mini":       ["Silver"],
    "iMac":           ["Silver", "Blue", "Green", "Pink", "Orange", "Purple", "Yellow"],
}

AIRTABLE_USER_IDS = {
    "abbye@allwhere.co":            "usrchDqcvUn3598fQ",
    "alex.leinwand@allwhere.co":    "usrAmpfbDlGkJXHaG",
    "alexa@allwhere.co":            "usrJTEgJErr6LrXIz",
    "alexandra@allwhere.co":        "usr62G6M7U30f9lLt",
    "alyssa@allwhere.co":           "usrvpZKIg9Ol3UYYK",
    "andrew.strack@allwhere.co":    "usrzyDRzHgzSa8NJh",
    "ari@allwhere.co":              "usr3kZbt0FZuYL8FR",
    "ariel@allwhere.co":            "usrXI5ns8h3MFBSEd",
    "brayden@allwhere.co":          "usrVHLUqpO4MRCChc",
    "brayden.page@allwhere.co":     "usrFvAA9oqTlnwrgC",
    "calum@allwhere.co":            "usrfg2ZtxChxNYE7b",
    "christian@allwhere.co":        "usrTMItwZmioPMRk4",
    "elaine@allwhere.co":           "usrS24KVkaNB0DNAf",
    "eliza@allwhere.co":            "usrSHZ3LhtZxPWyMu",
    "fernando@allwhere.co":         "usrQvioYqPCGFyupI",
    "giancarlo@allwhere.co":        "usrGjzPOYqQGOt8tP",
    "gigi@allwhere.co":             "usrgVspKrbTfdoBIr",
    "grace@allwhere.co":            "usrvAeIwJbROPiHlb",
    "haris@allwhere.co":            "usr3krZpuUH1kYsoh",
    "isabella@allwhere.co":         "usraT3HVeEiVTVi4j",
    "jadyn@allwhere.co":            "usrq9cfjfDGjqFiwh",
    "jared@allwhere.co":            "usrshQGj4AT68IsqC",
    "jamie@allwhere.co":            "usrQBZ713G30DH5Bx",
    "jeff@allwhere.co":             "usrGzypp6uh8GHyKG",
    "john@allwhere.co":             "usrrF17psw25rY9S1",
    "justin@allwhere.co":           "usr5VGrEO2E7LkQBO",
    "keajah@allwhere.co":           "usrFxqOEzpWUZaqNo",
    "kensley.russell@allwhere.co":  "usr89b9oBokZSAuV8",
    "krista@allwhere.co":           "usrAKbYsLI3qJEEng",
    "logan@allwhere.co":            "usr3EoMC2JTDseSha",
    "lola@allwhere.co":             "usrVV8LJ1m2PX9rnq",
    "manny@allwhere.co":            "usrHkpoyo6azuXCO8",
    "mario@allwhere.co":            "usrb03IzVtmKaiI5Y",
    "martin@allwhere.co":           "usreyybDkMbRoJnjR",
    "mira@allwhere.co":             "usr5GXE9eJP0Opesl",
    "noam@allwhere.co":             "usr1sp3K12T5H31f5",
    "olivia@allwhere.co":           "usr1dMqIOBuyzkZuB",
    "oscar@allwhere.co":            "usrFdBOW8YICtkFj7",
    "richard@allwhere.co":          "usrgL5tmlhtARxz5A",
    "sara@allwhere.co":             "usri2OdIIpmOl37cx",
    "vdellarciprete@allwhere.co":   "usrEH3NbPSOVQK8GP",
    "vincent@allwhere.co":          "usrOXkWeAhwJHVsC1",
    "yehuda@allwhere.co":           "usrHfKSwxwjP4LdaY",
}

_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_AUTOPILOT_TEMPLATE_DRIVE_ID = "1RUYzcnd38uHDo23CD-6ofLYSSXiFjCHO"

_AUTOPILOT_SHEET_NAME = "MS Autopilot Request Form"


def _strip_org_prefix(product_name: str) -> str:
    """Strip 'OrgName | ' prefix from Allwhere product names."""
    if " | " in product_name:
        return product_name.split(" | ", 1)[1].strip()
    return product_name


def _fmt(amount: float, currency: str = "USD") -> str:
    sym = CURRENCY_SYMBOLS.get(currency, "$")
    return f"{sym}{amount:,.2f}"


def _short_product_name(name: str) -> str:
    """Truncate after the first word following the dash separator."""
    dash_pos = name.find(" - ")
    if dash_pos == -1:
        return name
    after = name[dash_pos + 3:]
    first_word = after.split()[0] if after.strip() else ""
    return f"{name[:dash_pos]} - {first_word}".rstrip()


def detect_model_key(product_name: str) -> str:
    """Return the COLOR_MAP key for this product, or '' if no match."""
    name_words = set(re.findall(r"\w+", product_name.lower()))
    for key in sorted(COLOR_MAP.keys(), key=len, reverse=True):
        key_words = set(re.findall(r"\w+", key.lower()))
        if key_words.issubset(name_words):
            return key
    return ""


def is_peripheral(product_name: str) -> bool:
    """True if this is a peripheral/accessory (not a Mac computer)."""
    return detect_model_key(product_name) == ""


def _format_partial_order_note(item_results: list, vendor: str = "",
                               vendor_num: int = 1, currency: str = "USD") -> list:
    """
    Generate a partial order note for items that couldn't be fully resolved.
    vendor: pre-filled vendor name (e.g. "B&H") or "" for blank.
    vendor_num: the "Vendor 1:", "Vendor 2:" numbering prefix.
    Returns list of lines.
    """
    today = datetime.now().strftime("%m/%d/%Y")
    vendor_label = f"Vendor {vendor_num}:{' ' + vendor if vendor else ''}"
    lines = [vendor_label, f"Date placed: {today}", ""]

    # Group by variant_id — Allwhere may return qty>1 as separate unit-per-row entries
    grouped: dict = {}
    group_order: list = []
    for ir in item_results:
        item = ir["item"]
        key  = item.get("variant_id") or _strip_org_prefix(item.get("product_name", "")) or id(ir)
        if key not in grouped:
            grouped[key] = {
                "pname": _strip_org_prefix(item.get("product_name", "")),
                "price": item.get("price_charged", 0),
                "qty":   0,
                "mpn":   ir.get("result", {}).get("requested_mpn", ""),
            }
            group_order.append(key)
        grouped[key]["qty"] += item.get("quantity", 1)

    for i, key in enumerate(group_order, 1):
        g = grouped[key]
        if g["qty"] > 1:
            lines.append(f"{g['qty']}X")
        if g["mpn"]:
            lines.append(g["mpn"])
        lines.append(f"Item {i}: {_short_product_name(g['pname'])}")
        lines += [
            f"Price Charged: {_fmt(g['price'], currency)}",
            "Price Paid:",
            "",
        ]

    all_peripheral = all(is_peripheral(ir["item"].get("product_name", "")) for ir in item_results)
    lines += ["VendTax:", "VendShip:"]
    is_intl = vendor.startswith("Select ")
    if not all_peripheral and not is_intl:
        lines.append("Adult Signature Fee:")
    lines += ["", "Order #:", "________________"]
    return lines


def generate_order_note(order_number: str) -> dict:
    """
    Generate the formatted partial-PO order note for all items in an order.
    Returns {"note": ..., "cto_detected": bool, "lead_time_approved": bool}
    or {"error": "..."}.
    """
    header = get_order_header(order_number)
    if "error" in header:
        return header

    ew_fields = {
        "enterprise_warranty":       header.get("enterprise_warranty", False),
        "enterprise_warranty_notes": header.get("enterprise_warranty_notes", ""),
    }

    info = get_order_info_for_ticket(order_number)
    if "error" in info:
        return {**info, **ew_fields}

    lead_time_approved = info.get("lead_time_approved", False)
    # asset_id set = order item is tied to an existing, already-deployed asset
    # (e.g. a reassignment/redeploy), not new stock to purchase. Including it
    # in the note reads as "buy this" and causes duplicate/unnecessary orders.
    items = [i for i in info.get("items", []) if not i.get("asset_id")]

    if not items:
        internal = info.get("internal_notes", "").strip()
        if internal:
            return {"note": internal, "cto_detected": False, "lead_time_approved": lead_time_approved, **ew_fields}
        return {"error": "No items found for this order", **ew_fields}

    # Detect CTO across all items
    cto_detected = any(_item_is_cto(i, lead_time_approved) for i in items)
    cto_mpns     = [i["mpn"] for i in items if (i.get("mpn") or "").upper().startswith("Z")]

    item_results = []
    for item in items:
        item_results.append({
            "item": {
                "variant_id":    item.get("variant_id", ""),
                "product_name":  item.get("product_name", ""),
                "price_charged": item.get("price", 0),
                "quantity":      item.get("quantity", 1),
            },
            "result": {
                "requested_mpn": item.get("mpn", ""),
            },
        })

    # AppleCare → included at end. Kits (non-AppleCare) → silently skipped.
    applecare_irs = [ir for ir in item_results
                     if re.search(r"apple\s*care", ir["item"].get("product_name", ""), re.IGNORECASE)]
    other_irs     = [ir for ir in item_results
                     if not re.search(r"apple\s*care", ir["item"].get("product_name", ""), re.IGNORECASE)
                     and not re.search(r"\bkit\b",        ir["item"].get("product_name", ""), re.IGNORECASE)]

    shipping_country = (header.get("shipping_country") or "").strip().lower()
    if shipping_country in UK_COUNTRIES:
        vendor = "Select UK"
    elif shipping_country in EU_COUNTRIES:
        vendor = "Select EU"
    else:
        vendor = ""

    currency = header.get("currency", "USD")
    note_lines = _format_partial_order_note(other_irs + applecare_irs, vendor=vendor, vendor_num=1, currency=currency)
    return {
        "note":               "\n".join(note_lines).rstrip(),
        "cto_detected":       cto_detected,
        "cto_mpns":           cto_mpns,
        "lead_time_approved": lead_time_approved,
        **ew_fields,
    }


def add_order_external_link(order_number: str, url: str) -> bool:
    """
    Appends url to the externalLinks array on the Allwhere order.
    Fetches current links first so existing ones are preserved.
    Returns True on success, False on any failure (best-effort).
    """
    po_clean = clean_po(order_number)
    try:
        r = requests.get(
            f"{ALLWHERE_BASE}/order",
            auth=ALLWHERE_AUTH,
            params={"orderNumber": po_clean},
            timeout=15,
        )
        if r.status_code != 200 or not r.json().get("items"):
            return False
        order    = r.json()["items"][0]
        order_id = order["id"]
        existing = order.get("externalLinks") or []
        if url in existing:
            return True
        patch = requests.patch(
            f"{ALLWHERE_BASE}/order/{order_id}",
            auth=ALLWHERE_AUTH,
            json={"externalLinks": existing + [url]},
            timeout=15,
        )
        return patch.status_code in (200, 201)
    except Exception:
        return False


def create_pricing_approval_ticket(order_number: str, header: dict, products_text: str) -> dict:
    """
    Creates an Automated Pricing Approval ticket in ALLWHERE TICKETS.
    products_text is the pre-formatted block:
      SKU
      Product Name
      Old Price
      New Price
    """
    is_rush  = header.get("is_rush", False)
    org_name = header.get("org_name", "")

    fields = {
        "fldeKFtQ0zJr7C9oh": "Automated Pricing Approval",   # Action Request Type
        "fldebG0qifOIDrXKE": "Urgent" if is_rush else "High", # Priority
        "fldcBGJ46hG6aF2M3": order_number,                    # Order #
        "fldRrlioYQwe0DOf0": products_text,                    # Product #1 Name (products text)
    }

    if org_name:
        fields["fldIDtJqa4jgz6O7p"] = org_name                # Organization

    pm_email = header.get("procurement_manager_email", "")
    pm_id    = AIRTABLE_USER_IDS.get(pm_email)
    if pm_id:
        fields["fldCDwjxPNuLMT0ub"] = [{"id": pm_id}]         # Requested By

    om_email = header.get("order_manager_email", "")
    om_id    = AIRTABLE_USER_IDS.get(om_email)
    if om_id:
        fields["fldXipHrKdmbdx6pA"] = [{"id": om_id}]         # Assigned To

    fields = {k: v for k, v in fields.items() if v != ""}

    try:
        resp = requests.post(
            f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE}",
            headers={
                "Authorization": f"Bearer {AIRTABLE_PAT}",
                "Content-Type":  "application/json",
            },
            json={"fields": fields},
            timeout=15,
        )
        data = resp.json()
        if resp.status_code in (200, 201):
            rec_id = data.get("id", "")
            return {
                "ok":        True,
                "record_id": rec_id,
                "url":       f"https://airtable.com/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE}/{rec_id}",
            }
        else:
            return {"error": data.get("error", {}).get("message") or str(data)}
    except Exception as e:
        return {"error": str(e)}


def _get_google_creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    import os as _os2, json as _json2
    token_json = _os2.environ.get("GOOGLE_SHEETS_TOKEN_JSON", "")
    if token_json:
        creds = Credentials.from_authorized_user_info(_json2.loads(token_json), _GOOGLE_SCOPES)
    else:
        TOKEN_FILE = _os2.path.expanduser("~/Claude_projects/sheets_token.json")
        if not _os2.path.exists(TOKEN_FILE):
            raise FileNotFoundError("Finance sheet not set up. Ask Sara for help.")
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, _GOOGLE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def _get_sheets_service():
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=_get_google_creds()).spreadsheets()


def _get_drive_service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_get_google_creds())


def create_autopilot_review_sheet(order_data):
    """Copy the TD Synnex Autopilot template on Google Drive, fill in order data. Returns the sheet URL."""
    ap = order_data.get("autopilot_info") or {}
    purchaser = order_data["purchaser"]
    today = _dtmod.date.today().strftime("%m/%d/%Y")
    po = order_data["order_number"]

    drive = _get_drive_service()
    copied = drive.files().copy(
        fileId=_AUTOPILOT_TEMPLATE_DRIVE_ID,
        body={
            "name": f"Autopilot Form - {po}",
            "mimeType": "application/vnd.google-apps.spreadsheet",
        },
    ).execute()
    new_id = copied["id"]

    sheet_ref = f"'{_AUTOPILOT_SHEET_NAME}'"
    cell_updates = [
        (f"{sheet_ref}!I14", today),
        (f"{sheet_ref}!A16", purchaser["name"]),
        (f"{sheet_ref}!E16", purchaser["email"]),
        (f"{sheet_ref}!J25", "X"),
        (f"{sheet_ref}!B39", ap.get("name", order_data["org_name"])),
        (f"{sheet_ref}!B40", ap.get("domain", "")),
        (f"{sheet_ref}!B41", ap.get("id", "")),
        (f"{sheet_ref}!B42", po),
    ]

    ss = _get_sheets_service()
    ss.values().batchUpdate(
        spreadsheetId=new_id,
        body={
            "valueInputOption": "RAW",
            "data": [{"range": rng, "values": [[val]]} for rng, val in cell_updates],
        },
    ).execute()

    return f"https://docs.google.com/spreadsheets/d/{new_id}/edit"
