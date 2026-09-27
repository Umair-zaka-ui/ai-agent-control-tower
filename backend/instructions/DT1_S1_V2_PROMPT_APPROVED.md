# ACT DT1 — STAGE 1 IMPLEMENTATION PROMPT v2

**Paste this entire document into a fresh Claude Code session working in the `ai-agent-control-tower` repository. It is self-contained. Where it names repository facts, those facts were true on 2026-09-27 and are hints to verify, not truths to seal — §1 makes inspection mandatory and repository reality overrides this prompt.**

## 0. What this is, and what it is not

DT1 is the **Digital Twin** — a synthetic, deterministic, hash-sealed enterprise AI-agent estate that later stages point ACT at to measure what ACT truthfully sees, misses, enforces and refuses. **Stage 1 builds the estate and its truth; it never runs ACT against it.**

Stage 1 replaces a rejected earlier prompt. The rejected version used additive feature cohorts, had no healthy control group, merged objective truth with hand-authored ACT expectations, declared expected misses as passes, positioned F6-1 as the demo's hero, defaulted to PHI, and mixed a timestamp into the content hash. Every one of those is corrected below and must stay corrected; the delta is itemised at the end of this document.

**Standing rules (inherited from the V0–V9 validation programme; non-negotiable):**
- **Empty production ACT diff.** Stage 1 adds isolated lab tooling, fixtures/specifications, DT1 documentation and DT1 tests only. It changes no production runtime behaviour, model, API, policy, graph or containment code, and creates **no ACT migration**. If DT1 cannot be represented without modifying ACT: **STOP**, record a `DEMO_GAP` / architecture conflict, do not fix ACT inside S1.
- **Repository reality overrides this prompt.** Inspect first; if the live model cannot be inspected or materially contradicts DT1's assumptions: **STOP AND REPORT. Do not seal a guessed schema.**
- **Objective truth is separate from ACT observability.** `estate_truth` says what exists. `observability_contract` says what current ACT can legitimately observe/enforce/refuse, each non-observable boundary justified by the actual evidence/control boundary in code. Neither contains hand-authored "ACT should output X".
- **Known product weakness alone is never a justification.** "ACT is known to miss this, therefore EXPECTED_MISS" is forbidden. Name the evidence source that does not exist or the control boundary that cannot be crossed, with a code reference.
- **Synthetic only.** No real employee, customer or patient information; no real secret or credential value anywhere (fixtures, artifacts, logs, tests, docs). Credential-shaped test values are assembled by concatenation (GitHub push protection will otherwise reject the push).
- **A truthful absence is measurable, not pre-declared.** Stage 2 derives expectations from `estate_truth` + `observability_contract`; Stage 1 never encodes `EXPECTED_MISS = PASS`.
- **Determinism is a hard requirement.** Same seed + same generator version + same schema-grounding input ⇒ byte-identical canonical artifacts ⇒ identical content hashes, proven by regeneration.
- **Nothing merges.** Commit and push the DT1-S1 branch; await review.

**This prompt does not authorize:** running ACT against the estate; running ACT discovery; producing ACT findings; standing up real external agent cohorts or services; containment of any kind; the Stage-2 evaluator; the five-minute or technical demos; any production ACT change or migration; V10; M6.

## 1. Pre-flight — repository and schema grounding (MANDATORY FIRST; produces `SCHEMA_GROUNDING`)

Do nothing else until this section is complete and recorded.

### 1.1 Repository state — record verbatim
- `git rev-parse HEAD`, `git rev-parse --abbrev-ref HEAD`, `git status --porcelain` (must be clean), `git rev-parse main origin/main`, and the relationship of your base to `origin/main` (as of 2026-09-27: `main` = `9667707`, the Milestone 5 close; every post-M5 validation branch is **unmerged** and stacked; the stack tip was `validation/v10-authorization-template` @ `ab27fe3`). Record which base you branch from (default: the current stack tip, so DT1 sees the V7.5 cloud adapter; if the reviewer prefers `main`, say so and rebase — the DT diff is lab/docs only).
- `alembic current` from `backend/` with `backend/.venv` (expected head `0061_assurance_evidence`; live 152 tables). If `alembic current` cannot reach a database, record that and derive the head from `backend/migrations/versions/`.
- Open PRs (`gh pr list`), and the blocker/merge state that matters to DT1: **O-11** (image embeds `backend/.keys/`; pilot blocker), **V9-1** (reachability CTE), ADR-0024 status (Proposed), the V8 stop, the V10 authorization gate.
- Note the environment traps recorded in the repo's memory/docs: `gh auth` drifts to the wrong account — check `gh auth status` before pushing; a bare `python` hangs on this machine — always use `backend/.venv/Scripts/python`; never edit tracking files while the full suite runs.

