---
name: Catalog investigation constraints
description: Prioritize repairing catalog access and avoid inferring product history from legacy lookup failures.
---

Prioritize repairing and verifying catalog access, not description parsing or snapshot fallback as the primary solution. A legacy catalog 404 proves only that the endpoint did not find the exact record; it does not establish deletion or migration history.

**Why:** The user explicitly requested catalog repair first. The Samsung description had concatenated prose that looked like a part number; authentication revealed a structured catalog MPN without needing to infer it.

**How to apply:** Investigate residual MPN gaps only after successful authenticated reads. Never infer another person's environment has the same credential problem without inspecting its configuration securely.

Do not ask the user to choose the price source again for vendor auto-quotes; use the established catalog-price requirement.

**Why:** The user corrected an unnecessary source-selection question after catalog access was repaired: “you already know this answer.”

**How to apply:** Use the catalog-price requirement documented in replit.md when fixing auto-quote omissions, without reopening the same decision.
