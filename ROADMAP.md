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

### Part 3.4 — Approval queue & human review workbench ✅

- Backend: enriched approval APIs — filterable queue (`GET /approvals`),
  statistics, full detail (agent/policy/risk/payload/comments), audit-derived
  timeline, plus `escalate`/`assign` actions, history and escalations boards
  (migration 0005 adds `assigned_to_user_id`/`escalation_target`/`escalated_at`,
  the `ESCALATED`/`EXPIRED` decision states and `approval.view`/`escalate`/
  `assign` RBAC codes). Org-scoped with RBAC + audit logging.
- Frontend `src/modules/approvals/`: statistics cards, filterable approval queue
  (debounced search, status/priority/risk filters, bulk approve, CSV export),
  approval details page, the review workbench (approve/reject/escalate/assign
  with validated dialogs + comment thread), recharts risk breakdown, decision
  timeline, history table and an escalations board with live SLA countdowns.
  Role-based UI gating (`approval.view/review/escalate/assign`). Vitest tests added.

### Part 3.5 — Enterprise Audit & Compliance Center ✅

- Backend: read-only, RBAC-gated audit views over the immutable `audit_logs`
  trail — enriched filterable table (`GET /audit`), statistics, recent-activity
  timeline, event-type catalog, per-event forensic detail (with related-event
  flow), a security dashboard, an informational compliance summary and an export
  feed. Severity/category/decision/status/actor are derived at read time
  (`audit_view`); no new columns. Adds the `audit.export` RBAC code and writes
  `AUTH_LOGIN`/`AUTH_LOGIN_FAILED` events on login.
- Frontend `src/modules/audit/`: audit dashboard (statistics cards, activity
  timeline, recent events), events explorer (debounced search + filters +
  server-side pagination), forensic event detail (request/response viewers +
  related-events graph), security & compliance dashboards, and an export center
  (CSV/JSON). Role-based UI gating (`audit.view` vs `audit.export`). Vitest tests
  added. See [`docs/phase-3-part-5.md`](docs/phase-3-part-5.md).

### Part 3.6 — Enterprise Analytics & AI Operations Center ✅

- Backend: read-only, RBAC-gated `/analytics/*` endpoints (overview, KPIs,
  activity, fleet-health, risk, performance, policies, review, cost, insights,
  reports) aggregating agents/agent_actions/approvals/policies/audit_logs. Real
  signals are computed; latency/cost figures are deterministic estimates
  (flagged). Adds `analytics.view` / `analytics.executive` / `analytics.operations`
  RBAC codes.
- Frontend `src/modules/analytics/`: executive overview (animated KPI grid, fleet
  health, activity chart, risk donut, insights), role-gated executive & operations
  (live feed) dashboards, risk (heatmap), performance (agent ranking), agents,
  policies, cost (estimated) dashboards, and a reports center with CSV/JSON export.
  Auto-refresh per SRS; role-based UI gating. Vitest tests added. See
  [`docs/phase-3-part-6.md`](docs/phase-3-part-6.md).

### Part 3.7+ — Remaining modules (planned)

- Per-agent policy scoping (agent↔policy assignment) and trigger history.
- Users & RBAC management; role-based navigation gating; e2e tests.

## Phase 4 — Enterprise Identity Platform

### Part 4.1 — Identity Foundation ✅

- Isolated `backend/app/identity` package (api → services → repositories →
  database). Reuses existing users/organizations/roles and adds the new identity
  entities: departments, teams, service_accounts, external_clients,
  agent_identities, sessions, refresh_tokens, device_sessions, security_events
  (migration `0006`), plus a nullable `users.department_id`.
- Domain models + lifecycle (Created→…→Deleted with validated transitions),
  repository layer (User/Role/Permission/Organization/Department/Session),
  `IdentityService`, security/permissions/roles/sessions/tokens/audit engines.
- Versioned `/api/v1/identity` API with a standard error envelope
  (`{success,error{code,message},request_id}`) and identity audit integration.
- Minimal frontend `src/modules/identity/` (directory at `/identity`) + unit +
  integration test scaffolding. See [`docs/phase-4-part-1.md`](docs/phase-4-part-1.md).

### Part 4.1a — Unified identity lifecycle ✅

- Migration `0007` adds `status` (`IdentityStatus`) to `users` and
  `organizations`, so **every** identity — human, AI agent, service account,
  organization, external client — shares one canonical lifecycle with validated,
  audited transitions (`transition_status`; humans keep `is_active` in sync).
- Agent identities, service accounts and external clients are now operable
  end-to-end (repositories + service + versioned API; client secrets shown once).
  Meets the Part 4.1 Definition of Done without caveats. Backend 80/80 green.

### Part 4.2.1 — Authentication architecture & trust model ✅

- Isolated `app/identity/auth` layer: the `IdentityContext` and the seven core
  services (Authentication/Token/RefreshToken/Credential/Session/SecurityEvent/
  IdentityContextResolver). Real login → refresh-with-rotation → reuse-detection
  → logout on the Part 4.1 session/refresh-token/security-event tables; short-
  lived (15 min) access tokens with the full claim set; an authentication
  middleware dependency (`authenticate`, JWT resolved; machine-key dispatch
  stubbed for 4.2.2).
- Auth enums (identity types, auth methods, security events), the §25 error
  codes, threat model, and a token-table migration plan (no schema change this
  part — additive tables land in 4.2.2/4.2.3). Design docs under
  [`docs/identity/`](docs/identity/). Backend 91/91 green.
- MFA/step-up assurance seam: `AuthAssuranceLevel` (AAL0/1/2), `amr` and
  `mfa_pending` on the context + token claims, `require_assurance` gate, and a
  challenge/`complete_mfa` path (verifier stubbed) so MFA is additive.

### Part 4.2.2.1 — Enterprise human authentication ✅

- `/api/v1/auth/*` endpoints on the 4.2.1 services: `login`, `refresh` (rotating),
  `logout`, `me`, `sessions` list + revoke, plus the `mfa/verify` seam.
- **argon2id** password hashing (legacy bcrypt verifies + auto-upgrades on login),
  the full password-complexity policy (`PasswordService`), and **account lockout**
  (5 failures / 15 min) driven by a new `login_history` table (migration `0008`).
- New error codes (`ACCOUNT_LOCKED`, …) + the `AUTH_LOGIN_LOCKED` event.
- Frontend: refresh-token storage, **silent refresh** (5 min pre-expiry), an axios
  401→refresh→retry interceptor and a `SessionExpiredModal`. Docs:
  [`docs/identity/human-authentication.md`](docs/identity/human-authentication.md).
  Backend 112/112 green; frontend typecheck + lint clean.

## Future (Phase 4+)

Full auth migration onto the identity platform, MFA, OAuth/SSO, refresh-token
flows, device trust, Slack/webhook notifications, observability (Prometheus /
OpenTelemetry), anomaly detection, and load testing.
