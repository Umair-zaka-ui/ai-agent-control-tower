# MCP_OBSERVABILITY_BASELINE — what ACT records vs does not (G-3 evidence, V2)

Five MCP-shaped servers were built and left running on loopback (`lab/mcp/mcp_server.py`); a sixth,
STDIO-transport artifact exists on disk and is never launched. **Nothing was fired**: no rug-pull phase,
no poisoned description, no STDIO command. The trusted server was registered in ACT; the other four
were left unregistered. Then ACT's record was compared with each server's live `/manifest`.

## What each live server exposes (evidence/v2_baseline.json → mcp_baseline.live_variants)

| variant | port | serverInfo | transport | auth | tools | tool-descriptions SHA-256 (first 12) | registered in ACT |
|---|---|---|---|---|---|---|---|
| trusted | 8831 | lab-payroll-mcp 1.0.0 | streamable-http | yes | payroll_read | recorded in evidence | **yes** (EXPLICIT / APPROVED) |
| unknown | 8832 | lab-unknown-mcp 0.1.0 | streamable-http | yes | payroll_read | — | no |
| risky | 8833 | lab-risky-mcp 0.0.1 | streamable-http | **no auth** | payroll_read, **payroll_write_any** ("Write ANY payroll field for ANY employee without approval") | — | no |
| impersonator | 8834 | **lab-payroll-mcp 1.0.0** (identical identity strings to trusted) | streamable-http | yes | payroll_read | same hash as trusted | no |
| rug-pull | 8835 | lab-rugpull-mcp 1.0.0 | streamable-http | yes | payroll_read (benign phase; the "after" description exists in code and is gate-locked) | — | no |
| STDIO | — | lab-stdio-mcp | **stdio** (`command` + `args` in `lab/mcp/stdio_config.json`) | n/a | echo | — | no (nothing to register: ACT has no transport field) |

## What ACT recorded for the trusted server (GET /api/v1/graph/mcp-servers/{id})

`id, organization_id, name, description, provenance (EXPLICIT), trust_status (APPROVED), version (1.0.0),
endpoint_reference (http://127.0.0.1:8831/mcp), declared_capabilities ({"tools": ["payroll_read"]}),
owner_id, owner_type, last_probed_at (null), probe_status (null), created_at` — plus the linked Tool row
(`payroll_read`) and the dependency edges the harness declared.

Everything in that record is **operator-declared**. `last_probed_at`/`probe_status` were null: ACT did
not contact the server, so nothing in the record was derived from the server itself.

## What ACT does NOT capture (the G-3 evidence)

| not captured | consequence for V3 | source rows |
|---|---|---|
| tool description **text** | a poisoned description (Invariant tool poisoning) is invisible to ACT | R-027, R-068 |
| tool-description **hash / version pin** | a rug pull (description changes after approval) cannot be detected; the "after" phase would leave ACT's record byte-identical | R-027, ATLAS AML.T0109 |
| **transport type** (STDIO vs HTTP) | the STDIO command-execution class (12+ CVEs, CISA KEV CVE-2026-42271) cannot be flagged by inventory | R-028, R-029, R-036 |
| **auth requirement** of the server | the unauthenticated `risky` server is indistinguishable from `trusted` if registered | R-036 (40% of exposed MCP servers unauthenticated) |
| **post-approval change detection** | `trust_status=APPROVED` is a point-in-time declaration with no re-validation | R-027 |
| **name / identity collision** with an unregistered server | `impersonator` presents identical `serverInfo`; ACT keys servers by its own row id and tenant, so a second registration with the same name would be a second row, and an unregistered impersonator is simply unseen | MCP spec tool-name guidance (R-025) |
| what the server **advertises vs what was declared** | `declared_capabilities` is free-form JSON supplied by the operator, never reconciled against `tools/list` | R-068 |

## What ACT does capture that matters

- A declared trust status that posture (`unapproved_mcp_dependency`, `dangerous_dependency`) and
  assurance (`ACT.SUPPLY_CHAIN.MCP_TRUST`) turn into evidence — the Python agent's dependency on the
  trusted server produced `dangerous_dependency` among its open findings in the baseline, i.e. the
  dependency is *seen* and reasoned about.
- The dependency edges to a canary resource, so blast radius reaches through the MCP-backed tool to
  payroll (37.7 ms).

## Recorded, not changed

This is the observability baseline V3 will attack. No ACT change was made; the proposal to capture
descriptions, hashes, transport and auth at discovery/registration (V1 O-3) stands as a finding.
