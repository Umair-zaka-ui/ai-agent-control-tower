# ADAPTER_TESTS — unit + integration results

**Integration target: a faithful local mock, not a live sandbox** (stated per §4 of the brief). No cloud
account or read-only credential was available to the lab; no cloud endpoint was contacted. The mock is a
real `http.server` implementing the documented `ListAgents` wire shape (`POST /agents[/]`,
`maxResults`/`nextToken`, `agentSummaries`, opaque expiring page tokens, `ValidationException` 400,
`AccessDeniedException` 403, `ThrottlingException` 429 with `Retry-After`, `UnknownOperationException`
404 for any other path, 403 for any non-POST verb) and **independently verifies AWS Signature Version 4
on every request** from the request as received. Signature failures are counted and asserted to be zero.

## Runs

| run | scope | result | evidence |
|---|---|---|---|
| 1 | `tests/discovery/` (5.2 framework suite 35 + new adapter suite 33) | **65 passed, 3 failed** — all three in the new test file, all three harness defects (below); every 5.2 framework test passed incl. the updated AC-15 guard | `evidence/discovery_suites_run1_harness_defects.txt` |
| 2 | `tests/discovery/test_aws_bedrock_agents_adapter.py` | **33 passed** in 45.56 s | `evidence/adapter_suite_run2_pass.txt` |
| 3 | full backend, twice | run 1: 2,680 passed / 1 failed / 1 deselected (the failure a verified pre-existing fixture flake — `REGRESSION.md`); **run 2 on the final tree: 2,681 passed / 0 failed / 1 deselected** | `evidence/full_backend_run1.txt`, `evidence/full_backend_run2.txt` |
| 4 | frontend + build | **384 passed** (52 files), `tsc -b` clean, `vite build` green | `evidence/frontend_tests_and_build.txt` |

## Harness defects found and fixed (test-side only; the adapter was not changed in response to any failure)

| id | defect | fix |
|---|---|---|
| HD7.5-1 | `test_unit_sigv4_matches_…` compared the signing key to a value recalled from memory (`c4afb1cc…`), which was wrong. The adapter's derivation was checked against botocore 1.43.66's `SigV4Auth` chain and found **identical** (`2c94c0cf…`) before any change. | Replaced the recalled vector with known answers produced by botocore's signer at a pinned instant (IAM example, Bedrock POST, Bedrock POST + session token); recorded in the test and in `evidence/sigv4_botocore_crosscheck.txt`. |
| HD7.5-2 | `test_structural_…_no_aws_sdk` grepped the adapter's *source text* for `boto3`; the module docstring names boto3 in prose while explaining why it is not used. Also asserted boto3 is not installed, but it is pinned for the 2.2.4 SQS backend. | The AST import allowlist is the real check; added a module-globals check (`no name starts with "boto"`); dropped the text/installed assertions. |
| HD7.5-3 | `test_unit_credential_format_…` asserted the bad input is not echoed in the error for a one-character input `":"` — trivially present in the format hint. | Echo assertion gated to inputs ≥ 8 chars; always asserts the secret and access key id are absent. |

## Test inventory (33 items)

### Unit — the 5.2 contract, configuration, credential, signing, filter, normalization (15 items)
| test | proves |
|---|---|
| `test_unit_adapter_is_registered_and_implements_the_5_2_contract` | registered; `isinstance(DiscoveryAdapter)`; `requires_secret=True`; schema requires `region`, forbids unknown keys; `fetch()` has no `Session` |
| `test_unit_adapter_listed_by_the_api_with_its_secret_requirement` | `GET /api/v1/discovery/adapters` lists it with `requires_secret` and `region` |
| `test_unit_default_endpoint_is_derived_from_the_region_and_is_the_only_allowed_host` | one derived host; other region / other host / plaintext denied offline |
| `test_unit_region_is_pattern_validated_so_the_derived_host_cannot_be_hijacked` ×6 | `evil.com/#`, `us-east-1.evil.com`, `US-EAST-1`, `us-east`, ``, `us-east-1 ` → 422 |
| `test_unit_endpoint_override_is_amazonaws_https_or_a_declared_local_dev_host_only` | FIPS ok; local declared ok; evil / lookalike / plaintext-to-AWS / undeclared local / path prefix / smuggled `allowed_hosts` / oversize page rejected |
| `test_unit_credential_format_is_parsed_and_never_echoed` | both formats parse; malformed rejected with no echo |
| `test_unit_sigv4_body_path_and_content_type_mirror_the_governed_clients_wire_bytes` | body == httpx bytes (incl. non-ASCII token); content-type == httpx's; path == executor's (`/agents`); host == httpx's |
| `test_unit_sigv4_matches_the_aws_sdk_signer_known_answers` | signing key + 3 full Authorization values == botocore's |
| `test_unit_filter_includes_bedrock_agents_and_excludes_everything_else` | every status but `DELETING` included; 17 non-agent shapes excluded |
| `test_unit_normalize_is_a_pure_deterministic_mapping` | identifier form, name, provider (≤50), description, confidence 1.00, raw carries status/version/region; non-string description dropped |

