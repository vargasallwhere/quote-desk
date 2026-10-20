"""Australia depot notifications: synthetic orders and in-memory Gmail only."""
import base64
import copy
import tempfile
import unittest
from contextlib import ExitStack
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from unittest.mock import Mock, patch

import app
import scout_port
from depot_notification import DESTINATION, TO, CC, eligibility, preview
from depot_routes import HEADER
from depot_store import Store

PO = "163424-1-ALPA"


def item(sku="MAC", qty=1, name="Apple MacBook Pro", **attrs):
    return {"quantity": qty, "productVariantId": sku or "unknown",
            "productVariantSnapshot": {"sku": sku, "title": name, "mpn": "TEST-MPN",
                                       "attributes": attrs or {"Memory": "24GB"}, "price": 912.34}}


def order(po=PO):
    return {"id": "synthetic-order-" + po, "orderNumber": po, "status": "QUOTE_IN_PROGRESS",
            "orderType": {"toDepot": True}, "depot": {"name": DESTINATION},
            "finalDestination": DESTINATION, "orderItems": [item()],
            "recipient": {"address": {"country": "Australia"}}}


class FakeGmail:
    """Exercise the real Flask handlers/MIME, never the Google network client."""
    def __init__(self):
        self.service = Mock()
        self.drafts = self.service.users.return_value.drafts.return_value
        self.threads = self.service.users.return_value.threads.return_value
        self.saved = {}
        self.sent = {}
        self.mode = ""
        self.threads.list.return_value.execute.side_effect = self.list_threads
        self.threads.get.return_value.execute.side_effect = self.get_thread
        self.drafts.create.side_effect = lambda **kw: Mock(execute=lambda: self.save(None, kw["body"]))
        self.drafts.update.side_effect = lambda **kw: Mock(execute=lambda: self.save(kw["id"], kw["body"]))
        self.drafts.get.side_effect = lambda **kw: Mock(execute=lambda: self.read(kw["id"]))
        self.drafts.send.side_effect = lambda **kw: Mock(execute=lambda: self.send(kw["body"]["id"]))
        self.drafts.list.return_value.execute.side_effect = lambda: {
            "drafts": [{"id": k, "message": {"id": v["message"]["id"]}} for k, v in self.saved.items()]}

    def save(self, draft_id, body):
        if self.mode == "save-timeout":
            raise TimeoutError("private upstream information")
        draft_id = draft_id or "draft-" + str(len(self.saved) + len(self.sent) + 1)
        message = copy.deepcopy(body["message"])
        message.update(id="msg-" + draft_id, threadId=message.get("threadId") or "thread-" + draft_id)
        self.saved[draft_id] = {"id": draft_id, "message": message}
        return copy.deepcopy(self.saved[draft_id])

    def read(self, draft_id):
        return copy.deepcopy(self.saved[draft_id])

    def send(self, draft_id):
        if self.mode == "send-timeout":
            raise TimeoutError("private upstream information")
        if self.mode == "send-rejected":
            from googleapiclient.errors import HttpError
            import httplib2
            raise HttpError(httplib2.Response({"status": "403"}), b'{"error":{"message":"rejected"}}')
        message = self.saved.pop(draft_id)["message"]
        self.sent[draft_id] = message
        return {"id": message["id"], "threadId": message["threadId"]}

    def full(self, message, sent=False):
        mime = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(message["raw"]))
        return {"id": message["threadId"], "messages": [{
            "id": message["id"], "internalDate": "1", "labelIds": ["SENT" if sent else "DRAFT"],
            "payload": {"headers": [{"name": k, "value": str(v)} for k, v in mime.items()],
                        "mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(
                            mime.get_body(preferencelist=("plain",)).get_content().encode()).decode()}}}]}

    def list_threads(self):
        return {"threads": [{"id": v["message"]["threadId"]} for v in self.saved.values()] +
                           [{"id": v["threadId"]} for v in self.sent.values()]}

    def get_thread(self):
        # Mock's last call records the id used by execute.
        key = self.threads.get.call_args.kwargs["id"]
        for v in self.saved.values():
            if v["message"]["threadId"] == key:
                return self.full(v["message"])
        for v in self.sent.values():
            if v["threadId"] == key:
                return self.full(v, True)
        raise AssertionError("Unknown synthetic thread")


class DepotTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.db = temp + "/depot.sqlite3"
        self.stack.enter_context(patch.dict(app.app.config, {"DEPOT_STORE_PATH": self.db, "SECRET_KEY": "mock-only-key"}))
        self.stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Live requests forbidden")))
        self.stack.enter_context(patch("gmail_auth.get_gmail_service", side_effect=AssertionError("Live Gmail forbidden")))
        self.selected = order()
        self.stack.enter_context(patch.object(scout_port, "fetch_allwhere_order", side_effect=lambda po: copy.deepcopy(self.selected)))
        self.catalog_failure = False
        self.stack.enter_context(patch.object(scout_port, "_ps_variant", side_effect=self.catalog))
        self.fake = FakeGmail()
        self.stack.enter_context(patch.object(app, "gmail", return_value=self.fake.service))
        # register() receives a stable wrapper, so patching app.gmail works through it.
        self.client = app.app.test_client()

    def catalog(self, variant, sku):
        snap = next(x["productVariantSnapshot"] for x in self.selected["orderItems"]
                    if x["productVariantId"] == variant)
        if self.catalog_failure:
            return {"found": False, "status": "temporary_failure", "message": "Catalog unavailable"}
        return {"found": True, "status": "ok", "sku": snap["sku"], "mpn": snap["mpn"],
                "product_name": snap["title"], "attributes": snap["attributes"],
                "price_charged": 912.34, "is_build_to_order": False}

    def payload(self, revision=0):
        return {"po": PO, "subject": PO + " - Order coming to warehouse", "body": "Edited arrival\n\nBest,\nSara",
                "revision": revision}

    def post(self, action, payload=None):
        return self.client.post("/api/depot-" + action, json=payload or self.payload())

    def test_eligibility_exact_flag_name_conflict_and_no_country_heuristic(self):
        self.assertTrue(eligibility(order())["eligible"])
        for name in (" ALLWHERE  storage AUSTRALIA ", "\tallwhere storage Australia\n"):
            o = order()
            o["depot"]["name"] = name
            self.assertTrue(eligibility(o)["eligible"])
        for change in ({"orderType": {"toDepot": False}}, {"orderType": {"toDepot": "true"}},
                       {"orderType": {}}, {"depot": {}}, {"depot": {"name": "Other Australia depot"}},
                       {"depot": {"name": DESTINATION + " West"}}, {"finalDestination": "allwhere storage UK"}):
            self.assertFalse(eligibility({**order(), **change})["eligible"], change)

    def test_user_template_two_devices_all_specs_and_no_prices(self):
        self.selected["orderItems"] = [
            item("FIRST", 2, "Apple MacBook Air", Color="Midnight", Finish="Standard", Memory="16GB",
                 Storage="512GB", Keyboard="US English", Processor="M4", Graphics="10-core GPU", Display="13-inch"),
            item("SECOND", 1, "Apple MacBook Pro", Color="Silver", Memory="24GB", Storage="1TB")]
        before = copy.deepcopy(self.selected)
        response = self.client.get("/api/depot-preview/" + PO)
        self.assertEqual(response.status_code, 200, response.json)
        data = response.json
        self.assertEqual(data["subject"], PO + " - Order coming to warehouse")
        self.assertEqual(data["to"], TO)
        self.assertEqual(data["cc"], CC)
        self.assertEqual(data["body"], "Hi Team,\n\nPlease expect the following devices at your warehouse!\n\n"
                         "2X TEST-MPN\nApple MacBook Air\nMidnight, Standard, 16GB, 512GB, US English, M4, 10-core GPU, 13-inch"
                         "\n\n1X TEST-MPN\nApple MacBook Pro\nSilver, 24GB, 1TB\n\nBest,\nSara")
        self.assertEqual(before, self.selected)
        self.fake.drafts.create.assert_not_called()
        self.fake.drafts.send.assert_not_called()

    def test_equivalent_conflicting_blank_skus_and_nonphysical_exclusion(self):
        self.selected["orderItems"] = [item(qty=2), item(qty=3), item(qty=4, Memory="32GB"),
                                       item("", 1), item("", 1),
                                       *[item(str(i), name=n) for i, n in enumerate(
                                           ("AppleCare warranty", "Autopilot enrollment", "ABM Registration",
                                            "Software License", "Protection Plan"))]]
        data = preview(self.selected)
        self.assertEqual(data["body"].count("Apple MacBook Pro"), 4)
        self.assertIn("5X TEST-MPN", data["body"])
        self.assertIn("4X TEST-MPN", data["body"])
        for service in ("AppleCare", "Autopilot", "ABM", "License", "Protection"):
            self.assertNotIn(service, data["body"])
        self.assertNotIn("912.34", data["body"])

    def test_catalog_failure_missing_specs_and_null_mpn_warn_outside_template(self):
        self.catalog_failure = True
        self.selected["orderItems"][0]["productVariantSnapshot"].update(mpn=None, attributes={})
        data = preview(self.selected)
        self.assertIn("[MPN unavailable — review]", data["body"])
        self.assertGreaterEqual(len(data["warnings"]), 3)
        self.assertNotIn("catalog", data["body"])
        self.assertNotIn("price", data["body"])

    def test_reopen_reuse_attachments_and_exact_headers(self):
        saved = self.post("save")
        self.assertEqual(saved.status_code, 200, saved.json)
        state = saved.json["notification"]
        existing = self.fake.saved[state["draft_id"]]["message"]
        mime = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(existing["raw"]))
        mime.add_attachment(b"synthetic file", maintype="application", subtype="pdf", filename="mock.pdf")
        existing["raw"] = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        opened = self.client.get("/api/depot-preview/" + PO)
        self.assertEqual(opened.json["body"], self.payload()["body"])
        self.assertEqual(opened.json["notification"]["draft_id"], state["draft_id"])
        saved = self.post("save", self.payload(1))
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(len(self.fake.saved), 1)
        self.fake.drafts.create.assert_called_once()
        existing = self.fake.saved[state["draft_id"]]["message"]
        mime = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(existing["raw"]))
        self.assertEqual(mime[HEADER], PO)
        self.assertIsNone(mime["In-Reply-To"])
        self.assertIsNone(mime["References"])
        self.assertEqual(str(mime["Subject"]), self.payload()["subject"])
        self.assertEqual([p.get_payload(decode=True) for p in mime.iter_attachments()], [b"synthetic file"])
        from email.utils import getaddresses
        self.assertEqual([a for _, a in getaddresses([str(mime["To"])])],
                         ["Marc.Breynart@systemsgo.asia", "Support.AU@systemsgo.asia",
                          "Gener.Garcia@systemsgo.asia", "Wendy.Yu@systemsgo.asia"])
        self.assertEqual(str(mime["Cc"]), CC)

    def test_confirmation_bound_to_exact_message_and_revision_no_auto_resend(self):
        self.assertEqual(self.post("send").status_code, 409)
        confirmation = self.post("confirm").json["confirmation"]
        self.assertEqual(self.post("send", {**self.payload(), "confirmation": confirmation, "body": "changed"}).status_code, 409)
        sent = self.post("send", {**self.payload(), "confirmation": confirmation})
        self.assertEqual(sent.status_code, 200, sent.json)
        self.assertEqual(sent.json["notification"]["state"], "sent")
        self.assertEqual(self.post("send", {**self.payload(), "confirmation": confirmation}).status_code, 409)
        self.assertEqual(self.client.get("/api/depot-preview/" + PO).json["notification"]["state"], "sent")
        self.fake.drafts.send.assert_called_once()

    def test_stale_concurrent_click_and_restart_journal_cannot_duplicate(self):
        self.assertEqual(self.post("save").status_code, 200)
        self.assertEqual(self.post("save").status_code, 409)
        self.fake.drafts.create.assert_called_once()
        journal = Store(self.db)
        self.assertEqual(journal.get(PO)["state"], "draft")
        journal.claim(PO, 1)
        self.assertEqual(self.post("save", self.payload(2)).status_code, 409)

    def test_uncertain_sends_lock_retries_and_hide_private_errors(self):
        self.fake.mode = "send-timeout"
        confirmation = self.post("confirm").json["confirmation"]
        response = self.post("send", {**self.payload(), "confirmation": confirmation})
        self.assertEqual(response.status_code, 502)
        self.assertTrue(response.json["uncertain"])
        self.assertNotIn("private", response.json["error"])
        self.assertEqual(self.post("save", self.payload(1)).status_code, 409)
        self.assertEqual(self.post("confirm", self.payload(1)).status_code, 409)

    def test_definite_send_failure_is_not_reported_as_uncertain(self):
        self.fake.mode = "send-rejected"
        confirmation = self.post("confirm").json["confirmation"]
        response = self.post("send", {**self.payload(), "confirmation": confirmation})
        self.assertFalse(response.json["uncertain"])
        self.assertEqual(response.json["notification"]["state"], "draft")

    def test_destination_revalidated_on_every_write_and_cross_order_confirmation(self):
        confirmation = self.post("confirm").json["confirmation"]
        self.selected["orderType"]["toDepot"] = False
        for action in ("save", "confirm", "send"):
            self.assertEqual(self.post(action, {**self.payload(), "confirmation": confirmation}).status_code, 409)
        self.fake.drafts.create.assert_not_called()
        self.selected = order("OTHER-1-TEST")
        self.assertEqual(self.post("send", {**self.payload(), "confirmation": confirmation}).status_code, 409)

    def test_depot_conversations_excluded_from_vendor_and_vendor_quote_guard(self):
        self.post("save")
        self.assertEqual(self.client.get("/api/threads/" + PO).json["threads"], [])
        with patch.object(app, "generate_auto_quote_email", return_value={"email_text": "mock"}):
            self.assertEqual(self.client.post("/api/quote-draft", json={"po": PO}).status_code, 200)
        # An unrelated/vendor conversation still blocks creating a quote.
        full = self.fake.full(next(iter(self.fake.saved.values()))["message"])
        full["messages"][0]["payload"]["headers"] = []
        full["id"] = "unrelated"
        self.fake.threads.get.return_value.execute.side_effect = lambda: full
        self.assertEqual(self.client.post("/api/quote-draft", json={"po": PO}).status_code, 409)

    def test_cross_origin_writes_rejected(self):
        response = self.client.post("/api/depot-save", json=self.payload(), headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)
        self.fake.drafts.create.assert_not_called()

    def test_concurrent_saves_have_one_winner_and_one_gmail_create(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier = Barrier(2)
        def save():
            barrier.wait()
            return app.app.test_client().post("/api/depot-save", json=self.payload()).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: save(), range(2)))
        self.assertEqual(sorted(results), [200, 409])
        self.fake.drafts.create.assert_called_once()

    def test_unknown_line_is_visible_and_empty_services_block_preview(self):
        self.selected["orderItems"] = [{"quantity": 1, "productVariantSnapshot": {}}]
        result = preview(self.selected)
        self.assertIn("Product name unavailable", result["body"])
        self.assertIn("MPN unavailable", result["body"])
        self.assertTrue(result["warnings"])
        self.selected["orderItems"] = [item(name="Autopilot enrollment")]
        response = self.client.get("/api/depot-preview/" + PO)
        self.assertEqual(response.status_code, 409)
        self.assertIn("No physical items", response.json["error"])

    def test_unrelated_or_unreadable_saved_draft_cannot_be_overwritten(self):
        self.assertEqual(self.post("save").status_code, 200)
        saved = next(iter(self.fake.saved.values()))
        saved["message"]["threadId"] = "wrong-thread"
        self.assertEqual(self.post("save", self.payload(1)).status_code, 409)
        self.fake.drafts.update.assert_not_called()
        self.fake.drafts.send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