### 1.2 Schema and architecture — inspect the LIVE code, record actual names
Read the source (not this prompt) and record, in `SCHEMA_GROUNDING`, the real names, types, enums, constraints and the file/line where each is defined, for every item below that is present. Where an item is absent, record `ABSENT` with the search you ran.

| Area | What to record (verify all — 2026-09-27 beliefs in parentheses) |
|---|---|
| canonical agent model | table/model, key columns (`agents`; `app/models/agent.py`) |
| control state | column + legal values + transition/legality rule (`control_state ∈ DISCOVERED/CLAIMED/REGISTERED/GOVERNED`; `LEGAL_CONTROL_STATES_BY_ORIGIN` in `app/runtime/registry/control.py`: NATIVE→{GOVERNED}, EXTERNAL/UNKNOWN→{DISCOVERED,CLAIMED,REGISTERED}; ADR-0023) |
| origin / provenance | (`origin_category ∈ NATIVE/EXTERNAL/UNKNOWN`; `origin_provider` free text; NATIVE ⇒ `ACT_NATIVE`) |
| external reference | (`external_reference`, unique per `(organization_id, external_reference)`; the reconciliation matching key) |
| ownership | (`owner_type`, `owner_id`, `technical_owner_id`, `compliance_owner_id`; ownership history table) |
| lifecycle | (`lifecycle_status`, orthogonal to `control_state`; the 13-state machine) |
| discovery | tables and services (`discovery_sources/runs/observations/findings`; `app/discovery/`; adapter contract `DiscoveryAdapter` with session-free `fetch`; registry keys `HTTP_AGENT_REGISTRY`, `AWS_BEDROCK_AGENTS`; `ReconciliationService` outcomes CREATE/LINK/FLAG; `LINK_CREATE_CONFIDENCE_THRESHOLD`; staleness → `STALE_AGENT` finding) |
| control graph | (`control_graph_edges`; `NODE_TYPES`, `EDGE_TYPES`, `DEPENDENCY_EDGE_TYPES` in `app/models/graph.py`; `_EDGE_SHAPE` in `app/graph/dependencies.py`; `AGENT_DELEGATES_TO` declared with **no producer**; traversal in `app/graph/traversal.py`, `MAX_TRAVERSAL_DEPTH = 32`, default 16) |
| Tool / MCP | (`tools`, `mcp_servers`; MCP via the Tool domain — ADR-0018; `tools.mcp_server_id`; trust status) |
| credentials / resources | (`tool_credentials`, `provider_credentials`, `connector_credentials`, `resources` with `resource_type`; encrypted via `credential_crypto`) |
| posture / findings | (`posture_findings`, 16 rules in `app/posture/rules.py`; `threat_findings`, 6 rules in `app/threat/rules.py`; `containment_actions`, seven actions, `_REQUIRES_CONFIRMATION = True`, `truthful_capability()` requires `GOVERNED` — ADR-0020) |
| external governance | (`external_enforcement_mode ∈ OBSERVED/ADVISORY/GATEWAY_ENFORCED`, NULL = OBSERVED; `NATIVE_ENFORCED` derived, unstorable — ADR-0021; `external_capability_grants`, `external_gateway_calls`, `external_request_nonces`; capability keys `http_tool.invoke`, `telemetry.ingest`; HMAC scheme `ACT-HMAC-SHA256`) |
| cloud discovery adapter | (`app/discovery/adapters/aws_bedrock_agents.py` — present only on the stack; identifier `bedrock-agent:<region>:<agentId>`; ADR-0024) |
| tenant boundary | (`organization_id` on every domain table; per-hop tenant predicate in the CTE; cross-tenant → 404-class refusal) |
| identities | (`agent_identities`, `service_accounts`, `external_clients`, `federated_identities`, `delegations` HUMAN→HUMAN) |
| memory / context | (**no** memory or context model exists — the I-1 gap; confirm) |
| A2A relationships | (**no** producer for `AGENT_DELEGATES_TO`, no ingestion path — the I-2 gap; confirm) |
| detection ↔ gateway | (do any threat rules read `external_gateway_calls`? On 2026-09-25 none did — F6-1; confirm) |

