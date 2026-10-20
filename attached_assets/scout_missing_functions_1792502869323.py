"""
Two functions that scout_app.py imports, extracted so they can be read on their own.

  parse_device_text(text)   — originally in scout_sku_lookup.py
  create_airtable_ticket_v2 — originally in scout_engine.py

All credentials/IDs below are read from environment variables (set them as Replit Secrets).
"""

import logging
import os
import re

import requests

# ══════════════════════════════════════════════════════════════════════════════
# parse_device_text — extract specs from the pasted vendor alternative
# ══════════════════════════════════════════════════════════════════════════════

# "13inch", "13 inch", "13-inch", "13 inches" → keep just "13"
_SIZE_INCH_RE = re.compile(r'(\d+)\s*[-\s]?inch(?:es)?', re.IGNORECASE)
# '13"', including Unicode curly quotes → keep just "13"
_SIZE_QUOTE_RE = re.compile(r'(\d+)["“”‘’ʼʹ]')

_CHIP_PARSE_RE  = re.compile(r'\b(M\d+\s*(?:Pro|Max|Ultra)?)\b', re.IGNORECASE)
_APPLE_RAM_GB   = {8, 16, 18, 24, 32, 36, 48, 64, 96, 128}
_MEM_RE         = re.compile(r'\b(\d+)\s*[-\s]?GB(?:\s*(?:RAM|memory|unified))?', re.IGNORECASE)
_STOR_TB_RE     = re.compile(r'\b(\d+)\s*TB\b', re.IGNORECASE)
_STOR_GB_RE     = re.compile(r'\b(256|512|1024|2048)\s*GB\b', re.IGNORECASE)
# Non-breaking hyphen (U+2011) — Apple product pages use this instead of a regular hyphen
_NB_HYPHEN = '‑'

# CPU/GPU core counts. Handles "10-core 10-core", non-breaking hyphens,
# and "10-core CPU 10-core GPU" (Apple product page / alt approval format)
_CORES_RE = re.compile(
    r'\b(\d+)[\s\-' + _NB_HYPHEN + r']?core(?:\s+(?:cpu|processor))?\s+(\d+)[\s\-' + _NB_HYPHEN + r']?core\b',
    re.IGNORECASE,
)
_CORES_SLASH_RE = re.compile(r'\b(\d+)\s*[Cc]/(\d+)\s*[Cc]\b')

_COLOR_OPTIONS = [
    "Space Black", "Space Gray", "Space Grey", "Silver", "Starlight",
    "Midnight", "Sky Blue", "Teal", "Blue", "Green", "Pink",
    "Orange", "Purple", "Yellow", "Gold", "Rose Gold",
]
_COLORS_BY_LEN = sorted(_COLOR_OPTIONS, key=len, reverse=True)  # longest first → greedy

