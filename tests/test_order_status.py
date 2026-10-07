import unittest
from unittest.mock import Mock, patch

import requests
from app import app
import scout_port


class OrderStatusTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        catalog = patch.object(scout_port, "_ps_variant", return_value={
            "found": False, "status": "temporary_failure", "message": "Catalog unavailable.",
        })
        catalog.start()
        self.addCleanup(catalog.stop)

    def response(self, items, status_code=200):
        response = Mock(status_code=status_code)
        response.json.return_value = {"items": items}
        return response

    def test_exact_suffixed_order_is_selected_not_first_search_result(self):
        upstream = self.response([
            {"orderNumber": "123456-1-OTHER", "status": "PENDING_APPROVAL"},
            {"orderNumber": "123456-1-TEST", "status": "QUOTE_IN_PROGRESS"},
        ])
        with patch.object(scout_port.requests, "get", return_value=upstream) as get:
            result = self.client.get("/api/order-status/123456-1-TEST")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["status"], "QUOTE_IN_PROGRESS")
        self.assertEqual(get.call_args.kwargs["params"], {"orderNumber": "123456-1-TEST"})
        self.assertEqual(result.headers["Cache-Control"], "no-store")
        self.assertIsInstance(result.json["status_checked_at"], int)

    def test_each_check_reads_the_current_status(self):
        before = self.response([{"orderNumber": "123456-1-TEST", "status": "PENDING_APPROVAL"}])
        after = self.response([{"orderNumber": "123456-1-TEST", "status": "QUOTE_IN_PROGRESS"}])
        with patch.object(scout_port.requests, "get", side_effect=[before, after]) as get:
            first = self.client.get("/api/order-status/123456-1-TEST")
            second = self.client.get("/api/order-status/123456-1-TEST")
        self.assertEqual(first.json["status"], "PENDING_APPROVAL")
        self.assertEqual(second.json["status"], "QUOTE_IN_PROGRESS")
        self.assertEqual(get.call_count, 2)

    def test_initial_load_and_refresh_select_same_order_across_statuses(self):
        for suffix, status in [
            ("ALPHA", "PENDING_APPROVAL"),
            ("BETA", "QUOTE_IN_PROGRESS"),
            ("GAMMA", "ORDER_CONFIRMED"),
            ("DELTA", "SHIPPED"),
            ("EPSILON", "DELIVERED"),
            ("ZETA", "CANCELLED"),
        ]:
            po = f"123456-1-{suffix}"
            selected = {
                "orderNumber": po, "status": status,
                "recipient": {"firstName": suffix, "phoneNumber": "test-phone"},
                "deviceColorSwapApproved": True, "flexibleLeadTimeApproved": True,
                "orderItems": [{
                    "productVariantId": "test-variant", "quantity": 2,
                    "protectionPlan": "Test plan",
                    "productVariantSnapshot": {"title": suffix, "mpn": "TEST-MPN"},
                }, {
                    "quantity": 1,
                    "productVariantSnapshot": {"title": "AppleCare warranty", "price": 10},
                }],
            }
            upstream = self.response([
                {"orderNumber": "123456-1-UNRELATED", "status": "WRONG_STATUS"},
                selected,
                {"orderNumber": "123456-2-OTHER", "status": "WRONG_STATUS"},
            ])
            with self.subTest(po=po), patch.object(scout_port.requests, "get", return_value=upstream) as get:
                initial = self.client.get(f"/api/order/{po}")
                refreshed = self.client.get(f"/api/order-status/{po}")
                header = scout_port.get_order_header(po)
                recipient = scout_port.get_recipient_info(po)
            self.assertEqual(initial.status_code, 200)
            self.assertEqual(refreshed.status_code, 200)
            for response in [initial, refreshed]:
                self.assertEqual(response.json["order_number"], po)
                self.assertEqual(response.json["status"], status)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertIsInstance(response.json["status_checked_at"], int)
            self.assertEqual(initial.json["recipient"]["first_name"], suffix)
            self.assertEqual(initial.json["confirmation_phone"], "test-phone")
            self.assertTrue(initial.json["color_swap_approved"])
            self.assertTrue(initial.json["lead_time_approved"])
            self.assertEqual(initial.json["warranty"]["devices"][0]["qty"], 2)
            self.assertEqual(initial.json["warranty"]["lines"][0]["price"], 10)
            self.assertEqual(header["raw_items"][0]["snapshot"]["title"], suffix)
            self.assertEqual(recipient["first_name"], suffix)
            self.assertEqual(get.call_count, 4, "Each path must read exactly one order snapshot")
            for call in get.call_args_list:
                self.assertEqual(call.kwargs["params"], {"orderNumber": po})

    def test_abbreviated_po_resolves_only_one_order(self):
        upstream = self.response([{"orderNumber": "123456-1-TEST", "status": "SHIPPED"}])
        with patch.object(scout_port.requests, "get", return_value=upstream):
            for route in ["/api/order/", "/api/order-status/"]:
                result = self.client.get(route + "123456-1")
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json["order_number"], "123456-1-TEST")
                self.assertEqual(result.json["status"], "SHIPPED")

    def test_lookup_preserves_suffix_and_ignores_duplicate_email_marker(self):
        upstream = self.response([{"orderNumber": "123456-1-TEST", "status": "SHIPPED"}])
        with patch.object(scout_port.requests, "get", return_value=upstream) as get:
            result = self.client.get("/api/order/123456-1-test%20(2)")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["order_number"], "123456-1-TEST")
        self.assertEqual(get.call_args.kwargs["params"], {"orderNumber": "123456-1-test"})

    def test_initial_and_refresh_reject_ambiguous_abbreviated_po(self):
        upstream = self.response([
            {"orderNumber": "123456-1-TEST", "status": "SHIPPED"},
            {"orderNumber": "123456-1-OTHER", "status": "PENDING_APPROVAL"},
        ])
        with patch.object(scout_port.requests, "get", return_value=upstream):
            for route in ["/api/order/", "/api/order-status/"]:
                result = self.client.get(route + "123456-1")
                self.assertEqual(result.status_code, 502)
                self.assertNotIn("status", result.json)

    def test_ambiguous_or_wrong_order_does_not_supply_a_status(self):
        for items in [
            [{"orderNumber": "123456-1-OTHER", "status": "PENDING_APPROVAL"}],
            [{"orderNumber": "123456-1-TEST", "status": "PENDING_APPROVAL"}] * 2,
            [],
        ]:
            with self.subTest(items=items), patch.object(scout_port.requests, "get", return_value=self.response(items)):
                for route in ["/api/order/", "/api/order-status/"]:
                    result = self.client.get(route + "123456-1-TEST")
                    self.assertEqual(result.status_code, 502)
                    self.assertIn("error", result.json)
                    self.assertNotIn("status", result.json)

    def test_missing_status_and_malformed_responses_cannot_look_successful(self):
        for payload in [
            {"items": [{"orderNumber": "123456-1-TEST"}]},
            {"items": "invalid"},
            {"items": [None]},
            [],
        ]:
            upstream = self.response([])
            upstream.json.return_value = payload
            with self.subTest(payload=payload), patch.object(scout_port.requests, "get", return_value=upstream):
                for route in ["/api/order/", "/api/order-status/"]:
                    result = self.client.get(route + "123456-1-TEST")
                    self.assertEqual(result.status_code, 502)
                    self.assertNotIn("status", result.json)

    def test_initial_page_html_is_not_cached(self):
        result = self.client.get("/")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["Cache-Control"], "no-store")

    def test_service_failures_are_explicit_and_uncached(self):
        upstream = self.response([], status_code=401)
        with patch.object(scout_port.requests, "get", return_value=upstream):
            result = self.client.get("/api/order-status/123456-1-TEST")
        self.assertEqual(result.status_code, 502)
        self.assertIn("HTTP 401", result.json["error"])
        self.assertEqual(result.headers["Cache-Control"], "no-store")

        with patch.object(scout_port.requests, "get", side_effect=requests.Timeout("sensitive detail")):
            result = self.client.get("/api/order-status/123456-1-TEST")
        self.assertEqual(result.status_code, 502)
        self.assertNotIn("sensitive detail", result.json["error"])


if __name__ == "__main__":
    unittest.main()