Also record the **lab conventions**: lab tooling lives under `lab/<phase>/` (e.g. `lab/harness/`, `lab/scale/`), never under `backend/app`; phase evidence under `docs/validation/<phase>/`; the append-only lab ledger `lab/harness/ledger.py` (`init | anchor | verify`; `lab/run/` is gitignored); ADRs under `docs/architecture/adr/` with a numbered template.

### 1.3 Gap re-verification (mandatory — do not preserve stale assumptions)
For each of **F6-1, I-1, I-2, F-2, V9-1**, state from the code whether it is still present, changed, or fixed, with the file references that prove it. If any has changed: **REPORT IT** and adjust the `observability_contract` accordingly. Do not keep a gap in the estate "for the demo".

### 1.4 STOP conditions at pre-flight
STOP and report (no artifacts sealed, no commit beyond the grounding record if you choose to commit it) if: the live schema cannot be inspected; a DT1 assumption in §4–§6 materially contradicts the live model (e.g. a property dimension has no representable field, an enum value does not exist, a relationship has no table); representing the estate would require any production ACT change or migration; or the working tree is not clean.

### 1.5 Output of §1
`SCHEMA_GROUNDING` (Markdown + a machine-readable JSON of the field/enum map), carrying a `schema_grounding_version` (a content hash of the JSON — this becomes an input to determinism). Every later artifact uses only names recorded here.

## 2. Scope boundary

**MAY build:** `SCHEMA_GROUNDING`, `ESTATE_GENERATOR`, `AGENT_PROPERTY_MATRIX`, `ESTATE_TRUTH`, `OBSERVABILITY_CONTRACT`, `HASH_ANCHOR`, `MANIFEST_SELF_VALIDATOR`, `VALIDATOR_NEGATIVE_TESTS`, `DT1_S1_REPORT`, DT1 documentation, a mechanical architecture guard.

**MUST NOT:** run ACT against the estate; run ACT discovery; produce ACT findings; stand up real external agent cohorts or services; perform containment; build the Stage-2 evaluator; build the five-minute or technical demos; modify ACT production behaviour; create ACT schema migrations; touch `backend/app`, `backend/migrations`, `frontend/`, `backend/requirements*`, CI; begin V10; begin M6.

## 3. Repository location and isolation

Do **not** assume `lab/dt1` or `docs/validation/dt1`. After §1.2, choose the location consistent with the inspected conventions and state why. The expected outcome of that inspection is lab code under a dedicated `lab/<dt1-package>/` and records under `docs/<programme>/<dt1>/` — but decide from what you see.

Rules regardless of location:
- The Digital Twin **imports nothing from `app`** except, if unavoidable for schema grounding, read-only introspection of `Base.metadata` in the grounding step — and even that must be justified; prefer reading model source files. The generator, artifacts and validator must be runnable without a database and without importing ACT.
- Add a **mechanical architecture guard** (AST scan) proving production ACT (`backend/app/**`) imports nothing from the DT1 package, and that the DT1 package imports nothing from `app` at generation/validation time. The repository already uses this pattern (`imports nothing from app` guards in the V7 lab, AST import allow-lists in the V7.5 tests) — mirror it.
- DT1 tests: prefer a DT1-local test tree run with the backend venv's pytest by explicit path, so the production suite's count and file-reading guards are untouched; if repository convention argues for `backend/tests/<dt1>/`, say so and confirm no existing guard (moving-target lists, forbidden-marker scans, `test_ac01` file-readers) is affected.
- Nothing DT1 writes may land in `backend/.keys/`, `lab/run/` is the only scratch location, and no DT1 artifact is a secret.

## 4. The canonical estate

### 4.1 Size and shape — canonical agents with overlapping properties
Target **50–60 canonical agents** in one primary synthetic tenant (plus a small secondary tenant, §4.6). **Do not** build additive cohorts ("20 native + 15 gateway + 10 observed + 8 shadow + …"). Each canonical agent is one entity carrying **several** properties at once. Conceptually (using the *real* names recorded in §1 — the labels below are concepts, not field names):

