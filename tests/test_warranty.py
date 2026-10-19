"""Warranty requests through real builders and MIME creation, with all I/O mocked."""
import base64
import json
import unittest
from contextlib import ExitStack
from copy import deepcopy
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import Mock, patch

import app
import scout_port as scout


PO = "123456-1-TEST"
ABSENT = object()
REGIONS = [
    ("United States", "us", "Jeremy.Houck@tdsynnex.com", "Hi Jeremy & SMB Team,"),
    ("United Kingdom", "uk", "cian.samuel-maher@selecttechgroup.com", "Hi Cian,"),
    ("Ireland", "eu", "cian.samuel-maher@selecttechgroup.com", "Hi Cian,"),
    ("Australia", "au", "john.angel@compnow.com.au", "Hi John & Uyen,"),
    ("New Zealand", "nz", "darryl.coughey@cyclone.co.nz", "Hi Darryl,"),
    ("Unmapped country", "uk", "cian.samuel-maher@selecttechgroup.com", "Hi Cian,"),
    ("", "uk", "cian.samuel-maher@selecttechgroup.com", "Hi Cian,"),
]


def item(plan=ABSENT, qty=1, variant="device", title="Apple MacBook Test"):
    result = {
        "productVariantId": variant, "quantity": qty, "orderItemNumber": PO,
        "productVariantSnapshot": {
            "title": title, "sku": variant, "mpn": "TEST-" + variant,
            "price": 999, "attributes": {"Memory": "24 GB", "Color": "Black"},
        },
    }
    if plan is not ABSENT:
        result["protectionPlan"] = plan
    return result


def order(items, country="Ireland"):
    return {
        "orderNumber": PO, "status": "QUOTE_IN_PROGRESS", "orderItems": items,
        "organization": {"id": "test-org"}, "shippingType": {"name": "Standard"},
        "recipient": {
            "firstName": "Test", "lastName": "Recipient", "phoneNumber": "test-phone",
            "address": {"country": country, "streetAddress1": "Test street"},
        },
    }


class WarrantyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # Any unexpected network/Gmail path fails rather than reaching live services.
        self.stack.enter_context(patch("requests.sessions.Session.request",
                                      side_effect=AssertionError("Live network forbidden")))
        self.stack.enter_context(patch("gmail_auth.get_gmail_service",
                                      side_effect=AssertionError("Live Gmail forbidden")))
        self.selected = order([item("Add protection plan")])
        self.stack.enter_context(patch.object(scout, "fetch_allwhere_order",
                                             side_effect=lambda po: deepcopy(self.selected)))
        self.catalog_failure = False
        self.stack.enter_context(patch.object(scout, "_ps_variant", side_effect=self.catalog))
        self.org_notes = ""
        self.stack.enter_context(patch.object(scout.requests, "get", side_effect=self.organization))

    def catalog(self, variant, sku=None):
        if self.catalog_failure:
            return {"found": False, "status": "temporary_failure",
                    "message": "Catalog unavailable."}
        snap = next(i["productVariantSnapshot"] for i in self.selected["orderItems"]
                    if i["productVariantId"] == variant)
        return {
            "found": True, "status": "ok", "sku": snap["sku"],
            "product_name": snap["title"], "mpn": snap["mpn"],
            "price_charged": 27.85 if variant == "device" else 55.70,
            "price_available": True, "attributes": snap["attributes"],
            "is_build_to_order": False,
        }

    def organization(self, url, **kwargs):
        if url.endswith("/billing-address"):
            self.assertEqual(kwargs["params"], {"organizationId": "test-org"})
            response = Mock(status_code=200)
            response.json.return_value = {"items": []}
            return response
        self.assertTrue(url.endswith("/organizations/test-org"), "Unexpected upstream read")
        response = Mock(status_code=200)
        response.json.return_value = {
            "internalNotes": self.org_notes, "appleDepNumber": "TEST-ABM",
            "windowsAutopilot": "TEST-AUTOPILOT",
        }
        return response

    def save_new_draft(self, country):
        self.selected["recipient"]["address"]["country"] = country
        service = Mock()
        service.users.return_value.threads.return_value.list.return_value.execute.return_value = {}
        drafts = service.users.return_value.drafts.return_value
        drafts.create.return_value.execute.return_value = {
            "id": "test-draft", "message": {"id": "test-message"},
        }
        with patch.object(app, "gmail", return_value=service), \
                patch("gmail_auth.get_gmail_service", return_value=service):
            response = app.app.test_client().post("/api/quote-draft", json={"po": PO})
        self.assertEqual(response.status_code, 200, response.json)
        drafts.create.assert_called_once()
        # No existing-draft write, send, delete, or purchase/order mutation.
        drafts.update.assert_not_called()
        drafts.send.assert_not_called()
        drafts.delete.assert_not_called()
        service.users.return_value.messages.return_value.send.assert_not_called()
        raw = drafts.create.call_args.kwargs["body"]["message"]["raw"]
        message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
        text = message.get_content()
        self.assertEqual(text, response.json["email_text"])
        self.assertEqual(str(message["subject"]), PO)
        self.assertIn("sourcing@allwhere.co", str(message["cc"]))
        self.assertIn("Test Recipient\nTest street", text)
        return response.json, message, text

    def test_sanitized_observed_values_and_uncertainty_are_recorded(self):
        evidence = json.loads((Path(__file__).parent / "fixtures/warranty_source.json").read_text())
        self.assertIn("do not prove", evidence["evidence"]["limitation"])
        for sample in evidence["observed"]:
            with self.subTest(sample=sample["sample"]):
                self.assertEqual(bool(scout.device_protection_plan(sample["protectionPlan"])),
                                 sample["requested"])

    def test_plan_cases_agree_in_summary_and_all_new_regional_mime_bodies(self):
        cases = [
            ("Add protection plan", "Add protection plan"),
            ("AppleCare+ specified plan", "AppleCare+ specified plan"),
            ("  Vendor named coverage  ", "Vendor named coverage"),
            (ABSENT, ""), (None, ""), ("", ""), (" \t ", ""),
            ("No protection plan", ""), (" NO  protection PLAN ", ""),
            ("none", ""), ("No warranty", ""), ("no plan", ""),
            ("false", ""), ("no", ""), (False, ""), (True, ""),
            (0, ""), ({"name": "Unverified plan"}, ""), (["Unverified plan"], ""),
        ]
        for country, region, vendor, greeting in REGIONS:
            for value, plan in cases:
                with self.subTest(country=country, plan=value):
                    self.selected = order([item(value)], country)
                    # Insurance is not a substitute for a requested protection plan.
                    self.selected["orderItems"][0]["insuranceRequested"] = True
                    summary = scout.fetch_full_order(PO)["warranty"]
                    result, message, text = self.save_new_draft(country)
                    self.assertEqual(result["region"], region)
                    self.assertIn(vendor, str(message["to"]))
                    self.assertTrue(text.startswith(greeting))
                    if region == "nz":
                        self.assertIn("sam.savea@cyclone.co.nz", str(message["cc"]))
                    if plan:
                        self.assertEqual(summary["devices"], [
                            {"name": "Apple MacBook Test", "plan": plan, "qty": 1},
                        ])
                        self.assertIn("USD 27.85\nWith warranty — " + plan, text)
                        self.assertEqual(text.count("With warranty"), 1)
                    else:
                        self.assertEqual(summary["devices"], [])
                        self.assertNotIn("With warranty", text)
                    self.assertIn("USD 27.85", text)
                    self.assertIn("Enrolled in ABM: TEST-ABM", text)
                    self.assertNotIn("999.00", text)
                    self.assertNotIn("3 year", text)

    def test_mixed_repeated_devices_consolidate_only_matching_plans(self):
        for country, _, _, _ in REGIONS:
            with self.subTest(country=country):
                self.selected = order([
                    item("Add protection plan", 2), item("No protection plan", 3),
                    item("Plan Alpha", 4), item("Plan Beta", 5),
                    item("Add protection plan", 6), item(None, 7),
                ], country)
                summary = scout.fetch_full_order(PO)["warranty"]
                self.assertEqual({d["plan"]: d["qty"] for d in summary["devices"]},
                                 {"Add protection plan": 8, "Plan Alpha": 4, "Plan Beta": 5})
                _, _, text = self.save_new_draft(country)
                blocks = [block for block in text.split("\n\n") if "Apple MacBook Test" in block]
                self.assertEqual(len(blocks), 4)
                for block, qty, plan in zip(blocks, [8, 10, 4, 5],
                                            ["Add protection plan", "", "Plan Alpha", "Plan Beta"]):
                    self.assertRegex(block, rf"(?im)^{qty}x$")
                    self.assertIn("USD 27.85", block)
                    self.assertEqual("With warranty" in block, bool(plan))
                    if plan:
                        self.assertIn("With warranty — " + plan, block)
                self.assertEqual(text.splitlines().count("USD 27.85"), 4)
                self.assertNotIn("USD 222.80", text)

    def test_standalone_enterprise_and_catalog_failure_remain_distinct(self):
        for country, _, _, _ in REGIONS:
            for failure in (False, True):
                for enterprise in (False, True):
                    with self.subTest(country=country, failure=failure, enterprise=enterprise):
                        self.catalog_failure = failure
                        self.org_notes = "Enterprise warranty instruction" if enterprise else ""
                        self.selected = order([
                            item("No protection plan", 2),
                            item("Plan Gamma", 3, "second-device", "Dell Laptop Test"),
                            # A standalone product remains standalone even when it has a plan field.
                            item("Add protection plan", 4, "warranty", "AppleCare Warranty Test"),
                            item(None, 2, "warranty", "AppleCare Warranty Test"),
                        ], country)
                        summary = scout.fetch_full_order(PO)["warranty"]
                        self.assertEqual(summary["devices"], [
                            {"name": "Dell Laptop Test", "plan": "Plan Gamma", "qty": 3},
                        ])
                        self.assertEqual(sum(w["qty"] for w in summary["lines"]), 6)
                        _, _, text = self.save_new_draft(country)
                        self.assertEqual(text.count("With warranty"), 1)
                        self.assertIn("With warranty — Plan Gamma", text)
                        self.assertIn("AppleCare Warranty Test", text)
                        self.assertNotIn("With warranty — Add protection plan", text)
                        self.assertEqual("With Enterprise Warranty" in text, enterprise)
                        self.assertIn("TEST-AUTOPILOT" if country == "United States"
                                      else "CSV hash extraction", text)
                        self.assertIn("USD 55.70" if not failure
                                      else "Catalog unit price unavailable.", text)
                        self.assertNotIn("999.00", text)

    def test_existing_thread_or_draft_blocks_every_quote_write(self):
        for country, _, _, _ in REGIONS:
            for labels in ([], ["DRAFT"]):
                with self.subTest(country=country, labels=labels):
                    self.selected = order([item("Add protection plan")], country)
                    service = Mock()
                    service.users.return_value.threads.return_value.list.return_value.execute.return_value = {
                        "threads": [{"id": "existing-thread", "labelIds": labels}],
                    }
                    with patch.object(app, "gmail", return_value=service), \
                            patch.object(app, "generate_auto_quote_email") as generate:
                        response = app.app.test_client().post("/api/quote-draft", json={"po": PO})
                    self.assertEqual(response.status_code, 409)
                    generate.assert_not_called()
                    service.users.return_value.drafts.assert_not_called()
                    service.users.return_value.messages.assert_not_called()


if __name__ == "__main__":
    unittest.main()
