# ADAPTER_DESIGN — `AWS_BEDROCK_AGENTS` (V7.5, the one product-change exception)

Decision record: [`docs/architecture/adr/0024-cloud-discovery-adapter-aws-bedrock-agents.md`](../../architecture/adr/0024-cloud-discovery-adapter-aws-bedrock-agents.md).
Code: `backend/app/discovery/adapters/aws_bedrock_agents.py` (one module).
Tests: `backend/tests/discovery/test_aws_bedrock_agents_adapter.py`.

## 1. Provider and why

**AWS — Agents for Amazon Bedrock**, the provider's managed AI-agent primitive.

| criterion (§2 of the brief: "cheapest scoped read-only sandbox") | AWS Bedrock Agents |
|---|---|
| sandbox cost | free-tier account; `ListAgents` is free; AWS Budgets alerts are free |
| read-only scoping | one IAM action, `bedrock:ListAgents`; a custom policy with exactly that action and nothing else |
| the agent primitive | a first-class *agent* resource (`AgentSummary`) — not "every VM is an agent" |
| wire complexity | one signed HTTPS request per page; no OAuth token exchange with a second host (Azure/GCP need one) |
| API shape publicly specified | `POST /agents/`, `AgentSummary`, error codes, endpoint pattern, signing name — all from AWS reference docs and botocore's service model |

Alternatives are weighed in ADR-0024 (boto3, Azure AI Foundry, GCP Vertex Agent Engine, Cloud Control API, account-wide inventory) and were rejected or deferred for stated reasons.

## 2. The agent-definition filter (the hardest definition)

`is_bedrock_agent(summary)` — pure, fixed in code, not operator-configurable:

| rule | value | rationale |
|---|---|---|
| **construct type** | only elements of `ListAgents.agentSummaries` | the adapter calls no other operation, so nothing else can ever be listed |
| required identity | `agentId` matching `^[0-9a-zA-Z]{10}$` **and** a non-empty `agentName` | the API's own required `AgentSummary` fields; a malformed or foreign-shaped element is dropped, so a poisoned page cannot inflate the inventory |
| status **excluded** | `DELETING` | AWS reports the construct as leaving; discovering it would create an agent only to stale it next sweep |
| status **included** | `CREATING`, `PREPARING`, `PREPARED`, `NOT_PREPARED`, `FAILED`, `VERSIONING`, `UPDATING`, and absent | a defined-but-inoperable agent is still an agent in the estate; shadow-AI inventory cares about existence, not operability. Status is carried as metadata in the observation |

**Explicitly NOT agents (never listed, never observed):** foundation models, knowledge bases, flows, prompts, guardrails, **agent aliases** and **agent versions** (deployment pointers, not agents), Lambda functions, ECS tasks, EC2 instances, SageMaker endpoints — and any other AWS inventory. The unit test feeds shapes of each into the filter and asserts exclusion; the integration test feeds a mixed page and asserts only the two real agents are observed.

## 3. Configuration — the host is derived, never declared

```json
{ "region": "us-east-1" }
```
is a complete production config. Schema (`additionalProperties: false`):

| key | rule | effect |
|---|---|---|
| `region` (required) | `^[a-z]{2}(-gov)?-[a-z]+-[0-9]$` | host = `bedrock-agent.<region>.amazonaws.com`; a region cannot carry a host or path |
| `endpoint_url` | origin only (`^https?://host[:port]/?$`); host must be `https://*.amazonaws.com` (FIPS/VPC) **or** listed in `local_dev_hosts` | lab/mock path; no path prefix can be smuggled; plaintext to AWS impossible |
| `local_dev_hosts`, `allow_plaintext_http` | plaintext only with declared local hosts | the 5.2 test convention, no wider |
| `page_size` 1–200 (default 100), `max_pages` 1–100 (default 20) | absolute bound 20,000 items/sweep | same DoS ceiling as the reference adapter |

`build_client()` binds `GovernedHttpClient` to **exactly one host** — the derived one. Egress allowlist, SSRF/rebinding pinning, redirect re-validation and the 1 MiB response cap are inherited.

