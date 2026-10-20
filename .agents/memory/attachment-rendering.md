---
name: Attachment rendering verification
description: Verify actual document pixels rather than a mounted attachment frame.
---

Verify that a PDF actually paints readable content; a mounted frame or successful load alone does not prove rendering.

**Why:** The built-in PDF viewer produced a blank reading area in local Chromium while frame-visibility checks passed. Canvas rendering avoids reliance on the browser's PDF plugin.

**How to apply:** Keep a known-text, multipage PDF fixture and check painted pixels plus an actual screenshot, not just the presence of the viewer element.

Do not treat a passing current-source preview as proof that a published attachment problem is fixed.

**Why:** The user's separate-tab screenshot matched the preceding link behavior, while current source painted the same mocked flow successfully. Those observations alone cannot identify which release an external browser served.

**How to apply:** Distinguish local reproduction from published-version evidence, and report remaining merge/publication/reload requirements without claiming a live fix.