_MODEL_PATTERNS = [
    # MacBook Pro with screen size — both orderings, size normalized to bare number
    (r'macbook\s*pro\s*16|16\s*macbook\s*pro|macbook\s*pro.*\b16\b|\b16\b.*macbook\s*pro', 'MacBook Pro 16'),
    (r'macbook\s*pro\s*14|14\s*macbook\s*pro|macbook\s*pro.*\b14\b|\b14\b.*macbook\s*pro', 'MacBook Pro 14'),
    # MacBook Air with screen size — both orderings
    (r'macbook\s*air\s*15|15\s*macbook\s*air|macbook\s*air.*\b15\b|\b15\b.*macbook\s*air', 'MacBook Air 15'),
    (r'macbook\s*air\s*13|13\s*macbook\s*air|macbook\s*air.*\b13\b|\b13\b.*macbook\s*air', 'MacBook Air 13'),
    # Generic model names (no size)
    (r'macbook\s*pro',  'MacBook Pro'),
    (r'macbook\s*air',  'MacBook Air'),
    (r'mac\s*mini',     'Mac mini'),
    (r'imac\s*24|24[\-\s]?inch\s*imac|\b24\b.*imac|imac.*\b24\b', 'iMac 24'),
    (r'imac',           'iMac'),
    (r'mac\s*pro',      'Mac Pro'),
    (r'ipad\s*pro',     'iPad Pro'),
    (r'ipad\s*air',     'iPad Air'),
    (r'ipad\s*mini',    'iPad mini'),
    (r'ipad',           'iPad'),
    (r'iphone',         'iPhone'),
    (r'macbook',        'MacBook'),
    # Laptop/notebook synonym with screen size (size numbers only, not GB/TB values)
    (r'(?:laptop|notebook).*\b16\b(?!\s*(?:gb|tb))|\b16\b(?!\s*(?:gb|tb)).*(?:laptop|notebook)', 'MacBook Pro 16'),
    (r'(?:laptop|notebook).*\b14\b(?!\s*(?:gb|tb))|\b14\b(?!\s*(?:gb|tb)).*(?:laptop|notebook)', 'MacBook Pro 14'),
    (r'(?:laptop|notebook).*\b15\b(?!\s*(?:gb|tb))|\b15\b(?!\s*(?:gb|tb)).*(?:laptop|notebook)', 'MacBook Air 15'),
    (r'(?:laptop|notebook).*\b13\b(?!\s*(?:gb|tb))|\b13\b(?!\s*(?:gb|tb)).*(?:laptop|notebook)', 'MacBook Air 13'),
    (r'laptop|notebook', 'MacBook'),
]


def parse_device_text(text: str) -> dict:
    """
    Extract device specs from free-form text.
    Returns {model_query, chip, memory, storage, color, cpu_cores, gpu_cores} — any can be None.
    """
    # Pre-normalize size refs (13", 13-inch → 13) before model detection
    tn = _SIZE_INCH_RE.sub(lambda m: m.group(1), text)
    tn = _SIZE_QUOTE_RE.sub(lambda m: m.group(1), tn)
    tn = tn.replace('"', '').replace("'", '')
    tl = tn.lower()

    # Model
    model_query = None
    for pattern, label in _MODEL_PATTERNS:
        if re.search(pattern, tl):
            model_query = label
            break

    # Chip (e.g. "M4 Pro", "m5 max", "M4pro")
    chip = None
    m = _CHIP_PARSE_RE.search(tn)
    if m:
        raw = m.group(1).strip()
        raw = re.sub(r'^[mM](\d+)', lambda x: f'M{x.group(1)}', raw)
        raw = re.sub(r'\s*(Pro|Max|Ultra)', lambda x: f' {x.group(1).capitalize()}',
                     raw, flags=re.IGNORECASE)
        chip = raw.strip()

    # Storage: TB wins; then common GB storage sizes
    storage = None
    m = _STOR_TB_RE.search(tn)
    if m:
        storage = f"{m.group(1)} TB"
    else:
        m = _STOR_GB_RE.search(tn)
        if m:
            storage = f"{m.group(1)} GB"

    # Memory: first GB value in Apple RAM range
    memory = None
    for m in _MEM_RE.finditer(tn):
        val = int(m.group(1))
        if val in _APPLE_RAM_GB:
            memory = f"{val} GB"
            break

    # Color: longest match wins
    color = None
    for c in _COLORS_BY_LEN:
        if c.lower() in tl:
            color = c
            break

    # CPU/GPU core counts — relevant for base chips (e.g. M5 10-core/8-core vs 10-core/10-core)
    cpu_cores = None
    gpu_cores = None
    cm = _CORES_RE.search(tn)
    if cm:
        cpu_cores = int(cm.group(1))
        gpu_cores = int(cm.group(2))
    else:
        cm = _CORES_SLASH_RE.search(tn)
        if cm:
            cpu_cores = int(cm.group(1))
            gpu_cores = int(cm.group(2))

    return {
        "model_query": model_query,
        "chip":        chip,
        "memory":      memory,
        "storage":     storage,
        "color":       color,
        "cpu_cores":   cpu_cores,
        "gpu_cores":   gpu_cores,
    }


