import unittest
from unittest.mock import Mock, patch

import app
import scout_port


class OrderLookupTests(unittest.TestCase):
    def setUp(self):
        # Existing order tests isolate order identity/phone from the separate catalog.
        catalog = patch.object(scout_port, "_ps_variant", return_value={
            "found": False, "status": "temporary_failure", "message": "Catalog unavailable.",
        })
        catalog.start()
        self.addCleanup(catalog.stop)

    def test_lookup_normalization_preserves_numeric_order_segment(self):
        cases = {
            "161664-1-LANG": "161664-1",
            " 161664-1-LANG (2) ": "161664-1",
            "161664-1": "161664-1",
            "161664 (3)": "161664",
        }
        for entered, expected in cases.items():
            with self.subTest(entered=entered):
                self.assertEqual(scout_port._clean_po(entered), expected)
                self.assertEqual(scout_port.clean_po(entered), expected)

    def test_order_route_uses_one_exact_order_snapshot(self):
        upstream = Mock(status_code=200)
        upstream.json.return_value = {
            "items": [{
                "orderNumber": "161664-1-LANG",
                "status": "Test status",
                "recipient": {"firstName": "Test", "address": {"country": "US"}},
                "orderItems": [{
                    "quantity": 1,
                    "productVariantSnapshot": {"mpn": "TEST-MPN", "title": "Test device"},
                }],
            }]
        }
        with patch.object(scout_port.requests, "get", return_value=upstream) as get:
            response = app.app.test_client().get("/api/order/161664-1-LANG")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.json["order_number"], "161664-1-LANG")
        self.assertEqual(response.json["status"], "Test status")
        self.assertEqual(len(response.json["order_items"]), 1)
        self.assertEqual(get.call_count, 1)
        for call in get.call_args_list:
            self.assertEqual(call.kwargs["params"], {"orderNumber": "161664-1-LANG"})

    def test_confirmation_phone_comes_from_recipient(self):
        upstream = Mock(status_code=200)
        upstream.json.return_value = {"items": [{
            "orderNumber": "123456-1-TEST", "status": "QUOTE_IN_PROGRESS",
            "recipient": {"phoneNumber": "+61400000001"},
        }]}
        with patch.object(scout_port.requests, "get", return_value=upstream):
            self.assertEqual(scout_port.fetch_full_order("123456-1-TEST")["confirmation_phone"], "+61400000001")

    def test_confirmation_does_not_use_synthetic_shipping_phone(self):
        upstream = Mock(status_code=200)
        upstream.json.return_value = {"items": [{
            "orderNumber": "123456-1-TEST", "status": "QUOTE_IN_PROGRESS",
        }]}
        with patch.object(scout_port.requests, "get", return_value=upstream):
            self.assertEqual(scout_port.fetch_full_order("123456-1-TEST")["confirmation_phone"], "")


if __name__ == "__main__":
    unittest.main()
