---
name: Catalog investigation constraints
description: Prioritize repairing catalog access and avoid inferring product history from legacy lookup failures.
---

Prioritize repairing and verifying catalog access, not description parsing or snapshot fallback as the primary solution. A legacy catalog 404 proves only that the endpoint did not find the exact record; it does not establish deletion or migration history.

**Why:** The user explicitly requested catalog repair first. The Samsung description had concatenated prose that looked like a part number; authentication revealed a structured catalog MPN without needing to infer it.

**How to apply:** Investigate residual MPN gaps only after successful authenticated reads. Never infer another person's environment has the same credential problem without inspecting its configuration securely.

The earlier catalog-price inclusion decision was superseded; removing only a price label was not the user's intent.

**Why:** The user clarified that “get rid of it” meant remove the price itself, not just the label before the amount. Keeping a bare USD amount did not meet the request.

**How to apply:** Follow the current vendor-email requirement in replit.md rather than reopening the old price-source decision. Keep this correction scoped to vendor requests, not unrelated internal catalog data.