```
Finance Research Assistant
  origin: EXTERNAL            inventory: SHADOW (discoverable, unclaimed, unowned)
  owner: UNKNOWN              credential: finance-shared-service-account (OVER_PRIVILEGED)
  mcp: finance-mcp-legacy     sensitive_reach: Employee Payroll Database
  gateway: GATEWAY_ENFORCED   reality: ACTIVE_REAL_PROCESS_REQUIRED_STAGE2
  detection_characteristic: F6-1_RELEVANT
```

**Property dimensions** (each mapped in `SCHEMA_GROUNDING` to real fields/relations, or to an *objective estate-only* attribute when ACT has no field — which is itself a fact the contract must use):
origin/provenance · control/inventory status (shadow = exists, discoverable, not claimed) · accountable ownership (business/technical/compliance) · lifecycle/approval state · identity (agent identity, service account, external client) · credential posture (least-privilege / over-privileged / stale / shared) · tools and approval state · MCP dependency and trust state · resource reach (incl. sensitive) · delegation (human→human) · **actual** A2A relationships · **actual** memory/context state · gateway relationship and mode · environment · provenance quality · reality classification (§4.5) · adversarial condition tags (§4.3).

### 4.2 Healthy control group — MANDATORY
**10–15** canonical agents are deliberately well-governed: known accountable owner, valid lifecycle, approved identity, approved tools, approved MCP, least-privilege credential, expected delegation only, appropriate resource access, normal provenance, **no planted serious security condition**. Stage 1 records their objective state; Stage 2 measures specificity/false positives against them. The estate must not assume every agent is risky — the property distribution must show a realistic mix.

### 4.3 Adversarial conditions — objective, not pre-scored
Where §1.3 confirms the gap still exists, the estate must *contain the real condition*, recorded as objective fact only:
- **F6-1-relevant**: external, `GATEWAY_ENFORCED`, `REGISTERED` agents whose boundary calls Stage 2 will deny — the condition is "this agent's enforcement happens at the gateway, producing `external_gateway_calls`, never `agent_executions`".
- **I-1-relevant**: agents with actual persistent memory/context state in the estate (recorded in `estate_truth` because it is real there, even though ACT has no field for it).
- **I-2-relevant**: actual agent→agent handoff relationships (real A2A edges in the estate).
- Over-privileged / shared / stale credentials; unknown provenance; unapproved or legacy MCP dependency; dangerous dependency reaching a sensitive resource; unowned production access; dormant agents with active credentials; a NATIVE agent whose `external_reference` a discovered identifier collides with (the no-silent-merge condition).
- **Cross-tenant negative**: relationships that *would* cross tenants exist only as validator test cases, never in `estate_truth` (§4.6).

Do **not** write `EXPECTED_MISS`, `EXPECTED_FIND`, `EXPECTED_REFUSAL`, or any ACT expectation into `estate_truth`. If §1.3 shows a gap fixed, the condition stays in the estate as a fact and the contract classification changes — report the change.

### 4.4 Truthful-refusal scenario — MANDATORY in the estate
At least one external agent for which **ACT does not own or control the process** (it runs elsewhere; reality class §4.5 marks it a real independent process for Stage 2) **but ACT does control a meaningful boundary capability** — a gateway/tool grant (`http_tool.invoke` scoped to a tool ACT fronts). The estate makes both facts objectively real so Stage 2/3 can prove "ACT cannot truthfully suspend this process" and then "ACT can revoke the authority it genuinely controls". Stage 1 executes nothing.

### 4.5 Reality classification — every canonical agent carries exactly one
Use these unless §1 shows better existing names: `ACTIVE_REAL_PROCESS_REQUIRED_STAGE2` (must be a genuine independent process in Stage 2 — every gateway/containment-proof agent and every external A2A-proof agent), `REAL_EXTERNAL_SERVICE_REQUIRED_STAGE2` (a real service must exist — e.g. a discovery registry served over a real socket, an MCP server, a cloud inventory), `SIMULATED_ASSET`, `DORMANT_ASSET`. Stage 1 **specifies**; it instantiates nothing. Specify that **at least one later discovery path must cross a genuine process/network boundary** (name which source and which agents).

