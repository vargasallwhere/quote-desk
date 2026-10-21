---
name: Proxy origin evidence limits
description: Limits of local origin and approval-launch reproductions as evidence of a reported browser failure.
---

The official documentation lookup on 2026-10-20 did not establish whether Replit strips client-supplied forwarding headers or provides a stable trusted-peer/hop boundary. Treat those headers as attacker-controlled until independent evidence proves otherwise.

**Why:** HTTPS/internal-HTTP origin rejection is reproducible locally, but that does not establish the original browser's precise mismatch. Public-preview probing was explicitly excluded from the repair.

**How to apply:** Keep authority anchored to independently controlled runtime configuration; see `ALTERNATIVE_APPROVALS.md` for the supported address policy. If diagnosing the original browser later, obtain only sanitized origin/scheme/host facts with approval, not request dumps or session links.

Local malformed-item and sandbox/popup reproductions establish real launch defects, but do not establish which defect affected the reporting browser. Preserve that distinction even after all local browser checks pass.

**Why:** No approved original-browser/address verification was available; a matching symptom is not evidence of an identical cause.

**How to apply:** Report the locally demonstrated cause and the unresolved original-browser confirmation separately. Request browser/version, embedded-versus-separate-tab context and sanitized origin facts before authorized read-only diagnosis; do not infer the cause from earlier origin-only work.

On 2026-10-21 the user supplied a screenshot of the second-click origin-denial
message and confirmed they were using the published address, not development
preview. That identifies origin rejection as the reported stage; it does not
verify the repaired app in that browser.

**Why:** Earlier investigations only had local reproductions. The new evidence
distinguishes the actual second-click report from those earlier hypotheses.

**How to apply:** Use the independently verified operator-pinned published
origin documented in `ALTERNATIVE_APPROVALS.md`; do not expand development-origin
trust or infer authority from incoming headers. Keep local verification and
verification after the repair reaches the reporting app explicitly separate.
