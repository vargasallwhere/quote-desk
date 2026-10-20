#!/usr/bin/env python3
# ── Stock Checker Flask App ───────────────────────────────────────────────────
# Thin HTTP wrapper around scout_engine.py.
# Chrome extension posts to http://localhost:5001/check
# ─────────────────────────────────────────────────────────────────────────────

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

import re
import uuid
import json as _json
from flask import Flask, request, jsonify, send_from_directory, make_response
from flask_cors import CORS
import threading, time, logging
from scout_engine import run_stock_check, get_mpn_for_sku, find_sku_for_mpn, create_airtable_ticket, create_airtable_ticket_v2, create_pricing_approval_ticket, get_order_info_for_ticket, generate_order_note, generate_uk_email, generate_us_email, generate_eu_email, generate_auto_quote_email, add_order_external_link, get_recipient_info, send_to_finance_sheet, send_hold_to_finance_sheet, test_auto_sync, sync_infulfillment_orders, auto_sync_new_orders, resync_multi_vendor_orders, save_feedback_note, get_feedback_sheet_url
from scout_sku_lookup import drop_sku, parse_device_text
from cache_engine import cache_clear, cache_stats, flag_bh_not_available, get_bh_flags, add_reason_code, get_reason_codes, log_email_feedback, get_email_feedback
from scout_quote_validator import validate_quote
from po_readiness_engine import run_po_readiness_check, set_exception
from order_confirm_engine import process_confirmation, process_email_only, set_daily_card, get_daily_card
from alt_approval_engine import run_alt_approval_check, run_alt_approval_for_order
from eu_psu_engine import run_eu_psu_check
from order_quote_validator import run_quote_validator_check

app = Flask(__name__)
CORS(app)  # Allow the Chrome extension to call localhost

PANEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel")
_review_sessions = {}


@app.route("/panel")
def serve_panel():
    resp = make_response(send_from_directory(PANEL_DIR, "index.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/panel/<path:filename>")
def serve_panel_static(filename):
    resp = make_response(send_from_directory(PANEL_DIR, filename))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/review-v2")
def serve_review_v2():
    return send_from_directory(PANEL_DIR, "review_v2.html")


@app.route("/review-pricing")
def serve_review_pricing():
    return send_from_directory(PANEL_DIR, "review_pricing.html")


@app.route("/review-session", methods=["POST"])
def create_review_session():
    data = request.get_json(force=True)
    sid = uuid.uuid4().hex[:10]
    _review_sessions[sid] = data
    return jsonify({"session_id": sid})


@app.route("/review-session/<sid>", methods=["GET"])
def get_review_session(sid):
    data = _review_sessions.get(sid)
    if not data:
        return jsonify({"error": "Session not found or expired"}), 404
    return jsonify(data)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/check", methods=["POST"])
def check_order():
    data = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()

    if not order_number:
        return jsonify({"output_type": "error", "text": "Order number is required.", "details": {}}), 400

    force_lead_time = bool(data.get("force_lead_time", False))

    try:
        result = run_stock_check(order_number, force_lead_time=force_lead_time)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            "output_type": "error",
            "text":        f"Unexpected error: {e}",
            "details":     {},
        }), 500


@app.route("/part-number", methods=["POST"])
def part_number_route():
    data = request.get_json(force=True)
    sku  = (data.get("sku") or "").strip()
    if not sku:
        return jsonify({"error": "sku is required"}), 400
    result = get_mpn_for_sku(sku)
    return jsonify(result)


@app.route("/mpn-to-sku", methods=["POST"])
def mpn_to_sku_route():
    data = request.get_json(force=True)
    mpn  = (data.get("mpn") or "").strip()
    if not mpn:
        return jsonify({"error": "mpn is required"}), 400
    result = find_sku_for_mpn(mpn)
    return jsonify(result)


