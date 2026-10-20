"""Saving existing Gmail drafts retains files; all network access is mocked."""
import base64
import unittest
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from unittest.mock import Mock, patch

import app


class DraftAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.drafts = self.service.users.return_value.drafts.return_value
        self.drafts.update.return_value.execute.return_value = {"id": "existing-draft"}
        self.drafts.create.return_value.execute.return_value = {"id": "new-draft"}
        self.patch = patch.object(app, "gmail", return_value=self.service)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.network = patch("requests.sessions.Session.request",
                             side_effect=AssertionError("Live network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.client = app.app.test_client()
        self.payload = {"draftId": "existing-draft", "threadId": "existing-thread",
                        "to": "edited@example.test", "cc": "copy@example.test",
                        "subject": "Edited request", "body": "Edited request body"}

    def existing(self, message, thread="existing-thread"):
        self.drafts.get.return_value.execute.return_value = {"message": {
            "threadId": thread,
            "raw": base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("="),
        }}

    def saved(self):
        self.drafts.update.assert_called_once()
        args = self.drafts.update.call_args.kwargs
        self.assertEqual(args["id"], "existing-draft")
        self.assertEqual(args["body"]["message"]["threadId"], "existing-thread")
        raw = base64.urlsafe_b64decode(args["body"]["message"]["raw"])
        self.drafts.create.assert_not_called()
        self.drafts.send.assert_not_called()
        self.drafts.delete.assert_not_called()
        return BytesParser(policy=policy.default).parsebytes(raw)

    def test_quote_and_confirmation_save_keep_exact_file_bytes_and_names(self):
        for confirmation in (False, True):
            with self.subTest(confirmation=confirmation):
                self.drafts.reset_mock()
                message = EmailMessage()
                message["Subject"] = "Original request"
                message.set_content("Original request body")
                files = [
                    ("quote ∙ sample.pdf", "application", "pdf", b"%PDF-1.4\nmock\x00\xff"),
                    ("notes.txt", "text", "plain", b"notes with bytes\n"),
                ]
                for name, main, sub, content in files:
                    message.add_attachment(content, maintype=main, subtype=sub, filename=name)
                self.existing(message)
                payload = dict(self.payload)
                if confirmation:
                    payload.update(body="Edited confirmation\n\nOn Monday vendor wrote:\n> Quote",
                                   subject="Re: Original request", inReplyTo="vendor-message",
                                   references="earlier-message")
                result = self.client.post("/api/draft", json=payload)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json, {"draftId": "existing-draft"})
                saved = self.saved()
                self.assertEqual(str(saved["To"]), payload["to"])
                self.assertEqual(str(saved["Cc"]), payload["cc"])
                self.assertEqual(str(saved["Subject"]), payload["subject"])
                self.assertEqual(saved.get_body(preferencelist=("plain",)).get_content().strip(),
                                 payload["body"])
                self.assertEqual([(p.get_filename(), p.get_content_type(), p.get_payload(decode=True))
                                  for p in saved.iter_attachments()],
                                 [(name, main + "/" + sub, content) for name, main, sub, content in files])
                if confirmation:
                    self.assertEqual(saved["In-Reply-To"], "vendor-message")
                    self.assertEqual(saved["References"], "earlier-message vendor-message")

    def test_nested_inline_and_forwarded_files_are_kept_once(self):
        message = EmailMessage()
        message.set_content("Plain body")
        message.add_alternative("<p>HTML body<img src='cid:logo'></p>", subtype="html")
        message.get_payload()[1].add_related(b"image bytes", maintype="image", subtype="png",
                                            cid="<logo>", filename="logo.png", disposition="inline")
        forwarded = EmailMessage()
        forwarded.set_content("Forwarded email")
        forwarded.add_attachment(b"nested bytes", maintype="application",
                                 subtype="octet-stream", filename="nested.bin")
        message.add_attachment(forwarded, filename="forwarded.eml")
        self.existing(message)
        result = self.client.post("/api/draft", json=self.payload)
        self.assertEqual(result.status_code, 200)
        saved = self.saved()
        files = list(saved.iter_attachments())
        self.assertEqual([p.get_filename() for p in files], ["logo.png", "forwarded.eml"])
        self.assertEqual(files[0]["Content-ID"], "<logo>")
        self.assertEqual(files[0].get_content_disposition(), "inline")
        self.assertEqual(files[0].get_payload(decode=True), b"image bytes")
        nested = files[1].get_payload()[0]
        self.assertEqual(list(nested.iter_attachments())[0].get_payload(decode=True), b"nested bytes")

    def test_plain_existing_draft_stays_plain(self):
        message = EmailMessage()
        message.set_content("Old body")
        self.existing(message)
        self.assertEqual(self.client.post("/api/draft", json=self.payload).status_code, 200)
        self.assertFalse(self.saved().is_multipart())

    def test_new_draft_never_reads_an_existing_message(self):
        payload = {**self.payload, "draftId": None}
        result = self.client.post("/api/draft", json=payload)
        self.assertEqual(result.status_code, 200)
        self.drafts.get.assert_not_called()
        self.drafts.update.assert_not_called()
        self.drafts.create.assert_called_once()

    def test_failed_or_malformed_read_never_writes(self):
        responses = [{}, {"message": {"threadId": "existing-thread", "raw": "%%%"}},
                     {"message": {"threadId": "existing-thread", "raw": ""}}]
        responses.extend({"message": {"threadId": "existing-thread", "raw":
                                      base64.urlsafe_b64encode(raw).decode()}}
                         for raw in (b"not MIME", b"\n\nHeaderless body",
                                     b"Subject: Draft\n\nBody without MIME headers",
                                     b"MIME-Version: 1.0\n\nMissing content type",
                                     b"Content-Type: text/plain\n\nMissing MIME version"))
        for response in responses:
            with self.subTest(response=response):
                self.drafts.get.return_value.execute.return_value = response
                result = self.client.post("/api/draft", json=self.payload)
                self.assertEqual(result.status_code, 502)
                self.assertIn("Nothing was saved", result.json["error"])
                self.drafts.update.assert_not_called()
                self.drafts.create.assert_not_called()
        self.drafts.get.return_value.execute.side_effect = RuntimeError("private service details")
        result = self.client.post("/api/draft", json=self.payload)
        self.assertEqual(result.status_code, 502)
        self.assertNotIn("private", result.json["error"])
        self.drafts.update.assert_not_called()

    def test_wrong_thread_never_updates_or_creates(self):
        message = EmailMessage()
        message.set_content("Another order's draft")
        self.existing(message, thread="other-thread")
        self.assertEqual(self.client.post("/api/draft", json=self.payload).status_code, 409)
        self.drafts.update.assert_not_called()
        self.drafts.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
