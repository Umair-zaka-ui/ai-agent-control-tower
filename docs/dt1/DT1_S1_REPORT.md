# ACT DT1 — STAGE 1 REPORT

Executed 2026-09-27/28 under `VERDICT: APPROVED FOR DT1-S1 EXECUTION`, following
`backend/instructions/DT1_S1_V2_PROMPT_APPROVED.md` (SHA-256 `761c9decc7acdefa6f23e80f4032c50c1c2197c57ec866a4f4b5c725cdd55417`),
itself produced from `backend/instructions/DT1_S1_V2_INSTRUCTION.md` (`984688a1ee563fa8fef9e7a35363708ad8853dbb03f06b9db8d76e2addca1cc2`).
Every number below is measured; evidence files are in [`evidence/`](evidence/).

## A. Executive verdict

Stage 1 is complete. A synthetic, deterministic, hash-sealed enterprise estate of **60 canonical agents** (12 healthy
control) exists with its objective truth, an observability contract grounded in the live ACT code, and a per-agent
property matrix — sealed (`combined_root e06a0753…`) **before ACT has ever seen it**. The self-validator passes
**65/65** checks and is proven able to fail (**16 negative tests**); determinism is proven (3 byte-identical
regenerations, different-seed control differs); the production diff is **empty**. ACT was **not run** against the
estate, no findings exist, no process or service was instantiated, no migration or product change was made.

**VERDICT: DT1-S1 PASSED — READY FOR STAGE-2 REVIEW** (repeated as the final line).

## B. Verified repository / schema grounding

| item | verified value |
|---|---|
| branch / HEAD at grounding | `validation/v10-authorization-template` @ `ab27fe3a70e72bc3981e9b63afe36eacd5ce90c7` (the validation-programme stack tip) |
| `origin/main` | `9667707` — the Milestone 5 close (2026-09-16); **nothing from V0–V10 is merged**, V8 stopped at pre-flight, V10 not started |
| worktree | clean at start apart from the untracked `backend/instructions/` |
| migration head | `0061_assurance_evidence` (unchanged throughout) |
| grounding method | `lab/dt1/grounding.py`: AST literal extraction over the constant-bearing modules + `Base.metadata` after importing `app.main` (read-only; the only DT1 module that imports `app`) → `schema_grounding.json` (`schema_grounding_version bee4a00b55c813209ca3d59d01734a2117caed92f7a527916070eecdf53409c3`, 28 relevant tables) and `SCHEMA_GROUNDING.md` |
| canonical models / enums used | `agents.control_state ∈ {DISCOVERED, CLAIMED, REGISTERED, GOVERNED}`, `origin_category ∈ {NATIVE, EXTERNAL, UNKNOWN}`, `LEGAL_CONTROL_STATES_BY_ORIGIN` (NATIVE→{GOVERNED}; EXTERNAL/UNKNOWN→{DISCOVERED, CLAIMED, REGISTERED}, ADR-0023), `AGENT_LIFECYCLE` (13 states), `external_enforcement_mode ∈ {OBSERVED, ADVISORY, GATEWAY_ENFORCED}` (NULL = OBSERVED, ADR-0021), `NODE_TYPES` (12), `EDGE_TYPES` (13), `DEPENDENCY_EDGE_TYPES` (9), `_EDGE_SHAPE`, `MCP_TRUST_STATUSES`, `MAX_TRAVERSAL_DEPTH 32` / `DEFAULT_TRAVERSAL_DEPTH 16`, `LINK_CREATE_CONFIDENCE_THRESHOLD 0.75`, `_MAX_ITEMS_PER_FETCH 20000`, containment `_REQUIRES_CONFIRMATION = True`; tables `agents`, `agent_identities`, `service_accounts`, `external_clients`, `tool_credentials`, `provider_credentials`, `connector_credentials`, `tools`, `mcp_servers`, `control_graph_edges`, `delegations`, `external_capability_grants`, `external_gateway_calls`, `discovery_sources`, `agent_executions`, … |
| gap re-verification (1.3) | **F6-1 PRESENT** (all six rules in `app/threat/rules.py` read executions/decisions; nothing in `app/threat` reads `external_gateway_calls`) · **I-1 PRESENT** (no memory-state model; nearest `agent_definitions.memory_requirements` is a declared requirement) · **I-2 PRESENT** (`AGENT_DELEGATES_TO` declared, no producer, no A2A ingestion) · **F-2 PRESENT** (`reconstruct_authority_chain` starts `FROM agent_executions`) · **V9-1 PRESENT** (path-array cycle guard in `traversal.py`) |
| STOP conditions (1.4) | none triggered; the generator's `_check_vocab` found no drift between grounding and the live model |

