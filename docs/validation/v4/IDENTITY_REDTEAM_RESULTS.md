# IDENTITY_REDTEAM_RESULTS — V4 (T6): the 5.7 boundary under direct attack

Raw: [`evidence/v4_identity_results.json`](evidence/v4_identity_results.json). Fired inside the V2.1
egress-deny wrapper on 2026-09-22. **17 / 17 pass, 0 fail, identity-rejection rate 10/10, no P0.**

## The model under attack

From [`backend/app/bridge/identity.py`](../../../backend/app/bridge/identity.py): an external agent
holds a secret it never transmits and signs each request over
`SCHEME \n METHOD \n PATH \n TIMESTAMP \n NONCE \n SHA256(body)`. ACT recomputes the HMAC with the
stored secret and compares in constant time. The module's own statement of the boundary is the thing
V4 set out to falsify:

> identity **without a `users` row** — the grant names an `agents` row and nothing else. There is no
> session, no role, no token that any other ACT surface will accept … and cannot be escalated into
> internal identity by any path, because there is no path.

Verification order is deliberate — grant lookup, revoked, expired, timestamp window, nonce shape, HMAC,
and the **nonce is consumed last**, so a bad signature cannot burn a legitimate caller's nonce.

## Results

| # | scenario | attack | observed | verdict |
|---|---|---|---|---|
| T6-01 | valid signed call (**control**) | correctly signed, in scope | `200 ALLOWED` | PASS (control) |
| T6-02 | signed-request replay | resend an identical signed request | `200` then **`409 EXTERNAL_REPLAY_DETECTED`** | PASS (contained) |
| T6-03 | stale timestamp | timestamp an hour outside the window | `401 EXTERNAL_SIGNATURE_EXPIRED` | PASS (contained) |
| T6-04 | forged signature | sign with an attacker-chosen secret | `401 EXTERNAL_SIGNATURE_INVALID` | PASS (contained) |
| T6-05 | stripped signature | empty `X-ACT-Signature` | `401 EXTERNAL_SIGNATURE_MISSING` | PASS (contained) |
| T6-06 | algorithm / scheme confusion | sign with a different scheme line | `401 EXTERNAL_SIGNATURE_INVALID` | PASS (contained) |
| T6-07 | body tampering after signing | swap the body for a forbidden target | `401 EXTERNAL_SIGNATURE_INVALID` | PASS (contained) |
| T6-08 | path tampering | sign one path, send to another | `401 EXTERNAL_SIGNATURE_INVALID` | PASS (contained) |
| T6-09 | unknown key id | a key id ACT never issued | `401 EXTERNAL_SIGNATURE_INVALID` | PASS (contained) |
| T6-10 | expired grant | present a grant past expiry | `403 EXTERNAL_GRANT_EXPIRED` | PASS (contained) |
| T6-11 | revoked grant | act on a revoked grant | `403 EXTERNAL_GRANT_REVOKED` | PASS (contained) |
| T6-12 | identity substitution | agent B signs for a target scoped to agent A | `403 DENIED`, attributed to **B**, not A | PASS (contained + correctly attributed) |
| **T6-13** | **P0: external → internal escalation** | present the signed identity at internal endpoints | **all rejected** (see below) | **PASS (no escalation path)** |
| **T6-14** | **P0: gateway bypass** | invoke the capability with no valid signed identity | all `401`, none accepted | **PASS (no bypass)** |
| T6-15 | machine-identity collision | two agents given the same display name | 2 distinct agent rows; B using A's scoped target → `403` | PASS (distinguished) |
| T6-16 | weak-signal reconciliation | a second source advertises the same agents | 0 created / 3 linked, 0 duplicate external references, agent count unchanged (3→3) | PASS (no auto-merge) |
| T6-17 | credential theft via config | exfiltrate a canary credential via a capability the grant lacks | `403`, no canary in ACT's records | PASS (contained) |

Every denial carries a **distinct, rule-specific error code** — replay, expired signature, invalid
signature, missing signature, expired grant, revoked grant are six different codes, so a denial is
always attributable to one rule rather than a generic "no".

## The P0 line, explicitly

**No external → internal identity escalation occurred, and no gateway bypass occurred.**

- T6-13 presented a *valid* signed external identity at five internal endpoints —
  `/api/v1/auth/me` (`401`), `/api/v1/delegations` (`403`), `/api/v1/graph/trust-edges` (`403`),
  `/api/v1/command-center/agents`, `/api/v1/runtime/tools`. **None authenticated.** The signed identity
  is accepted only at the gateway capability endpoint and mints no session, role, or internal principal.
- T6-14 tried three bypass shapes — unsigned, the grant secret presented as a bearer token, and a key id
  with no signature. All three `401`. The secret is not a bearer credential and there is no unsigned path.

## Honest note on two results

T6-10 and T6-11 initially showed FAIL because the harness asserted `401`. ACT's own error mapping
(`backend/app/identity/errors.py`) maps `EXTERNAL_GRANT_EXPIRED` and `EXTERNAL_GRANT_REVOKED` to **403**.
Both were genuine rejections all along; the harness assertion was wrong, not ACT. The expected behaviour
("must reject") was never changed — only the status-code assertion was corrected to the documented
mapping. Recorded as harness defect **HD-1** and the first-run log is kept at
[`evidence/v4_identity_firstrun.log`](evidence/v4_identity_firstrun.log) rather than discarded.
