"""Airtable Alternate Approval payloads and single-attempt external writes."""
import json
import os
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlsplit

import requests

ALT_TYPES = ("Out of stock / backordered", "CTO device", "EOL device",
             "Build / model does not exist", "Shipping speed unavailable", "Unavailable in region")
SUB_TYPES = ("Model unavailable", "Color unavailable", "Keyboard language unavailable",
             "Storage (SSD) unavailable", "Processor unavailable", "Display unavailable",
             "Memory (RAM) unavailable", "Other")
DEVICE_TYPES = ("Laptop", "Tablet", "Mobile Phone", "Other")
REQUESTERS = [
    {"email": "sara@allwhere.co", "name": "Sara Vargas"},
    {"email": "keajah@allwhere.co", "name": "Keajah"},
    {"email": "giancarlo@allwhere.co", "name": "Giancarlo Sanchez"},
    {"email": "olivia@allwhere.co", "name": "Olivia"},
    {"email": "emma@allwhere.co", "name": "Emma Vasey"},
]
FIELD_MAP = {
    "requested_sku": "fldMJEbwUw0CqIoHg", "multiple_skus": "fldyd6IBR3KibgUuS",
    "device_type": "fld32xZvPtF9cbSEU", "make": "fldulC1rDDTsalmKc",
    "model": "fldBoqiTT5plbMzvX", "processor": "fldarIWmFLfm6VZgL",
    "storage": "fldfuX8Bt5OHsX86A", "memory": "fldV5gLCmINlyf6v8",
    "display_size": "fldYcRSBVPbsSKHRw", "keyboard_language": "fldbbayVkyrVFg7nb",
    "color": "fldCC32qR3dxpk1uW", "sku_country": "fld3dCMkB6hK4nfvi",
    "price": "flddENlxF5Xg8EnPI", "mpn": "fldchZyDD59k8ovxy",
    "lead_time": "fldwNopw8xbc8nHmi",
}


def configuration():
    keys = ("AIRTABLE_PAT", "AIRTABLE_BASE_ID", "AIRTABLE_TABLE",
            "AUTOMATED_APPROVALS_WEBHOOK_URL", "AUTOMATED_APPROVALS_WEBHOOK_SECRET")
    cfg = {k: os.environ.get(k, "").strip() for k in keys}
    errors = [f"Set {k} in workspace Secrets before submitting." for k in keys if not cfg[k]]
    if cfg["AIRTABLE_BASE_ID"] and not re.fullmatch(r"app[A-Za-z0-9]+", cfg["AIRTABLE_BASE_ID"]):
        errors.append("AIRTABLE_BASE_ID must be an Airtable base ID beginning with app.")
    if cfg["AIRTABLE_TABLE"] and not re.fullmatch(r"tbl[A-Za-z0-9]+", cfg["AIRTABLE_TABLE"]):
        errors.append("AIRTABLE_TABLE must be the destination table ID beginning with tbl.")
    try:
        url = urlsplit(cfg["AUTOMATED_APPROVALS_WEBHOOK_URL"])
        valid_url = (url.scheme == "https" and url.hostname and not url.username
                     and not url.password and not url.fragment and url.port != 0)
    except ValueError:
        valid_url = False
    if cfg["AUTOMATED_APPROVALS_WEBHOOK_URL"] and not valid_url:
        errors.append("AUTOMATED_APPROVALS_WEBHOOK_URL must be a valid HTTPS URL without credentials or fragment.")
    try:
        users = json.loads(os.environ.get("AIRTABLE_USER_IDS_JSON", "{}"))
        if not isinstance(users, dict) or any(
                not isinstance(k, str) or "@" not in k or not isinstance(v, str)
                or not re.fullmatch(r"usr[A-Za-z0-9]+", v) for k, v in users.items()):
            raise ValueError
        cfg["users"] = {k.strip().lower(): v for k, v in users.items()}
    except (ValueError, TypeError):
        cfg["users"] = {}
        errors.append("AIRTABLE_USER_IDS_JSON must map email addresses to Airtable usr IDs.")
    if not cfg["users"]:
        errors.append("Configure AIRTABLE_USER_IDS_JSON for Requested By and Assigned To.")
    for k in ("AIRTABLE_PAT", "AUTOMATED_APPROVALS_WEBHOOK_SECRET"):
        if "\n" in cfg[k] or "\r" in cfg[k]:
            errors.append(f"Correct the invalid {k} in workspace Secrets.")
    return cfg, errors


