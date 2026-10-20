---
name: Proxy origin evidence limits
description: What was and was not established about Replit forwarding-header sanitization.
---

The official documentation lookup on 2026-10-20 did not establish whether Replit strips client-supplied forwarding headers or provides a stable trusted-peer/hop boundary. Treat those headers as attacker-controlled until independent evidence proves otherwise.

**Why:** HTTPS/internal-HTTP origin rejection is reproducible locally, but that does not establish the original browser's precise mismatch. Public-preview probing was explicitly excluded from the repair.

**How to apply:** Keep authority anchored to independently controlled runtime configuration; see `ALTERNATIVE_APPROVALS.md` for the supported address policy. If diagnosing the original browser later, obtain only sanitized origin/scheme/host facts with approval, not request dumps or session links.
