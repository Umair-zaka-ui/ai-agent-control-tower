# CANARY_REGISTER — build `07a88edd` (rebuilt lab, 2026-09-19)

All tokens are synthetic and may be recorded here; none is a real secret. Every token embeds the
marker `ACTLAB-CANARY` (or a lab-shaped credential prefix) so a single grep over any artifact is
unambiguous. Tokens are regenerated on every `lab_up.py`; this table is the rebuilt lab's set and
`evidence/canaries.json` is the machine copy.

| kind | token | planted where | expected to appear in ACT? |
|---|---|---|---|
| agent_config_py | ACTLAB-CANARY-AGENT_CONFIG_PY-07a88edd-fd929a614fa7 | `lab/run/agents/python.json` (the Python agent's config) | **no** |
| agent_config_node | ACTLAB-CANARY-AGENT_CONFIG_NODE-07a88edd-65280d937b29 | `lab/run/agents/node.json` | **no** |
| agent_config_mcp | ACTLAB-CANARY-AGENT_CONFIG_MCP-07a88edd-58ae6207dc9a | `lab/run/agents/mcp.json` | **no** |
| mcp_config | ACTLAB-CANARY-MCP_CONFIG-07a88edd-086f5b4d7c19 | bearer token every MCP-zone server requires; `stdio_config.json` env | **no** |
| credential_store | ACTLAB-CANARY-CREDENTIAL_STORE-07a88edd-8a6b48fc01b3 | reserved for the V3 credential-store target (unused in V2) | **no** |
| object_store | ACTLAB-CANARY-OBJECT_STORE-07a88edd-0b5d69710678 | every object-store response (:8821) | **no** |
| mailbox | ACTLAB-CANARY-MAILBOX-07a88edd-a33c4eb78f7a | every mailbox response (:8822) | **no** |
| finance | ACTLAB-CANARY-FINANCE-07a88edd-86756b4d38e6 | every finance-tool response (:8823) — the governed capability's downstream | **no** (ACT records the dispatch outcome, not the downstream body) |
| metadata_decoy | ACTLAB-CANARY-METADATA_DECOY-07a88edd-9bae57746b65 | the cloud-metadata-shaped decoy's fake IAM credentials (:8824) | **no** |
| attacker_sim | ACTLAB-CANARY-ATTACKER_SIM-07a88edd-d3e820aea75e | the attacker-sim endpoint's response (:8825) | **no** |
| grant_label | ACTLAB-CANARY-GRANT_LABEL-07a88edd-f85c168753fc | the `label` field of each grant the harness issues | **yes, by design** — an operator-supplied label ACT must store (grant row + `EXTERNAL_GRANT_ISSUED` audit meta). It is the *proof the scan works*, not a leak |
| pii ×5 | ACTLAB-CANARY-PII-07a88edd-0001 … -0005 ("Canary Person n 07a88edd", `CAN-07a88edd-000n`, `LB00ACTLAB07a88edd…`) | `lab_payroll.employees` rows and the object-store export | **no** |
| fake credential (OpenAI-shaped) | sk-ACTLAB-07a88edd-8b8d7964f9f932fa | agent config files (`fake_credentials`) | **no** |
| fake credential (AWS-shaped) | AKIAACTLAB07A88EDD52E860A0 | agent config files | **no** |
| fake credential (bearer-shaped) | actlab_bearer_07a88edd_6eb2af0789279d5e | agent config files | **no** |

## §5 baseline-zero scan (after the full baseline run, rebuilt lab)

Scope scanned: every text/varchar/json/jsonb column of every table in `act_lab` (`information_schema`),
ACT's process log (`lab/run/logs/act.log`), the OTLP collector's captured payloads (`lab/run/otlp/`).
19 tokens checked.

| where | hits | attribution |
|---|---|---|
| `external_capability_grants.label` | 3 | grant_label — expected (the three grants) |
| `authorization_audit.meta` | 3 | grant_label — expected (`EXTERNAL_GRANT_ISSUED` ×3) |
| every other column of every table | 0 | — |
| ACT log | 0 | — |
| OTLP payloads | 0 | (no spans exported in V2; see BASELINE_OBSERVATIONS §9) |

**Baseline: zero unexpected appearances.** The only hits are the one token ACT is required to store,
which doubles as the positive control for the scan itself. The first build (`b54de795`) gave the same
result before its harness distinguished the expected grant-label hits.
