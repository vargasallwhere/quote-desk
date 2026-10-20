---
name: Attachment rendering verification
description: Verify actual document pixels rather than a mounted attachment frame.
---

Verify that a PDF actually paints readable content; a mounted frame or successful load alone does not prove rendering.

**Why:** The built-in PDF viewer produced a blank reading area in local Chromium while frame-visibility checks passed. Canvas rendering avoids reliance on the browser's PDF plugin.

**How to apply:** Keep a known-text, multipage PDF fixture and check painted pixels plus an actual screenshot, not just the presence of the viewer element.
