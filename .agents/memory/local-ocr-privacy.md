---
name: Local scanned-quote recognition
description: Privacy and interaction decisions for recognizing scanned vendor quotes.
---

Keep quote OCR on-device and explicitly requested per page, with recognition results treated as uncertain evidence rather than verified specifications.

**Why:** Vendor quotes can contain customer information; external OCR requires explicit consent. Recognition is costly and fallible, so opening a quote must not silently process every page or imply catalog verification.

**How to apply:** Future OCR improvements must preserve local processing, clear uncertainty labels, cancellation while leaving the reader usable, and no persistent storage of recognized quote content. Additional languages can use locally served models, not remote document-processing APIs.