@app.route("/sku-drop", methods=["POST"])
def sku_drop_route():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    result = drop_sku(text)
    return jsonify(result)


@app.route("/order-note", methods=["POST"])
def order_note_route():
    data         = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    if not order_number:
        return jsonify({"error": "order_number is required"}), 400
    result = generate_order_note(order_number)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route("/uk-email", methods=["POST"])
def uk_email_route():
    data         = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    if not order_number:
        return jsonify({"error": "order_number is required"}), 400
    result = generate_uk_email(order_number)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route("/us-email", methods=["POST"])
def us_email_route():
    data         = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    if not order_number:
        return jsonify({"error": "order_number is required"}), 400
    result = generate_us_email(order_number)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route("/eu-email", methods=["POST"])
def eu_email_route():
    data         = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    if not order_number:
        return jsonify({"error": "order_number is required"}), 400
    result = generate_eu_email(order_number)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route("/auto-quote", methods=["POST"])
def auto_quote_route():
    data         = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    if not order_number:
        return jsonify({"error": "order_number is required"}), 400
    result = generate_auto_quote_email(order_number)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route("/order-info", methods=["POST"])
def order_info_route():
    data         = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    if not order_number:
        return jsonify({"error": "order_number is required"}), 400
    result = get_order_info_for_ticket(order_number)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route("/create-airtable-ticket", methods=["POST"])
def create_ticket_route():
    data         = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    subject      = (data.get("subject") or "").strip()
    description  = (data.get("description") or "").strip()
    header       = data.get("header") or {}
    priority     = (data.get("priority") or "").strip()
    mpns         = data.get("mpns") or []

    if not order_number or not description:
        return jsonify({"error": "order_number and description are required"}), 400

    result = create_airtable_ticket(order_number, subject, description, header, priority=priority, mpns=mpns)
    if result.get("ok") and result.get("url"):
        add_order_external_link(order_number, result["url"])
    return jsonify(result)


@app.route("/recipient", methods=["GET"])
def recipient_route():
    order_number = (request.args.get("orderNumber") or "").strip()
    if not order_number:
        return jsonify({"error": "orderNumber is required"}), 400
    result = get_recipient_info(order_number)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route("/feedback/bh-flag", methods=["POST"])
def bh_flag_route():
    data = request.get_json(force=True)
    skus = data.get("skus") or []  # [{"sku": "...", "name": "..."}]
    if not skus:
        return jsonify({"error": "skus list is required"}), 400
    for entry in skus:
        sku  = (entry.get("sku") or "").strip()
        name = (entry.get("name") or "").strip()
        if sku:
            flag_bh_not_available(sku, name)
    return jsonify({"ok": True, "flagged": len(skus)})


@app.route("/feedback/bh-flags", methods=["GET"])
def bh_flags_route():
    return jsonify({"flags": get_bh_flags()})


@app.route("/email-reason-codes", methods=["GET"])
def email_reason_codes_get_route():
    return jsonify({"codes": get_reason_codes()})


@app.route("/email-reason-codes", methods=["POST"])
def email_reason_codes_post_route():
    data = request.get_json(force=True)
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify({"error": "code is required"}), 400
    add_reason_code(code)
    return jsonify({"ok": True, "codes": get_reason_codes()})


@app.route("/email-feedback", methods=["GET"])
def email_feedback_get_route():
    return jsonify({"entries": get_email_feedback()})


@app.route("/email-feedback", methods=["POST"])
def email_feedback_post_route():
    data         = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    region       = (data.get("region") or "").strip()
    status       = (data.get("status") or "").strip()
    reason_code  = (data.get("reason_code") or "").strip()
    if not order_number or not region or status not in ("green", "orange"):
        return jsonify({"error": "order_number, region, and status (green/orange) are required"}), 400
    log_email_feedback(order_number, region, status, reason_code)
    return jsonify({"ok": True})


@app.route("/review-email-feedback")
def serve_review_email_feedback():
    return send_from_directory(PANEL_DIR, "review_email_feedback.html")