## 4. Read-only credential model (authenticate the source, never extend identity)

- Source `secret` = `ACCESS_KEY_ID:SECRET_ACCESS_KEY` or `ACCESS_KEY_ID:SECRET_ACCESS_KEY:SESSION_TOKEN` (STS temporary credentials supported). Stored encrypted by `credential_crypto` (M4.11 key lifecycle); `secret_hint` is the last four characters only; the plaintext `config` carries **no** credential material.
- The credential is parsed only inside `fetch()`, never persisted, never logged, never echoed in an error.
- **Required IAM policy** (the complete scope; `ListAgents` supports no resource-level restriction):

```json
{ "Version": "2012-10-17",
  "Statement": [ { "Effect": "Allow", "Action": [ "bedrock:ListAgents" ], "Resource": "*" } ] }
```
- The credential authenticates ACT-to-AWS. It never becomes a `users` row, a grant, or an authority. A discovered Bedrock agent lands at `origin_category=EXTERNAL`, `control_state=DISCOVERED`; `GOVERNED` is unreachable for it (ADR-0023) — asserted in the integration test with a `409`.

**Sandbox status in this phase: NOT ESTABLISHED.** No cloud account or credential of any scope was available to the lab, and the brief forbids using a broad one. No cloud endpoint was contacted. The integration proof runs against a faithful local server implementing the documented wire shape and **verifying SigV4 on every request**; the signer is separately known-answer-tested against values produced by the AWS SDK's own `SigV4Auth` (`evidence/sigv4_botocore_crosscheck.txt`). A first live run against a read-only sandbox is the outstanding review condition.

## 5. Discovery flow

```
DiscoverySource(adapter_key=AWS_BEDROCK_AGENTS, config={region}, encrypted_secret)
  └─ DiscoveryRunService.run_source           [5.2, unchanged: 3 short transactions]
       ├─ T1  insert RUNNING run → COMMIT
       ├─ fetch()   ── NO Session in scope (AC-06) ──────────────────────────────
       │    ListAgents  POST /agents  {"maxResults": n[, "nextToken": t]}   (SigV4-signed)
       │    → filter agentSummaries with is_bedrock_agent()
       │    → RawDiscoveryItem(external_identifier="bedrock-agent:<region>:<agentId>", payload=summary+region)
       │    → paginate on nextToken; bounded by max_pages / 20,000 items
       ├─ normalize() → NormalizedObservation(name=agentName, origin_provider=AWS_BEDROCK_AGENTS,
       │                                       agent_type=ASSISTANT, confidence=1.00, raw=summary)
       ├─ T3a persist observations (scrubbed, each its own SAVEPOINT, append-only)
       ├─ T3b ReconciliationService: CREATE (DISCOVERED/EXTERNAL) | LINK | FLAG (NATIVE collision, low confidence)
       │      check_staleness: missing agent → OPEN STALE_AGENT finding (never a deletion), auto-resolved on re-observation
       └─ T4  finish run SUCCEEDED | PARTIAL | FAILED → COMMIT
```

## 6. Failure modes (all inherited 5.2 semantics; the adapter only maps AWS statuses)

| condition | adapter behaviour | run outcome | agents |
|---|---|---|---|
| no secret / malformed secret | `DISCOVERY_SOURCE_INVALID_CONFIG` before any request | `FAILED` | untouched |
| first page: connection refused / timeout / egress denial / 403 / 429 / 5xx | `DISCOVERY_SOURCE_UNREACHABLE` with status + fixed classification | `FAILED` | untouched, **no staleness** (absence of evidence ≠ evidence of absence) |
| later page: 429 / 5xx | keep collected evidence, degrade | `PARTIAL`, checkpoint `{next_token}` | created/linked from collected pages |
| resumption token rejected (400 on first resumed page) | one fresh sweep from the beginning | normally `SUCCEEDED` | idempotent |
| asset removed in the cloud | — | `SUCCEEDED` + 1 `STALE_AGENT` finding | `control_state` unchanged |
| `max_pages` reached | bounded, resumable | `PARTIAL` | — |
| malformed JSON page | empty page | per the page-1/page-N rule | — |

