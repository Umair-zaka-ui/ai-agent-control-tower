# CONTAINMENT_PROOF — the adapter inherits containment; it introduces no new trust or network path

Every property below is asserted by a named test in
`backend/tests/discovery/test_aws_bedrock_agents_adapter.py` (33 items, all passing —
`evidence/adapter_suite_run2_pass.txt`) or by the pre-existing 5.2 guard that iterates every registered
adapter. **S** = structural (AST / signature / registry), **B** = behavioural (real local server, real DB).

## 1. `GovernedHttpClient` only — no ad-hoc HTTP, no AWS SDK

| assertion | kind | test |
|---|---|---|
| module imports from `app.*` are exactly `{discovery.adapters.base, discovery.adapters.registry, identity.errors, integration.base, integration.sdk}` | S | `test_structural_discovery_plane_only_imports_…` |
| no import of `boto3`, `botocore`, `httpx`, `requests`, `urllib.request`, `urllib3`, `socket`, `aiohttp`, `http.client`, `ssl`; no `boto*` name bound in the module | S | `test_structural_governed_http_client_is_the_only_network_primitive_and_no_aws_sdk` |
| exactly **one** `.request(` call site in the module | S | `test_structural_read_only_exactly_one_list_operation_and_one_iam_action` |
| `build_client()` returns a `GovernedHttpClient` bound to **one** derived host; other hosts (incl. another AWS region) and plaintext-to-AWS are denied by the allowlist alone, offline | B (offline `evaluate`) | `test_unit_default_endpoint_is_derived_from_the_region_and_is_the_only_allowed_host` |
| region cannot smuggle a host/path (`evil.com/#`, `us-east-1.evil.com`, case, whitespace) | B | `test_unit_region_is_pattern_validated_…` (6 cases) |
| `endpoint_url` must be `https://*.amazonaws.com` or a declared local host; no path prefix; no `allowed_hosts` key accepted; plaintext requires local hosts | B | `test_unit_endpoint_override_is_amazonaws_https_or_a_declared_local_dev_host_only` |

## 2. Discovery-plane only (the exception boundary — cannot drift into F6-1 territory)

| assertion | kind | test |
|---|---|---|
| no import from `app.threat`, `app.bridge`, `app.posture`, `app.graph`, `app.runtime`, `app.models`, `app.observability`, `app.scheduler`, `app.command_center`, `app.assurance`, nor from the discovery service/reconciliation | S | `test_structural_discovery_plane_only_imports_…` |
| the only product effect is observations → 5.2 reconciliation → `EXTERNAL`/`DISCOVERED` agents; `GOVERNED` refused `409` | B | `test_integration_inventory_lands_as_external_discovered_agents` |
| no new table, migration (head stays `0061_assurance_evidence`), or route | S | `test_structural_no_migration_no_table_no_route_was_added` |

## 3. Read-only — no write/delete to the cloud is possible

| assertion | kind | test |
|---|---|---|
| the single call site's method is the constant `LIST_AGENTS_METHOD == "POST"`, path `/agents/` (AWS's documented list operation); no `PUT`/`DELETE`/`PATCH`/`GET` literal in the module; no `bedrock:(Get|Create|Delete|Update|Prepare|Invoke|Associate|Disassociate|Tag)` in any literal; `REQUIRED_IAM_ACTIONS == ("bedrock:ListAgents",)` | S | `test_structural_read_only_exactly_one_list_operation_and_one_iam_action` |
| across a full paginated sweep the server saw only `POST /agents`, bodies with keys ⊆ `{maxResults, nextToken}`, zero non-list calls (the mock records and refuses any GET/PUT/DELETE/PATCH) | B | `test_integration_inventory_lands_as_external_discovered_agents` |
| credential scope: the documented IAM policy allows exactly one action (ADAPTER_DESIGN §4) | policy | — |

## 4. No cloud credential in any observation, audit record, run error, or API read