@app.route("/cache/clear", methods=["POST"])
def cache_clear_route():
    data      = request.get_json(force=True) if request.data else {}
    namespace = (data.get("namespace") or "") if data else ""
    cache_clear(namespace or None)
    return jsonify({"ok": True, "namespace": namespace or "all"})


@app.route("/cache/stats", methods=["GET"])
def cache_stats_route():
    return jsonify(cache_stats())


def _build_processor(parsed: dict) -> str:
    chip = parsed.get("chip") or ""
    cpu = parsed.get("cpu_cores")
    gpu = parsed.get("gpu_cores")
    cores = f"{cpu}C/{gpu}C" if cpu and gpu else ""
    parts = [p for p in (chip, cores) if p]
    return " ".join(parts)


def _parse_alt_description(text: str, country: str = "") -> dict:
    """
    Parse a free-form alternative device description into V2 form fields.
    Reuses sku_lookup_engine's parse_device_text for model/chip/memory/storage/color,
    then extracts make, display size, MPN, and price on top.
    """
    parsed     = parse_device_text(text)
    model_query = parsed.get("model_query") or ""

    # Split trailing screen size from model name ("MacBook Air 13" → "MacBook Air", "13\"")
    model        = model_query
    display_size = ""
    if model_query:
        m = re.search(r'\b(13|14|15|16|24)\s*$', model_query)
        if m:
            model        = model_query[:m.start()].strip()
            display_size = f"{m.group(1)}\""

    # Fallback: find display size directly in text ("13-inch", '14"', "16 inch")
    if not display_size:
        m = re.search(r'\b(13|14|15|16|24)\s*(?:["”]|-?\s*inch)', text, re.IGNORECASE)
        if m:
            display_size = f"{m.group(1)}\""

    # Make — scan for known brands (longest match first to avoid false partial hits)
    _KNOWN_BRANDS = [
        "Western Digital", "Blue Yeti", "Sennheiser", "Plantronics", "SteelSeries",
        "CalDigit", "Logitech", "Microsoft", "Samsung", "Lenovo", "Corsair",
        "HyperX", "Kingston", "Seagate", "Synology", "Ubiquiti", "Elgato",
        "Apple", "Sony", "Jabra", "Bose", "Razer", "Belkin", "Anker",
        "Dell", "Asus", "Acer", "Rode", "Poly", "LG", "HP",
    ]
    make = ""
    for brand in _KNOWN_BRANDS:
        if re.search(r'\b' + re.escape(brand) + r'\b', text, re.IGNORECASE):
            make = brand
            break
    # Infer Apple from known Apple model names when brand not explicit in text
    if not make and model:
        if any(kw in model.lower() for kw in ["macbook", "imac", "mac mini", "mac pro", "ipad", "iphone"]):
            make = "Apple"

    # MPN — Apple format e.g. MXW73LL/A, Z1CX000LL/A
    mpn = ""
    m = re.search(r'\b([A-Z][A-Z0-9]{4,8}[A-Z]{2}/[A-Z])\b', text)
    if m:
        mpn = m.group(1)

    # Price — strip $ and commas e.g. "$2,499.00" → "2499.00"
    price = ""
    m = re.search(r'\$\s*([\d,]+(?:\.\d{1,2})?)', text)
    if m:
        price = m.group(1).replace(",", "")

    return {
        "make":             make,
        "model":            model,
        "display_size":     display_size,
        "processor":        _build_processor(parsed),
        "memory":           parsed.get("memory") or "",
        "storage":          parsed.get("storage") or "",
        "color":            parsed.get("color") or "",
        "mpn":              mpn,
        "price":            price,
        "keyboard_language": "UK" if country == "uk" else ("US" if country == "us" else ""),
        "sku_country":      "UK" if country == "uk" else ("US" if country == "us" else ""),
    }