### Integration — real local server, SigV4 verified (9 items)
| test | proves |
|---|---|
| `test_integration_inventory_lands_as_external_discovered_agents` | 23 agents over 3 signed pages → 23 observations, 23 `EXTERNAL`/`DISCOVERED` agents, `GOVERNED` → 409; only `POST /agents`; zero signature failures; zero non-list calls |
| `test_integration_only_agent_constructs_are_observed_from_a_mixed_page` | KB / alias / DELETING / malformed / junk dropped; 2 real agents observed |
| `test_integration_rediscovery_is_idempotent` | 7 created → 7 linked → 7 linked; 21 append-only observations; 7 agents |
| `test_integration_removed_asset_is_a_stale_finding_and_reappearance_resolves_it` | one `STALE_AGENT`, no state change, no repeat per miss, `RESOLVED` on return |
| `test_integration_outage_is_a_failed_run_never_a_deletion_or_staleness` | connection refused → `FAILED` (`status=None`, "no HTTP response"); 403 → `FAILED` naming `bedrock:ListAgents`, body not recorded; agents untouched; no staleness |
| `test_integration_throttled_later_page_degrades_to_partial_and_resumes` | page 2 → 429 → `PARTIAL` (10 created, checkpoint token); next sweep resumes with that token → `SUCCEEDED`, 15 more |
| `test_integration_expired_resumption_token_falls_back_to_a_fresh_sweep` | resumed token rejected 400 → one fresh sweep → `SUCCEEDED` (10 linked, 2 created) |
| `test_integration_temporary_credentials_sign_the_session_token` | `x-amz-security-token` signed and sent; verified by the mock |
| `test_integration_missing_secret_is_a_failed_run_not_a_crash` | `FAILED`, zero requests sent |

### No-lock (1) · Containment (3) · Structural (5)
| test | proves |
|---|---|
| `test_no_lock_held_across_the_cloud_call_behavioral` | concurrent `FOR UPDATE` on the source row completes in < 2 s while the cloud call is held open |
| `test_containment_no_cloud_credential_in_observations_audit_runs_or_the_source_read` | no credential in observations / run errors / audit / source read; shape-scrubbing visible |
| `test_containment_tenant_scoped_a_source_only_ever_creates_agents_in_its_own_tenant` | tenant isolation both ways |
| `test_containment_native_collision_flags_never_links` | NATIVE collision → finding; native untouched |
| `test_structural_discovery_plane_only_imports_nothing_from_threat_gateway_posture_graph_or_models` | exact `app.*` import set |
| `test_structural_governed_http_client_is_the_only_network_primitive_and_no_aws_sdk` | no transport/SDK import; no `boto*` binding |
| `test_structural_read_only_exactly_one_list_operation_and_one_iam_action` | one call site; `POST`; one IAM action; no mutating literals |
| `test_structural_no_migration_no_table_no_route_was_added` | head `0061`; no bedrock/cloud/aws table or route |
| `test_structural_no_forbidden_markers_in_the_new_files` | no skip/xfail/placeholder markers |

## Pre-existing 5.2 guards now covering the new adapter automatically
- `test_ac06_adapter_fetch_signature_never_accepts_a_session` — iterates every registered adapter.
- `test_ac15_reference_adapter_distinguished_no_vendor_catalog` — updated intent-preservingly to the new exhaustive registry tuple; the other vendor keys remain banned (passed in run 1).

## Not weakened, not skipped
No test was skipped, xfailed, loosened, or deleted. The single existing-test edit is AC-15's exhaustive
tuple, which is the guard doing its job (it is *supposed* to fail when the registry changes) and is
recorded in `REGRESSION.md` as part of the scoped diff.
