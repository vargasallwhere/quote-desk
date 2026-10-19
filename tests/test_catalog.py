"""Sanitized catalog fixtures; no real Gmail calls or credential values."""
import os
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

import requests

import app
import catalog
import scout_port as scout


VARIANTS = [
    ("686df253-3798-40b6-aec1-c776c6091323", "16699", "KM3322W-R-UK", "Dell Keyboard and Mouse"),
    ("bd389f4e-97d9-4c80-8188-7ae0b7ba9d64", "16702", "KM555-BLK-UK", "Dell Pro Compact Silent Keyboard and Mouse"),
    ("690b978a-a4f2-441b-a6fe-714369436176", "10237", "LS24D310EAUXXU", "Samsung Essential S3"),
]
PRICES = [27.85, 55.70, 129.18]


def payload(index=0):
    vid, sku, mpn, title = VARIANTS[index]
    return {"id": vid, "sku": int(sku), "mpn": mpn, "title": title, "price": PRICES[index],
            "attributes": {"Color": "Black"}, "is_build_to_order": False}


def response(data=None, code=200):
    result = Mock(status_code=code)
    result.json.return_value = data
    return result


def order(po):
    indices = [0, 1] if po == "161876-1-JUST" else [2]
    return {
        "orderNumber": po, "status": "QUOTE_IN_PROGRESS", "serviceCountry": "Ireland",
        "recipient": {"phoneNumber": "test-recipient-phone", "address": {"country": "Ireland"}},
        "orderItems": [{
            "productVariantId": VARIANTS[i][0], "quantity": 2,
            "orderItemNumber": f"{po}-{n}-TEST", "protectionPlan": "Test warranty",
            "productVariantSnapshot": {
                "sku": VARIANTS[i][1], "mpn": VARIANTS[i][2] if i < 2 else None,
                "title": VARIANTS[i][3], "price": 999, "attributes": [],
                "description": "Part # LS24D310EAUXXUPrice and availability subject to change",
            },
        } for n, i in enumerate(indices, 1)],
    }