@app.route("/send-to-finance", methods=["POST"])
def send_to_finance_route():
    data              = request.get_json(force=True)
    order_number      = (data.get("order_number") or "").strip()
    proc_manager_name = (data.get("proc_manager_name") or "").strip()
    notes_text        = (data.get("notes_text") or "").strip()
    total_items       = int(data.get("total_items") or 0)
    if not notes_text:
        return jsonify({"error": "notes_text is required"}), 400
    result = send_to_finance_sheet(order_number, proc_manager_name, notes_text, total_items)
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route("/send-hold-to-finance", methods=["POST"])
def send_hold_to_finance_route():
    data              = request.get_json(force=True)
    order_number      = (data.get("order_number") or "").strip()
    proc_manager_name = (data.get("proc_manager_name") or "").strip()
    hold_items        = data.get("hold_items") or []
    total_items       = int(data.get("total_items") or 0)
    if not hold_items:
        return jsonify({"error": "hold_items is required"}), 400
    result = send_hold_to_finance_sheet(order_number, proc_manager_name, hold_items, total_items)
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route("/sync-infulfillment", methods=["POST"])
def sync_infulfillment_route():
    result = sync_infulfillment_orders()
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route("/test-auto-sync", methods=["POST"])
def test_auto_sync_route():
    data         = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    if not order_number:
        return jsonify({"error": "order_number is required"}), 400
    result = test_auto_sync(order_number)
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route("/resync-multi-vendor", methods=["POST"])
def resync_multi_vendor_route():
    result = resync_multi_vendor_orders()
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route("/parse-alt-description", methods=["POST"])
def parse_alt_route():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    country = (data.get("country") or "").strip().lower()
    return jsonify(_parse_alt_description(text, country))


@app.route("/create-airtable-ticket-v2", methods=["POST"])
def create_ticket_v2_route():
    data         = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    header       = data.get("header") or {}
    ticket_data  = data.get("ticket_data") or {}

    if not order_number:
        return jsonify({"error": "order_number is required"}), 400

    result = create_airtable_ticket_v2(order_number, header, ticket_data)
    # Yehuda's automation (runPipeline) attaches the external link itself once it
    # processes the webhook — adding it here too caused duplicate airtable.com links
    # on the order's External Links.
    return jsonify(result)


@app.route("/create-pricing-approval", methods=["POST"])
def create_pricing_approval_route():
    data         = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    header       = data.get("header") or {}
    products_text = (data.get("products_text") or "").strip()

    if not order_number:
        return jsonify({"error": "order_number is required"}), 400

    result = create_pricing_approval_ticket(order_number, header, products_text)
    if result.get("ok") and result.get("url"):
        add_order_external_link(order_number, result["url"])
    return jsonify(result)


@app.route("/validate-quote", methods=["POST"])
def validate_quote_route():
    ct = request.content_type or ""
    if "json" in ct:
        data = request.get_json(force=True)
        item           = data.get("item")
        all_items      = data.get("all_items")
        quote_text     = (data.get("quote_text") or "").strip() or None
        quote_pdf_b64  = data.get("quote_file") or None
    else:
        item           = _json.loads(request.form.get("item", "{}"))
        all_items      = _json.loads(request.form.get("all_items", "[]"))
        quote_text     = (request.form.get("quote_text") or "").strip() or None
        f              = request.files.get("quote_file")
        import base64 as _b64
        quote_pdf_b64  = _b64.b64encode(f.read()).decode() if f else None

    if not item:
        return jsonify({"error": "item is required"}), 400
    if not quote_text and not quote_pdf_b64:
        return jsonify({"error": "Paste quote text or upload a PDF"}), 400

    try:
        result = validate_quote(item, all_items, quote_text, quote_pdf_b64)
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Validation failed: {e}"}), 500


# ── PO Readiness Dashboard ───────────────────────────────────────────────────

