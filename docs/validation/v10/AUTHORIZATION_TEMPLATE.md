# ACT V10 — ORGANIZATION VALIDATION
# WRITTEN AUTHORIZATION & RULES OF ENGAGEMENT (TEMPLATE)

> **Repository note (2026-09-27).** This is the template exactly as issued by the programme owner. It is
> stored here so that a V10 pre-flight can reference it. **No V10 activity has occurred and none may occur
> until a completed, signed instance exists.** A signed instance contains names, contact details and system
> identifiers of a real organization — it must **not** be committed to this repository; keep it in an
> access-controlled location and have the V10 pre-flight reference it by SHA-256 only. Every field below is
> intentionally blank; the ACT operator is not a party who can fill in the organization's side.

**Status: TEMPLATE — not an authorization until signed by both parties.**
This document must be **completed and signed by an authorized representative of the participating organization AND the ACT operator** before any V10 activity begins. The V10 execution prompt **will not run** until a signed instance of this document exists and is referenced in V10 pre-flight.

**Nothing in V10 — not discovery, not observation, not a single API call against the organization's environment — may occur before this is signed.**

---

## 1. PARTIES

- **Participating organization:** ____________________
- **Authorizing representative** (must have authority to authorize security testing of the named systems): name ______, title ______, email ______, signature ______, date ______
- **ACT operator:** name ______, signature ______, date ______
- **Escalation / incident contact (org side), reachable during the window:** name ______, phone ______, email ______
- **Escalation contact (ACT side):** name ______, phone ______, email ______

---

## 2. SCOPE — SYSTEMS IN

**Only the systems explicitly listed here are in scope. Anything not listed is OUT.**

- Environment: ☐ non-production / sandbox (REQUIRED for initial engagement) ☐ production (only by separate explicit approval — §7)
- In-scope systems / accounts / tenants (enumerate exactly): ____________________
- In-scope agent estate — the genuine AI agents/applications to be discovered (target **5–20** for the initial engagement): ____________________
- Discovery sources ACT may read (e.g. a read-only cloud account, an MCP registry, an agent inventory API): ____________________
- **Credential scope:** every credential ACT is given is ☐ read-only ☐ scoped to inventory/identity listing only. **No write/delete/admin credential is provided.**

## 3. SCOPE — EXPLICITLY OUT

- Any system, account, tenant, or network not listed in §2.
- Production (unless §7 separately signed).
- Third-party systems the organization does not own.
- Any credential broader than read-only listing.
- **Enforcement / containment of any kind** (see §5 — OBSERVE_ONLY first).
- Code execution, exploitation, or any action that modifies the organization's environment.

## 4. DATA HANDLING

- **Data classes ACT will encounter:** ____________________ (the organization identifies any sensitive/regulated data in scope; ACT is configured METADATA_ONLY and scrubs before persist — 4.8).
- **ACT captures:** ☐ metadata only (REQUIRED default) — no prompt/tool/model content unless separately approved in writing.
- **Where ACT's data lives during the engagement:** ____________________ (region/host; the organization confirms this meets its residency requirements).
- **Retention:** ACT-held data about the organization is retained for ______ and then ☐ returned ☐ destroyed, confirmed in writing to the organization.
- **No real secret, credential value, or regulated record leaves the organization's boundary** in any ACT artifact, log, report, or evidence bundle. Findings reference assets, never secret values.
- **Right to withdraw:** the organization may withdraw at any time; on withdrawal, ACT stops immediately and returns/destroys held data per the above.

## 5. MODE — OBSERVE_ONLY FIRST (non-negotiable for the initial engagement)

- The initial engagement is **OBSERVE_ONLY**: ACT discovers, inventories, maps, assesses posture, and reconstructs — **it takes NO enforcement, containment, denial, revocation, or any action that affects a running agent.**
- **Enforcement is enabled only after a SEPARATE, explicit, written approval** (§7), narrowly scoped, and never in production without that production-specific approval.
- If ACT's design would, in any configured path, take an enforcing action in OBSERVE_ONLY mode, that is a **stop condition** — ACT must be verifiably observe-only for the engagement.

## 6. TIME WINDOW & CADENCE

- Authorized window: from ______ to ______.
- Permitted activity hours (if restricted): ____________________
- Notification before each session: ☐ required (to whom: ______) ☐ not required.
- The engagement pauses/stops outside this window.

## 7. ENFORCEMENT / PRODUCTION — SEPARATE APPROVALS (leave blank until/unless granted)

- ☐ **Enforcement approved** — scope: ______, systems: ______, rep signature: ______, date: ______
- ☐ **Production approved** — scope: ______, systems: ______, rep signature: ______, date: ______
- Absent these, the engagement is OBSERVE_ONLY on non-production only.

## 8. STOP CONDITIONS

ACT and the ACT operator **STOP IMMEDIATELY** and notify the org escalation contact on any of:
- any action that would affect a running agent or modify the environment (in OBSERVE_ONLY);
- any credential proving broader than read-only listing;
- any access to a system not in §2;
- any real secret/regulated record about to leave the boundary;
- any organization request to stop or withdraw;
- any P0 (cross-tenant exposure, credential exposure, a false containment claim, an enforcement action taken without §7 approval);
- any ambiguity about whether an action is authorized — **stop and ask, do not proceed.**

## 9. EXIT CRITERIA & DELIVERABLE TO THE ORGANIZATION

- Agreed exit criteria: ____________________
- The organization receives: the estate inventory ACT found, the ownership/shadow/posture findings, the dependency/blast-radius map, and — the value question — **a record of what ACT surfaced that the organization could not previously answer quickly and reliably**, each finding classified by the organization as `KNOWN_ALREADY / NEW_INFORMATION / FALSE_POSITIVE / FALSE_NEGATIVE / NOT_OBSERVABLE`.
- Data returned/destroyed per §4; withdrawal honored.

## 10. LIABILITY / LEGAL

- This engagement is security *validation*, not a penetration test of the organization's defenses; ACT tests **its own** ability to discover/govern the organization's AI estate, in OBSERVE_ONLY mode, against authorized read-only sources.
- Standard mutual NDA / liability terms as agreed between the parties: ____________________
- Governing terms / contract reference: ____________________

---

**SIGNATURES**

Organization authorizing representative: ______________________  date: ______
ACT operator: ______________________  date: ______

**Until both signatures are present, this is a template, not an authorization, and V10 does not run.**