# ══════════════════════════════════════════════════════════════════════════════
# create_airtable_ticket_v2 — creates the Alternate Approval ticket
# ══════════════════════════════════════════════════════════════════════════════

# Set these as Replit Secrets / environment variables.
AIRTABLE_PAT      = os.environ.get("AIRTABLE_PAT", "")
AIRTABLE_BASE_ID  = os.environ.get("AIRTABLE_BASE_ID", "")
AIRTABLE_TABLE    = os.environ.get("AIRTABLE_TABLE", "")   # ALLWHERE TICKETS table
AUTOMATED_APPROVALS_WEBHOOK_URL    = os.environ.get("AUTOMATED_APPROVALS_WEBHOOK_URL", "")
AUTOMATED_APPROVALS_WEBHOOK_SECRET = os.environ.get("AUTOMATED_APPROVALS_WEBHOOK_SECRET", "")

# email → Airtable user id ("usrXXXX"), used to fill Requested By / Assigned To.
# Left empty here; the real map is internal. Those two fields are skipped when an email isn't found.
AIRTABLE_USER_IDS: dict = {}


def _notify_automated_approvals_webhook(rec_id: str, record_fields: dict,
                                         order_number: str, alt_type: str,
                                         ticket_data: dict) -> None:
    """
    Replicates the POST the Airtable automation would normally send on form submission.
    Best-effort — failure here shouldn't block ticket creation.
    """
    if not AUTOMATED_APPROVALS_WEBHOOK_SECRET:
        logging.warning("AUTOMATED_APPROVALS_WEBHOOK_SECRET not set — skipping webhook notify for %s", rec_id)
        return

    payload = {
        "record_id":           rec_id,
        "status":              record_fields.get("Status", ""),
        "orderNumbers":        [order_number] if order_number else [],
        "requestedSKU":        ticket_data.get("requested_sku", ""),
        "subject":             record_fields.get("Summary/Subject", ""),
        "alternativeType":     alt_type,
        "make":                ticket_data.get("make", ""),
        "model":               ticket_data.get("model", ""),
        "processor":           ticket_data.get("processor", ""),
        "memory":              ticket_data.get("memory", ""),
        "storage":             ticket_data.get("storage", ""),
        "language":            ticket_data.get("keyboard_language", ""),
        "color":               ticket_data.get("color", ""),
        "display":             ticket_data.get("display_size", ""),
        "price":               ticket_data.get("price", ""),
        "mpn":                 ticket_data.get("mpn", ""),
        "secondAlt":           False,
        "secondAltMake":       "",
        "secondAltModel":      "",
        "secondAltProcessor":  "",
        "secondAltMemory":     "",
        "secondAltStorage":    "",
        "secondAltLanguage":   "",
        "secondAltColor":      "",
        "secondAltDisplay":    "",
        "secondAltPrice":      "",
        "secondAltMPN":        "",
        "leadTime":            ticket_data.get("lead_time", ""),
    }
    # Validator requires multipleSKU to be null or omitted — never a boolean.
    if ticket_data.get("multiple_skus"):
        payload["multipleSKU"] = True

    try:
        resp = requests.post(
            AUTOMATED_APPROVALS_WEBHOOK_URL,
            headers={
                "Content-Type":      "application/json",
                "X-Webhook-Secret":  AUTOMATED_APPROVALS_WEBHOOK_SECRET,
            },
            json=payload,
            timeout=15,
        )
        if resp.status_code >= 300:
            logging.warning("Automated Approvals webhook returned %s for %s: %s",
                             resp.status_code, rec_id, resp.text[:300])
    except Exception as e:
        logging.warning("Automated Approvals webhook failed for %s: %s", rec_id, e)