@app.route("/po-readiness-check", methods=["POST"])
def po_readiness_check_route():
    result = run_po_readiness_check()
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route("/po-readiness-exception", methods=["POST"])
def po_readiness_exception_route():
    data = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    exception_type = (data.get("exception_type") or "").strip()
    note = (data.get("note") or "").strip()
    if not order_number or not exception_type:
        return jsonify({"error": "order_number and exception_type are required"}), 400
    result = set_exception(order_number, exception_type, note)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/process-alt-approval", methods=["POST"])
def process_alt_approval_route():
    data = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    if not order_number:
        return jsonify({"error": "order_number is required"}), 400
    try:
        result = run_alt_approval_for_order(order_number)
        if "error" in result:
            return jsonify(result), 400
        from scout_engine import get_order_header
        h = get_order_header(order_number)
        result["order_notes"] = h.get("internal_notes", "")
        return jsonify(result)
    except Exception as e:
        logging.exception("Alt approval processing error")
        return jsonify({"error": str(e)}), 500


@app.route("/check-alt-approvals", methods=["POST"])
def check_alt_approvals_route():
    try:
        result = run_alt_approval_check()
        if "error" in result:
            return jsonify(result), 500
        return jsonify(result)
    except Exception as e:
        logging.exception("Alt approval check error")
        return jsonify({"error": str(e)}), 500


@app.route("/check-eu-psu", methods=["POST"])
def check_eu_psu_route():
    try:
        result = run_eu_psu_check()
        if "error" in result:
            return jsonify(result), 500
        return jsonify(result)
    except Exception as e:
        logging.exception("EU PSU check error")
        return jsonify({"error": str(e)}), 500


_SYNC_INTERVAL = 300  # 5 minutes
_PO_READINESS_INTERVAL = 900  # 15 minutes
_ALT_APPROVAL_INTERVAL = 300  # 5 minutes
_EU_PSU_INTERVAL = 900  # 15 minutes
_QUOTE_VALIDATOR_INTERVAL = 900  # 15 minutes

def _finance_sync_loop():
    time.sleep(30)  # initial delay — let Flask start first
    while True:
        try:
            result = auto_sync_new_orders()
            if result.get("synced"):
                logging.info(f"Finance auto-sync: {result['synced']} new orders synced")
        except Exception as e:
            logging.warning(f"Finance auto-sync error: {e}")
        time.sleep(_SYNC_INTERVAL)


def _po_readiness_loop():
    time.sleep(60)  # initial delay — let Flask + first finance sync go first
    while True:
        try:
            result = run_po_readiness_check()
            if result.get("ok"):
                logging.info(f"PO readiness: {result.get('orders_checked', 0)} orders — {result.get('status_counts', {})}")
            else:
                logging.warning(f"PO readiness error: {result.get('error', 'unknown')}")
        except Exception as e:
            logging.warning(f"PO readiness loop error: {e}")
        time.sleep(_PO_READINESS_INTERVAL)


def _alt_approval_loop():
    time.sleep(90)  # initial delay — let other loops start first
    while True:
        try:
            result = run_alt_approval_check()
            if result.get("processed"):
                logging.info(f"Alt approval: processed {result['processed']} tickets")
        except Exception as e:
            logging.warning(f"Alt approval loop error: {e}")
        time.sleep(_ALT_APPROVAL_INTERVAL)


def _eu_psu_loop():
    time.sleep(120)  # initial delay — let other loops start first
    while True:
        try:
            result = run_eu_psu_check()
            if result.get("added_count"):
                logging.info(f"EU PSU: added PSU to {result['added_count']} orders: {result['added']}")
        except Exception as e:
            logging.warning(f"EU PSU loop error: {e}")
        time.sleep(_EU_PSU_INTERVAL)


