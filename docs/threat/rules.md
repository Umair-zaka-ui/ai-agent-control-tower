# Runtime threat rules (Phase 5.6 / M5.6)

The deterministic threat rule catalog lives in
[`app/threat/rules.py`](../../backend/app/threat/rules.py). Each rule is a
pure function of (runtime signals + graph evidence) over a lookback window
(default 1 hour) — no ML (`test_ac02_no_ml_import_in_threat` walks the AST).

| Rule id | Default severity | Fires when | Evidence |
| --- | --- | --- | --- |
| `behavioral_anomaly_threat` | HIGH | an ANOMALOUS `behavioral_findings` row (Phase 4.5) evaluated in the window | `behavioral_findings` |
| `governance_denial_spike` | HIGH | ≥3 STOP/DENY `runtime_governance_decisions` for this agent's executions in the window | `runtime_governance_decisions` |
| `repeated_tool_egress_denial` | HIGH | ≥3 `tool_calls` with `egress_decision='DENIED'` in the window | `tool_calls` |
| `tool_schema_validation_failure` | HIGH | ≥2 `tool_calls` with `validation_error` set in the window | `tool_calls` |
| `unapproved_mcp_tool_invoked` | **CRITICAL** | an OBSERVED `DEPENDS_ON_TOOL` dependency (Phase 5.4) onto a tool an unapproved-trust-status MCP server exposes, **actually called** in the window | `control_graph_edges`, `mcp_servers`, `tool_calls` |
| `flagged_credential_used` | WARNING | recent execution activity while holding a credential Phase 5.5 already flagged (`stale_credential`/`expired_credential_still_active`) | `posture_findings` |

`unapproved_mcp_tool_invoked` is the canonical posture-vs-threat example: 5.4/
5.5 already know the *dependency* exists; this rule asks whether it was
*used*. A rule returns `FINDING` (open/sustain) or `CLEAR` (auto-resolve any
open finding for it) — never a third "maybe": absence of the signal in the
window is a real, deterministic answer.

## Evidence gaps — recorded, not fabricated

Two rules the SRS names are **not** delivered:

- **"prompt/indirect-injection"** — there is no reason-code taxonomy for
  content-based governance denials to key a rule off; inventing one would be
  a guess dressed as a signal.
- **"cross-agent/delegation abuse"** — Phase 5.3's delegation edges are
  human↔human with no timestamped "used after revocation" evidence; there is
  nothing deterministic to detect against.

Recorded here and in ADR-0020 rather than fabricated (unknown ≠ safe, but
also ≠ a fabricated finding).

## Recommendation, not execution

A newly-opened or reopened HIGH/CRITICAL finding creates a **RECOMMENDED**
containment action (always `SUSPEND_AGENT` — the one action available
regardless of which specific tool/credential/connector is involved). Nothing
is invoked: this is the bounded half of "bounded automated containment" —
automation may suggest, never act. An operator (`containment.execute`) turns
a recommendation into a real containment by confirming it.
