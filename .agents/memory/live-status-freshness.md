---
name: Live status freshness
description: Keep Allwhere status current without disrupting email work.
---

Order status must refresh independently of Gmail threads and the reply composer. Never refresh the whole order/thread view just to update the status badge while someone may be editing a reply.

**Why:** The user repeatedly reported incorrect statuses, including across other orders after a freshness change. Freshness is a requirement, not proof of the underlying cause; validating a single order or only the refresh path is insufficient.

**How to apply:** Read live Allwhere status for the selected order, preserve draft edits, discard late results for a different selected order, and clearly label the last-known status if a refresh fails.

Validate initial loading and subsequent refreshes against the same exact order identity. Before claiming a broad status issue is resolved, reproduce a reported mismatch against the user's expected status; do not assume polling or a successful service response proves correctness.
