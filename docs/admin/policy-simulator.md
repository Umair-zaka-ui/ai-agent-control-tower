# Policy Simulator

Phase 4.3.7 §12. What-if evaluation of the full authorization stack without
modifying production state or executing the action.

## Inputs

Identity (any user in the organization), action/permission, an optional
registered resource, attribute overrides (environment, device, AI signals)
and an optional inline draft policy.

## Outputs

- Baseline RBAC result,
- resource authorization result (when a resource is named),
- ABAC evaluation: matched policies, per-condition trace, obligations,
- the final decision and evaluation time.

## Surfaces

- **Portal page**: `/authorization/abac/simulator` (Phase 4.3.5).
- **Portal API**: `POST /api/v1/admin/policy-simulator` (gated
  `admin.simulator.use`) — same read-only semantics; every run emits a
  `SIMULATION_EXECUTED` audit event (§22) alongside the ABAC engine's own
  `ABAC_POLICY_SIMULATED`.

Simulation never enforces: nothing is recorded as a live decision and no
obligation is executed.
