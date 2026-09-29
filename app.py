"""Quote Desk v1 — read-only. Order details from Allwhere, vendor threads straight from Gmail.
Reuses Scout Dev's login and order lookup; edits nothing there."""
import base64, os, sys, time
from email.mime.text import MIMEText
from email.utils import getaddresses, formataddr
from email.utils import parsedate_to_datetime
from flask import Flask, jsonify, request, Response, send_from_directory

sys.path.insert(0, os.path.expanduser("~/Claude_projects/sourcing-scout-dev/backend"))
from gmail_auth import get_gmail_service
import requests
from order_confirm_engine import fetch_full_order, build_confirmation_email
from scout_engine import ALLWHERE_AUTH, generate_auto_quote_email

app = Flask(__name__)
_svc = {}


def gmail():
    if "s" not in _svc:
        _svc["s"] = get_gmail_service()
    return _svc["s"]


def _walk(part, out):
    out.append(part)
    for p in part.get("parts") or []:
        _walk(p, out)


def _b64(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def _message(m):
    parts = []
    _walk(m["payload"], parts)
    html = text = ""
    atts = []
    for p in parts:
        mt, body = p.get("mimeType", ""), p.get("body", {})
        if p.get("filename") and body.get("attachmentId"):
            atts.append({"name": p["filename"], "type": mt, "size": body.get("size", 0),
                         "id": body["attachmentId"], "msg": m["id"]})
        elif mt == "text/html" and body.get("data") and not html:
            html = _b64(body["data"])
        elif mt == "text/plain" and body.get("data") and not text:
            text = _b64(body["data"])
    h = {x["name"].lower(): x["value"] for x in m["payload"].get("headers", [])}
    return {"id": m["id"], "from": h.get("from", ""), "to": h.get("to", ""), "cc": h.get("cc", ""),
            "subject": h.get("subject", ""), "message_id": h.get("message-id", ""),
            "references": h.get("references", ""), "reply_to": h.get("reply-to", ""), "date": h.get("date", ""),
            "ts": int(m.get("internalDate", 0)), "labels": m.get("labelIds", []),
            "html": html, "text": text, "attachments": atts}


from googleapiclient.errors import HttpError


@app.errorhandler(HttpError)
def gmail_error(e):
    if e.resp.status == 404:
        return jsonify({"error": "That draft is no longer in Gmail (deleted or already sent). Refresh to see the current thread."}), 404
    return jsonify({"error": f"Gmail said: {e.reason}"}), 502


@app.get("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "index.html")


@app.get("/api/order/<po>")
def order(po):
    o = fetch_full_order(po)
    if "error" not in o:
        r = requests.get("https://service.production.allwhere.co/v2/order", auth=ALLWHERE_AUTH,
                         params={"orderNumber": o["order_number"]}, timeout=15).json()["items"][0]
        o["status"] = r.get("status") or ""
        import re as _re
        devices, lines = {}, []
        for oi in r.get("orderItems", []):
            snap = oi.get("productVariantSnapshot") or {}
            name = snap.get("title") or snap.get("productName") or ""
            plan = oi.get("protectionPlan")
            if plan:
                k = (name, plan)
                devices[k] = devices.get(k, 0) + int(oi.get("quantity") or 1)
            elif _re.search(r"applecare|warranty|protection|service agreement", name, _re.I):
                lines.append({"name": name, "sku": str(snap.get("sku", "")), "qty": int(oi.get("quantity") or 1),
                              "price": float(snap.get("price") or 0)})
        o["warranty"] = {"devices": [{"name": k[0], "plan": k[1], "qty": q} for k, q in devices.items()], "lines": lines}
        o["color_swap_approved"] = bool(r.get("deviceColorSwapApproved"))
        o["lead_time_approved"] = bool(r.get("flexibleLeadTimeApproved"))
    return jsonify(o)


@app.get("/api/threads/<po>")
def threads(po):
    """Every Gmail thread whose subject contains the PO, plus any draft in it. Straight from Gmail."""
    svc = gmail()
    found = svc.users().threads().list(userId="me", q=f'subject:"{po}" in:anywhere', maxResults=10).execute()
    out = []
    for t in found.get("threads", []):
        full = svc.users().threads().get(userId="me", id=t["id"], format="full").execute()
        msgs = [_message(m) for m in full["messages"]]  # Gmail's own order
        if all({"TRASH", "SPAM"} & set(m["labels"]) for m in msgs):
            continue
        out.append({"id": t["id"], "historyId": full.get("historyId"), "messages": msgs})
    out.sort(key=lambda t: max(m["ts"] for m in t["messages"]), reverse=True)
    drafts, tok = {}, None
    while True:  # every draft, not just the first page
        page = svc.users().drafts().list(userId="me", maxResults=500, pageToken=tok).execute()
        drafts.update({d["message"]["id"]: d["id"] for d in page.get("drafts", [])})
        tok = page.get("nextPageToken")
        if not tok:
            break
    return jsonify({"threads": out, "drafts": drafts, "synced": int(time.time())})


def _mime(d):
    msg = MIMEText(d["body"], "plain", "utf-8")
    msg["To"], msg["Cc"], msg["Subject"] = d["to"], d.get("cc", ""), d["subject"]
    if d.get("inReplyTo"):
        msg["In-Reply-To"] = d["inReplyTo"]
        msg["References"] = (d.get("references", "") + " " + d["inReplyTo"]).strip()
    return {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}


@app.post("/api/draft")
def save_draft():
    """Create the reply draft in this thread, or update the one already there (never a second draft)."""
    d = request.get_json()
    body = _mime(d)
    body["threadId"] = d["threadId"]
    drafts = gmail().users().drafts()
    if d.get("draftId"):
        r = drafts.update(userId="me", id=d["draftId"], body={"message": body}).execute()
    else:
        r = drafts.create(userId="me", body={"message": body}).execute()
    return jsonify({"draftId": r["id"]})


@app.post("/api/send")
def send_draft():
    """Send exactly this draft. Gmail deletes a draft once sent, so a second click has nothing to send."""
    r = gmail().users().drafts().send(userId="me", body={"id": request.get_json()["draftId"]}).execute()
    return jsonify({"sent": r["id"]})


@app.post("/api/quote-draft")
def quote_draft():
    """Scout Dev's Auto-Quote Draft, unchanged. Refuses if this PO already has any Gmail thread or draft."""
    po = request.get_json()["po"].strip()
    if gmail().users().threads().list(userId="me", q=f'subject:"{po}" in:anywhere -in:trash', maxResults=1).execute().get("threads"):
        return jsonify({"error": "This PO already has a Gmail thread or draft. Refresh to see it."}), 409
    r = generate_auto_quote_email(po)
    return jsonify(r), (404 if "error" in r else 200)


SCOUT = "http://localhost:5002"  # Scout Dev backend; its review pages and parser are reused as they are


def _scout(path, body):
    r = requests.post(SCOUT + path, json=body, timeout=30)
    return r.json()


def _device_type(name):
    n = name.lower()
    if "macbook" in n or "laptop" in n: return "Laptop"
    if "ipad" in n or "tablet" in n: return "Tablet"
    if "iphone" in n or "phone" in n: return "Mobile Phone"
    return "Other"


@app.get("/api/ticket-info/<po>")
def ticket_info(po):
    return jsonify(_scout("/order-info", {"order_number": po}))


def _header(info):
    return {k: info.get(k, "") for k in ("org_name", "order_manager_name", "order_manager_email",
                                          "procurement_manager_email", "procurement_manager_name")} | {"is_rush": info.get("is_rush", False)}


@app.post("/api/alt-review")
def alt_review():
    """Same as Scout Dev's Alternative Approval: parse the pasted alternative, open its review page."""
    d = request.get_json()
    info = _scout("/order-info", {"order_number": d["po"]})
    items = [info["items"][i] for i in d["items"]]
    country = "uk" if "kingdom" in (info.get("shipping_country") or "").lower() else ("us" if "states" in (info.get("shipping_country") or "").lower() else "")
    parsed = _scout("/parse-alt-description", {"text": d["text"], "country": country}) if d.get("text", "").strip() else {}
    p = items[0]
    mpn = parsed.get("mpn") or p.get("mpn") or ""
    review = {**_header(info), "order_number": d["po"], "requested_sku": p.get("sku", ""), "multiple_skus": len(items) > 1,
              "alt_type": "CTO device" if mpn.upper().startswith("Z") else "Out of stock / backordered",
              "alt_subtype": "Model unavailable", "device_type": _device_type(p.get("product_name", "")),
              "make": parsed.get("make") or ("Apple" if "apple" in p.get("product_name", "").lower() else ""),
              "model": parsed.get("model", ""), "display_size": parsed.get("display_size", ""), "processor": parsed.get("processor", ""),
              "memory": parsed.get("memory", ""), "storage": parsed.get("storage", ""), "color": parsed.get("color", ""),
              "mpn": parsed.get("mpn", ""), "price": parsed.get("price", ""),
              "keyboard_language": parsed.get("keyboard_language", country.upper()), "sku_country": parsed.get("sku_country", country.upper())}
    sid = _scout("/review-session", review)["session_id"]
    return jsonify({"url": f"{SCOUT}/review-v2?session={sid}"})


@app.post("/api/price-review")
def price_review():
    d = request.get_json()
    info = _scout("/order-info", {"order_number": d["po"]})
    review = {**_header(info), "order_number": d["po"],
              "items": [{"sku": info["items"][i].get("sku", ""), "product_name": info["items"][i].get("product_name", "")} for i in d["items"]]}
    sid = _scout("/review-session", review)["session_id"]
    return jsonify({"url": f"{SCOUT}/review-pricing?session={sid}"})


@app.post("/api/td-confirm")
def td_confirm():
    """Scout Dev's TD Synnex confirmation text, built the same way. Returns text only; creates no Gmail draft."""
    po = request.get_json()["po"].strip()
    order = fetch_full_order(po)
    if "error" in order:
        return jsonify(order), 404
    try:
        card = requests.get(SCOUT + "/daily-card", timeout=10).json().get("last4", "")
    except Exception:
        card = ""
    return jsonify({"body": build_confirmation_email(order, card or "____", None), "card_set": bool(card)})


@app.post("/api/autopilot")
def autopilot():
    """Scout Dev's Generate Autopilot Form: creates the Google Sheet and returns its link."""
    r = _scout("/autopilot-sheet", {"order_number": request.get_json()["po"].strip()})
    return jsonify(r), (400 if "error" in r else 200)


@app.get("/api/attachment/<msg>/<att>")
def attachment(msg, att):
    a = gmail().users().messages().attachments().get(userId="me", messageId=msg, id=att).execute()
    data = base64.urlsafe_b64decode(a["data"] + "=" * (-len(a["data"]) % 4))
    name, mt = request.args.get("name", "file"), request.args.get("type", "application/octet-stream")
    return Response(data, mimetype=mt, headers={"Content-Disposition": f'inline; filename="{name}"'})


if __name__ == "__main__":
    app.run(port=5070, debug=False)
