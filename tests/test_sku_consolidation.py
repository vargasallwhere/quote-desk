"""Regional presentation regression checks. Every external read/write is forbidden."""
import unittest
from copy import deepcopy
from unittest.mock import patch

import scout_port as scout


class SkuConsolidationTests(unittest.TestCase):
    def test_diagnostic_quantities_come_from_units_not_warning_count(self):
        items = [{"sku": "137", "quantity": q, "mpn_source": "unavailable",
                  "catalog": {"status": "invalid_data", "message": "Invalid product data."}}
                 for q in (2, 3)]
        before = deepcopy(items)
        self.assertEqual([w["quantity"] for w in scout._catalog_warnings(items)], [2, 3])
        self.assertEqual(scout._catalog_warnings([{
            "sku": "137", "qty": 5, "catalog": {"status": "invalid_data"}}])[0]["quantity"], 5)
        self.assertIsNone(scout._catalog_warnings([{
            "sku": "137", "catalog": {"status": "invalid_data"}}])[0]["quantity"])
        self.assertEqual(items, before)

    def build(self, builder, entries):
        raw = [{"productVariantId": str(i), "quantity": entry["quantity"],
                "protection_plan": entry.get("plan", "")}
               for i, entry in enumerate(entries)]
        header = {"raw_items": raw, "lead_time_approved": False}
        before = deepcopy((header, entries))
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Live network forbidden")), \
                patch("gmail_auth.get_gmail_service", side_effect=AssertionError("Live Gmail forbidden")), \
                patch.object(scout, "get_order_header", return_value=header), \
                patch.object(scout, "get_recipient_info", return_value={}), \
                patch.object(scout, "get_item_details",
                             side_effect=lambda vid, qty, snap: deepcopy(entries[int(vid)])):
            result = builder("MOCK")
        self.assertNotIn("error", result)
        self.assertEqual((header, entries), before)
        return result["email_text"]

    def test_all_regions_equivalent_skus_plans_warranties_and_unknown_identity(self):
        product = {"sku": "137", "product_name": "Apple Device Test", "quantity": 2,
                   "allwhere_mpn": "MPN-TEST", "specs": {"Memory": "24GB"},
                   "price_charged": 912.34, "plan": "Plan Alpha exact"}
        care = {**product, "sku": "CARE", "product_name": "Warranty Standalone",
                "plan": "", "price_charged": 55.7}
        entries = [product, {**product, "quantity": 3}, {**product, "quantity": 4, "plan": "Plan Beta exact"},
                   care, {**care, "quantity": 3},
                   {**care, "product_name": "Warranty Other Coverage", "quantity": 7},
                   {**care, "price_charged": 99, "quantity": 8},
                   {**product, "sku": "", "product_name": "Apple Unknown", "quantity": 1},
                   {**product, "sku": "", "product_name": "Apple Unknown", "quantity": 1},
                   {**product, "sku": "137", "product_name": "Apple Changed Metadata", "quantity": 6},
                   {**product, "sku": "case", "product_name": "Apple Case-sensitive", "quantity": 1},
                   {**product, "sku": "CASE", "product_name": "Apple Case-sensitive", "quantity": 1}]
        for builder in (scout.generate_us_email, scout.generate_uk_email, scout.generate_eu_email):
            with self.subTest(builder=builder.__name__):
                text = self.build(builder, entries)
                self.assertEqual(text.count("Apple Device Test"), 2)
                self.assertRegex(text, r"5[xX]\n(?:MPN: )?MPN-TEST")
                self.assertRegex(text, r"4[xX]\n(?:MPN: )?MPN-TEST")
                self.assertIn("With warranty — Plan Alpha exact", text)
                self.assertIn("With warranty — Plan Beta exact", text)
                self.assertEqual(text.count("5x Warranty Standalone"), 1)
                self.assertIn("7x Warranty Other Coverage", text)
                self.assertIn("8x Warranty Standalone", text)
                self.assertEqual(text.count("Apple Unknown"), 2)
                self.assertEqual(text.count("Apple Case-sensitive"), 2)
                self.assertRegex(text, r"6[xX]\n(?:MPN: )?MPN-TEST\nApple Changed Metadata")
                self.assertLess(text.index("Plan Alpha exact"), text.index("Plan Beta exact"))
                self.assertNotIn("912.34", text)
                self.assertNotIn("55.70", text)
                self.assertNotIn("Unit price", text)
                self.assertNotIn("USD ", text)

    def test_unknown_and_exact_identity_keys(self):
        for sku in ("", " ", None):
            self.assertNotEqual(scout._quote_identity({"sku": sku}), scout._quote_identity({"sku": sku}))
        for sku in ("A", "a", " A "):
            self.assertEqual(scout._quote_identity({"sku": sku}), scout._quote_identity({"sku": sku}))
        self.assertNotEqual(scout._quote_identity({"sku": "A"}), scout._quote_identity({"sku": "a"}))


if __name__ == "__main__":
    unittest.main()
