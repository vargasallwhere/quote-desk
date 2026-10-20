"""Quote Desk v1 — read-only. Order details from Allwhere, vendor threads straight from Gmail.
Reuses Scout Dev's login and order lookup; edits nothing there."""
import base64, os, sys, time
import re
import hashlib
from pathlib import Path
from urllib.parse import quote
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.parser import BytesParser
from email import policy
from email.utils import getaddresses, formataddr
from email.utils import parsedate_to_datetime
from flask import Flask, jsonify, request, Response, send_from_directory

from gmail_auth import get_gmail_service
import requests
from scout_port import (fetch_full_order, build_confirmation_email, get_order_info_for_ticket,
                        generate_auto_quote_email, fetch_order_status)

app = Flask(__name__)
from alt_origin import replit_origin
app.config["ALT_REVIEW_EXTERNAL_ORIGIN"] = replit_origin(os.environ.get("REPLIT_DEV_DOMAIN"))
from alt_reviews import register as register_alt_reviews
register_alt_reviews(app, lambda po: get_order_info_for_ticket(po))
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
    # Bind the page and its viewer assets to the same release, even behind caches.
    files = ("static/attachment-preview.js", "static/attachment-preview.css", "package-lock.json")
    version = hashlib.sha256(b"".join((Path(app.root_path) / f).read_bytes() for f in files)).hexdigest()[:16]
    html = (Path(app.root_path) / "index.html").read_text()
    return Response(html.replace("__VIEWER_VERSION__", version), mimetype="text/html")

@app.get("/attachment-renderer/<path:filename>")
def attachment_renderer(filename):
    # Serve only PDF.js browser assets, never arbitrary dependency files.
    allowed = filename in ("build/pdf.min.mjs", "build/pdf.worker.min.mjs")
    allowed = allowed or (
        filename.startswith(("cmaps/", "standard_fonts/", "wasm/"))
        and filename.endswith((".bcmap", ".pfb", ".ttf", ".wasm")))
    if not allowed:
        return jsonify(error="Not found"), 404
    root = Path(app.root_path) / "node_modules" / "pdfjs-dist"
    if not (root / "build/pdf.min.mjs").is_file() or not (root / "build/pdf.worker.min.mjs").is_file():
        return jsonify(error="PDF renderer is not installed. Ask the app owner to run the dependency setup."), 503
    return send_from_directory(root, filename,
                               mimetype="text/javascript" if filename.endswith(".mjs") else None)

@app.after_request
def fresh_order_responses(response):
    if request.path in ("/", "/static/attachment-preview.js", "/static/attachment-preview.css") or request.path.startswith(("/attachment-renderer/", "/api/order/", "/api/order-status/", "/api/ticket-info/")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/api/order-status/<po>")
def order_status(po):
    result = fetch_order_status(po)
    return jsonify(result), (502 if "error" in result else 200)


@app.get("/api/order/<po>")
def order(po):
    o = fetch_full_order(po)
    return jsonify(o), (502 if "error" in o else 200)


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


def _mime(d, attachments=()):
    msg = MIMEText(d["body"], "plain", "utf-8")
    if attachments:
        body = msg
        msg = MIMEMultipart("mixed")
        msg.attach(body)
        for attachment in attachments:
            msg.attach(attachment)
    msg["To"], msg["Cc"], msg["Subject"] = d["to"], d.get("cc", ""), d["subject"]
    if d.get("inReplyTo"):
        msg["In-Reply-To"] = d["inReplyTo"]
        msg["References"] = (d.get("references", "") + " " + d["inReplyTo"]).strip()
    return {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}


def _draft_attachments(raw):
    """Keep existing attachment MIME parts, including inline and nested files."""
    if not isinstance(raw, str) or not raw:
        raise ValueError("Missing draft MIME")
    decoded = base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True)
    message = BytesParser(policy=policy.default).parsebytes(decoded)
    # The parser also accepts headerless text, so defects alone do not prove
    # this is the complete raw MIME draft returned by Gmail.
    if (message.get("MIME-Version", "").strip() != "1.0"
            or not message.get("Content-Type")
            or any(part.defects for part in message.walk())):
        raise ValueError("Invalid draft MIME")
    parts = []

    def collect(part):
        # Stop at attached containers (e.g. forwarded .eml), retaining them whole.
        if (part.get_filename() or part.get_content_disposition() in ("attachment", "inline")
                or part.get("Content-ID")
                or (not part.is_multipart() and part.get_content_maintype() != "text")):
            parts.append(part)
        elif part.is_multipart():
            for child in part.iter_parts():
                collect(child)

    collect(message)
    return parts


