import unittest
from unittest.mock import Mock, patch

import requests
from app import app
import scout_port


class OrderStatusTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

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

    def test_ambiguous_or_wrong_order_does_not_supply_a_status(self):
        for items in [
            [{"orderNumber": "123456-1-OTHER", "status": "PENDING_APPROVAL"}],
            [{"orderNumber": "123456-1-TEST", "status": "PENDING_APPROVAL"}] * 2,
            [],
        ]:
            with self.subTest(items=items), patch.object(scout_port.requests, "get", return_value=self.response(items)):
                result = self.client.get("/api/order-status/123456-1-TEST")
                self.assertEqual(result.status_code, 502)
                self.assertIn("error", result.json)
                self.assertNotIn("status", result.json)

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
