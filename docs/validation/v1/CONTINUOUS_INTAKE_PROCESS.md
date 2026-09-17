# CONTINUOUS_INTAKE_PROCESS — v1.0 (2026-09-18)

**Defined, not automated** (V1 §7). Research produces evidence for review; it never modifies production
security behaviour on its own.

## Cadence and owner

- **Cadence:** monthly, first working week; plus an out-of-band intake within 2 working days for any
  item that is (a) a CISA KEV entry touching an AI/agent component ACT discovers or runs, (b) a
  disclosed incident in an ACT integration surface (SAP, Salesforce, ServiceNow, Oracle, MCP), or
  (c) a new edition of a Tier 1 source (OWASP, ATLAS, NIST, MCP/A2A spec revision).
- **Owner:** the AI Security Validation Lead (this program's role), with the architecture reviewer as
  approver for `ARCHITECTURAL CHANGE` items. Nobody else may change a classification.
- **Artifact updated:** `docs/validation/v1/AI_SECURITY_RESEARCH_REGISTER.csv` (append-only rows;
  version bump in the file header comment of the accompanying report) and, where a row changes ACT's
  expected capability, `ACT_THREAT_COVERAGE_MATRIX.md` and `COVERAGE_GAP_REPORT.md`. The
  `RETRIEVAL_LOG.md` gets one section per intake run.

## What is reviewed each cycle

1. Agent / MCP / framework CVEs — CERT/CC, OSV/PyPI advisories, GitHub Security Advisories for the V7
   candidate frameworks (LangGraph, CrewAI, LlamaIndex, OpenAI Agents SDK) and MCP SDKs; CISA KEV.
2. Prompt-injection and goal-hijack research (Unit 42, OpenAI, Anthropic, Google, academic).
3. Public incidents involving agents (OWASP exploit round-ups, vendor disclosures, incident write-ups).
4. Cloud-agent platform guidance changes (Microsoft Agent 365/Entra, AWS AgentCore, Google Agent
   Platform/SAIF, SAP/Salesforce/ServiceNow/Oracle policies such as SAP API Policy revisions).
5. Identity attacks against non-human identities (Okta, CSA, CyberArk/Palo Alto).
6. Model-security findings (ATLAS data-file diffs, NIST AI 100-2 revisions).
7. Supply-chain compromises (packages, skills marketplaces, MCP registries).
8. Sandbox escapes and agent-swarm behaviour (frontier-lab disclosures).
9. Tool poisoning and memory poisoning research.
10. Protocol revisions: MCP spec changelog, A2A releases, OWASP ACS releases.

## The one rule (inherited from V1 §0)

Every new register row must come from a document retrieved in that intake session, with publisher,
title, version, publication date, retrieval date and URL. Retrieval failures are recorded as
`NOT RETRIEVABLE` / `NOT FOUND` in the log, never filled from memory. Labels are never upgraded without
a citation that supports the higher label.

## Classification of each item

| class | meaning | who can close it |
|---|---|---|
| `NO ACTION` | already covered by a proven test, or out of ACT's scope | validation lead |
| `NEW TEST` | ACT capability exists; add a red-team/regression test in the relevant V-phase | validation lead (test PR through normal review) |
| `NEW DETECTION` | a 5.6 rule or posture rule can be built from an existing deterministic signal | architecture reviewer (rule sets are versioned product code) |
| `NEW POLICY` | a 4.3 / 5.7 policy or scope change, no code | architecture reviewer |
| `NEW MITIGATION` | product code within an existing authority (e.g. an adapter, a hash capture) | architecture reviewer |
| `ARCHITECTURAL CHANGE` | new authority, new plane, new signal source, schema change | the architecture gate (ADR required) |

## Record per item

`intake_id · date · source row (register id) · classification · rationale · owner · target phase or
release · status (OPEN / SCHEDULED / DONE / DECLINED)`. Declines carry a reason.

## Explicit non-automation

No scheduler job, webhook, or agent performs intake. If retrieval tooling is used to *assist* a human,
the human records the retrieval date and reads the source before a row is added. This mirrors the
repository's own rule that discovery is evidence, never authority (ADR-0016).

## Items already queued from V1

| intake_id | source | class | note |
|---|---|---|---|
| IN-001 | R-003 OWASP LLM Top 10 2026 (PDF) | NO ACTION until read | retrieve the PDF and add the ten 2026 entries |
| IN-002 | R-016 NSA MCP CSI (PDF) | NO ACTION until read | primary blocked in-session; obtain via another channel |
| IN-003 | R-017 ENISA TL 2025 AI section | NO ACTION until read | |
| IN-004 | R-070 NIST AI 100-2e2025 PDF | NO ACTION until read | verify NISTAML identifiers |
| IN-005 | ATLAS T0086 / T0110 | NO ACTION until verified | confirm in a newer ATLAS data release |
| IN-006 | R-028/R-029 MCP STDIO RCE class | NEW MITIGATION (proposed) | transport attribute in 5.4 inventory (G-3) |
| IN-007 | R-027 tool poisoning | NEW MITIGATION (proposed) | description capture + change detection (G-3) |
| IN-008 | R-044 cross-agent correlation | NEW DETECTION (proposed) | G-4 |
| IN-009 | R-042/R-040 approvals | NEW MITIGATION (proposed) | approval payload binding + flood control (G-7) |
| IN-010 | R-060/R-061 SAP API Policy v4/2026 | NEW POLICY (proposed) | connector routing policy for SAP surfaces |
| IN-011 | R-069 OWASP ACS | NO ACTION (watch v0.2.0, 2027-03) | export-format alignment |