### 4.6 Tenants and sensitive resources
- One primary tenant holds the canonical estate; one small secondary tenant exists so tenant isolation is an objective property (its agents/resources are never referenced from the primary tenant — the validator enforces this).
- Sensitive resources are **generic, fictional enterprise** ones: `Employee Payroll Database`, `Employee Compensation Records`, `Financial Records` (and similar). **PHI is not the default**; healthcare is a possible future vertical, not this estate. All records synthetic; every name obviously fictional.

### 4.7 `AGENT_PROPERTY_MATRIX`
A canonical, deterministic table (JSON + rendered Markdown) mapping each canonical agent id → every property value → reality class → adversarial condition tags → control-group membership. Derived from `estate_truth` by the generator, never hand-edited. Include summary counts (per property value, control-group size, adversarial-condition presence) that the report cites.

## 5. `estate_truth` — objective synthetic reality only

Contents (each entity with a stable id, §7): tenants; agents; owners (business/technical/compliance) as synthetic people; identities (agent identities, service accounts, external clients); credentials (posture, sharing, staleness — **never a secret value**, only an opaque synthetic label); permissions/scopes; tools and their approval state; MCP servers and trust state; resources (with `resource_type`, sensitivity label); dependencies (agent→tool, agent→MCP, MCP→tool, tool→credential, credential→resource, agent→resource); delegations (human→human, and any agent→agent authority the estate really has); environments; lifecycle and approval state; origin/provenance; **actual** A2A relationships; **actual** memory/context state; **actual** gateway relationships (which agents call through the gateway, with which grants and scopes — no secret); **actual** sensitive-resource reachability (the objective path, e.g. Agent → Credential → MCP → Employee Payroll Database); reality classifications.

`estate_truth` describes **what exists**. It must contain no field, tag or note describing what ACT is expected to output, observe, miss, refuse or find. The validator rejects any key matching `EXPECTED_*`, `ACT_SHOULD*`, `finding*`, `verdict*` (§9).

Define its schema explicitly (JSON Schema or an equivalent committed contract) and version it (`estate_truth_schema_version`).

## 6. `observability_contract` — what current ACT can legitimately do, and why

For every relationship/property class in `estate_truth` (not per agent — per *class of fact*, with agent examples), one classification:

| class | meaning |
|---|---|
| `OBSERVE` | an existing ACT evidence source captures this fact directly (name the table/service/route) |
| `PARTIALLY_OBSERVE` | captured in part or only under conditions (state which part, which condition) |
| `NOT_OBSERVE` | no existing evidence source or control boundary reaches this fact |
| `ENFORCE` | ACT holds a real authority over this fact (name the authority and its precondition) |
| `REFUSE` | ACT must truthfully refuse to act on this fact (name the guard that refuses) |

**Every** `NOT_OBSERVE`, `PARTIALLY_OBSERVE`, `ENFORCE` and `REFUSE` entry carries an **architectural justification** of the form: *the fact (from `estate_truth`) + the evidence source / control boundary that does or does not exist (code reference: file, symbol, ADR/known-gap id) = the classification*. Examples of the required shape (verify each against §1.3 before writing it):
- External A2A handoff in `estate_truth` + `AGENT_DELEGATES_TO` has no producer and no ingestion path (`app/models/graph.py`, ADR-0017, I-2) ⇒ `NOT_OBSERVE`.
- Persistent memory state in `estate_truth` + no memory/context model in any table (I-1) ⇒ `NOT_OBSERVE`.
- A denied gateway call by a `GATEWAY_ENFORCED` agent ⇒ the call record is `OBSERVE` (`external_gateway_calls`) and the boundary is `ENFORCE` (`GatewayService.decide`), while a *threat finding* for it is `NOT_OBSERVE` because every threat rule keys off `agent_executions` (`app/threat/rules.py`, F6-1) — three classifications for one fact, each justified.
- Suspending an external process ⇒ `REFUSE` (`ContainmentOrchestrator.truthful_capability` requires `control_state == 'GOVERNED'`, ADR-0020/0023); revoking that agent's grant ⇒ `ENFORCE` (`ExternalGrantService.revoke`).
- Reachability from a branching trust graph at depth ≥ 16 ⇒ `PARTIALLY_OBSERVE` with the V9-1 justification, if still present.

