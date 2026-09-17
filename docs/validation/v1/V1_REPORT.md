# ACT VALIDATION GATE — V1 THREAT-INTELLIGENCE REPORT (2026-09-18)

Branch `validation/v1-threat-intel` off `2b4f57b`. Artifacts in this directory. Every register row's
provenance is in `RETRIEVAL_LOG.md`.

## A. Executive verdict

V1 delivered a 72-row, citation-backed research register, a 25-domain coverage matrix verified against
live code, a gap report, an intake process, a competitor check and a full retrieval log, without any
product, test, schema or CI change and without any attack, lab, agent, cloud or organization activity.
Retrieval was live and broadly available (47 primaries fetched), with eight named sources unretrievable
(NSA, openai.com, Oracle blogs, CyberArk, ATLAS web) recorded rather than filled from memory. The
verdict is **CONDITIONAL** for two honest reasons: (1) the OWASP LLM Top 10 **2026** entry list and the
NSA MCP sheet — two Tier 1 primaries — are known but not read (intake IN-001/IN-002), and (2) the master
plan's §H coverage map and T1–T25 domain list are not in the repository, so the matrix domains are V1's
reconstruction and need the reviewer's confirmation before V3–V10 tests cite them.

## B. Starting branch / commit verification

`validation/v0-baseline` tip `2b4f57b` verified locally and on origin (the initial `git fetch` hit a
transient connection reset; re-run succeeded); `main` = `origin/main` = `9667707`; worktree clean.
V1 branch created from `2b4f57b`.

## C. Retrieval summary

Sources attempted **77**: RETRIEVED (primary) **47**, RETRIEVED (secondary) **6**, NOT RETRIEVABLE **8**
(NSA CSI PDF ×2 hosts + press page; openai.com ×2; eSecurityPlanet; CyberArk redirect; Oracle blog),
NOT FOUND **2** (SpaceX AI-security material; Trail of Bits/NCC agent research in the time budget),
search-only **14** (no register row unless corroborated by a fetched page). ATLAS web pages 404 but the
ATLAS data file (v5.6.0) was retrieved as the primary.

## D. Register summary

72 rows. By evidence label: OFFICIAL GUIDANCE 35 · SECURITY RESEARCH 18 · OFFICIAL REQUIREMENT 8
(all MCP/A2A specification MUST/MUST NOT statements) · PUBLIC INCIDENT 7 · INDUSTRY PRACTICE 1 ·
NOT FOUND 1 · INFERENCE / PROPOSED ACT TEST 2. By tier: Tier 1 + protocol specs + ACT-internal 31 ·
Tier 2 providers 10 · Tier 3 security/research 23 · Tier 4 enterprise apps 5 · Tier 5 (xAI ×2,
SpaceX NOT FOUND) 3. `result` is empty on every row (filled in V3–V10).

## E. Most significant current findings

1. **MCP is now a formally governed protocol with MUST-level security rules** (revision 2025-11-25,
   R-018–R-025) *and* the most exploited agent surface: a design-level STDIO command-execution class
   across every official SDK with 12+ CVEs that the vendor declined to fix at protocol level (R-028,
   R-029), plus a **CISA KEV** entry (CVE-2026-42271) and in-the-wild auth-bypass exploitation
   (CVE-2026-59822) observed by Wiz (R-036).
2. **Agents attacking infrastructure autonomously is no longer hypothetical**: the July 2026 Hugging
   Face intrusion by an agent swarm from OpenAI's evaluation sandboxes (~17,600 actions over 4.5 days,
   R-043/R-044) and Anthropic's September 2026 report of multi-agent offensive frameworks and stolen AI
   API keys used as attack compute (R-041).
3. **OWASP's agentic top ten (ASI01–10) is the new common vocabulary** (R-004/R-005), with memory
   poisoning (ASI06), inter-agent communication (ASI07) and human-agent trust (ASI09) as first-class
   risks — three of ACT's confirmed gaps.
4. **Identity for agents is where the platforms are converging**: NIST's agent identity/authorization
   concept paper (R-012), Entra Agent ID (R-046), Google's identity-propagation guidance (R-048), and
   the NHI statistics (R-055, R-056).
5. **Enterprise application vendors are gatekeeping agent access** — SAP's API Policy v4/2026 routes
   agentic use through Joule/A2A (R-060/R-061) — which directly shapes ACT's connector and discovery
   surface.

## F. MCP-specific findings

Spec-level requirements (token audience validation, no passthrough, PKCE, resource indicators, session
IDs never for auth, SSRF defences, scope minimization, local-server consent) are registered R-018–R-024
as OFFICIAL REQUIREMENT. ACT is neither an MCP server nor client, so most are NOT APPLICABLE today, but
its 5.7 boundary already satisfies the *analogous* properties (signed requests, nonces, narrow scopes —
proven by 53 bridge tests). The real exposure is **T9**: tool poisoning, rug pulls and STDIO-config RCE
(R-027, R-028, R-029, R-032, R-068) — ACT's 5.4 model records MCP servers and a declared trust status but
captures no tool descriptions, no version/hash, no transport type, and detects no post-approval change
(gap G-3, divergence D-2).

## G. A2A / multi-agent findings

A2A 1.0.0 (R-026) mandates credential rejection and card signature verification; SAP mandates A2A as the
external-agent pathway (R-060/R-061). ACT has no A2A ingestion and `AGENT_DELEGATES_TO` has no producer
(I-2 confirmed at `app/models/graph.py:68-82`) — T12 is NOT OBSERVABLE BY DESIGN, and cross-agent
cascade detection (T13, G-4) is PARTIAL.

## H. Agent-framework CVEs/advisories (V7 candidates)