def requester_options(review):
    options = [dict(o) for o in REQUESTERS]
    email = review.get("procurement_manager_email", "").strip().lower()
    if email and email not in {o["email"] for o in options}:
        options.append({"email": email, "name": review.get("procurement_manager_name") or email})
    return options


def mapping_errors(review, requested_by, cfg):
    errors = []
    for label, email in (("Requested By", requested_by), ("Assigned To (order manager)", review.get("order_manager_email"))):
        if not email:
            errors.append(f"{label} has no email. Resolve the order manager or select Requested By before submitting.")
        elif email.strip().lower() not in cfg["users"]:
            errors.append(f"{label}: {email} is unmapped. Add this email to AIRTABLE_USER_IDS_JSON; no assignment has been saved.")
    return errors


def validate_ticket(data, review):
    if not isinstance(data, dict):
        raise ValueError("Submit a JSON object containing the reviewed fields.")
    ticket = {}
    required = set(FIELD_MAP) - {"multiple_skus", "mpn", "lead_time"}
    for key in (*FIELD_MAP, "alt_type", "alt_subtype", "requested_by"):
        val = data.get(key, "")
        if key == "multiple_skus":
            if type(val) is not bool:
                raise ValueError("Multiple SKUs must be a checkbox value.")
        else:
            if not isinstance(val, str) or len(val) > 1000 or any(ord(c) < 32 for c in val):
                raise ValueError(f"Enter a valid {key.replace('_', ' ')} (up to 1000 characters).")
            val = val.strip()
            if key in required and not val:
                raise ValueError(f"Enter {key.replace('_', ' ')} before submitting.")
        ticket[key] = val
    for key, choices in (("alt_type", ALT_TYPES), ("alt_subtype", SUB_TYPES), ("device_type", DEVICE_TYPES)):
        if ticket[key] not in choices:
            raise ValueError(f"Select a valid {key.replace('_', ' ')}.")
    ticket["requested_by"] = ticket["requested_by"].lower()
    if ticket["requested_by"] not in {o["email"] for o in requester_options(review)}:
        raise ValueError("Select Requested By from the review's procurement users.")
    try:
        price = Decimal(ticket["price"])
        if not price.is_finite() or price < 0 or price > Decimal("999999999.99"):
            raise InvalidOperation
    except InvalidOperation:
        raise ValueError("Price must be a finite, non-negative USD amount, without currency symbols or commas.") from None
    if ticket["alt_type"] not in ("CTO device", "Out of stock / backordered"):
        ticket["lead_time"] = ""
    return ticket


def airtable_fields(review, ticket, cfg):
    fields = {field: ticket[key] for key, field in FIELD_MAP.items()}
    fields.update({
        "fldeKFtQ0zJr7C9oh": "Alternate Approval",
        "fldebG0qifOIDrXKE": "Urgent" if review.get("is_rush") else "High",
        "fldcBGJ46hG6aF2M3": review["order_number"],
        "fldXxx6BIslbdAhgT": [ticket["alt_type"]],
        "fldmbDKEdzVJlBald": [ticket["alt_subtype"]],
        "fldQtfsOMZblbXVP4": "No", "fldIW7HeL5uq1W9iI": True,
        "fldCDwjxPNuLMT0ub": [{"id": cfg["users"][ticket["requested_by"]]}],
        "fldXipHrKdmbdx6pA": [{"id": cfg["users"][review["order_manager_email"].lower()]}],
        "fldIDtJqa4jgz6O7p": review.get("org_name", ""),
    })
    return {k: v for k, v in fields.items() if v != ""}


