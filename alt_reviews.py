"""Same-origin review endpoints with durable, atomic, single-attempt submission."""
import json
import hashlib
import os
import secrets
import sqlite3
import re
import time
from contextlib import contextmanager
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_from_directory
from alt_parser import build_review
from alt_origin import allowed_write_origin
from alt_tickets import (configuration, requester_options, mapping_errors,
                         validate_ticket, create_ticket)

bp = Blueprint("alt_reviews", __name__)
TTL = 2 * 60 * 60
MAX_REVIEWS = 500
ASSETS = Path(__file__).resolve().parent / "static"


@contextmanager
def database():
    path = current_app.config.get("ALT_REVIEW_DB", str(Path(__file__).resolve().parent / ".cache/alt-reviews.sqlite3"))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    os.chmod(path, 0o600)
    db.row_factory = sqlite3.Row
    try:
        db.execute("CREATE TABLE IF NOT EXISTS reviews (sid TEXT PRIMARY KEY, expires REAL, review TEXT, state TEXT, result TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS review_launches (launch_id TEXT PRIMARY KEY, fingerprint TEXT, sid TEXT)")
        with db:
            yield db
    finally:
        db.close()


def snapshot(row):
    review = json.loads(row["review"])
    cfg, errors = configuration()
    return {"review": review, "state": row["state"],
            "result": json.loads(row["result"]) if row["result"] else None,
            "configuration_errors": errors,
            "mapping_errors": mapping_errors(review, review["requested_by"], cfg),
            "requested_by_options": requester_options(review)}


def missing():
    return jsonify(error="This review is missing or expired. If you submitted it, check Airtable before starting another review. Otherwise reopen it from Quote Desk."), 410


@bp.after_request
def private(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.before_request
def same_origin_writes():
    if request.method == "POST" and not allowed_write_origin():
        return jsonify(
            error="This address is not configured for Quote Desk review writes. Ask the app owner to check quote-desk.toml and restart the serving app. Your selection and vendor reply have not changed.",
            stage="origin", retryable=False), 403


@bp.get("/alt-review")
def page():
    response = send_from_directory(ASSETS, "alt-review.html")
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


@bp.get("/alt-review-launch")
def waiting():
    return send_from_directory(ASSETS, "alt-review-launch.html")


@bp.get("/alt-review-assets/<name>")
def asset(name):
    if name not in ("alt-review.css", "alt-review.js"):
        return "", 404
    return send_from_directory(ASSETS, name)


def register(app, lookup):
    @bp.post("/api/alt-review")
    def open_review():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="Provide an order and selected items as JSON."), 400
        po, text = data.get("po"), data.get("text", "")
        if not isinstance(po, str) or not po.strip() or len(po) > 120 or not isinstance(text, str) or len(text) > 20000:
            return jsonify(error="Enter a valid PO and optional alternative description (up to 20,000 characters)."), 400
        indices = data.get("items")
        if not isinstance(indices, list) or not indices or len(indices) > 500:
            return jsonify(error="Select at least one requested item (up to 500)."), 400
        launch_id = data.get("launch_id")
        if launch_id is not None and (not isinstance(launch_id, str) or
                                     not re.fullmatch(r"[a-f0-9]{32}", launch_id)):
            return jsonify(error="Invalid review launch identifier.", stage="creation"), 400
        fingerprint = hashlib.sha256(json.dumps(
            [po.strip(), indices, text], separators=(",", ":")).encode()).hexdigest()

        def existing(db):
            if not launch_id:
                return None
            row = db.execute(
                "SELECT l.fingerprint,l.sid FROM review_launches l JOIN reviews r ON r.sid=l.sid "
                "WHERE l.launch_id=? AND r.expires>?", (launch_id, time.time())).fetchone()
            if row:
                if row["fingerprint"] != fingerprint:
                    return jsonify(error="The saved launch has different items or text. Reopen the picker.", stage="creation"), 409
                return jsonify(url="/alt-review?session=" + row["sid"])
            return None

        try:
            with database() as db:
                previous = existing(db)
                if previous is not None:
                    return previous
        except (sqlite3.Error, OSError):
            return jsonify(error="The local review store is unavailable. Retry opening; no ticket was submitted.",
                           stage="storage"), 503
        try:
            info = lookup(po.strip())
        except Exception:
            return jsonify(error="Order lookup failed. Retry opening shortly; no need to reload your email.", stage="lookup"), 502
        if not isinstance(info, dict) or info.get("error") or not info.get("order_number"):
            return jsonify(error="The order could not be verified. Retry opening shortly; no need to reload your email.", stage="lookup"), 502
        try:
            review = build_review(info, indices, text.strip())
        except ValueError as exc:
            return jsonify(error=str(exc), stage="selection"), 400
        except Exception:
            return jsonify(error="The order details could not be prepared for review. Ask the app owner to check the order data.",
                           stage="preparation"), 502
        sid = secrets.token_urlsafe(32)
        try:
            with database() as db:
                db.execute("BEGIN IMMEDIATE")
                previous = existing(db)
                if previous is not None:
                    return previous
                db.execute("DELETE FROM reviews WHERE expires < ?", (time.time(),))
                db.execute("DELETE FROM review_launches WHERE sid NOT IN (SELECT sid FROM reviews)")
                if db.execute("SELECT count(*) FROM reviews").fetchone()[0] >= MAX_REVIEWS:
                    return jsonify(error="Too many active reviews. Close unused reviews and try again after their two-hour expiry.",
                                   stage="storage"), 503
                db.execute("INSERT INTO reviews VALUES (?,?,?,?,NULL)",
                           (sid, time.time() + TTL, json.dumps(review), "pending"))
                if launch_id:
                    db.execute("INSERT INTO review_launches VALUES (?,?,?)", (launch_id, fingerprint, sid))
        except (sqlite3.Error, OSError):
            return jsonify(error="The local review store could not save this review. Retry opening; no ticket was submitted.",
                           stage="storage"), 503
        return jsonify(url="/alt-review?session=" + sid)

    app.register_blueprint(bp)


