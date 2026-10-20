"""Same-origin review endpoints with durable, atomic, single-attempt submission."""
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_from_directory
from alt_parser import build_review
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
    origin = request.headers.get("Origin")
    if request.method == "POST" and origin and origin != request.host_url.rstrip("/"):
        return jsonify(error="Submit from this Quote Desk review tab.", retryable=False), 403


@bp.get("/alt-review")
def page():
    response = send_from_directory(ASSETS, "alt-review.html")
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


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
        try:
            info = lookup(po.strip())
        except Exception:
            return jsonify(error="Order lookup failed. Reload the order before opening a review."), 502
        if not isinstance(info, dict) or info.get("error") or not info.get("order_number"):
            return jsonify(error="The order could not be verified. Reload it before opening a review."), 502
        try:
            review = build_review(info, indices, text.strip())
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        sid = secrets.token_urlsafe(32)
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM reviews WHERE expires < ?", (time.time(),))
            if db.execute("SELECT count(*) FROM reviews").fetchone()[0] >= MAX_REVIEWS:
                return jsonify(error="Too many active reviews. Close unused reviews and try again after their two-hour expiry."), 503
            db.execute("INSERT INTO reviews VALUES (?,?,?,?,NULL)",
                       (sid, time.time() + TTL, json.dumps(review), "pending"))
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
    origin = request.headers.get("Origin")
    if origin and origin != request.host_url.rstrip("/"):
        return jsonify(error="Submit from this Quote Desk review tab.", retryable=False), 403
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
