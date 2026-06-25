# AI Agent Control Tower — Roadmap

## Phase 1 — Backend MVP ✅

FastAPI + PostgreSQL control plane: agents, permissions, deterministic risk
scoring, allow/block/approval decisions, approval queue and immutable audit
logs. JWT auth.

## Phase 2 — Production-oriented platform ✅

Agent API-key auth, database-driven policy engine, advanced RBAC, approval
queue enhancements (priority/SLA/comments), email notifications, forensic
audit, dashboard APIs, risk engine v2 and Docker. 33 tests green.

## Phase 3 — Enterprise Dashboard UI 🚧

A modern React + TypeScript web interface (`frontend/`) consuming the Phase 1/2
APIs. Dark, enterprise design language (Azure / Datadog / Stripe / Linear feel).

### Part 1 — Scaffold & app shell ✅ (this branch)

- React 19 + TypeScript (strict) on Vite.
- TailwindCSS dark theme with the SRS palette as semantic tokens; Inter font.
- shadcn/ui primitives, Recharts, TanStack Query, Axios, React Router v7,
  React Hook Form + Zod, Lucide, Sonner, Framer Motion.
- Folder structure per SRS (components / layouts / pages / hooks / contexts /
  services / types / utils / constants / routes / config).
- Base dashboard layout: sidebar + top navigation, mobile-responsive.
- Auth layout + login page (RHF + Zod) wired to an Auth context; route guards.
- Service layer for every backend resource; typed domain models; data hooks.
- Coding standards documented; project builds and runs with `npm run dev`.

### Part 2+ — Feature build-out (planned)

- Dashboard data wiring (summary KPIs, recent/high-risk actions, approvals).
- Agents management (table, status controls, API-key issuance).
- Policy authoring (list, condition builder, priorities).
- Approval queue (review/approve/reject, comments, SLA).
- Audit timeline (filters, entity drill-down, export).
- Analytics (risk distributions, decision breakdowns).
- Users & RBAC management.
- Role-based navigation gating, route-level code splitting, e2e tests.

## Future (Phase 4+)

Real action execution & callbacks, Slack/webhook notifications, policy
versioning & simulation, API-key rotation, observability (Prometheus /
OpenTelemetry), anomaly detection, multi-tenant isolation & load testing.
