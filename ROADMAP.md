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

### Part 2 — Authentication & app shell ✅

- JWT login (React Hook Form + Zod) wired to the backend; token storage.
- Axios client attaches the token and redirects to `/login` on 401.
- `AuthContext`, `ProtectedRoute`/`PublicRoute`, sidebar + top navbar, logout.

### Part 3.1 — Live dashboard & data integration ✅

- Six KPI cards, agent-activity + 30-day risk-trend charts (Recharts, lazy),
  pending-approval queue (inline approve/reject), recent actions, recent audit
  logs and a system-health widget — all live from the backend.
- TanStack Query auto-refresh every 60s + manual refresh; skeleton/error/empty
  states; route-level code splitting for charts.
- New backend endpoints: `/dashboard/activity`, `/dashboard/risk-trend`,
  `/system/health`, plus `today_actions` on `/dashboard/summary`.
- Vitest unit/component tests added.

### Part 3.2a — Agent management module ✅

- Backend: agent metadata fields (owner, department, version, capabilities,
  risk config), ARCHIVED/BLOCKED statuses (migration 0003), paginated/searchable
  list, `PUT`/`DELETE`/`/stats` endpoints. Fixed a Part 3.1 timezone bug.
- Frontend `src/modules/agents/`: server-driven table (debounced search,
  filters, sort, pagination, CSV/JSON export, row actions), 5-step Create wizard
  with one-time API-key reveal, Details (Overview + live stats), Edit form,
  expandable sidebar group. Vitest tests added.

### Part 3.2b — Agent module, continued (planned)

- Activity timeline, API-key rotation/management, permission matrix, agent↔policy
  assignment (new join table), bulk actions, the remaining details tabs.

### Part 3.3 — Policy management module ✅

- Backend: policy lifecycle fields (priority, severity, status, trigger
  counters), `enable`/`disable`/`test`/`audit` endpoints and built-in policy
  templates (migration 0004). Org-scoped CRUD with RBAC + audit logging.
- Frontend `src/modules/policies/`: enterprise policy table (debounced search,
  status/decision/severity/resource filters, CSV export, row actions), 6-step
  policy builder with a JSON condition editor + live plain-English preview,
  Details page (Overview, Conditions, Audit timeline, Settings/danger zone),
  Edit form, Test/simulation panel and a template gallery. Role-based UI gating
  (ADMIN/SUPER_ADMIN manage, REVIEWER tests, others view). Vitest tests added.

### Part 3.4+ — Remaining modules (planned)

- Per-agent policy scoping (agent↔policy assignment) and trigger history.
- Approval queue page (comments, SLA), audit timeline, analytics.
- Users & RBAC management; role-based navigation gating; e2e tests.

## Future (Phase 4+)

Real action execution & callbacks, Slack/webhook notifications, policy
versioning & simulation, API-key rotation, observability (Prometheus /
OpenTelemetry), anomaly detection, multi-tenant isolation & load testing.