## C. Canonical estate

- **60 canonical agents**: 56 in the primary tenant *Northwind Payroll & Finance Group* (`northwind-pfg`) + 4 in the
  isolation-control tenant *Contoso Logistics* (`contoso-logistics`). No cohorts: each agent is one entity with many
  properties (`AGENT_PROPERTY_MATRIX.md`).
- **Distribution**: origin NATIVE 23 · EXTERNAL 32 · UNKNOWN 5 — control state GOVERNED 23 (all NATIVE) · REGISTERED 15 ·
  CLAIMED 5 · DISCOVERED 17 — inventory REGISTERED_IN_ACT 43 · SHADOW_DISCOVERABLE 12 · SHADOW_DARK 5 — enforcement
  mode (external agents known to ACT) GATEWAY_ENFORCED 12 · ADVISORY 2 · OBSERVED 4 (42 agents carry none: NATIVE or
  unknown to ACT) — lifecycle ACTIVE 56 · SUSPENDED 1 · RETIRED 1 · DRAFT 1 · PENDING_APPROVAL 1 — credential posture
  LEAST_PRIVILEGE 39 · OVER_PRIVILEGED 16 · SHARED 7 · STALE 2 · EXPIRED_STILL_ACTIVE 1 — memory NONE 53 · PERSISTENT 6 ·
  SESSION 1 — provider stacks LangGraph, CrewAI, custom HTTP/A2A, Bedrock, desktop/browser tools.
