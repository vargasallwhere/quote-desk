"""Isolated alternative-approval tests. Every external service is denied or mocked."""
import json
import os
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

import requests
import app
import alt_reviews
from alt_parser import parse_alt_description, build_review
from alt_tickets import FIELD_MAP, configuration, webhook_payload

CONFIG = {
    "AIRTABLE_PAT": "test-only-pat", "AIRTABLE_BASE_ID": "appTest", "AIRTABLE_TABLE": "tblTest",
    "AUTOMATED_APPROVALS_WEBHOOK_URL": "https://notify.invalid/approvals",
    "AUTOMATED_APPROVALS_WEBHOOK_SECRET": "test-only-webhook",
    "AIRTABLE_USER_IDS_JSON": json.dumps({"sara@allwhere.co": "usrSara", "om@example.test": "usrOM",
                                        "emma@allwhere.co": "usrEmma"}),
}
INFO = {
    "order_number": "123-1-TEST", "resolved_order_number": "123-1-TEST",
    "org_name": "Test Org", "order_manager_email": "om@example.test", "order_manager_name": "Test OM",
    "procurement_manager_email": "sara@allwhere.co", "procurement_manager_name": "Test PM",
    "is_rush": True, "shipping_country": "United States",
    "items": [{"sku": "101", "mpn": "Z12345678", "product_name": "Apple MacBook Air"},
              {"sku": "101", "mpn": "Z12345678", "product_name": "Apple MacBook Air"},
              {"sku": "202", "mpn": "", "product_name": "Dell Monitor"}],
}
TEXT = 'Apple MacBook Air 13-inch M4 10-core CPU 8-core GPU 24GB 512GB Midnight MXW73LL/A $2,499.00'


def response(data=None, code=200):
    return Mock(status_code=code, json=Mock(return_value=data))


def valid_ticket(review=None):
    ticket = dict(review or build_review(INFO, [0], TEXT))
    ticket.update(requested_by="sara@allwhere.co", price="2499.00")
    return {k: ticket[k] for k in (*FIELD_MAP, "alt_type", "alt_subtype", "requested_by")}


class AltReviewFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old_path = app.app.config.get("ALT_REVIEW_DB")
        app.app.config["ALT_REVIEW_DB"] = self.temp.name + "/reviews.sqlite3"
        self.addCleanup(lambda: app.app.config.update(ALT_REVIEW_DB=self.old_path) if self.old_path else app.app.config.pop("ALT_REVIEW_DB", None))
        self.client = app.app.test_client()
        self.env = patch.dict(os.environ, CONFIG, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.lookup = patch.object(app, "get_order_info_for_ticket", return_value=deepcopy(INFO)).start()
        self.gmail = patch.object(app, "gmail", side_effect=AssertionError("Gmail must not be used")).start()
        self.get = patch.object(requests, "get", side_effect=AssertionError("No live reads")).start()
        self.post = patch.object(requests, "post", side_effect=AssertionError("No live writes")).start()
        self.addCleanup(patch.stopall)

    def open(self, **overrides):
        result = self.client.post("/api/alt-review", json={"po": "123-1-TEST", "items": [0], "text": TEXT, **overrides})
        self.assertEqual(result.status_code, 200, result.json)
        return result.json["url"].split("session=")[1]

    def read(self, sid):
        return self.client.get("/api/alt-review/" + sid)

    def submit(self, sid, ticket=None):
        return self.client.post("/api/alt-review/" + sid + "/submit", json=ticket or valid_ticket())

    def mock_success(self, webhook_code=200):
        self.post.side_effect = [response({"id": "recTest", "fields": {"Status": "Open", "Summary/Subject": "Test summary"}}, 201),
                                 response({}, webhook_code)]


class AltReviewTests(AltReviewFixture):
    def test_creation_retry_reuses_session_even_after_submission_or_lost_response(self):
        launch_id = "a" * 32
        sid = self.open(launch_id=launch_id, items=[2, 0])
        self.lookup.reset_mock()
        self.assertEqual(self.open(launch_id=launch_id, items=[2, 0]), sid)
        self.lookup.assert_not_called()
        self.mock_success()
        self.submit(sid, valid_ticket(self.read(sid).json["review"]))
        before = self.post.call_count
        self.assertEqual(self.open(launch_id=launch_id, items=[2, 0]), sid)
        self.assertEqual(self.read(sid).json["state"], "completed")
        self.assertEqual(self.post.call_count, before)
        for override in ({"items":[0]}, {"text":"changed"}):
            payload = {"po":"123-1-TEST","items":[2,0],"text":TEXT,"launch_id":launch_id, **override}
            self.assertEqual(self.client.post("/api/alt-review", json=payload).status_code, 409)
        with app.app.app_context(), alt_reviews.database() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM reviews").fetchone()[0], 1)

    def test_creation_stage_errors_and_bad_launch_id(self):
        for launch_id in ("", "not-valid", [], "A"*32):
            result = self.client.post("/api/alt-review", json={
                "po":"TEST","items":[0],"launch_id":launch_id})
            self.assertEqual(result.status_code, 400)
        with patch("alt_reviews.database", side_effect=OSError("private storage path")):
            result = self.client.post("/api/alt-review", json={"po":"TEST","items":[0]})
            self.assertEqual(result.status_code, 503)
            self.assertEqual(result.json["stage"], "storage")
            self.assertNotIn("private storage path", str(result.json))
        with patch("alt_reviews.build_review", side_effect=TypeError("private malformed data")):
            result = self.client.post("/api/alt-review", json={"po":"TEST","items":[0]})
            self.assertEqual(result.status_code, 502)
            self.assertEqual(result.json["stage"], "preparation")
        self.post.assert_not_called()

    def test_concurrent_open_retries_share_one_session(self):
        barrier = threading.Barrier(2)
        def lookup(_po):
            barrier.wait(timeout=5)
            return deepcopy(INFO)
        self.lookup.side_effect = lookup
        results = []
        def open_once():
            with app.app.test_client() as client:
                result = client.post("/api/alt-review", json={
                    "po":"TEST", "items":[0,2], "text":TEXT, "launch_id":"b"*32})
                results.append((result.status_code, result.json))
        threads = [threading.Thread(target=open_once) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 2)
        self.assertEqual([r[0] for r in results], [200,200])
        self.assertEqual(results[0][1]["url"], results[1][1]["url"])
        with app.app.app_context(), alt_reviews.database() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM reviews").fetchone()[0], 1)
        self.post.assert_not_called()

    def test_parser_source_examples(self):
        parsed = parse_alt_description(TEXT, "us")
        self.assertEqual(parsed, dict(make="Apple", model="MacBook Air", display_size='13"',
                                     processor="M4 10C/8C", memory="24 GB", storage="512 GB",
                                     color="Midnight", mpn="MXW73LL/A", price="2499.00",
                                     keyboard_language="US", sku_country="US"))
        for text in ('MacBook Pro 16” m5max 36GB 2TB Space Black 14‑core CPU 32‑core GPU',
                     'MacBook Pro 16-inch M5 Max 36 GB 2 TB Space Black 14C/32C'):
            result = parse_alt_description(text)
            self.assertEqual(result["processor"], "M5 Max 14C/32C")
            self.assertEqual(result["display_size"], '16"')
            self.assertEqual(result["storage"], "2 TB")
        self.assertEqual(parse_alt_description("")["price"], "")
        self.assertEqual(parse_alt_description("unrecognized device")["model"], "")
        self.assertEqual(parse_alt_description("Logitech Mouse")["make"], "Logitech")

    def test_regions_empty_text_cto_and_selection(self):
        for country, expected in (("United States", "US"), ("US", "US"), ("United Kingdom", "UK"),
                                  ("GB", "UK"), ("Australia", "UK"), ("Ireland", ""), ("Germany", "")):
            self.lookup.return_value = {**deepcopy(INFO), "shipping_country": country}
            sid = self.open(text="", items=[0, 1, 2, 2])
            r = self.read(sid).json["review"]
            self.assertEqual(r["sku_country"], expected)
            self.assertEqual(r["keyboard_language"], expected)
            self.assertEqual(r["selected_skus"], ["101", "202"])
            self.assertTrue(r["multiple_skus"])
            self.assertEqual(r["alt_type"], "CTO device")
            self.assertEqual(r["lead_time"], "3-5 weeks")
            self.assertEqual(r["model"], "")
            self.assertEqual(r["price"], "")
            self.assertEqual(r["mpn"], "")
        sid = self.open(items=[0, 1])
        self.assertFalse(self.read(sid).json["review"]["multiple_skus"])
        self.post.assert_not_called()
        self.gmail.assert_not_called()

    def test_make_and_device_type_match_source(self):
        for name, make, dtype in (("MacBook Air", "Apple", "Laptop"), ("Logitech keyboard", "Logitech", "Other"),
                                  ("Samsung tablet", "Samsung", "Tablet"), ("Apple iPhone", "Apple", "Mobile Phone")):
            review = build_review({**INFO, "items": [{"sku": "1", "product_name": name}]}, [0], "")
            self.assertEqual((review["make"], review["device_type"]), (make, dtype))

    def test_bad_inputs_and_lookup_failures_never_create_review(self):
        for body in (None, [], {}, {"po": 42}, {"po": "x", "items": []}, {"po": "x", "items": [True]},
                     {"po": "x", "items": [-1]}, {"po": "x", "items": [10]},
                     {"po": "x", "items": [0], "text": {}}, {"po": "x", "items": [0], "text": "a" * 20001}):
            result = self.client.post("/api/alt-review", json=body)
            self.assertEqual(result.status_code, 400, result.json)
        for info in ({"error": "sensitive service detail"}, None):
            self.lookup.return_value = info
            self.assertEqual(self.client.post("/api/alt-review", json={"po": "x", "items": [0]}).status_code, 502)
        self.post.assert_not_called()

    def test_sessions_isolated_expiring_bounded_and_no_cache(self):
        first = self.open()
        self.lookup.return_value = {**deepcopy(INFO), "order_number": "other", "resolved_order_number": "other"}
        second = self.open()
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 40)
        self.assertEqual(self.read(first).json["review"]["order_number"], "123-1-TEST")
        self.assertEqual(self.read(second).json["review"]["order_number"], "other")
        self.assertEqual(self.read(first).headers["Cache-Control"], "no-store")
        self.assertEqual(self.read(first).headers["Referrer-Policy"], "no-referrer")
        with app.app.app_context(), alt_reviews.database() as db:
            db.execute("UPDATE reviews SET expires=? WHERE sid=?", (time.time() - 1, first))
        self.assertEqual(self.read(first).status_code, 410)
        self.assertEqual(self.submit(first).status_code, 410)
        self.assertEqual(self.read("unknown").status_code, 410)
        with patch.object(alt_reviews, "MAX_REVIEWS", 1):
            result = self.client.post("/api/alt-review", json={"po": "x", "items": [0]})
            self.assertEqual(result.status_code, 503)
        with app.app.app_context(), alt_reviews.database() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM reviews WHERE sid=?", (first,)).fetchone()[0], 0)

    def test_scout_gating_unchanged_except_alt(self):
        with patch.object(app, "SCOUT", ""):
            self.open()
            self.assertEqual(self.client.get("/api/config").json, {"scout": False})
            for endpoint in ("/api/price-review", "/api/autopilot"):
                self.assertEqual(self.client.post(endpoint, json={}).status_code, 503)

    def test_exact_airtable_and_webhook_payload_and_edits(self):
        sid = self.open(items=[0, 2])
        ticket = valid_ticket(self.read(sid).json["review"])
        ticket.update(requested_by="emma@allwhere.co", model="Edited model", requested_sku="edited SKU",
                      lead_time="6 weeks", multiple_skus=True, price="0")
        ticket.update(header={"org_name": "forged", "is_rush": False}, order_number="forged")
        self.mock_success()
        result = self.submit(sid, ticket)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["notification"], "accepted")
        self.assertEqual(result.json["url"], "https://airtable.com/appTest/tblTest/recTest")
        calls = self.post.call_args_list
        self.assertEqual(calls[0].args[0], "https://api.airtable.com/v0/appTest/tblTest")
        fields = calls[0].kwargs["json"]["fields"]
        expected = {field: ticket[key] for key, field in FIELD_MAP.items() if ticket[key] != ""}
        expected.update({
            "fldeKFtQ0zJr7C9oh": "Alternate Approval", "fldebG0qifOIDrXKE": "Urgent",
            "fldcBGJ46hG6aF2M3": "123-1-TEST", "fldXxx6BIslbdAhgT": [ticket["alt_type"]],
            "fldmbDKEdzVJlBald": ["Model unavailable"], "fldQtfsOMZblbXVP4": "No",
            "fldIW7HeL5uq1W9iI": True, "fldCDwjxPNuLMT0ub": [{"id": "usrEmma"}],
            "fldXipHrKdmbdx6pA": [{"id": "usrOM"}], "fldIDtJqa4jgz6O7p": "Test Org"})
        self.assertEqual(fields, expected)
        payload = calls[1].kwargs["json"]
        self.assertEqual(payload, {
            "record_id": "recTest", "status": "Open", "orderNumbers": ["123-1-TEST"],
            "requestedSKU": "edited SKU", "subject": "Test summary", "alternativeType": ticket["alt_type"],
            "make": "Apple", "model": "Edited model", "processor": "M4 10C/8C",
            "memory": "24 GB", "storage": "512 GB", "language": "US", "color": "Midnight",
            "display": '13"', "price": "0", "mpn": "MXW73LL/A", "secondAlt": False,
            "secondAltMake": "", "secondAltModel": "", "secondAltProcessor": "", "secondAltMemory": "",
            "secondAltStorage": "", "secondAltLanguage": "", "secondAltColor": "", "secondAltDisplay": "",
            "secondAltPrice": "", "secondAltMPN": "", "leadTime": "6 weeks",
        })
        self.assertNotIn("multipleSKU", payload)
        self.assertFalse(calls[0].kwargs["allow_redirects"])
        self.assertEqual(calls[1].kwargs["headers"]["X-Webhook-Secret"], "test-only-webhook")
        self.gmail.assert_not_called()
        self.get.assert_not_called()

    def test_missing_configuration_and_unmapped_people_are_explicit(self):
        sid = self.open()
        for key in CONFIG:
            with patch.dict(os.environ, {key: ""}):
                result = self.submit(sid)
                self.assertEqual(result.status_code, 503, key)
                self.assertIn(key, str(result.json))
                self.assertTrue(result.json["retryable"])
        with patch.dict(os.environ, {"AIRTABLE_USER_IDS_JSON": '{"other@test.com":"usrOther"}'}):
            result = self.submit(sid)
            self.assertIn("Assigned To", str(result.json))
            self.assertIn("Requested By", str(result.json))
        self.post.assert_not_called()
        for value in ("http://bad.test", "https://[invalid", "https://user:pass@example.test"):
            with patch.dict(os.environ, {"AUTOMATED_APPROVALS_WEBHOOK_URL": value}):
                self.assertTrue(configuration()[1])

    def test_validation_failures_never_write(self):
        sid = self.open()
        for key, value in (("price", "NaN"), ("price", "-1"), ("price", "Infinity"),
                           ("price", "$12"), ("make", ""), ("multiple_skus", "true"),
                           ("alt_type", "invalid"), ("requested_by", "unlisted@test.com"),
                           ("model", ["bad"]), ("memory", "bad\nvalue")):
            ticket = valid_ticket()
            ticket[key] = value
            self.assertEqual(self.submit(sid, ticket).status_code, 400, key)
        self.post.assert_not_called()

    def test_completed_session_persists_and_cannot_repeat(self):
        sid = self.open()
        self.mock_success()
        first = self.submit(sid).json
        # A new client simulates a tab reload / new worker using the same durable store.
        second = app.app.test_client().post("/api/alt-review/" + sid + "/submit", json={}).json
        self.assertEqual(second, first)
        self.assertEqual(self.read(sid).json["state"], "completed")
        self.assertEqual(self.post.call_count, 2)

    def test_webhook_partial_success_and_timeout_keep_ticket_link(self):
        for failure in (response({}, 500), requests.Timeout("sensitive exception")):
            sid = self.open()
            self.post.side_effect = [response({"id": "recPartial"}, 201), failure]
            result = self.submit(sid)
            self.assertTrue(result.json["created"])
            self.assertFalse(result.json["retryable"])
            self.assertIn("Do not create another", result.json["message"])
            self.assertIn("recPartial", result.json["url"])
            self.assertNotIn("sensitive", str(result.json))
            self.assertEqual(self.submit(sid).json, result.json)

    def test_ambiguous_creation_never_retries(self):
        for upstream in (requests.Timeout("sensitive"), requests.ConnectionError("sensitive"),
                         response({}, 500), response({}, 302), response({}, 200),
                         response(None, 201)):
            sid = self.open()
            self.post.reset_mock()
            self.post.side_effect = [upstream]
            result = self.submit(sid)
            self.assertEqual(result.status_code, 409)
            self.assertEqual(result.json["state"], "uncertain")
            self.assertIn("Airtable", result.json["error"])
            self.assertNotIn("sensitive", str(result.json))
            self.submit(sid)
            self.assertEqual(self.post.call_count, 1)

    def test_upstream_rejection_is_sanitized_and_retryable(self):
        sid = self.open()
        self.post.side_effect = [response({"error": {"message": "secret token"}}, 422)]
        result = self.submit(sid)
        self.assertEqual(result.status_code, 502)
        self.assertTrue(result.json["retryable"])
        self.assertNotIn("secret token", str(result.json))
        self.assertEqual(self.read(sid).json["state"], "pending")

    def test_concurrent_submit_only_creates_once(self):
        sid = self.open()
        entered, release = threading.Event(), threading.Event()
        def post(url, **kwargs):
            if "api.airtable" in url:
                entered.set()
                release.wait(5)
                return response({"id": "recConcurrent"}, 201)
            return response({})
        self.post.side_effect = post
        results = []
        thread = threading.Thread(target=lambda: results.append(
            app.app.test_client().post("/api/alt-review/" + sid + "/submit", json=valid_ticket())))
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.submit(sid).status_code, 409)
            self.assertEqual(self.read(sid).json["state"], "submitting")
        finally:
            release.set()
            thread.join(5)
        self.assertEqual(results[0].status_code, 200)
        self.assertEqual(self.post.call_count, 2)

    def test_crash_after_creation_preserves_checkpoint(self):
        sid = self.open()
        self.post.side_effect = [response({"id": "recCrash"}, 201), RuntimeError("simulated crash")]
        result = self.submit(sid)
        self.assertTrue(result.json["created"])
        self.assertEqual(result.json["notification"], "uncertain")
        self.assertEqual(self.submit(sid).json["record_id"], "recCrash")
        self.assertEqual(self.post.call_count, 2)

    def test_normal_priority_canonical_po_assets_and_origin(self):
        self.lookup.return_value = {**INFO, "is_rush": False, "order_number": "123-1", "resolved_order_number": "123-1-TEST"}
        sid = self.open()
        self.mock_success()
        self.submit(sid)
        fields = self.post.call_args_list[0].kwargs["json"]["fields"]
        self.assertEqual(fields["fldebG0qifOIDrXKE"], "High")
        self.assertEqual(fields["fldcBGJ46hG6aF2M3"], "123-1-TEST")
        for path in ("/alt-review?session=" + sid, "/alt-review-assets/alt-review.css", "/alt-review-assets/alt-review.js"):
            result = self.client.get(path)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.headers["Cache-Control"], "no-store")
            result.close()
        result = self.client.post("/api/alt-review/" + sid + "/submit", json=valid_ticket(), headers={"Origin": "https://evil.invalid"})
        self.assertEqual(result.status_code, 403)


if __name__ == "__main__":
    unittest.main()