def webhook_payload(record_id, fields, review, ticket):
    payload = {
        "record_id": record_id, "status": fields.get("Status", ""),
        "orderNumbers": [review["order_number"]], "requestedSKU": ticket["requested_sku"],
        "subject": fields.get("Summary/Subject", ""), "alternativeType": ticket["alt_type"],
        "secondAlt": False, "leadTime": ticket["lead_time"],
    }
    for target, key in (("make", "make"), ("model", "model"), ("processor", "processor"),
                        ("memory", "memory"), ("storage", "storage"), ("language", "keyboard_language"),
                        ("color", "color"), ("display", "display_size"), ("price", "price"), ("mpn", "mpn")):
        payload[target] = ticket[key]
        payload["secondAlt" + ("MPN" if target == "mpn" else target[0].upper() + target[1:])] = ""
    # The supplied validator requires multipleSKU null/omitted, despite source code emitting true.
    return payload


def create_ticket(review, ticket, cfg, checkpoint):
    """Never retry a write. Persist the record BEFORE attempting notification."""
    base, table = cfg["AIRTABLE_BASE_ID"], cfg["AIRTABLE_TABLE"]
    try:
        resp = requests.post(
            f"https://api.airtable.com/v0/{quote(base)}/{quote(table)}",
            headers={"Authorization": "Bearer " + cfg["AIRTABLE_PAT"], "Content-Type": "application/json"},
            json={"fields": airtable_fields(review, ticket, cfg)}, timeout=15, allow_redirects=False)
    except requests.RequestException:
        return {"ok": False, "state": "uncertain", "retryable": False,
                "error": "Airtable creation outcome is unknown. Check Airtable for this order before taking any further action. Do not resubmit."}
    if resp.status_code not in (200, 201):
        # 5xx may occur after a write; do not assume rejection.
        uncertain = resp.status_code >= 500 or 300 <= resp.status_code < 400 or resp.status_code == 408
        return {"ok": False, "state": "uncertain" if uncertain else "pending", "retryable": not uncertain,
                "error": (f"Airtable returned HTTP {resp.status_code}. Check Airtable before any further action; do not resubmit."
                          if uncertain else f"Airtable rejected the request (HTTP {resp.status_code}); no ticket was confirmed. Check destination, permissions and field configuration.")}
    try:
        data = resp.json()
        rec_id = data["id"]
        if not isinstance(rec_id, str) or not re.fullmatch(r"rec[A-Za-z0-9]+", rec_id):
            raise ValueError
        fields = data.get("fields", {})
        if not isinstance(fields, dict):
            fields = {}
    except (ValueError, KeyError, TypeError):
        return {"ok": False, "state": "uncertain", "retryable": False,
                "error": "Airtable accepted the request but its ticket ID could not be read. Check Airtable; do not resubmit."}
    result = {"ok": True, "created": True, "record_id": rec_id,
              "url": f"https://airtable.com/{base}/{table}/{rec_id}",
              "state": "completed", "retryable": False, "notification": "uncertain",
              "message": "Ticket created. Notification is not confirmed. Do not create another ticket; check Airtable."}
    checkpoint(result)
    try:
        resp = requests.post(cfg["AUTOMATED_APPROVALS_WEBHOOK_URL"],
                             headers={"Content-Type": "application/json", "X-Webhook-Secret": cfg["AUTOMATED_APPROVALS_WEBHOOK_SECRET"]},
                             json=webhook_payload(rec_id, fields, review, ticket), timeout=15, allow_redirects=False)
        if 200 <= resp.status_code < 300:
            result.update(notification="accepted", message="Ticket created; notification workflow accepted the request. This does not confirm email delivery.")
        else:
            result.update(notification="failed", message=f"Ticket created, but notification webhook returned HTTP {resp.status_code}. Do not create another ticket; check the notification workflow.")
    except requests.RequestException:
        result["message"] = "Ticket created, but notification outcome is unknown. Do not create another ticket or resend automatically; check the notification workflow."
    return result
