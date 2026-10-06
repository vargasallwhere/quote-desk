---
name: Imported configuration quoting
description: A non-obvious failure when transferring desktop Allwhere settings into Replit Secrets.
---

Desktop settings copied into secrets can retain surrounding literal quotes. Treat benign literal quoting as an import-format issue, not a missing-order result.

**Why:** Secret presence alone does not mean imported configuration is usable; malformed URL syntax can look like an order lookup failure.

**How to apply:** Validate configuration through sanitized error categories and HTTP status codes, not by printing secret values. Preserve compatibility with imported settings when adjusting configuration loading.