def _quote_validator_loop():
    time.sleep(150)  # initial delay — let other loops start first
    while True:
        try:
            result = run_quote_validator_check()
            if result.get("processed"):
                logging.info(f"Quote validator: processed {len(result['processed'])} orders: {result['processed']}")
            if result.get("errors"):
                logging.warning(f"Quote validator errors: {result['errors']}")
        except Exception as e:
            logging.warning(f"Quote validator loop error: {e}")
        time.sleep(_QUOTE_VALIDATOR_INTERVAL)


# ── Feedback Notes ────────────────────────────────────────────────────────────

@app.route("/save-feedback", methods=["POST"])
def save_feedback_route():
    data    = request.get_json(force=True)
    text    = (data.get("text") or "").strip()
    project = (data.get("project") or "N/A").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    try:
        result = save_feedback_note(project, text)
        return jsonify(result)
    except Exception as e:
        logging.exception("Feedback save error")
        return jsonify({"error": str(e)}), 500

@app.route("/feedback-sheet-url", methods=["GET"])
def feedback_sheet_url_route():
    url = get_feedback_sheet_url()
    return jsonify({"url": url})


# ── Confirm Order ─────────────────────────────────────────────────────────────

@app.route("/daily-card", methods=["GET"])
def daily_card_get():
    return jsonify({"last4": get_daily_card()})


@app.route("/daily-card", methods=["POST"])
def daily_card_set():
    data = request.get_json(force=True)
    last4 = (data.get("last4") or "").strip()
    if not last4:
        return jsonify({"error": "last4 is required"}), 400
    set_daily_card(last4)
    return jsonify({"ok": True, "last4": last4})


@app.route("/confirm-order", methods=["POST"])
def confirm_order_route():
    order_number = (request.form.get("order_number") or "").strip()
    card_last4 = (request.form.get("card_last4") or "").strip()
    quote_file = request.files.get("quote")

    if not order_number:
        return jsonify({"error": "order_number is required"}), 400
    if not quote_file:
        return jsonify({"error": "quote file is required"}), 400

    try:
        quote_bytes = quote_file.read()
        result = process_confirmation(order_number, quote_bytes, card_last4 or None)
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        logging.exception("Confirm order error")
        return jsonify({"error": str(e)}), 500


@app.route("/autopilot-sheet", methods=["POST"])
def autopilot_sheet_route():
    from order_confirm_engine import fetch_full_order, create_autopilot_review_sheet
    data = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    if not order_number:
        return jsonify({"error": "order_number is required"}), 400
    try:
        order = fetch_full_order(order_number)
        if "error" in order:
            return jsonify(order), 400
        sheet_url = create_autopilot_review_sheet(order)
        return jsonify({"ok": True, "url": sheet_url})
    except Exception as e:
        logging.exception("Autopilot sheet error")
        return jsonify({"error": str(e)}), 500


@app.route("/confirm-email-only", methods=["POST"])
def confirm_email_only_route():
    data = request.get_json(force=True)
    order_number = (data.get("order_number") or "").strip()
    card_last4 = (data.get("card_last4") or "").strip()

    if not order_number:
        return jsonify({"error": "order_number is required"}), 400

    try:
        result = process_email_only(order_number, card_last4 or None)
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        logging.exception("Confirm email-only error")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Scout [DEV] running on http://localhost:5002")
    threading.Thread(target=_finance_sync_loop, daemon=True).start()
    print("Finance auto-sync started (every 5 min)")
    threading.Thread(target=_po_readiness_loop, daemon=True).start()
    print("PO readiness dashboard started (every 15 min)")
    threading.Thread(target=_alt_approval_loop, daemon=True).start()
    print("Alt approval monitor started (every 5 min)")
    threading.Thread(target=_eu_psu_loop, daemon=True).start()
    print("EU PSU auto-add started (every 15 min)")
    threading.Thread(target=_quote_validator_loop, daemon=True).start()
    print("Order quote validator started (every 15 min)")
    app.run(host="127.0.0.1", port=5002, debug=False)