class CatalogTests(unittest.TestCase):
    def assert_no_quote_prices(self, text):
        self.assertNotRegex(text, r"(?im)^\s*(?:USD|GBP|EUR|AUD|NZD|\$)\s*[\d,]+\.\d{2}\s*$")
        self.assertNotIn("Catalog unit price", text)
        self.assertNotIn("999.00", text, "Snapshot prices must not leak into quote requests")

    def setUp(self):
        env = patch.dict(os.environ, {"PS_USER": "test-user", "PS_PASS": "test-password"})
        env.start()
        self.addCleanup(env.stop)

    def test_valid_basic_auth_and_exact_identity(self):
        with patch.object(catalog.requests, "get", return_value=response(payload())) as get:
            result = catalog.lookup_variant(VARIANTS[0][0], "16699")
        self.assertTrue(result["found"])
        self.assertEqual(result["mpn"], "KM3322W-R-UK")
        self.assertEqual(get.call_args.kwargs["auth"], ("test-user", "test-password"))
        self.assertEqual(get.call_args.kwargs["timeout"], 15)
        self.assertEqual(get.call_args.args[0], catalog.BASE + "/product-variants/" + VARIANTS[0][0])

    def test_missing_or_blank_config_never_sends_empty_auth(self):
        for values in ({}, {"PS_USER": "test-user"}, {"PS_PASS": "test-password"},
                       {"PS_USER": " ", "PS_PASS": "test-password"}):
            with self.subTest(values=list(values)), patch.dict(os.environ, values, clear=True), \
                    patch.object(catalog.requests, "get") as get:
                self.assertEqual(catalog.lookup_variant("test")["status"], "missing_configuration")
                get.assert_not_called()

    def test_invalid_configuration(self):
        for key, value in (("PS_USER", "bad:user"), ("PS_PASS", "bad\npassword"), ("PS_USER", "bad\u2603")):
            with patch.dict(os.environ, {key: value}), patch.object(catalog.requests, "get") as get:
                self.assertEqual(catalog.lookup_variant("test")["status"], "invalid_configuration")
                get.assert_not_called()

    def test_http_failures_are_distinct_and_sanitized(self):
        for code, expected in [(401, "authentication_rejected"), (403, "access_denied"),
                               (404, "not_found"), (429, "temporary_failure"),
                               (503, "temporary_failure"), (400, "http_error")]:
            with self.subTest(code=code), patch.object(catalog.requests, "get", return_value=response(code=code)):
                result = catalog.lookup_variant("test")
            self.assertEqual(result["status"], expected)
            self.assertEqual(result["http_status"], code)
            self.assertNotIn("test-password", str(result))

    def test_timeout_and_connection_error_are_sanitized(self):
        for error in [requests.Timeout("test-password"), requests.ConnectionError("test-user")]:
            with patch.object(catalog.requests, "get", side_effect=error):
                result = catalog.lookup_variant("test")
            self.assertEqual(result["status"], "temporary_failure")
            self.assertNotIn(str(error), str(result))

    def test_malformed_payloads(self):
        malformed = [None, [], {}, {**payload(), "mpn": 42}, {**payload(), "mpn": ""},
                     {**payload(), "title": []}, {**payload(), "attributes": []},
                     {**payload(), "price": "bad"}, {**payload(), "price": float("nan")},
                     {**payload(), "price": False}, {**payload(), "price": ""},
                     {**payload(), "sku": None}, {**payload(), "sku": True},
                     {**payload(), "is_build_to_order": "false"}, {**payload(), "id": None}]
        missing_mpn = payload()
        missing_mpn.pop("mpn")
        malformed.append(missing_mpn)
        for data in malformed:
            with self.subTest(data=data), patch.object(catalog.requests, "get", return_value=response(data)):
                self.assertEqual(catalog.lookup_variant(VARIANTS[0][0])["status"], "invalid_response")
        upstream = response()
        upstream.json.side_effect = ValueError("test-password")
        with patch.object(catalog.requests, "get", return_value=upstream):
            self.assertEqual(catalog.lookup_variant("test")["status"], "invalid_response")

    def test_sku_and_variant_mismatches(self):
        for data in [{**payload(), "sku": 16702}, {**payload(), "id": "wrong-id"}]:
            with patch.object(catalog.requests, "get", return_value=response(data)):
                result = catalog.lookup_variant(VARIANTS[0][0], "16699")
            self.assertEqual(result["status"], "identity_mismatch")
            self.assertFalse(result["found"])

    def test_explicit_null_is_success_and_overrides_snapshot(self):
        with patch.object(catalog.requests, "get", return_value=response({**payload(), "mpn": None})):
            result = scout.get_item_details(VARIANTS[0][0], 3, {"sku": "16699", "mpn": "OLD-MPN"})
        self.assertEqual(result["allwhere_mpn"], "")
        self.assertEqual(result["mpn_source"], "catalog")
        self.assertEqual(result["catalog"]["status"], "no_mpn")
        self.assertEqual(result["quantity"], 3)

    def test_failure_does_not_cache_or_discard_snapshot(self):
        with patch.object(catalog.requests, "get", side_effect=[response(code=503), response(payload())]) as get:
            snap = {"sku": "16699", "mpn": "KM3322W-R-UK", "title": "Dell"}
            fallback = scout.get_item_details(VARIANTS[0][0], 2, snap)
            recovered = scout.get_item_details(VARIANTS[0][0], 2, snap)
        self.assertEqual(fallback["allwhere_mpn"], "KM3322W-R-UK")
        self.assertEqual(fallback["mpn_source"], "order_snapshot")
        self.assertEqual(recovered["mpn_source"], "catalog")
        self.assertEqual(get.call_count, 2)

    def test_config_updates_are_loaded_without_stale_auth(self):
        with patch.object(catalog.requests, "get", return_value=response(payload())) as get:
            catalog.lookup_variant(VARIANTS[0][0])
            with patch.dict(os.environ, {"PS_PASS": "updated-test-password"}):
                catalog.lookup_variant(VARIANTS[0][0])
        self.assertEqual(get.call_args.kwargs["auth"][1], "updated-test-password")

    def mock_reads(self, po, catalog_code=200, null_mpn=False, mismatch=False):
        selected = order(po)
        def read(url, **kwargs):
            if "/product-variants/" in url:
                index = next(i for i, v in enumerate(VARIANTS) if url.endswith(v[0]))
                data = payload(index)
                if null_mpn:
                    data["mpn"] = None
                if mismatch:
                    data["sku"] = "wrong-sku"
                return response(data, catalog_code)
            if url.endswith("/order"):
                return response({"items": [{"orderNumber": "161876-1-OTHER", "status": "WRONG"}, deepcopy(selected)]})
            raise AssertionError("Unexpected request: " + url)
        return read

    def test_both_orders_all_read_only_quote_paths_and_endpoints(self):
        for po in ("161876-1-JUST", "161880-1-JUST"):
            expected = VARIANTS[:2] if po == "161876-1-JUST" else VARIANTS[2:]
            with self.subTest(po=po), patch.object(scout.requests, "get", side_effect=self.mock_reads(po)), \
                    patch("gmail_auth.get_gmail_service", side_effect=AssertionError("No Gmail verification")):
                for builder in (scout.generate_eu_email, scout.generate_uk_email, scout.generate_us_email):
                    quote = builder(po)
                    self.assertEqual(quote["catalog_warnings"], [])
                    for _, _, mpn, name in expected:
                        self.assertIn(mpn, quote["email_text"])
                        self.assertIn(name, quote["email_text"])
                client = app.app.test_client()
                ticket = client.get("/api/ticket-info/" + po)
                full = client.get("/api/order/" + po)
            for result, key in ((ticket, "items"), (full, "order_items")):
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.headers["Cache-Control"], "no-store")
                self.assertEqual(result.json["order_number"], po)
                self.assertEqual([x["mpn"] for x in result.json[key]], [x[2] for x in expected])
                self.assertEqual(result.json["catalog_warnings"], [])
            self.assertEqual(full.json["confirmation_phone"], "test-recipient-phone")
            self.assertEqual(full.json["warranty"]["devices"][0]["qty"], 2)

    def test_outage_and_mismatch_preserve_dell_associations_and_samsung_visibility(self):
        for code, mismatch in ((401, False), (403, False), (404, False), (503, False), (200, True)):
            for po in ("161876-1-JUST", "161880-1-JUST"):
                with self.subTest(code=code, po=po), patch.object(
                        scout.requests, "get", side_effect=self.mock_reads(po, code, mismatch=mismatch)):
                    quote = scout.generate_eu_email(po)
                    full = scout.fetch_full_order(po)
                    ticket = scout.get_order_info_for_ticket(po)
                self.assertTrue(quote["catalog_warnings"])
                self.assertTrue(full["catalog_warnings"])
                self.assertTrue(ticket["catalog_warnings"])
                if po == "161876-1-JUST":
                    for _, _, mpn, _ in VARIANTS[:2]:
                        self.assertIn(mpn, quote["email_text"])
                    self.assertEqual([i["mpn"] for i in full["order_items"]], [v[2] for v in VARIANTS[:2]])
                else:
                    self.assertIn("Samsung Essential S3", quote["email_text"])
                    self.assertNotIn("LS24D310EAUXXU", quote["email_text"])
                    self.assertEqual(len(full["order_items"]), 1)
                    self.assertEqual(full["order_items"][0]["mpn"], "")

    def test_authoritative_null_quotes_do_not_restore_old_snapshot_mpn(self):
        with patch.object(scout.requests, "get", side_effect=self.mock_reads("161876-1-JUST", null_mpn=True)):
            for builder in (scout.generate_eu_email, scout.generate_uk_email, scout.generate_us_email):
                result = builder("161876-1-JUST")
                self.assertIn("Dell", result["email_text"])
                self.assertNotIn("KM3322W", result["email_text"])
                self.assertNotIn("KM555", result["email_text"])
                self.assertTrue(all(w["status"] == "no_mpn" for w in result["catalog_warnings"]))
            full = scout.fetch_full_order("161876-1-JUST")
            ticket = scout.get_order_info_for_ticket("161876-1-JUST")
        self.assertEqual([i["mpn"] for i in full["order_items"]], ["", ""])
        self.assertEqual([i["mpn"] for i in ticket["items"]], ["", ""])

    def test_unknown_variant_remains_visible(self):
        with patch.object(catalog.requests, "get", return_value=response(code=404)):
            result = scout.get_item_details("unknown", 4)
        self.assertEqual(result["product_name"], "Variant unknown")
        self.assertEqual(result["quantity"], 4)
        self.assertEqual(result["allwhere_mpn"], "")
        self.assertEqual(result["catalog"]["status"], "not_found")

    def test_existing_gmail_thread_guard_still_blocks_quote_mutations(self):
        service = Mock()
        service.users.return_value.threads.return_value.list.return_value.execute.return_value = {"threads": [{"id": "test"}]}
        with patch.object(app, "gmail", return_value=service), patch.object(app, "generate_auto_quote_email") as generate:
            result = app.app.test_client().post("/api/quote-draft", json={"po": "161876-1-JUST"})
        self.assertEqual(result.status_code, 409)
        generate.assert_not_called()

    def test_auto_quote_propagates_mpns_and_diagnostics_using_only_mock_gmail(self):
        for po in ("161876-1-JUST", "161880-1-JUST"):
            for code in (200, 503):
                service = Mock()
                service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
                    "id": "mock-draft", "message": {"id": "mock-message"},
                }
                with patch.object(scout.requests, "get", side_effect=self.mock_reads(po, code)), \
                        patch("gmail_auth.get_gmail_service", return_value=service):
                    result = scout.generate_auto_quote_email(po)
                self.assertEqual(result["region"], "eu")
                self.assertEqual(bool(result["catalog_warnings"]), code == 503)
                self.assert_no_quote_prices(result["email_text"])
                if po == "161876-1-JUST":
                    for _, _, mpn, _ in VARIANTS[:2]:
                        self.assertIn(mpn, result["email_text"])
                elif code == 200:
                    self.assertIn("LS24D310EAUXXU", result["email_text"])
                else:
                    self.assertIn("Samsung", result["email_text"])
                    self.assertNotIn("LS24D310EAUXXU", result["email_text"])

    def test_all_regional_templates_keep_mpns_without_prices(self):
        for po in ("161876-1-JUST", "161880-1-JUST"):
            with patch.object(scout.requests, "get", side_effect=self.mock_reads(po)):
                for builder in (scout.generate_eu_email, scout.generate_uk_email, scout.generate_us_email):
                    text = builder(po)["email_text"]
                    indices = [0, 1] if po == "161876-1-JUST" else [2]
                    for i in indices:
                        self.assertIn(VARIANTS[i][2], text)
                        self.assertNotIn(f"{PRICES[i]:.2f}", text)
                    self.assert_no_quote_prices(text)

    def test_missing_catalog_price_is_not_invented_and_explicit_zero_is_valid(self):
        for raw_price in (None, "missing", 0):
            data = payload()
            if raw_price == "missing":
                data.pop("price")
            else:
                data["price"] = raw_price
            with patch.object(catalog.requests, "get", return_value=response(data)):
                details = scout.get_item_details(VARIANTS[0][0], 2, {"sku": "16699", "price": 999})
            self.assertEqual(details.get("catalog_unit_price"), 0 if raw_price == 0 else None)
            self.assertEqual(details["allwhere_mpn"], "KM3322W-R-UK")

    def test_duplicate_quantities_are_preserved_without_prices(self):
        selected = order("161876-1-JUST")
        duplicate = deepcopy(selected["orderItems"][0])
        duplicate["quantity"] = 3
        selected["orderItems"].append(duplicate)
        read = self.mock_reads("161876-1-JUST")
        def requests_get(url, **kwargs):
            return response({"items": [selected]}) if url.endswith("/order") else read(url, **kwargs)
        with patch.object(scout.requests, "get", side_effect=requests_get):
            for builder in (scout.generate_eu_email, scout.generate_uk_email, scout.generate_us_email):
                text = builder("161876-1-JUST")["email_text"]
                self.assertIn("5X" if builder == scout.generate_us_email else "5x", text)
                self.assert_no_quote_prices(text)
                self.assertNotIn("139.25", text)

    def test_warranty_requests_do_not_include_catalog_prices(self):
        read = self.mock_reads("161876-1-JUST")
        def requests_get(url, **kwargs):
            result = read(url, **kwargs)
            if url.endswith(VARIANTS[1][0]):
                result.json.return_value["title"] = "Dell Warranty"
            return result
        with patch.object(scout.requests, "get", side_effect=requests_get):
            for builder in (scout.generate_eu_email, scout.generate_uk_email, scout.generate_us_email):
                text = builder("161876-1-JUST")["email_text"]
                self.assertIn("Dell Warranty", text)
                self.assertNotIn("55.70", text)
                self.assert_no_quote_prices(text)

    def test_regional_product_and_warranty_zero_and_unavailable_prices(self):
        for raw_price in (0, None, "missing", 2419.12):
            read = self.mock_reads("161876-1-JUST")
            def requests_get(url, **kwargs):
                result = read(url, **kwargs)
                if "/product-variants/" in url:
                    data = result.json.return_value
                    if raw_price == "missing":
                        data.pop("price")
                    else:
                        data["price"] = raw_price
                    if url.endswith(VARIANTS[1][0]):
                        data["title"] = "Dell Warranty"
                return result
            with patch.object(scout.requests, "get", side_effect=requests_get), \
                    patch("gmail_auth.get_gmail_service", side_effect=AssertionError("No Gmail verification")):
                for builder in (scout.generate_eu_email, scout.generate_uk_email, scout.generate_us_email):
                    with self.subTest(price=raw_price, region=builder.__name__):
                        text = builder("161876-1-JUST")["email_text"]
                        self.assertIn("Dell Warranty", text)
                        self.assertNotIn("2,419.12", text)
                        self.assert_no_quote_prices(text)


if __name__ == "__main__":
    unittest.main()