**No AWS error body is ever recorded.** A SigV4 rejection from AWS echoes the canonical request, which can include a session token; run errors therefore carry status and classification only.

## 7. Signing — the one NEW capability, and why it is not a new primitive

AWS accepts only Signature Version 4; the 5.2 pattern only knows a bearer header. `boto3` would be a second transport outside `GovernedHttpClient` (its own DNS, redirects, proxies, endpoint resolution — none under the egress guard). So SigV4 is a ~40-line standard-library **header computation** (`hmac`/`hashlib`) that signs exactly what the governed executor transmits:

- `_encode_json_as_sent` mirrors httpx 0.28.1's `encode_json` (compact separators) — pinned against `httpx.Request(...).content`.
- `_path_as_sent` mirrors `http_executor._build_target_url`, which drops a trailing slash (`/agents/` → `/agents`) — pinned against the real function. Smithy URI matching treats trailing slashes as "always optional", so `/agents` routes to `ListAgents`.
- `content-type` (value as httpx sends it), `host` (netloc as httpx sends it), `x-amz-date`, and `x-amz-security-token` when present are the signed headers.
- Verified against botocore 1.43.66's `SigV4Auth` at a pinned instant: IAM example, Bedrock POST, Bedrock POST with session token — all three identical.

## 8. Reuse map

| capability | class | source |
|---|---|---|
| adapter contract (`describe/validate_configuration/build_client/fetch/normalize`) | **REUSE** | `app/discovery/adapters/base.py` |
| fixed decorator registry, `DISCOVERY_ADAPTER_UNKNOWN` | **REUSE** | `adapters/registry.py` |
| the network primitive + egress/SSRF/redirect/size containment | **REUSE** | `app.integration.sdk.GovernedHttpClient` → `execute_http_tool` |
| JSON-schema config validation | **REUSE** | `validate_configuration_schema` |
| secret at rest, hint, decryption at sweep time | **REUSE** | `credential_crypto` via `DiscoverySourceService` |
| scrubbing before persistence | **REUSE** | `app.observability.scrubbing.scrub` (in `_persist_observations`) |
| three-transaction sweep, no lock across fetch | **REUSE** | `DiscoveryRunService.run_source` |
| CREATE/LINK/FLAG, NATIVE collision, staleness | **REUSE** | `ReconciliationService` |
| API surface, permissions, audit events, scheduler handler | **REUSE** | `/api/v1/discovery`, `discovery.source.*`, `discovery.sweep` |
| tables | **REUSE** | `discovery_sources/runs/observations/findings` — no migration |
| registry import list | **EXTEND** | one line in `registry._ensure_reference_adapter_registered` |
| AC-15 moving-target guard | **EXTEND** (intent-preserving) | registry exhaustive: `("AWS_BEDROCK_AGENTS", "HTTP_AGENT_REGISTRY")`, other vendors still banned |
| SigV4 header computation | **NEW** | AWS does not accept bearer auth; boto3 would bypass the primitive |
| credential-string parser (`AKID:SECRET[:TOKEN]`) | **NEW** | one encrypted field must carry three parts so `config` stays credential-free |
| pattern-validated region → derived host; bounded `endpoint_url` | **NEW (tightening)** | stricter than the reference adapter; no free-form host list |

## 9. What the adapter does NOT do (the exception boundary)

- No detection, threat, posture, graph or gateway emission; no import from those packages. **F6-1 is not addressed** — cloud-discovered agents inherit it by design for V8 to observe.
- No second cloud, no catalog, no `GetAgent`, no aliases/versions, no write of any kind to AWS.
- No new table, column, route, permission, error code, audit event, dependency or migration.
- No change to any M1–M5 behaviour. The trailing-slash normalization in the M1 executor was *worked with*, not altered.
