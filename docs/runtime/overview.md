# Agent Runtime & Lifecycle Management — Overview

Phase 5.0 · mounted at `/api/v1/runtime` · frontend at `/runtime`.

> **Phase 5.1 note**: the agent registry described in this doc set (§7.1,
> the 8-state lifecycle in [agent-lifecycle.md](agent-lifecycle.md)) has
> since been superseded by the full enterprise registry — accountable
> ownership, mandatory machine identity, a 13-state lifecycle, validation
> reports, duplicate detection, and import/export. See
> [registry/overview.md](registry/overview.md).

Phases 1-4 governed identities, permissions, policies, approvals and audit.
Phase 5 is the execution layer: register, version, deploy, execute, suspend,
monitor and retire real AI agents as managed enterprise workloads, under the
same governance and security controls as everything else on the platform.

> A secure, model-agnostic control plane and execution runtime for
> enterprise AI agents.

## What's here

| Doc | Covers |
|---|---|
| [architecture.md](architecture.md) | Control/execution plane split, component map, reuse decisions |
| [agent-lifecycle.md](agent-lifecycle.md) | Agent registry, `lifecycle_status` state machine |
| [versioning.md](versioning.md) | Immutable versions, checksums, semantic versioning |
| [deployments.md](deployments.md) | Environments, deployment lifecycle, RECREATE strategy, rollback |
| [executions.md](executions.md) | The Runtime Gateway, execution state machine, idempotency |
| [workers-and-queue.md](workers-and-queue.md) | The Postgres-backed queue, worker claim/lock/retry, dead-lettering |
| [capabilities-and-tools.md](capabilities-and-tools.md) | Capability/tool registries, assignment, authorization |
| [gateways.md](gateways.md) | Model Gateway and Tool Gateway adapters |
| [providers.md](providers.md) | Phase 5.7a.1 — the `ModelProvider` interface, registry, and provider-neutral internal representation |
| [runtime-policy-and-approvals.md](runtime-policy-and-approvals.md) | Runtime limits, policy evaluation, human approval |
| [health-and-observability.md](health-and-observability.md) | Heartbeats, health, telemetry, cost tracking, the dashboard |
| [operations-and-kill-switch.md](operations-and-kill-switch.md) | Operations Center, suspension, the emergency kill switch |
| [security.md](security.md) | Default deny, tenant isolation, checksum tampering, audit |

## What's deliberately not here

Deferred to later phases, per the SRS: a visual workflow builder, multi-agent
orchestration graphs, distributed event streaming at hyperscale, automated
model optimization, reinforcement learning, autonomous agent creation, a
marketplace, multi-cloud federation, a Kubernetes operator and GPU
scheduling. The data model and gateway contracts do not preclude any of
these being added later.

## Quick reference

- Every request goes through `AuthorizationGateway` (Phase 4.3.6) — the
  runtime does not have its own RBAC/ABAC engine, it calls the existing one.
- Every agent is still one row in the pre-existing `agents` table
  (Phase 1/3) — Phase 5 adds columns and hangs new tables off it, it does
  not fork a second agent registry. See [architecture.md](architecture.md).
- The execution queue *is* the `agent_executions` table — no Redis/Celery
  dependency in this environment. See [workers-and-queue.md](workers-and-queue.md).
- The model side (Phase 5.7a.1-5) executes for real: `MOCK` and
  `OPENAI_COMPATIBLE` (Ollama/vLLM/LM Studio/OpenAI) both run through a
  pluggable provider interface, with streaming, classified error
  handling/retry, and per-organization encrypted credentials. See
  [providers.md](providers.md).
- On the tool side, `FUNCTION`/`echo` and (Phase 5.6a.1) `HTTP` actually
  execute; everything else is fully modeled (registry, assignment,
  authorization) but fails closed if invoked. `HTTP` makes real outbound
  requests behind a hardened, per-tool egress allowlist — the SSRF
  containment boundary every real tool call goes through — see
  [gateways.md](gateways.md)'s "Egress control" section for the full
  defense (address validation, DNS-rebinding pinning, redirect
  re-validation, the local-dev HTTPS exception). The model-driven loop
  that lets an agent actually *call* a tool mid-execution was Phase
  5.6a.3, **since built** — `ToolLoopOrchestrator` runs the real
  model→tool→model cycle with iteration, token, wall-clock and
  repeated-call caps. This sub-phase built the execution primitive; the
  orchestration around it arrived in 5.6a.3.
- Agents can also trigger their own next run via `POST
  /runtime/executions/self`, authenticated by API key rather than a human
  session and authorized through ABAC alone (self-only, no agent-to-agent
  chaining). See [executions.md](executions.md).