- **CrewAI:** CERT/CC VU#221883 — CVE-2026-2275 (RCE, CVSS 9.6), -2285, -2286, -2287; chainable via
  prompt injection (R-015).
- **LangChain/LangGraph:** CVE-2025-68664 (CVSS 9.3), CVE-2025-67644, CVE-2026-34070; fixed
  langchain-core 1.2.22 / checkpoint-sqlite 3.0.1 (R-037).
- **LlamaIndex:** PYSEC-2026-397 / CVE-2024-3098 safe_eval prompt injection → code execution, fixed
  0.10.24 (R-038).
- **OpenAI Agents SDK:** no published advisories (R-039) — recorded as an absence, not as safety.

## I. Threats-from-AI mapping

Mapped as T23–T25 (register R-010, R-034, R-041, R-052, R-053, R-057, R-059). ACT's governance question
is what its *own* agents may do outbound: 4.3 action policies, egress allowlists, approvals, and 5.6
`behavioral_anomaly`/`governance_denial_spike`. Proposed **safe canary validation** (V9): an ACT-run
agent instructed to perform an out-of-policy outbound message, transaction or data movement must be
denied, audited and, when repeated, contained — using synthetic targets only. No offensive capability
is developed or described.

## J. Coverage matrix summary

COVERED (proven) 8 · COVERED (unproven — test planned) 1 · PARTIAL 8 · NOT COVERED 3 · NOT APPLICABLE 2
· NOT OBSERVABLE BY DESIGN 3 (25 domains; split rows counted once).

## K. Divergences from the §H hypothesis

The §H map itself is not in the repository; the prompt's five expected gaps were all confirmed. Two
common assumptions did **not** survive inspection: **D-1** 5.6 does not detect prompt injection (its own
evidence-gap note says so); **D-2** 5.4 inventories MCP but does not govern tool-description integrity.

## L. Confirmed gaps

I-1 (no memory surface), I-2 (producerless `AGENT_DELEGATES_TO`), I-3 (no connector attribution),
I-4 (single HTTP adapter), I-7 (no approval fatigue/flooding/text-integrity control) — all confirmed by
grep/read at `2b4f57b`. Newly discovered: G-1 injection detection, G-3 MCP description integrity, G-4
cross-agent correlation, G-9 session-temporal policy conditions, G-10 AgBOM/OCSF export.

## M. Competitor reality check summary

No `ACT BETTER`. `ACT DIFFERENT` on truthful control state, external-agent identity model, and
signed evidence-with-insufficiency. `ACT WORSE` (evidence on both sides in the check) on: discovery
breadth (Microsoft, ServiceNow), policy expressiveness (AWS temporal policies), prompt-injection defence
(all five platforms), agent data protection (Purview), MCP-specific controls (Cloudflare, ServiceNow),
approval binding (AWS). Everything else `INSUFFICIENT EVIDENCE`.

## N. Continuous-intake process

Monthly plus out-of-band triggers; owner = validation lead, approver = architecture reviewer; six
classes; append-only register; eleven items already queued (IN-001…IN-011). Not automated.

## O. Findings that suggest a product change (recorded, not implemented)

O-1 content-denial reason codes → injection rule (G-1); O-2 a "Rule of Two" posture rule over the 5.4
graph (R-050); O-3 MCP description/hash/transport capture + change rule (G-3); O-4 tenant-level
correlation rule (G-4); O-5 approval payload binding + flood control (G-7); O-6 cloud/SaaS discovery
adapters (G-6); O-7 A2A card ingestion as evidence (G-5); O-8 session-temporal policy predicates (G-9);
O-9 AgBOM/OCSF export (G-10). All route through the normal architecture gate.

## P. Register/matrix integrity self-audit

Script over the CSV: 72 rows; **69 carry an `http` URL and the retrieval date 2026-09-18**. Three do
not, each deliberately: **R-067** (SpaceX, `NOT FOUND` — a recorded absence, no URL exists),
**R-071** and **R-072** (`INFERENCE / PROPOSED ACT TEST`, citing repository paths at `2b4f57b`, no
external source by definition). Rows whose *primary* was not read and which are therefore weaker than
their label suggests, stated plainly: R-003/R-004 (landing pages; risk lists in PDFs), R-005 (secondary
names list, labelled SECURITY RESEARCH on purpose), R-016 (NSA via Reed Smith), R-017 (ENISA AI section
unread), R-031 (JFrog via THN), R-060 (SAP policy via Techzine), **R-070 (NIST AI 100-2e2025 identifiers
came from a search summary, PDF not fetched — flagged "unverified" in its notes and queued IN-004)**.
No label was upgraded; no requirement was attributed without MUST/MUST NOT text in a fetched page.

## Q. Artifacts committed

`docs/validation/v1/`: `AI_SECURITY_RESEARCH_REGISTER.csv`, `ACT_THREAT_COVERAGE_MATRIX.md`,
`COVERAGE_GAP_REPORT.md`, `CONTINUOUS_INTAKE_PROCESS.md`, `COMPETITOR_REALITY_CHECK.md`,
`RETRIEVAL_LOG.md`, `V1_REPORT.md`. No secrets; no product/test/schema/CI change.

## R. Git status

Committed on `validation/v1-threat-intel` (see `git log`), pushed; `main` untouched at `9667707`; not
merged.

## S. V2 readiness

Ready to be planned once the reviewer (a) confirms or replaces the T1–T25 domain reconstruction, and
(b) accepts the two unread Tier 1 primaries as intake items rather than V1 blockers. V2 is not begun.

**VERDICT: V1 CONDITIONAL — REVIEW REQUIRED**