| assertion | kind | test |
|---|---|---|
| observations: access key id, secret, session token absent; a `sk-…`/`AKIA…`-shaped description is `***REDACTED***` (scrubbed by shape, not merely absent) | B | `test_containment_no_cloud_credential_in_observations_audit_runs_or_the_source_read` |
| `discovery_runs.error` after a forced 403: no credential material; AWS response body not recorded | B | same |
| `authorization_audit.meta` for the tenant: no credential material | B | same |
| `discovery_sources.encrypted_secret` is ciphertext; `secret_hint` = last 4 chars; `GET /sources/{id}` exposes neither secret nor ciphertext; plaintext `config` key set ⊆ the schema's credential-free keys | B | same |
| credential parse errors never echo the value | B | `test_unit_credential_format_is_parsed_and_never_echoed` |
| a missing secret sends **nothing** (zero requests) and fails the run | B | `test_integration_missing_secret_is_a_failed_run_not_a_crash` |

## 5. Tenant-scoped

| assertion | kind | test |
|---|---|---|
| a source in tenant A creates agents only in tenant A; tenant B cannot read or run the source (404) and sees no agent | B | `test_containment_tenant_scoped_a_source_only_ever_creates_agents_in_its_own_tenant` |

## 6. No DB lock across the cloud call (the M1 deadlock discipline)

| assertion | kind | test |
|---|---|---|
| `fetch()` signature: exactly `(client, configuration, secret, checkpoint)`, no `Session` type anywhere | S | `test_unit_adapter_is_registered_and_implements_the_5_2_contract` and the 5.2 guard `test_ac06_adapter_fetch_signature_never_accepts_a_session` (iterates every registered adapter) |
| while the sweep is blocked on a held-open cloud response, a separate session takes `FOR UPDATE` on the same `discovery_sources` row and commits in < 2 s; the sweep then completes `SUCCEEDED` | B | `test_no_lock_held_across_the_cloud_call_behavioral` |

## 7. Deterministic reconciliation, no silent merge, NATIVE collision flags, staleness non-destructive

| assertion | kind | test |
|---|---|---|
| a Bedrock `agentId` colliding with a NATIVE agent's `external_reference` → `RECONCILIATION_AMBIGUOUS` finding, 0 created, 0 linked; the native agent's name/state untouched | B | `test_containment_native_collision_flags_never_links` |
| three sweeps → 7 created, then 7 linked, then 7 linked; 21 append-only observations; 7 agents | B | `test_integration_rediscovery_is_idempotent` |
| removed asset → one `STALE_AGENT` finding, `control_state` unchanged, no second finding per miss, resolved on reappearance | B | `test_integration_removed_asset_is_a_stale_finding_and_reappearance_resolves_it` |
| outage / 403 → `FAILED` run, agents untouched, **no** staleness finding | B | `test_integration_outage_is_a_failed_run_never_a_deletion_or_staleness` |

## 8. The signature is over what is actually on the wire

| assertion | kind | test |
|---|---|---|
| body bytes == `httpx.Request(...).content`; signed `content-type` == httpx's; canonical path == `_build_target_url`'s output (`/agents`) | B (pinned mirrors) | `test_unit_sigv4_body_path_and_content_type_mirror_the_governed_clients_wire_bytes` |
| known answers equal botocore's `SigV4Auth` output (IAM example; Bedrock POST; Bedrock POST + session token) | KAT | `test_unit_sigv4_matches_the_aws_sdk_signer_known_answers`, `evidence/sigv4_botocore_crosscheck.txt` |
| the mock server independently recomputes SigV4 from the request **as received** on every call; `signature_failures == 0` across every integration test | B | all `test_integration_*` |

## 9. What is *not* proven here (honest scope)

- Live AWS behaviour (routing of `/agents` without the trailing slash; acceptance of the signature by AWS) — no sandbox credential was available. Mitigated by the Smithy specification and the botocore cross-check; a live read-only run is the review condition.
- Adversarial source behaviour (poisoned pages, identifier collisions across regions, oversized fields, replay of stale inventory) — that is **V8**. The 5.2 bounds it inherits are the same ones V5 exercised against the reference adapter.
