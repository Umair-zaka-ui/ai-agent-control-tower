# Obligations

Obligations modify execution; they never replace authorization (Phase 4.3.6
§16). The ABAC engine attaches them to a decision; the middleware's
`ObligationExecutor` turns them into concrete enforcement outcomes; the
enforcement point honours them.

## Supported obligations

| Obligation | Origin (policy effect) | Enforcement |
| --- | --- | --- |
| `CREATE_APPROVAL` | `REQUIRE_APPROVAL` | Route into the Human Review Workbench (agent actions land in the approval queue automatically); the request is blocked until approved |
| `REQUIRE_MFA` | `REQUIRE_MFA` | Typed `MFA_REQUIRED` error → the SPA launches the MFA challenge |
| `REQUIRE_JUSTIFICATION` | `REQUIRE_JUSTIFICATION` | Typed `JUSTIFICATION_REQUIRED` error → the SPA collects a reason; retrying with `X-Justification` satisfies the challenge and the justification is audited |
| `MASK_FIELDS` | `MASK_FIELDS` | `ObligationExecutor.mask_fields(payload, fields)` — recursive, non-destructive redaction; the SPA renders `***` |
| `LIMIT_ACTION` | `LIMIT_ACTION` | `ObligationExecutor.apply_limits(params, limits)` clamps known parameters (`limit_rows`, `limit_tokens`, `limit_cost`, `maximum_export_rows`, `limit_export`, `target_count`); unknown limits pass through under `_limits` |
| `NOTIFY_SECURITY` | any (extra obligation) | Emits a `SECURITY_NOTIFICATION` audit event immediately |
| `LOG_ONLY` | `LOG_ONLY` | Observation only — never changes the decision |

## Rules

- A **deny renders challenge/constraint obligations moot** — only `LOG_ONLY`
  observations survive a deny (4.3.5 §14).
- Challenge decisions (`REQUIRE_*`) are **never cached**: approval state, MFA
  state and justifications are per-request.
- Every applied obligation is audited (`OBLIGATIONS_APPLIED`, §24).

## Frontend behaviors (§33)

`decisionToUi(decision)` maps the gateway decision to what the SPA does:

| Decision | UI |
| --- | --- |
| `ALLOW` | continue |
| `DENY` | access-denied state (`AuthorizationErrorBoundary` catches unhandled ones) |
| `REQUIRE_APPROVAL` | `ApprovalRequiredDialog` → link to the approval queue |
| `REQUIRE_MFA` | `MFAChallenge` |
| `REQUIRE_JUSTIFICATION` | `ObligationDialog` collects the reason |
| `MASK_FIELDS` | render redacted (`maskFields(data, fields)`) |
| `LIMIT_ACTION` | restrict the UI capability (`actionLimits(obligations)`) |