Forbidden: any entry whose justification is only "known weakness", "ACT misses this", or a demo intention. The contract must let Stage 2 **derive** expectations mechanically: if every hop of an `estate_truth` path is `OBSERVE`, Stage 2 derives that ACT should reconstruct it; if any hop is `NOT_OBSERVE`, Stage 2 derives a truthful absence and evaluates *that* — without Stage 1 ever writing the answer. Version the contract (`observability_contract_version`) and make it deterministic (it is derived from `SCHEMA_GROUNDING` + a committed rule set, not typed per run).

## 7. Deterministic generator

- One explicit **default demo seed** (a committed constant, e.g. `DT1_CANONICAL_SEED = "dt1-canonical-v2-2026"`; pick and document it), plus `generator_version` and `schema_grounding_version` as inputs. Different seeds may produce controlled variation; the canonical demo always uses the fixed seed.
- **Canonical serialization**: UTF-8 JSON, sorted keys, fixed separators, `\n` line endings, trailing newline, no floats where a decimal string will do, and a documented canonical key order for lists (sort by stable id).
- **Stable identifiers**: derived, never random — e.g. `sha256(seed || entity_type || natural_key)` truncated to a fixed length, or deterministic UUIDv5/UUID-from-HMAC; **no `uuid4`, no wall-clock time, no unordered iteration over dicts/sets, no environment-dependent paths, no database-generated ids** inside hashed content. Any such value that must exist is normalized *outside* the hashed content.
- **Proof**: regenerate at least **3** times from the same seed; assert byte-identical canonical artifacts and identical content hashes; also show a *different* seed produces different hashes (a negative control that the determinism proof is not vacuous).

## 8. Hash / seal design

- Independent SHA-256 **content hashes** of the canonical bytes of `estate_truth`, `observability_contract`, `agent_property_matrix`; a `combined_root` = SHA-256 over the three hex digests concatenated in a documented fixed order. No timestamp, path, or anchor data inside any hashed content; no hash of a document that contains its own hash (no self-reference).
- A **separate `HASH_ANCHOR` record** containing approximately: `seed`, `generator_version`, `schema_grounding_version`, `estate_truth_schema_version`, `observability_contract_version`, `git_commit`, `estate_truth_sha256`, `observability_contract_sha256`, `agent_property_matrix_sha256`, `combined_root_sha256`, `created_at`. The anchor timestamp records **when the already-computed hashes were sealed**; it is not part of them. Additionally anchoring the artifacts and the anchor record in the existing lab ledger (`lab/harness/ledger.py`) is encouraged if it fits conventions — it is a second, append-only witness, not a replacement.
- Stage 2 will later verify the anchor predates ACT's first DT1 execution; make the anchor easy to verify (document the exact command that recomputes and compares the hashes).

## 9. Self-validator — validates the ARTIFACTS, never ACT