@app.post("/api/draft")
def save_draft():
    """Create the reply draft in this thread, or update the one already there (never a second draft)."""
    d = request.get_json()
    drafts = gmail().users().drafts()
    attachments = []
    if d.get("draftId"):
        # An update replaces the entire Gmail MIME message. Read first so saving
        # text edits never silently removes files from the existing draft.
        try:
            existing = drafts.get(userId="me", id=d["draftId"], format="raw").execute()["message"]
            if existing["threadId"] != d["threadId"]:
                return jsonify({"error": "The draft belongs to another thread. Refresh from Gmail before saving."}), 409
            attachments = _draft_attachments(existing["raw"])
        except HttpError:
            raise
        except Exception:
            return jsonify({"error": "Could not safely read the existing Gmail draft and its attachments. Nothing was saved. Refresh from Gmail before trying again."}), 502
    body = _mime(d, attachments)
    body["threadId"] = d["threadId"]
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


SCOUT = os.environ.get("SCOUT_URL", "")  # Scout Dev backend, only reachable from Sara's Mac. Empty on Replit.


def _scout(path, body):
    r = requests.post(SCOUT + path, json=body, timeout=30)
    return r.json()


@app.get("/api/config")
def config():
    return jsonify({"scout": bool(SCOUT)})


@app.before_request
def scout_only():
    if not SCOUT and request.path in ("/api/price-review", "/api/autopilot"):
        return jsonify({"error": "This button needs Scout Dev, which only runs on Sara's Mac."}), 503


def _device_type(name):
    n = name.lower()
    if "macbook" in n or "laptop" in n: return "Laptop"
    if "ipad" in n or "tablet" in n: return "Tablet"
    if "iphone" in n or "phone" in n: return "Mobile Phone"
    return "Other"


@app.get("/api/ticket-info/<po>")
def ticket_info(po):
    return jsonify(get_order_info_for_ticket(po))


def _header(info):
    return {k: info.get(k, "") for k in ("org_name", "order_manager_name", "order_manager_email",
                                          "procurement_manager_email", "procurement_manager_name")} | {"is_rush": info.get("is_rush", False)}


@app.post("/api/price-review")
def price_review():
    d = request.get_json()
    info = get_order_info_for_ticket(d["po"])
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
    card = ""
    if SCOUT:
        try:
            card = requests.get(SCOUT + "/daily-card", timeout=10).json().get("last4", "")
        except Exception:
            pass
    return jsonify({"body": build_confirmation_email(order, card or "____", None), "card_set": bool(card)})


@app.post("/api/autopilot")
def autopilot():
    """Scout Dev's Generate Autopilot Form: creates the Google Sheet and returns its link."""
    r = _scout("/autopilot-sheet", {"order_number": request.get_json()["po"].strip()})
    return jsonify(r), (400 if "error" in r else 200)


@app.get("/api/attachment/<msg>/<att>")
def attachment(msg, att):
    try:
        a = gmail().users().messages().attachments().get(userId="me", messageId=msg, id=att).execute()
        data = base64.urlsafe_b64decode(a["data"] + "=" * (-len(a["data"]) % 4))
    except HttpError as exc:
        message = ("This attachment is no longer available in Gmail." if exc.resp.status == 404
                   else "Gmail could not retrieve this attachment. Try again.")
        return jsonify(error=message), (404 if exc.resp.status == 404 else 502)
    except Exception:
        return jsonify(error="Could not retrieve this attachment. Try again."), 502
    name = re.sub(r'[\x00-\x1f\x7f/\\]', "_", request.args.get("name", "file"))[:240] or "file"
    claimed = request.args.get("type", "").split(";")[0].strip().lower()
    # Never serve active content inline, even when a caller supplies a misleading MIME type.
    signatures = {
        "application/pdf": data.startswith(b"%PDF-"),
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/gif": data.startswith((b"GIF87a", b"GIF89a")),
        "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        "image/bmp": data.startswith(b"BM"),
    }
    mt = claimed if signatures.get(claimed, False) else "application/octet-stream"
    fallback = name.encode("ascii", "ignore").decode().replace('"', "_") or "attachment"
    return Response(data, mimetype=mt, headers={
        "Content-Disposition": f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(name, safe="")}',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "no-store",
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5070))
    app.run(host="0.0.0.0" if os.environ.get("PORT") else "127.0.0.1", port=port, debug=False)