- **Overlapping-property example** (the brief's own): *Finance Research Assistant* — EXTERNAL/CUSTOM, SHADOW_DISCOVERABLE,
  unowned, `svc-finance-shared` (SHARED + OVER_PRIVILEGED, reaches payroll/compensation/ledger/treasury), legacy MCP of
  UNKNOWN trust, persistent memory (365 d), calls ACT's gateway **with a grant issued to `Finance Data Connector`** and
  attempts out-of-scope targets — **15 estate conditions** on one agent. Others: *Finance Close Orchestrator* (GATEWAY_ENFORCED,
  LangGraph parent of two workers, attempts `treasury-initiate-payment`), *Vendor Master Sync* (NATIVE/GOVERNED whose
  `external_reference` collides with a discoverable external process), *Vendor Portal Sync Bot* (vendor-operated,
  truthful-refusal subject). 27 agents carry ≥ 2 serious conditions, 19 carry ≥ 4.
- **Healthy control group: 12** (10–15 required) — full three-way ownership, ACTIVE, approved tools/MCP, least-privilege
  ACT-held credentials, zero serious conditions (validator `control_group.*`).
- **Reality classification** (exactly one per agent): ACTIVE_REAL_PROCESS_REQUIRED_STAGE2 **15** ·
  REAL_EXTERNAL_SERVICE_REQUIRED_STAGE2 **9** · SIMULATED_ASSET **33** · DORMANT_ASSET **3**.

## D. `estate_truth`

- **Schema** `1.0.0`, 22 top-level keys: `schema_version, generator, vocabulary_sources, tenants, environments, people,
  resources, credentials, identities, tools, mcp_servers, discovery_sources, agents, dependencies, delegations,
  agent_authority, a2a_handoffs, sensitive_reachability, identifier_collisions, control_group_agent_ids,
  truthful_refusal_subject_agent_ids, summary`.
- **Counts**: tenants 2 · environments 3 · people 19 · resources 19 · credentials 23 (`secret_value` null on every one) ·
  identities 38 · tools 23 · MCP servers 7 · discovery sources 3 (Enterprise Agent Registry HTTP lists 25; Cloud Agent
  Inventory Bedrock us-east-1 lists 6; Contoso Agent Registry lists 1) · agents 60 · **dependency edges 244** (all in
  `DEPENDENCY_EDGE_TYPES`) · human delegations 4 · agent-authority facts 5 · **real A2A handoffs 6** (all crossing a process
  boundary) · **sensitive-reach paths 78** (objective BFS over the estate's own edges) · **identifier collisions 1** ·
  control-group ids 12 · truthful-refusal subject ids 13.
- **Adversarial conditions (agents carrying each; derived, never typed)**: UNOWNED 18 · OVER_PRIVILEGED_CREDENTIAL 16 ·
  PRODUCTION_ACCESS_UNOWNED 15 · SHADOW_DISCOVERABLE 12 · DANGEROUS_DEPENDENCY_SENSITIVE_REACH 12 · UNKNOWN_PROVENANCE 11 ·
  UNAPPROVED_MCP 10 · SHARED_CREDENTIAL 7 · UNAPPROVED_TOOL 6 · OUT_OF_SCOPE_GATEWAY_ATTEMPTS 6 · F6_1_RELEVANT 6 ·
  I1_RELEVANT 6 · SHADOW_DARK 5 · DORMANT_WITH_ACTIVE_CREDENTIAL 3 · NATIVE_REFERENCE_COLLISION 2 · STALE_CREDENTIAL 2 ·
  EXPIRED_CREDENTIAL_STILL_ACTIVE 1 · LIFECYCLE_NOT_ACTIVE_BUT_RUNNING 1 · SHARED_GATEWAY_GRANT 1; structural:
  GATEWAY_ENFORCED_EXTERNAL 12 · I2_RELEVANT 12 · TRUTHFUL_REFUSAL_SUBJECT 13 · REGISTRY_DISCOVERABLE 26 · CLOUD_DISCOVERABLE 6.
- **What it does not contain** (validator-enforced): no `EXPECTED_*`/finding/verdict keys, no secret-shaped string, no PHI
  marker, no non-`.example` email, no cross-tenant reference, no ACT execution artifact, no timestamp/path/self-hash.

## E. `observability_contract`

**35 entries** (`1.0.0`): **OBSERVE 13 · PARTIALLY_OBSERVE 6 · NOT_OBSERVE 10 · ENFORCE 4 · REFUSE 2**. Every non-OBSERVE
entry carries live code references, an architectural justification and a boundary/precondition (validator
`contract.*`; rendered in `OBSERVABILITY_CONTRACT.md`). Justifications, in short:

- **OBSERVE** — inventory/ownership/lifecycle/control-state of agents ACT holds; ACT-held credential age/expiry; tools and
  MCP trust status; recorded dependency edges; registry/cloud-discoverable shadows via the two adapters (exact
  `external_reference`); NATIVE collision → `RECONCILIATION_AMBIGUOUS`, never a merge; human delegation chains for NATIVE
  executions; tenant isolation (cross-tenant traversal refused, V5).
- **PARTIALLY_OBSERVE** — sensitive reach only over *recorded* edges (resource sensitivity has no field); reachability under
  the depth cap and **V9-1**'s exponential path enumeration (precondition: small trust graph or the frontier-dedup fix);
  shared-grant callers attributed to the grant holder (`Finance Data Connector`), recorded objectively; external agents'
  authority by grant/issuer, not chain (**F-2**); enforcement mode as ACT's record, not the enterprise's approval workflow.
- **NOT_OBSERVE** — dark shadows (fixed adapter registry, no other source); external credential privilege/sharing outside
  ACT; provenance *quality*; runtime memory state (**I-1**); actual A2A handoffs and agent→agent authority (**I-2**, no
  producer); threat findings for gateway-enforced agents' denials (**F6-1** — rules read `agent_executions` /
  `RuntimeGovernanceDecision`, never `external_gateway_calls`); whether a dormant process is actually running.
- **ENFORCE** — gateway scope for GATEWAY_ENFORCED agents (in-scope dispatched, out-of-scope denied and never dispatched);
  grant revocation with real effect (subsequent calls 403); NATIVE containment on GOVERNED agents (confirmation-gated,
  ADR-0020); tenant boundary.
- **REFUSE** — `SUSPEND_AGENT`/kill on an external process ACT does not run (truthful refusal, process verifiably still
  live); containment on non-GOVERNED agents (`truthful_capability`).

## F. Hash / seal

| field | value |
|---|---|
| seed | `dt1-canonical-v2-2026` |
| generator version | `2.0.0` |
| schema-grounding version | `bee4a00b55c813209ca3d59d01734a2117caed92f7a527916070eecdf53409c3` |
| `estate_truth.json` | `888eb44160dd40c271df2a7b2a2ca6c1931928c68661340f88b6eda36fb5c691` (236,558 B) |
| `observability_contract.json` | `caa7db49ce5cb74e70284639c9a6632802e5b0ac050c87670a6d3d1aa19e78f9` (28,638 B) |
| `agent_property_matrix.json` | `115574630f6a29df9e0eb662636c209f75311a3bc32cf9dc824890b52d747287` (47,704 B) |
| **combined root** (SHA-256 of the three hex digests, truth‖contract‖matrix) | `e06a07532d48c9d9e4681d827ea5ec8b1bece9909e4fd5e84db14f1fbbdebf5a` |
| anchor timestamp | `2026-09-27T19:09:19+00:00` (in `anchor.json` only — not in any hashed content) |
| git commit at sealing / base commit | `ab27fe3a70e72bc3981e9b63afe36eacd5ce90c7` (both) |
| lab ledger | entries #25–#31 (`evidence/ledger_entries.jsonl`) chain the five artifacts and both instruction files |

## G. Determinism proof

`cli.py determinism --runs 3` (`evidence/determinism_run.txt`): **3 regenerations byte-identical** (`identical: true`),
hashes equal to the sealed values above, **`different_seed_differs: true`** (negative control). The validator repeats the
proof on every run (`determinism.regenerate_estate_truth/observability_contract/agent_property_matrix`) and checks the
bytes on disk equal canonical re-serialization (`canonical.*`). No `uuid4`, wall-clock, path or unordered iteration reaches
an artifact.

## H. Self-validator

- **Positive**: `VALID: 65/65 checks passed` on the sealed set (`evidence/validator_run.txt`).
- **Tests**: `lab/dt1/tests` — **30 passed** (7 positive/determinism · **16 negative** · 7 boundary), 2.90 s
  (`evidence/dt1_tests.txt`).
- **Proof it can fail**: each negative test mutates a copy of the sealed artifacts and asserts the *named* check fails —
  duplicate agent, missing owner, invalid credential/MCP reference, cross-tenant relationship, control group < 10, control
  group inflated with a risky agent, required adversarial condition removed, truthful-refusal scenario removed,
  non-deterministic field, one-byte tamper of truth and of contract after sealing, inserted secret shape, inserted
  `EXPECTED_*` key, real-data shapes, production-diff violation in a temporary repository. Details: `VALIDATOR.md`.

## I. Security / privacy

No real secret: every credential is an opaque label with `secret_value = null`; the validator applies the product
scrubber's credential-shape patterns to every string (`secrets.no_secret_shapes`), and the negative test that inserts a
credential-shaped value assembles it by concatenation. No real PII: fictional people, `@northwind-pfg.example` /
`@contoso-logistics.example` addresses only (`privacy.fictional_emails`), no PHI (`privacy.no_phi_markers`) — sensitive
resources are payroll, compensation, treasury, ledger and applicant data, generic and fictional. No cloud credential or
network call was involved at any point.

## J. Product boundary

- **No ACT execution**: ACT was not started against the estate; no discovery run, no posture evaluation, no finding, no
  containment; the artifacts contain no ACT execution keys (`boundary.no_act_execution_artifacts`).
- **No ACT product change, no migration**: `git diff ab27fe3 -- backend/app backend/migrations backend/requirements.txt
  backend/tests frontend .github` is **empty** (`evidence/production_diff.txt`; validator `boundary.empty_production_diff`
  and `test_boundaries.py`); newest migration still `0061_assurance_evidence`; `backend/app` imports nothing from DT1;
  DT1 imports nothing from `app` except the read-only grounding scan; nothing written under `backend/.keys/`.
- Repository changes outside `lab/dt1/`, `docs/dt1/`, `backend/instructions/`: one DT1 tracking row/paragraph each in
  `ROADMAP.md` and `REPO_STATE.md`, and three `-text` rules appended to `.gitattributes` scoped to the DT1 paths (see K.2).
  Nothing else.

## K. Conflicts / demo gaps

1. **The approved prompt had no local copy.** The approval said "re-read the complete approved prompt from the local
   filesystem"; only the instruction file existed on disk. The executing session materialized the approved prompt
   verbatim from the approved chat text as `backend/instructions/DT1_S1_V2_PROMPT_APPROVED.md`, hashed it
   (`761c9dec…`) and recorded both hashes (`evidence/INSTRUCTION_HASHES.md`). The reviewer should confirm that file is
   the text they approved.
2. **Line endings would have broken the seal on the next checkout.** `.gitattributes` has `* text=auto` and this machine
   runs `core.autocrlf=true`, so the LF-only sealed JSON would come back CRLF (hash mismatch) and the CRLF instruction
   file was stored LF-normalized in `e06a669` (blob `dded1924…` ≠ `984688a1…`). Fix in the follow-up commit: `-text`
   for `lab/dt1/artifacts/**`, `backend/instructions/**`, `docs/dt1/evidence/**` and `git add --renormalize`; the staged
   blobs now hash to exactly the sealed / recorded values. A non-production, DT1-scoped repository hygiene change.
3. **Grounding false positive corrected**: the first I-1 scan pattern matched `RequestContextMiddleware` as a "memory/
   context model"; tightened to ORM-model declarations and recorded the nearest related field. I-1 stays PRESENT.
4. **Design conflict resolved by legality, not by weakening**: the multi-property shadow cannot itself be
   `GATEWAY_ENFORCED` (enforcement mode requires REGISTERED and known to ACT). It is modelled as an unknown process calling
   the gateway with `Finance Data Connector`'s grant (`uses_grant_issued_to_agent_id`); its gateway conditions derive from
   that shared grant. The estate keeps the objective behaviour; the contract classifies attribution as PARTIALLY_OBSERVE.
5. **Demo gaps to plan around** (Stage 2 / demo, not Stage 1 defects): the 5 dark shadows are NOT_OBSERVE by design — the
   demo must show that absence truthfully; F6-1's detection silence for 6 agents is a limitation entry (`LIMITATIONS.md`),
   not a hero; V9-1 keeps the estate's trust graph deliberately small; the cloud inventory needs a faithful mock or a
   signed read-only sandbox (none exists — V8 stopped for that reason); O-11 must be closed before any non-lab deployment.
6. **Lab ledger**: `ledger.py verify` still reports the pre-existing V9 alteration of `v9_recovery.json` (documented in
   `docs/validation/v9/RESULTS_LEDGER.md`); the DT1 entries #25–#31 verify (`evidence/ledger_verify.txt`).
7. Evidence hygiene: the first `production_diff.txt` listed `__pycache__` as the newest migration (a sort artefact);
   regenerated correctly before the follow-up commit.

## L. Artifacts

| path | role | SHA-256 (prefix) |
|---|---|---|
| `lab/dt1/artifacts/estate_truth.json` | objective synthetic reality (236,558 B) | `888eb44160dd40c2…` |
| `lab/dt1/artifacts/observability_contract.json` | 35 grounded entries (28,638 B) | `caa7db49ce5cb74e…` |
| `lab/dt1/artifacts/agent_property_matrix.json` | 60 rows (47,704 B) | `115574630f6a29df…` |
| `lab/dt1/artifacts/anchor.json` | seal record (1,062 B) | `8f321031498126fa…` |
| `lab/dt1/artifacts/schema_grounding.json` | live-model grounding, 28 tables, gap statuses (53,462 B) | `b22b96445d065ede…` |
| `docs/dt1/` | `DT1_S1_REPORT.md` (this), `ESTATE_DESIGN.md`, `OBSERVABILITY_CONTRACT.md`, `AGENT_PROPERTY_MATRIX.md`, `SCHEMA_GROUNDING.md`, `DETERMINISM_AND_SEAL.md`, `VALIDATOR.md`, `STAGE2_READINESS.md`, `LIMITATIONS.md`, `evidence/` (validator, determinism, tests, SHA256SUMS, anchor copy, instruction hashes, ledger entries + verify, production diff) | — |
| `lab/dt1/` code | `grounding.py`, `dt1_versions.py`, `canonical.py`, `estate.py`, `contract.py`, `matrix.py`, `seal.py`, `validator.py`, `cli.py`, `tests/` (3 files + conftest), `BASE_COMMIT`, `README.md` | — |
| `backend/instructions/` | `DT1_S1_V2_INSTRUCTION.md` `984688a1…`, `DT1_S1_V2_PROMPT_APPROVED.md` `761c9dec…` | — |

Full hashes: `evidence/SHA256SUMS.txt`.

## M. Git

Base `ab27fe3` (`validation/v10-authorization-template`). Branch **`dt1/s1-canonical-estate`**. Commit **`e06a669`** —
"dt1(s1): canonical Digital-Twin estate …" — 40 files, 4,668 insertions (generator, validator, tests, artifacts, docs,
instructions). A follow-up commit carries this report, the two tracking rows, the `.gitattributes` rules and the
renormalized blobs (its hash is stated in the delivery message). Pushed to `origin` as `Umair-zaka-ui`. **Not merged; no
pull request.** `origin/main` remains `9667707`.

## N. Stage-2 readiness

Detailed in `STAGE2_READINESS.md`. **Real processes required (15)**: every GATEWAY_ENFORCED or shared-grant agent and every
A2A participant (Finance Close Orchestrator + 2 workers, Recruiting Crew Manager + 2 crew, Finance Data Connector,
Treasury Payment Scheduler, Vendor Portal Sync Bot, Employee Q&A Copilot, HR Helpdesk Agent, Budget Forecaster, Vendor
Onboarding Assistant, Finance Research Assistant) — the V7 lab agents are the substrate. **Services required**: the
Enterprise Agent Registry (HTTP, 25 agents — the guaranteed process/network-boundary crossing), the Cloud Agent
Inventory (Bedrock `ListAgents` shape, 6 agents — mock or signed sandbox), the Contoso registry (1), and MCP/tool
endpoints as dispatch targets. **Stage 2 must evaluate, derived from truth + contract**: discovery accuracy vs truth
(exact `external_reference`, truthful absence of the 5 dark shadows, collision → ambiguity finding, never a merge);
posture specificity (0 serious findings on the 12 control agents); blast radius vs the 78 reach paths over recorded
edges; effect-verified gateway enforcement and shared-grant attribution; F6-1 absence with the denials present in
`external_gateway_calls`; truthful refusal *then* real revocation; I-1/I-2 truthful absences; authority by chain (NATIVE)
vs by grant (external); tenant isolation; and seal precedence (`anchor.json` predates the first ACT run and still
verifies). Inherited prerequisites: O-11 closure, a V9-1 gate decision or role-level timeouts, a fresh dedicated lab
database, the V2.1 egress-deny wrapper, no cloud spend without a signed authorization. Stage 2 may not modify production
ACT to make the twin work.

---

VERDICT: DT1-S1 PASSED — READY FOR STAGE-2 REVIEW