@bp.get("/api/alt-review/<sid>")
def get_review(sid):
    with database() as db:
        row = db.execute("SELECT * FROM reviews WHERE sid=? AND expires>?", (sid, time.time())).fetchone()
    return jsonify(snapshot(row)) if row else missing()


def save_result(sid, result):
    with database() as db:
        db.execute("UPDATE reviews SET state=?, result=? WHERE sid=?",
                   (result["state"], json.dumps(result), sid))


@bp.post("/api/alt-review/<sid>/submit")
def submit_review(sid):
    # JSON-only writes plus browser Origin checking prevent cross-origin form submissions.
    data = request.get_json(silent=True)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM reviews WHERE sid=? AND expires>?", (sid, time.time())).fetchone()
        if not row:
            return missing()
        if row["state"] != "pending":
            result = json.loads(row["result"]) if row["result"] else {
                "error": "Submission is in progress or was interrupted. Check Airtable; do not submit again.",
                "state": "submitting", "retryable": False}
            return jsonify(result), (200 if result.get("created") else 409)
        review = json.loads(row["review"])
        try:
            ticket = validate_ticket(data, review)
        except ValueError as exc:
            return jsonify(error=str(exc), retryable=True), 400
        cfg, errors = configuration()
        mappings = mapping_errors(review, ticket["requested_by"], cfg)
        if errors or mappings:
            return jsonify(error="Submission blocked. Complete the configuration and collaborator mappings; no ticket was created.",
                           configuration_errors=errors, mapping_errors=mappings, retryable=True), 503
        # Keep edited data for recovery; immutable order metadata always comes from the session.
        review.update(ticket)
        db.execute("UPDATE reviews SET state='submitting',review=? WHERE sid=?", (json.dumps(review), sid))
    try:
        result = create_ticket(review, ticket, cfg, lambda result: save_result(sid, result))
    except Exception:
        # Includes a storage failure after external creation. Never unlock for another POST.
        with database() as db:
            row = db.execute("SELECT * FROM reviews WHERE sid=?", (sid,)).fetchone()
        if row and row["result"]:
            return jsonify(json.loads(row["result"])), 200
        result = {"state": "uncertain", "retryable": False,
                  "error": "Submission outcome is unknown. Check Airtable before further action; do not resubmit."}
    save_result(sid, result)
    return jsonify(result), (200 if result.get("created") else (502 if result["state"] == "pending" else 409))
