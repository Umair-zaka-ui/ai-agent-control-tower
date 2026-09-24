# ADR-0024 — One cloud discovery adapter (AWS Bedrock Agents) on the 5.2 connector-containment pattern: discovery-plane-only, read-only source credential, never a second identity or network path

- **Status:** Proposed — V7.5 architecture review pending; becomes Accepted on merge of `validation/v7.5-cloud-adapter`
- **Date:** 2026-09-24
- **Deciders:** Post-Milestone-5 Validation Programme, phase V7.5 (the programme's one deliberate product-change exception)
- **Supersedes:** —
- **Relates to:** ADR-0016 (observations are evidence; reconciliation derives truth — this adapter feeds that pipeline and nothing else), ADR-0015 / ADR-0023 (`control_state`; `GOVERNED` ⇔ `NATIVE`, so a cloud-discovered agent can never be governed by declaration), ADR-0021 (truthful enforcement modes — a discovered cloud agent has none), V7 report §R point 3 ("keep the identity boundary exactly where it is").

## Context

The post-M5 validation programme (V0–V7) ran under a standing rule: **no product code changes**. V8 is
the cloud red-team phase, and it cannot red-team cloud discovery because ACT has no cloud discovery
adapter — Phase 5.2 shipped the vendor-neutral framework and one reference adapter
(`HTTP_AGENT_REGISTRY`) and explicitly deferred every vendor adapter ("Azure AI Foundry, AWS Bedrock
Agents, …", SRS M5.2 §5; `docs/discovery/framework.md`). V7.5 suspends the no-change rule for exactly
one artifact so that V8 has something real to attack.

Because the rule is suspended, the exception has to be drawn narrowly and be auditable. The forces:

- **The 5.2 substrate is complete and proven.** `DiscoveryAdapter` (`describe` / `validate_configuration`
  / `build_client` / `fetch` / `normalize`), a fixed decorator registry, `GovernedHttpClient` as the
  sole network primitive (egress allowlist, SSRF/rebinding pinning, redirect re-validation, 1 MiB cap),
  `credential_crypto` for secrets at rest, append-only `discovery_observations`, deterministic
  `ReconciliationService` (CREATE / LINK / FLAG, no silent merge, NATIVE collision flags, non-destructive
  staleness), and `fetch()` structurally unable to hold a DB session (AC-06). A new adapter should be
  *only* the provider-specific part.
- **V7's lessons.** F6-1: detection does not see gateway-enforced agents; wiring that is an M6 product
  decision, not something to pre-patch through a discovery adapter. Point 3: uniform governance came
  from the signed-request boundary being the only thing ACT looks at — a cloud adapter must extend
  inventory, never authority.
- **AWS's API is not bearer-authenticated.** Every AWS request needs Signature Version 4. The 5.2
  reference adapter only knows `Authorization: Bearer`. Something has to sign.
- **The lab has no cloud.** No cloud account or credential is available to this session; V8 runs in the
  V2.1 wrapper with no egress anyway. The adapter must be provable against a faithful local server and
  must fail *loud and safe* on a live cloud, not silently.
- **Provider API shape.** Agents for Amazon Bedrock lists agents with `ListAgents` — documented as
  `POST /agents/` with `maxResults`/`nextToken` in the JSON body, endpoint
  `bedrock-agent.<region>.amazonaws.com`, SigV4 signing name `bedrock` (botocore service model
  `bedrock-agent/2023-06-05`). `AgentSummary` carries `agentId` (`[0-9a-zA-Z]{10}`), `agentName`,
  `agentStatus` (`CREATING | PREPARING | PREPARED | NOT_PREPARED | DELETING | FAILED | VERSIONING |
  UPDATING`), `description`, `latestAgentVersion`, `updatedAt`. `ListAgents` supports no resource-level
  IAM restriction (`Resource: "*"`).
- **A primitive detail that mattered.** `execute_http_tool._build_target_url` (M1) strips a trailing
  slash from the request path, so the governed client emits `/agents`, not the documented `/agents/`.
  Altering that M1 behaviour is out of scope. The Smithy HTTP-binding spec states that trailing slashes
  in URI patterns "are always optional", so `/agents` routes to `ListAgents`; the adapter signs the path
  as actually sent.

## Options considered

### Option A — Agents for Amazon Bedrock, `ListAgents` only, through `GovernedHttpClient`, SigV4 in the standard library (**chosen**)
- Pros: AWS offers the cheapest scoped read-only sandbox (free-tier account, a one-action IAM policy,
  free budget alerts); Bedrock Agents is the provider's *agent* primitive, so the agent-definition
  filter is precise by construction; one operation, one host derived from a pattern-validated region;
  every byte goes through the governed client; the credential is a *source* credential that never
  touches ACT identity; no dependency added.
- Cons: SigV4 has to be implemented (≈40 lines of `hmac`/`hashlib`, a header computation — not a
  transport); `ListAgents` is a POST-bodied list, so read-only-ness rests on the operation and IAM
  scope rather than the verb; a live AWS run could not be performed in this phase.

### Option B — `boto3`
- Pros: signing, endpoints, pagination and retries for free; already pinned in `requirements.txt` for
  the 2.2.4 SQS queue backend.
- Cons: a **second network primitive** outside `GovernedHttpClient` — its own transport, DNS, redirects,
  proxies and endpoint resolution, none of it under the egress guard or the SSRF pinning. Rule 3 of the
  phase ("invent no new primitive; `GovernedHttpClient` only") forbids exactly this. Rejected.

### Option C — Azure AI Foundry Agents or GCP Vertex AI Agent Engine
- Pros: both list a managed agent construct over plain HTTPS.
- Cons: both require an OAuth2 token exchange with a second host (`login.microsoftonline.com` /
  `oauth2.googleapis.com`) before the inventory call — two allowed hosts and a token-acquisition flow,
  more surface than SigV4's single signed request; neither sandbox is cheaper. Breadth, not depth.
  Deferred, not rejected on merit.

### Option D — AWS Cloud Control API `ListResources(TypeName="AWS::Bedrock::Agent")`
- Pros: `POST /` (no trailing-slash question); the type name *is* the filter.
- Cons: an indirection over the same underlying `bedrock:ListAgents` permission; the list handler's
  returned property shape is not documented precisely enough to build a faithful mock from; less
  direct as "the provider's agent primitive". Rejected.

### Option E — Account-wide inventory (Resource Groups Tagging, AWS Config, Resource Explorer)
- Cons: over-broad (every tagged resource), incomplete (untagged agents invisible), or requiring paid
  setup (Config recorder, Resource Explorer index). Violates the conservative agent-definition rule.
  Rejected.

## Decision

We chose **Option A**: one adapter, `app/discovery/adapters/aws_bedrock_agents.py`, registered as
`AWS_BEDROCK_AGENTS`, implementing the unchanged 5.2 `DiscoveryAdapter` contract, calling exactly one
AWS operation (`ListAgents`) through `GovernedHttpClient`, signed with a standard-library SigV4 helper
that hashes precisely the bytes and path the governed executor transmits.

The decision has six load-bearing parts:

1. **Discovery plane only.** The module imports only `app.discovery.adapters.base`,
   `app.discovery.adapters.registry`, `app.identity.errors`, `app.integration.base` and
   `app.integration.sdk` (asserted over the AST). It emits observations; reconciliation derives an agent
   at `origin_category=EXTERNAL`, `control_state=DISCOVERED`, `origin_provider=AWS_BEDROCK_AGENTS`.
   It emits no detection, threat, posture, graph or gateway signal. **F6-1 is deliberately not
   addressed**: cloud-discovered agents inherit it, and V8 is expected to observe that.
2. **The agent-definition filter is conservative and fixed in code** (`is_bedrock_agent`): a mapping
   with a well-formed `agentId` and a non-empty `agentName` whose `agentStatus` is not `DELETING`.
   Foundation models, knowledge bases, flows, prompts, guardrails, agent aliases and versions, Lambda,
   ECS, EC2 and SageMaker are never listed (the adapter calls nothing that would return them), and a
   foreign-shaped element inside `agentSummaries` is dropped, so a poisoned page cannot inflate the
   inventory. `DELETING` is excluded because AWS itself reports the construct as leaving; `FAILED` and
   `NOT_PREPARED` are included because a defined-but-inoperable agent is still an agent in the estate.
   The filter is not operator-configurable.
3. **Read-only source credential, never internal identity.** The source secret is
   `ACCESS_KEY_ID:SECRET_ACCESS_KEY[:SESSION_TOKEN]`, stored encrypted by `credential_crypto`; the
   plaintext `config` carries no credential material. The required IAM scope is exactly
   `bedrock:ListAgents` (`REQUIRED_IAM_ACTIONS`). The credential authenticates ACT-to-AWS and nothing
   else: it never becomes a `users` row, a grant, or an authority; a discovered agent gains no internal
   authority and `GOVERNED` remains unreachable for it (ADR-0023).
4. **The allowed host is derived, never declared.** `region` is pattern-validated
   (`^[a-z]{2}(-gov)?-[a-z]+-[0-9]$`) and the host is computed from it. An `endpoint_url` override must
   be an `https://*.amazonaws.com` origin (FIPS/VPC) or a host listed in `local_dev_hosts` (the lab
   path); it may carry no path prefix; `allow_plaintext_http` requires `local_dev_hosts`; the config
   schema forbids unknown keys, so an `allowed_hosts` list cannot be smuggled in. This is stricter than
   the reference adapter.
5. **No AWS error body is ever recorded.** A SigV4 rejection from AWS echoes the canonical request, which
   can include a session token. Run errors carry the HTTP status and a fixed classification only.
6. **Fail-open shape unchanged from 5.2.** First-page failure → `FAILED` run, nothing touched, no
   staleness (absence of evidence is not evidence of absence); later-page failure → `PARTIAL` with the
   page token as checkpoint; an expired resumption token (AWS 400 on the first resumed page) → one fresh
   sweep rather than a stuck source; a removed asset → `STALE_AGENT` finding, never a deletion.

**Reuse map.** REUSE: `DiscoveryAdapter`, the registry, `GovernedHttpClient` and everything under it,
`validate_configuration_schema`, `credential_crypto` via `DiscoverySourceService`, `scrub`,
`DiscoveryRunService`'s three-transaction sweep, `ReconciliationService`, `check_staleness`, the
`/api/v1/discovery` surface, the `discovery.sweep` scheduler handler, `DiscoverySource` /
`DiscoveryRun` / `DiscoveryObservation` / `DiscoveryFinding` unchanged. EXTEND: the registry's import
list (one line), the `test_ac15` moving-target guard (intent-preserving: the registry is still
exhaustive and still not a catalog). NEW: the SigV4 header computation and the credential-string parser
— both because the 5.2 pattern only knows bearer tokens and AWS does not accept one; neither is a
transport, a registry, or an identity path.

## Consequences

### Positive
- V8 has a real cloud discovery adapter to attack, built on the same containment the rest of discovery
  already has — nothing new to trust.
- The exception is auditable: the product diff is the adapter module, one registry import, one package
  docstring, and one intent-preserving guard update. No migration, no table, no route, no dependency.
- Every containment property is asserted structurally or behaviourally in
  `tests/discovery/test_aws_bedrock_agents_adapter.py`, against a real local server that verifies SigV4
  on every request; the signer is additionally known-answer-tested against values produced by the AWS
  SDK's own `SigV4Auth`.

### Negative / accepted cost
- **No live AWS call was made in this phase.** No cloud account or read-only credential was available
  to the lab, and the phase forbids using a broad one. The integration proof is against a faithful
  mock of the documented wire shape with SigV4 verification; live routing of `POST /agents` (trailing
  slash dropped by the M1 executor) rests on the Smithy specification, and live signing on the botocore
  cross-check. A first live sandbox run is the outstanding review condition.
- ≈40 lines of SigV4 are now ACT's to maintain. Two "mirror" helpers (`_encode_json_as_sent`,
  `_path_as_sent`) restate httpx's JSON encoding and the executor's path normalization; both are pinned
  by tests so a change in either breaks loudly at test time rather than as a live 403.
- A bounded (`PARTIAL`) sweep triggers `check_staleness` against a partial observation set — a
  pre-existing 5.2 behaviour, inherited unchanged (findings are non-destructive and auto-resolve on
  re-observation). Recorded, not altered.
- `ListAgents` is a POST. Read-only-ness is a property of the operation and the IAM scope; a reviewer
  cannot infer it from the verb.
- `boto3` remains installed for the SQS backend; it is unused here and the AST guard keeps it that way.

### Residual risk
- A compromised read-only key exposes agent inventory metadata (names, statuses, descriptions) — nothing
  more, by IAM scope.
- Source poisoning (a hostile or spoofed inventory) is contained the same way the reference adapter is
  (bounded fields, no silent merge, NATIVE collision flags) and is V8's job to attack; it is not proven
  here.
- Cloud-discovered agents are invisible to the detection plane (F6-1) by design until M6 wires the
  gateway plane into detection.

## Revisit when

- The first live read-only sandbox run completes — confirm routing and signing, then flip Status.
- A second cloud is authorized — generalize the credential-string shape and the signing helper only if
  the second provider needs the same; do not build a catalog speculatively.
- AWS changes `ListAgents` (URI, pagination, `AgentSummary` fields) — the mock and the filter must
  follow the documented shape, not the other way round.
- M6 wires gateway-plane events into detection — cloud-discovered agents should then become visible
  without any change to this adapter; if they do not, this ADR's plane boundary is being crossed
  somewhere.
