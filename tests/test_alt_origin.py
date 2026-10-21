"""No network: proxy-equivalent requests and hostile headers at both write gates."""
import os
from unittest.mock import patch

from flask import request

import alt_reviews
from alt_origin import replit_origin, valid_origin, public_origin
from test_alt_reviews import AltReviewFixture, TEXT, valid_ticket
import app


class AltOriginTests(AltReviewFixture):
    def test_reported_published_address_requires_operator_pin(self):
        # Reproduce the screenshot's exact rejected stage without any public access.
        origin = "https://quote-desk-sara455.replit.app"
        kwargs = self.origins("http://internal.test:5000", origin, {
            "X-Forwarded-Host": "attacker.test", "X-Forwarded-Proto": "garbage"})
        data = {"po":"SYNTHETIC", "items":[2, 0], "text":TEXT}
        with patch.dict(app.app.config, {"ALT_REVIEW_EXTERNAL_ORIGIN":None,
                                        "ALT_REVIEW_PUBLIC_ORIGIN":None}):
            denied = self.client.post("/api/alt-review", json=data, **kwargs)
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(denied.json["stage"], "origin")
            self.lookup.assert_not_called()
        with patch.dict(app.app.config, {"ALT_REVIEW_PUBLIC_ORIGIN":public_origin(origin)}):
            opened = self.client.post("/api/alt-review", json=data, **kwargs)
            self.assertEqual(opened.status_code, 200)
            sid = opened.json["url"].split("session=")[1]
            review = self.read(sid).json["review"]
            self.assertEqual(review["selected_skus"], ["202","101"])
            self.assertEqual(review["model"], "MacBook Air")
            for bad in ("https://other.replit.app", origin + ".evil.test", "null"):
                denied = self.client.post("/api/alt-review", json=data,
                    **self.origins("http://internal.test:5000", bad,
                                   {"X-Forwarded-Host":origin.split("://")[1]}))
                self.assertEqual(denied.status_code, 403)
        self.post.assert_not_called()
        self.gmail.assert_not_called()

    def test_public_origin_startup_validation(self):
        for value in ("", None, "http://example.test", "https://example.test/",
                      "https://*.replit.app", "https://example.test/path",
                      "https://user@example.test", "https://a.test,https://b.test"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                public_origin(value)

    def origins(self, base, origin, headers=None):
        return dict(base_url=base, headers={"Origin": origin, **(headers or {})})

    def test_local_reproduction_of_old_guard(self):
        with app.app.test_request_context(
                "/api/alt-review", base_url="http://internal.test:5000",
                headers={"Origin": "https://quote-test.replit.dev",
                         "X-Forwarded-Proto": "https",
                         "X-Forwarded-Host": "quote-test.replit.dev"}):
            # Only synthetic scheme/host facts; no customer/session/header dumps.
            self.assertEqual(request.scheme, "http")
            self.assertEqual(request.host, "internal.test:5000")
            self.assertNotEqual(request.headers["Origin"], request.host_url.rstrip("/"))
            self.assertEqual(request.headers["X-Forwarded-Host"], "quote-test.replit.dev")

    def test_runtime_domain_is_exact_configuration_not_request_input(self):
        self.assertEqual(replit_origin("quote-test.replit.dev"), "https://quote-test.replit.dev")
        for domain in (None, "", "evil.test", "quote-test.replit.dev.evil.test",
                       "quote-test.replit.dev:443", "quote-test.replit.dev/path",
                       "quote-test.replit.dev, evil.test", "user@quote-test.replit.dev"):
            self.assertIsNone(replit_origin(domain), domain)
        for origin in ("http://[::1]evil", "http://[::1]:", "http://localhost:05070",
                       "http://localhost?", "http://localhost#", "http://localhost/",
                       "http://localhost:0", "http://localhost:65536", "http://localhost\t"):
            self.assertFalse(valid_origin(origin), origin)

    def test_direct_and_pinned_proxy_open_submit_and_duplicate_lock(self):
        external = "https://quote-test.replit.dev"
        with patch.dict(app.app.config, {"ALT_REVIEW_EXTERNAL_ORIGIN": external}):
            for base, origin, headers in (
                    ("http://localhost:5070", "http://localhost:5070", {}),
                    ("http://127.0.0.1:5070", "http://127.0.0.1:5070", {}),
                    ("http://[::1]:5070", "http://[::1]:5070", {}),
                    ("http://quote-test.replit.dev", external, {}),
                    ("http://internal.test:5000", external, {
                        "X-Forwarded-Proto": "http, https",
                        "X-Forwarded-Host": "attacker.test, quote-test.replit.dev",
                        "X-Forwarded-For": "203.0.113.1, 127.0.0.1",
                        "Forwarded": "host=attacker.test;proto=http"}),
                    ("http://internal.test:5000", external, {
                        "X-Forwarded-Proto": "garbage", "X-Forwarded-Host": "evil.test"}),
                    ("https://quote-test.replit.dev", external, {})):
                with self.subTest(base=base, headers=headers):
                    kwargs = self.origins(base, origin, headers)
                    opened = self.client.post("/api/alt-review",
                                              json={"po": "123-1-TEST", "items": [2, 0], "text": TEXT},
                                              **kwargs)
                    self.assertEqual(opened.status_code, 200, opened.json)
                    sid = opened.json["url"].split("session=")[1]
                    review = self.read(sid).json["review"]
                    self.assertEqual(review["selected_skus"], ["202", "101"])
                    self.assertEqual(review["model"], "MacBook Air")
                    self.mock_success()
                    before = self.post.call_count
                    path = "/api/alt-review/" + sid + "/submit"
                    result = self.client.post(path, json=valid_ticket(review), **kwargs)
                    self.assertEqual(result.status_code, 200, result.json)
                    self.assertEqual(self.client.post(path, json={}, **kwargs).json, result.json)
                    self.assertEqual(self.post.call_count, before + 2)
        self.gmail.assert_not_called()

    def test_hostile_origins_blocked_before_lookup_storage_and_writes(self):
        external = "https://quote-test.replit.dev"
        sid = self.open()
        self.lookup.reset_mock()
        bad = ("https://evil.test", "null", "", "https://quote-test.replit.dev.evil.test",
               "https://quote-test.replit.dev@evil.test", "https://evil.test@quote-test.replit.dev",
               external + "/", external + "/path", external + "?x", external + "#x",
               external + ":443", external + ":444", "http://quote-test.replit.dev",
               external + ", https://evil.test", external + " https://evil.test",
               "https://quote-test.replit.dev\\@evil.test", "https://[invalid",
               "https://quote-test.replit.dev:", "https://quote-test.replit.dev:99999",
               "https://quote-test.replit.dev.", "https://other.replit.dev")
        with patch.dict(app.app.config, {"ALT_REVIEW_EXTERNAL_ORIGIN": external}), \
                patch.object(alt_reviews, "database", side_effect=AssertionError("Origin must precede DB")):
            for origin in bad:
                for path in ("/api/alt-review", f"/api/alt-review/{sid}/submit"):
                    result = self.client.post(path, json=valid_ticket(),
                                              **self.origins("http://internal.test:5000", origin, {
                                                  "X-Forwarded-Host": "quote-test.replit.dev",
                                                  "X-Forwarded-Proto": "https"}))
                    self.assertEqual(result.status_code, 403, origin)
        self.lookup.assert_not_called()
        self.post.assert_not_called()
        self.gmail.assert_not_called()
        self.assertEqual(self.read(sid).json["state"], "pending")

    def test_spoofed_forwarding_cannot_establish_authority(self):
        with patch.dict(app.app.config, {"ALT_REVIEW_EXTERNAL_ORIGIN": None}), \
                patch.object(alt_reviews, "database", side_effect=AssertionError("No session access")):
            for base, origin in (
                    ("http://127.0.0.1:5070", "https://quote-test.replit.dev"),
                    ("http://127.0.0.1:5070", "http://localhost:5070"),
                    ("http://localhost:5070", "http://localhost:5000"),
                    ("http://localhost:5070", "https://localhost:5070"),
                    ("http://evil.test", "http://evil.test"),
                    ("http://quote-test.replit.dev", "https://quote-test.replit.dev")):
                for path in ("/api/alt-review", "/api/alt-review/unknown/submit"):
                    result = self.client.post(path, json={}, **self.origins(base, origin, {
                        "X-Forwarded-Host": origin.split("://")[1],
                        "X-Forwarded-Proto": origin.split(":")[0],
                        "Forwarded": 'for=127.0.0.1;host="quote-test.replit.dev";proto=https'}))
                    self.assertEqual(result.status_code, 403, (base, origin))
        self.lookup.assert_not_called()
        self.post.assert_not_called()

    def test_json_only_missing_origin_and_missing_config_compatibility(self):
        # Existing non-browser clients deliberately do not need Origin.
        sid = self.open(text="")
        for path in ("/api/alt-review", f"/api/alt-review/{sid}/submit"):
            for content_type in ("text/plain", "application/x-www-form-urlencoded"):
                result = self.client.post(path, data='{"po":"x","items":[0]}',
                                          content_type=content_type, headers={"Origin": "http://localhost"})
                self.assertEqual(result.status_code, 400)
        external = "https://quote-test.replit.dev"
        with patch.dict(app.app.config, {"ALT_REVIEW_EXTERNAL_ORIGIN": external}), \
                patch.dict(os.environ, {"AIRTABLE_PAT": ""}):
            kwargs = self.origins("http://internal.test:5000", external)
            opened = self.client.post("/api/alt-review", json={"po": "123-1-TEST", "items": [0]}, **kwargs)
            self.assertEqual(opened.status_code, 200)
            sid = opened.json["url"].split("session=")[1]
            self.assertIn("AIRTABLE_PAT", str(self.read(sid).json["configuration_errors"]))
            path = f"/api/alt-review/{sid}/submit"
            self.assertEqual(self.client.post(path, json={}, **kwargs).status_code, 400)
            self.assertEqual(self.client.post(path, json=valid_ticket(), **kwargs).status_code, 503)
            self.assertEqual(self.read(sid).json["state"], "pending")
        self.post.assert_not_called()
        self.gmail.assert_not_called()
