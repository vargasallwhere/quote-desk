"""Attachment endpoint tests. No credentials or external services."""
import base64
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import app
from googleapiclient.errors import HttpError


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.service = Mock()
        self.mock = patch.object(app, "gmail", return_value=self.service)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def retrieve(self, data, name="quote.pdf", mime="application/pdf"):
        self.service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {
            "data": base64.urlsafe_b64encode(data).decode().rstrip("=")}
        return self.client.get("/api/attachment/message/attachment?" + urlencode({"name": name, "type": mime}))

    def test_binary_bytes_safe_headers_and_unicode_filename(self):
        for mime, data in [
            ("application/pdf", b"%PDF-1.7\nbinary\xff"),
            ("image/png", b"\x89PNG\r\n\x1a\nbinary"),
            ("image/jpeg", b"\xff\xd8\xffbinary"),
            ("image/gif", b"GIF89abinary"),
            ("image/webp", b"RIFF1234WEBPbinary"),
            ("image/bmp", b"BMbinary"),
        ]:
            with self.subTest(mime=mime):
                result = self.retrieve(data, '报价 "quote"\r\n/\\file', mime)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.data, data)
                self.assertEqual(result.mimetype, mime)
                disposition = result.headers["Content-Disposition"]
                self.assertTrue(disposition.startswith("attachment;"))
                self.assertIn("filename*=UTF-8''", disposition)
                self.assertNotIn("\r", disposition)
                self.assertNotIn("\n", disposition)
                self.assertEqual(result.headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(result.headers["Cache-Control"], "no-store")
                self.assertIn("sandbox", result.headers["Content-Security-Policy"])
        self.service.users.return_value.messages.return_value.attachments.return_value.get.assert_called_with(
            userId="me", messageId="message", id="attachment")

    def test_active_and_mislabeled_content_is_download_only(self):
        for mime, data in [
            ("text/html", b"<script>parent.compromised=true</script>"),
            ("image/svg+xml", b'<svg onload="alert(1)"/>'),
            ("application/pdf", b"<html>not a pdf</html>"),
            ("image/png", b'<svg onload="alert(1)"/>'),
            ("text/html\r\nBad: header", b"<html/>"),
            ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK"),
        ]:
            with self.subTest(mime=mime):
                result = self.retrieve(data, 'file.html', mime)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.mimetype, "application/octet-stream")
                self.assertTrue(result.headers["Content-Disposition"].startswith("attachment;"))

    def test_retrieval_errors_are_clear_without_internal_details(self):
        execute = self.service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute
        for error, status, message in [
            (HttpError(Mock(status=404, reason="not found"), b'{}'), 404, "no longer available"),
            (HttpError(Mock(status=403, reason="forbidden"), b'{}'), 502, "Try again"),
            (RuntimeError("private detail"), 502, "Try again"),
        ]:
            with self.subTest(status=status):
                execute.side_effect = error
                result = self.client.get("/api/attachment/m/a")
                self.assertEqual(result.status_code, status)
                self.assertIn(message, result.json["error"])
                self.assertNotIn("private", result.json["error"])

    def test_renderer_only_exposes_required_browser_assets(self):
        self.assertEqual(self.client.get("/attachment-renderer/build/pdf.min.mjs").status_code, 200)
        for path in ("package.json", "../app.py", "build/pdf.sandbox.min.mjs"):
            self.assertEqual(self.client.get("/attachment-renderer/" + path).status_code, 404)


if __name__ == "__main__":
    unittest.main()
