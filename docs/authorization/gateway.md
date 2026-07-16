# Authorization Gateway

The single coordination point for every authorization subsystem (Phase 4.3.6
§21, §22). Internal modules call the gateway; **nothing calls RBAC, resource
authorization or ABAC directly**.

## API

```python
from app.authorization.middleware.gateway import AuthorizationGateway

gateway = AuthorizationGateway(db)

# Users (REST dependency, explicit checks, admin surfaces)
decision = gateway.authorize(
    user, "dataset.export",
    resource_type="DATASET", resource_id=dataset_id,
    context={"action.target_count": 20000},   # dynamic ABAC context
    ip_address=…, request_id=…, correlation_id=…,
    justification=…,                          # satisfies REQUIRE_JUSTIFICATION
)

# Background principals — workers, schedulers, workflow nodes (§28, §30)
decision = gateway.authorize_background(
    principal_id, "report.generate", source="WORKER", job_name="nightly-report",
)

# Agent principals — AI runtime, API-key integrations (§29, §31)
decision = gateway.authorize_agent(
    agent, "claim.read", ai_context={"ai.autonomy_level": "AUTONOMOUS"},
)

# Post-execution hook (§24)
gateway.execution_completed(decision, outcome="EXECUTED")
```

## The decision object (§17)

```json
{
  "allowed": false,
  "decision": "REQUIRE_APPROVAL",
  "reason": "Policy 'High-risk autonomous actions' requires human approval.",
  "permission": "agent.execute",
  "matched_policies": [{"policy_id": "…", "name": "…", "effect": "…", "priority": 100}],
  "obligations": [{"type": "CREATE_APPROVAL", "priority": "CRITICAL"}],
  "pipeline_trace": [{"stage": "RBAC", "status": "✓"}, …],
  "request_id": "…",
  "evaluation_time_ms": 7.1,
  "cache_hit": false
}
```

`obligation_outcome` (an `ObligationOutcome`) accompanies the decision in
process: challenge flags, masked fields, parameter clamps.

## Decision cache

Keyed by identity × permission × resource × organization × **RBAC cache
version** × **ABAC policy generation**, with a short TTL and an identity epoch:

| Trigger (§19) | Mechanism |
| --- | --- |
| Role / assignment / permission change | RBAC version bumps → key rotates |
| Policy / attribute-definition change | ABAC generation bumps → key rotates |
| Organization change | RBAC version bump (org-scoped) |
| Session revoked | identity epoch bump → all entries for that identity die |
| Time-based attributes | short TTL; challenge decisions and dynamic-context evaluations are never cached |

## Audit (§24)

Uncached evaluations emit `AUTHORIZATION_STARTED`, `DECISION_GENERATED` (with
the pipeline trace), `OBLIGATIONS_APPLIED` (when any), and
`AUTHORIZATION_COMPLETED` or `AUTHORIZATION_FAILED`. Enforcement points report
`EXECUTION_COMPLETED` after the business action. Cache hits replay an
already-audited decision and are not re-audited. Denials are additionally
recorded in `authorization_decisions` (4.3.2 §20).