def create_airtable_ticket_v2(order_number: str, header: dict, ticket_data: dict) -> dict:
    """
    Creates a structured V2 ticket in ALLWHERE TICKETS using the Automated Approvals
    form fields. Sets 'Send Alt/Pricing Email' = true so the customer notification fires
    exactly like the Airtable form does.
    """
    is_rush  = header.get("is_rush", False)
    org_name = header.get("org_name", "")

    alt_type    = ticket_data.get("alt_type") or "Out of stock / backordered"
    alt_subtype = ticket_data.get("alt_subtype") or "Model unavailable"

    resolved_priority = "Urgent" if is_rush else "High"

    fields = {
        # fldFikpvi5DTsVySh (Summary/Subject) intentionally omitted — auto-generated by Airtable
        "fldeKFtQ0zJr7C9oh": "Alternate Approval",                     # Action Request Type
        "fldebG0qifOIDrXKE": resolved_priority,                        # Priority
        "fldcBGJ46hG6aF2M3": order_number,                             # Order #
        "fldXxx6BIslbdAhgT": [alt_type],                               # Alternate Type
        "fldmbDKEdzVJlBald": [alt_subtype],                            # Alternate Sub-type
        "fldMJEbwUw0CqIoHg": ticket_data.get("requested_sku", ""),     # Requested Product SKU
        "fldyd6IBR3KibgUuS": bool(ticket_data.get("multiple_skus")),   # Multiple SKUs?
        "fld32xZvPtF9cbSEU": ticket_data.get("device_type", "Laptop"), # Device Type
        "fldulC1rDDTsalmKc": ticket_data.get("make", ""),              # Make
        "fldBoqiTT5plbMzvX": ticket_data.get("model", ""),             # Model
        "fldarIWmFLfm6VZgL": ticket_data.get("processor", ""),         # Processor
        "fldfuX8Bt5OHsX86A": ticket_data.get("storage", ""),           # Storage
        "fldV5gLCmINlyf6v8": ticket_data.get("memory", ""),            # Memory
        "fldYcRSBVPbsSKHRw": ticket_data.get("display_size", ""),      # Display Size
        "fldbbayVkyrVFg7nb": ticket_data.get("keyboard_language", "US"), # Keyboard Language
        "fldCC32qR3dxpk1uW": ticket_data.get("color", ""),             # Color
        "fld3dCMkB6hK4nfvi": ticket_data.get("sku_country", "US"),     # SKU Country/Region
        "flddENlxF5Xg8EnPI": ticket_data.get("price", ""),             # Price
        "fldchZyDD59k8ovxy": ticket_data.get("mpn", ""),               # MPN (if applicable)
        "fldwNopw8xbc8nHmi": ticket_data.get("lead_time", ""),         # Lead Time
        "fldQtfsOMZblbXVP4": "No",                                      # Secondary alternative?
        "fldIW7HeL5uq1W9iI": True,                                      # Send Alt/Pricing Email
    }

    pm_email = header.get("procurement_manager_email", "")
    pm_id    = AIRTABLE_USER_IDS.get(pm_email)
    if pm_id:
        fields["fldCDwjxPNuLMT0ub"] = [{"id": pm_id}]     # Requested By → procurement manager

    if org_name:
        fields["fldIDtJqa4jgz6O7p"] = org_name             # Organization

    om_email = header.get("order_manager_email", "")
    om_id    = AIRTABLE_USER_IDS.get(om_email)
    if om_id:
        fields["fldXipHrKdmbdx6pA"] = [{"id": om_id}]     # Assigned To → OM

    # Strip empty string values for text fields (keeps records clean)
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
            _notify_automated_approvals_webhook(
                rec_id, data.get("fields", {}), order_number, alt_type, ticket_data
            )
            return {
                "ok":        True,
                "record_id": rec_id,
                "url":       f"https://airtable.com/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE}/{rec_id}",
            }
        else:
            return {"error": data.get("error", {}).get("message") or str(data)}
    except Exception as e:
        return {"error": str(e)}
