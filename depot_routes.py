"""Isolated standalone Gmail notification endpoints."""
import base64
import hashlib
import json
import os
from email import policy
from email.parser import BytesParser
from flask import jsonify, request
from itsdangerous import URLSafeTimedSerializer, BadSignature
from googleapiclient.errors import HttpError

import scout_port
from depot_notification import preview, eligibility, TO, CC
from depot_store import Store

HEADER = "X-Quote-Desk-Depot"


def register(app, gmail, mime, attachments):
    store_cache = {}

    def store():
        path = app.config.get("DEPOT_STORE_PATH", ".cache/depot-notifications.sqlite3")
        if str(path) not in store_cache:
            store_cache[str(path)] = Store(path)
        return store_cache[str(path)]

    def is_depot_thread(full):
        if not isinstance(full, dict):
            return False  # Unreadable/unclassified conversations remain vendor guarded.
        if store().known_thread(full.get("id", "")):
            return True
        return any(h.get("name", "").lower() == HEADER.lower()
                   for m in full.get("messages", []) for h in m.get("payload", {}).get("headers", []))

    def verified(po):
        if not isinstance(po, str) or not po.strip() or len(po) > 120 or any(c in po for c in '\r\n"'):
            raise ValueError("Enter a valid order number.")
        order = scout_port.fetch_allwhere_order(po)
        if order.get("error"):
            raise ValueError("Could not verify the selected order. Nothing was written.")
        check = eligibility(order)
        if not check["eligible"]:
            raise ValueError(check["reason"])
        return order

    def serializer():
        # Existing shared secret; never persist a second credential.
        secret = app.secret_key or os.environ.get("SESSION_SECRET")
        if not secret:
            raise ValueError("Send confirmation is unavailable: SESSION_SECRET is not configured.")
        return URLSafeTimedSerializer(secret, salt="depot-send")

    def fingerprint(d, po):
        return hashlib.sha256(json.dumps([po, TO, CC, d["subject"], d["body"], d["revision"]],
                                        ensure_ascii=False).encode()).hexdigest()

    def fields():
        d = request.get_json(silent=True)
        if not isinstance(d, dict):
            raise ValueError("Provide the edited notification as JSON.")
        if (not isinstance(d.get("subject"), str) or not d["subject"].strip()
                or len(d["subject"]) > 998 or any(c in d["subject"] for c in "\r\n")
                or not isinstance(d.get("body"), str) or not d["body"].strip()
                or len(d["body"]) > 100000 or type(d.get("revision")) is not int):
            raise ValueError("Provide a subject, body and current notification revision.")
        return d

    def read_draft(row):
        existing = gmail().users().drafts().get(userId="me", id=row["draft_id"], format="raw").execute()["message"]
        if existing["threadId"] != row["thread_id"]:
            raise ValueError("Depot draft thread changed. Check Gmail before continuing.")
        raw = existing["raw"]
        parts = attachments(raw)  # Validate MIME, preserve all files.
        message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if message.get(HEADER) != row["po"] or message.get("In-Reply-To"):
            raise ValueError("This is not the app's standalone depot draft. Nothing was changed.")
        return message, parts

    @app.get("/api/depot-preview/<po>")
    def depot_preview(po):
        try:
            order = verified(po)
            result = preview(order)
            row = store().get(order["orderNumber"])
            if row["state"] == "draft":
                message, _ = read_draft(row)
                body = message.get_body(preferencelist=("plain",))
                if body is None:
                    raise ValueError("Depot draft has no editable plain text. Check Gmail.")
                result.update(subject=str(message["Subject"]), body=body.get_content())
            result["notification"] = row
            return jsonify(result)
        except ValueError as exc:
            return jsonify(error=str(exc)), 409
        except Exception:
            return jsonify(error="Could not safely read the depot notification. Check Gmail; no writes were requested."), 502

    @app.post("/api/depot-confirm")
    def depot_confirm():
        try:
            d = fields()
            order = verified(d.get("po"))
            row = store().get(order["orderNumber"])
            if row["revision"] != d["revision"] or row["state"] not in ("new", "draft"):
                raise ValueError("Notification changed or is locked. Reopen it before confirming.")
            return jsonify(confirmation=serializer().dumps(fingerprint(d, order["orderNumber"])))
        except ValueError as exc:
            return jsonify(error=str(exc)), 409

    def write(send=False):
        claimed = False
        attempted = False
        po = None
        try:
            d = fields()
            order = verified(d.get("po"))
            po = order["orderNumber"]
            if send:
                try:
                    signed = serializer().loads(d.get("confirmation", ""), max_age=300)
                except (BadSignature, TypeError):
                    raise ValueError("Confirm this exact edited email again before sending.") from None
                if signed != fingerprint(d, po):
                    raise ValueError("The message changed. Confirm the edited email again.")
            row = store().claim(po, d["revision"])
            claimed = True
            drafts = gmail().users().drafts()
            parts = []
            if row.get("draft_id"):
                _, parts = read_draft(row)
            message = mime({"to": TO, "cc": CC, "subject": d["subject"], "body": d["body"]}, parts)
            raw = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(message["raw"]))
            raw[HEADER] = po
            message["raw"] = base64.urlsafe_b64encode(raw.as_bytes()).decode()
            if row.get("thread_id"):
                message["threadId"] = row["thread_id"]
            attempted = True
            if row.get("draft_id"):
                saved = drafts.update(userId="me", id=row["draft_id"], body={"message": message}).execute()
            else:
                saved = drafts.create(userId="me", body={"message": message}).execute()
            draft_id = saved["id"]
            thread_id = saved["message"]["threadId"]
            if row.get("thread_id") and thread_id != row["thread_id"]:
                raise RuntimeError("Unexpected thread")
            state = store().set(po, "sending" if send else "draft", draft_id=draft_id, thread_id=thread_id)
            if send:
                sent = drafts.send(userId="me", body={"id": draft_id}).execute()
                state = store().set(po, "sent", sent_id=sent["id"])
            return jsonify(notification=state)
        except ValueError as exc:
            if claimed:
                state = store().set(po, "uncertain" if attempted else row["state"])
                return jsonify(error=str(exc), notification=state, uncertain=attempted), 409
            return jsonify(error=str(exc)), 409
        except Exception as exc:
            # A definite 4xx rejection did not succeed. Timeouts/5xx may have.
            definite = isinstance(exc, HttpError) and 400 <= exc.resp.status < 500 and exc.resp.status not in (408, 404)
            uncertain = attempted and not definite
            if claimed:
                state = store().set(po, "uncertain" if uncertain else ("draft" if store().get(po).get("draft_id") else "new"))
            else:
                state = None
            return jsonify(error=("Outcome uncertain. Check Gmail before any further action; automatic retry is blocked."
                                  if uncertain else "Gmail operation failed. Nothing was sent; review the notification before trying again."),
                           uncertain=uncertain, notification=state), 502

    app.add_url_rule("/api/depot-save", "depot_save", lambda: write(False), methods=["POST"])
    app.add_url_rule("/api/depot-send", "depot_send", lambda: write(True), methods=["POST"])

    @app.before_request
    def depot_write_origin():
        from alt_origin import allowed_write_origin
        if request.path.startswith("/api/depot-") and request.method == "POST" and not allowed_write_origin():
            return jsonify(error="Submit this notification from Quote Desk."), 403

    @app.after_request
    def private_depot(response):
        if request.path.startswith(("/api/depot-", "/static/depot-review")):
            response.headers["Cache-Control"] = "no-store"
        return response

    return is_depot_thread
