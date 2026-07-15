# ABAC policy simulation (Phase 4.3.5 §35)

The simulator answers "what would happen if…" **without executing anything**
and without recording a live access decision — only an `ABAC_POLICY_SIMULATED`
audit event.

## Inputs

Identity (self or, for admins, any org member), action, optional resource,
and attribute overrides — including `identity.*` (the one path where subject
overrides are honored; live evaluation drops them). Gated by
`authorization.abac.simulate`.

## Endpoints

```
POST /api/v1/authorization/abac/simulate                # full stack, optional inline draft policy
POST /api/v1/authorization/abac/policies/{id}/simulate  # one stored policy in isolation (drafts too)
```

## Outputs

- **Baseline RBAC decision** — what the Permission Engine says.
- **Resource authorization decision** — when a resource is named (4.3.4 chain).
- **ABAC decision** — matched policies, per-condition results (the condition
  evaluation tree with pass/fail and missing-attribute flags), winning effect,
  obligations, evaluation time.

The per-policy variant is how a draft is tested before publishing: build →
simulate → validate → publish. The UI (Settings → Security → Context policies →
Simulator) renders each condition with a pass/fail marker and the full
decision breakdown.
