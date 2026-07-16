# Authorization Pipeline

Every protected request follows the same fixed stage order (Phase 4.3.6 §4,
§9). The order is deterministic by construction — `AuthorizationPipeline.STEPS`
is a pinned tuple, the trace service rejects out-of-order recording, and the
unit tests assert the exact sequence.

```
Incoming request
  1. AUTHENTICATION          JWT / API key verified (upstream dependency)
  2. IDENTITY_CONTEXT        account resolved, enabled, not locked
  3. SESSION_VALIDATION      session active & not revoked (N/A for workers/agents)
  4. ORGANIZATION_CONTEXT    org hierarchy path + cross-org isolation
  5. RBAC                    PermissionEngine (roles, wildcards, scope, deny-wins)
  6. RESOURCE_AUTHORIZATION  ownership / ACL / delegation / sharing / visibility
  7. ABAC                    context-aware policies (4.3.5)
  8. OBLIGATIONS             approval / MFA / justification / mask / limit
  9. AUDIT                   §24 events + decision record
 10. CACHE                   store/replay the final decision
  → business logic
```

Stages 1–3 are performed by the authentication dependencies on HTTP paths and
recorded into the trace as verified; background sources record
`SESSION_VALIDATION -` (not applicable) because no HTTP session exists — the
account itself is still validated. For *registered* resources, stage 6 embeds
the role decision (the 4.3.4 chain); for unregistered resources stage 5 decides
and stage 6 records `-`.

## Decision trace (§18)

Each evaluation carries an ordered trace — stage, status (`✓` passed, `✗`
failed/decided against, `-` not applicable) and optional detail:

```json
[
  {"stage": "AUTHENTICATION", "status": "✓", "detail": "verified upstream"},
  {"stage": "IDENTITY_CONTEXT", "status": "✓"},
  {"stage": "SESSION_VALIDATION", "status": "✓"},
  {"stage": "ORGANIZATION_CONTEXT", "status": "✓"},
  {"stage": "RBAC", "status": "✓"},
  {"stage": "RESOURCE_AUTHORIZATION", "status": "-", "detail": "unregistered resource"},
  {"stage": "ABAC", "status": "✗", "detail": "REQUIRE_APPROVAL"},
  {"stage": "OBLIGATIONS", "status": "✓"},
  {"stage": "AUDIT", "status": "✓"},
  {"stage": "CACHE", "status": "-", "detail": "dynamic context"}
]
```

The trace is stored inside the `DECISION_GENERATED` audit event, so every
decision can be replayed from its audit record.

## Failure semantics

- A stage failure short-circuits: later stages record nothing and the decision
  is a deny (default deny, §36).
- An ABAC evaluation *error* *fails closed*: the request is denied
  (`ABAC_ERROR` event, `authorization_policy_errors_total` metric) — an engine
  fault never becomes an allow.