An independent lab program that loads the generated artifacts and checks at least: canonical schema validity (both schemas) · referential integrity across every reference type · canonical-agent uniqueness · stable identifiers (regeneration-invariant) · ownership consistency (owners exist; control-group agents have accountable owners) · identity references · credential references · tool references · MCP references · resource references · dependency references · delegation references · **tenant isolation** (no cross-tenant reference) · healthy control-group count within 10–15 · adversarial-condition presence · F6-1 / I-1 / I-2 conditions represented **where §1.3 shows them still applicable** · truthful-refusal scenario represented · Stage-2 real-process markings present and consistent (every gateway/containment-proof and external-A2A-proof agent is `ACTIVE_REAL_PROCESS_REQUIRED_STAGE2`; at least one discovery path crosses a real boundary) · no forbidden real data (no PHI default, obviously-fictional names) · **no real secrets** (shape scan: `sk-`, `AKIA`, JWT, PEM, `Bearer`, DSNs with credentials; reuse the product's `app/observability/scrubbing.py` *patterns* by copying the regexes, not by importing `app`) · no `EXPECTED_*`/expectation keys in `estate_truth` · deterministic canonical serialization (re-serialize == bytes on disk) · content hashes match the anchor · no ACT execution artifacts (no `discovery_runs`, findings, containment records, gateway calls in the DT tree) · **empty production ACT diff** against the recorded base (`git diff <base> -- backend/app backend/migrations frontend/` is empty).

**The validator must be capable of failing** — exit non-zero with a named check on the first violation, and report all violations.

## 10. Negative validator tests — MANDATORY

Tests that mutate copies of the artifacts (in memory or in `lab/run/`) and assert the validator **rejects** each: duplicate canonical agent · missing owner reference · invalid credential reference · invalid MCP reference · cross-tenant relationship · control group below 10 (and above 15) · a required adversarial condition removed · truthful-refusal scenario removed · non-deterministic artifact (inject a timestamp/UUID into hashed content) · `estate_truth` tampered after sealing (one byte) · `observability_contract` tampered after sealing · a real-looking secret inserted (assembled by concatenation in the test) · an `EXPECTED_*` key inserted into `estate_truth` · a production-diff violation simulated (validator input pointing at a tree with a `backend/app` change — or a unit test of the diff check). Happy-path tests alone are insufficient.

## 11. Product boundary — hard gate, verified twice

Before commit and again in the report: `git diff <base> --stat -- backend/app backend/migrations backend/requirements.txt frontend/ .github/` must print nothing; `alembic heads` unchanged; the architecture guard passes; the production test suite is **not** modified (if you chose a `backend/tests` location, list exactly what was added and confirm no existing test changed). If any of these fail: fix the DT tree, never ACT.

## 12. Documentation (DT1 docs only)

Write, in the chosen docs location: the Stage-1 design (estate model, property dimensions, control group, adversarial conditions, reality classes), `SCHEMA_GROUNDING`, the observability contract's rationale with code references, the determinism and sealing procedure with the exact reproduction commands, the validator's check list, a **limitations** document that records F6-1, I-1, I-2, F-2 and V9-1 (as re-verified) as technical/evidence gaps — **F6-1 is not the five-minute hero**: it belongs in the technical deep dive, the evidence pack and the limitations documentation; the later five-minute buyer demo (not built here) focuses on estate, shadow discovery, blast radius, authority, truthful refusal, real effect-verified containment, evidence provenance and the design-partner invitation — and a Stage-2 readiness note (§13.N). One tracking paragraph each in `ROADMAP.md` and `REPO_STATE.md` per repository convention, added **after** any full test run, never during.

## 13. Git and the Stage-1 report

Branch off the recorded base with a name following repository convention (the validation programme used `validation/<phase>`; propose `dt1/s1-canonical-estate` unless conventions say otherwise). Commit on the DT1-S1 branch; `gh auth status` must show the repository's owner account before `git push`; **do not merge**. Return:

# ACT DT1 — STAGE 1 REPORT

**A.** EXECUTIVE VERDICT · **B.** VERIFIED REPOSITORY / SCHEMA GROUNDING — branch, HEAD, origin/main relationship, worktree, migrations, relevant closures/merges, actual canonical models/enums/fields used, gap re-verification results · **C.** CANONICAL ESTATE — total canonical agents, property distribution, overlapping-property examples, healthy control-group count, reality classifications · **D.** ESTATE_TRUTH — schema, counts, objective relationships, adversarial conditions · **E.** OBSERVABILITY_CONTRACT — OBSERVE / PARTIALLY_OBSERVE / NOT_OBSERVE / ENFORCE / REFUSE, with the architectural justification for each non-observable/control boundary · **F.** HASH / SEAL — seed, generator version, schema-grounding version, individual content hashes, combined root, anchor timestamp, git commit · **G.** DETERMINISM PROOF — ≥ 3 regenerations byte-identical, identical hashes, different-seed negative control · **H.** SELF-VALIDATOR — positive validation, negative tests, proof the validator can fail · **I.** SECURITY / PRIVACY — no real secrets, no real PII, synthetic-data confirmation · **J.** PRODUCT BOUNDARY — no ACT execution, no ACT product changes, no ACT migrations, empty production ACT diff · **K.** CONFLICTS / DEMO GAPS · **L.** ARTIFACTS · **M.** GIT — branch, commits, push state, no merge · **N.** STAGE-2 READINESS — which assets later require real processes, which services must later be instantiated, what Stage 2 must evaluate.

End with exactly one of:
`VERDICT: DT1-S1 PASSED — READY FOR STAGE-2 REVIEW` · `VERDICT: DT1-S1 CONDITIONAL — REVIEW REQUIRED` · `VERDICT: DT1-S1 BLOCKED`

Then **STOP.** Do not begin Stage 2. Do not run ACT against the estate. Do not begin V10 or M6.

## 14. Execution order (do these, in this order, and nothing more)

1. Inspect repository and schema (§1) and write `SCHEMA_GROUNDING`; **STOP on material conflict.**
2. Choose and justify the repository location; add the architecture guard (§3).
3. Implement the deterministic generator, `estate_truth`, `observability_contract`, `AGENT_PROPERTY_MATRIX` (§4–§7) — Stage 1 only.
4. Implement the self-validator and its negative tests; run both (§9–§10).
5. Prove determinism (§7) and seal the artifacts (§8).
6. Verify the empty production ACT diff and the guard (§11); write the DT1 docs and tracking paragraphs (§12).
7. Commit and push the DT1-S1 branch; do not merge (§13).
8. Return the Stage-1 report with exactly one verdict line, then STOP.

---

# ARCHITECTURE DELTA FROM REJECTED S1

| # | Rejected S1 | v2 correction (where enforced) |
|---|---|---|
| 1 | **Additive feature cohorts** (20 native + 15 gateway + 10 observed + 8 shadow + separate dangerous-dependency / IAM / F6-1 agents) | **50–60 canonical agents, each carrying overlapping properties** (external + shadow + unowned + over-privileged + MCP-dependent + gateway-enforced + unknown-provenance on one entity), with a generated `AGENT_PROPERTY_MATRIX` proving the overlap — §4.1, §4.7; validator counts and uniqueness — §9. |
| 2 | **No healthy control group** — every agent was risky | **10–15 deliberately well-governed control agents** with objective healthy state, for Stage-2 specificity/false-positive measurement; validator enforces the count and their accountable ownership — §4.2, §9, §10. |
| 3 | **One combined manifest** mixing objective truth with `EXPECTED_FIND / EXPECTED_MISS / EXPECTED_REFUSAL` | **Two artifacts**: `estate_truth` (what exists, expectation-free — validator rejects `EXPECTED_*` keys) and `observability_contract` (what current ACT can OBSERVE / PARTIALLY_OBSERVE / NOT_OBSERVE / ENFORCE / REFUSE, justified by evidence/control boundaries in code) — §5, §6, §9. |
| 4 | **Manually declared expected misses** treated as passes ("ACT is known to miss this ⇒ EXPECTED_MISS") | **Stage-2 expectations become derivable**: every non-observable/control classification names the actual missing evidence source or control boundary with a code reference and gap id; "known weakness" alone is forbidden; gaps are re-verified against live code first (§1.3) and reported if changed — §6, §4.3. |
| 5 | **F6-1 as the five-minute demo's "hero honesty beat"** | F6-1 retained as an **objective estate condition and a technical/evidence gap** (deep dive, evidence pack, limitations doc) and **removed from the primary five-minute hero**, whose later focus is listed explicitly — §4.3, §12. |
| 6 | **PHI as the default sensitive resource** | **Generic fictional enterprise resources** — Employee Payroll Database, Employee Compensation Records, Financial Records; healthcare deferred to an optional future vertical; all data synthetic — §4.6, §9 (no-real-data check). |
| 7 | **Hash/timestamp ambiguity** — the anchor time inside the content hash | **Deterministic content hashes** (SHA-256 per artifact + a documented `combined_root`, no timestamps/paths/self-reference inside hashed content) **separated from a distinct anchor record** whose `created_at` records only when the already-computed hashes were sealed; determinism proven by ≥ 3 regenerations plus a different-seed negative control — §7, §8, §10. |

No correction had to be weakened for an architectural conflict at prompt-writing time. Two conditions the executing session must confirm rather than assume, and STOP if they fail: that every property dimension in §4.1 is representable with real fields *or* as an objective estate-only attribute without any ACT change (§1.4, §15-rule), and that the gaps named in §4.3 still exist in the live code (§1.3) — if one is fixed, the estate keeps the objective condition and the contract classification changes, which is reported, not hidden.

VERDICT: DT1-S1 v2 PROMPT READY FOR ARCHITECTURE APPROVAL
