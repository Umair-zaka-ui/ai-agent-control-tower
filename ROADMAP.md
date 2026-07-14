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

### Part 4.2.2.2 — Login, logout & session lifecycle ✅

The session — not the JWT — is now the source of truth. `authenticate` loads and
revalidates `auth_sessions` on **every** authenticated request, so logout, admin
force-logout, device block, idle timeout (30 min), absolute timeout (12 h) and
refresh-token-reuse termination all take effect immediately. This closes the
access-token revocation gap that ADR-0003 knowingly accepted; see
[ADR-0007](docs/architecture/adr/0007-stateful-session-validation.md).

- `auth_sessions` (states, dual deadlines, device, geo, security score) and
  `auth_devices` (fingerprint, trust posture); refresh-token **families** with
  `family_id` + `reuse_detected_at`. Migration `0009`, downgrade round-tripped.
- Four services: `SessionLifecycleService`, `SessionSecurityService`,
  `DeviceService`, `RefreshRotationService`.
- Concurrent sessions (max 5, oldest evicted), "remember me" (extends the
  *absolute* ceiling only), sliding idle window with a throttled activity write.
- Suspending or disabling an identity now revokes its live sessions
  (`ACCOUNT_DISABLED`) — previously they survived to the 12-hour ceiling.
- Endpoints: session list/detail/revoke, logout-all, device list/trust/block.
- **Administrative** session management (`session.view` / `session.revoke`,
  migration `0010`): an admin can list, inspect and force-logout any session in
  their organization, or sign a user out of every device — with the acting
  administrator recorded on the audit event. Cross-tenant access returns 404.
- All twelve SRS §26 audit events are emitted (timeouts, `SESSION_SUSPICIOUS` and
  the `IDLE`→`ACTIVE` transition were previously defined but never fired); a test
  greps the sources so an event type cannot become dead code again.
- Frontend: Settings → Security → Sessions & Devices, with confirm-before-revoke.
- **Auditable**: `security_events` gained a read path (per-org stream, per-identity
  timeline, per-session history) plus the indexes to serve it (migration `0011`). It was
  a write-only table — an audit event nobody can read is not an audit trail. Gated on
  `session.view`, *not* `audit.view`, which every role including `VIEWER` holds.
- Session/device audit UI: a user sees their own security activity; an admin sees any
  member's, and one session's full history ("who revoked it, when, and why?").
- Fixed a platform-wide defect found while verifying: the SPA's `/api/v1/auth` token was
  rejected by the legacy decoder (`Invalid audience`), so **every dashboard request 401'd**
  for real users. Both auth dependencies now accept it *and* revalidate its session, so
  revocation is immediate platform-wide rather than only on `/api/v1/auth`.
- Docs: [session-lifecycle](docs/identity/session-lifecycle.md),
  [token-rotation](docs/identity/token-rotation.md),
  [device-management](docs/identity/device-management.md),
  [security-events](docs/identity/security-events.md).
  Backend 187/187 green; frontend 123/123 green; typecheck + build clean.

### Part 4.2.2.3.1 — Enterprise registration & invitations ✅

Authentication is only half of identity. This part answers the other half: how a human
becomes a trusted identity. The enterprise default is **invitation only** — every
existing organization was migrated to `INVITE_ONLY`, because an upgrade must never
silently open public registration.

- Full lifecycle `INVITED → REGISTERED → EMAIL_PENDING → EMAIL_VERIFIED → ACTIVE`, each
  state persisted and observable. `REGISTERED` is where a user sits when SMTP fails —
  the state an operator needs to see, and what `resend-verification` retries from.
- `invitations`, `email_verifications`, `user_profiles`, `rate_limit_hits`
  (migration `0012`, downgrade round-tripped). One live invitation per (org, email),
  enforced by a **partial** unique index on PENDING rows.
- Tokens: 32 bytes of CSPRNG, SHA-256 at rest, single use, expiring (7 d / 24 h).
  Resend **rotates** — otherwise "single use" quietly becomes "N uses".
- Five services: Registration, Invitation, EmailVerification, UserProvisioning,
  RegistrationAudit. `UserProvisioningService` is the seam SSO and SCIM will use.
- **Rate limiting** (the platform's first): 5 req/min/IP on every public endpoint,
  Postgres-backed because ADR-0002 forbids a second datastore. Fixed window, and the
  docs say so.
- Enumeration-safe: `resend-verification` answers identically for unknown, pending and
  already-verified addresses.
- The login gate now says *why*: `EMAIL_NOT_VERIFIED` and `ACCOUNT_PENDING_APPROVAL`
  instead of a useless "this identity is not permitted to authenticate".
- Frontend: accept-invitation, verify-email, register, invitation-expired and
  registration-success pages, plus an admin **Invitations** panel — reachable, not just
  built. Password-strength meter mirrors the server policy without becoming a second gate.
- `notification_service.send_email` now reports delivery instead of swallowing failures,
  which is what makes `REGISTERED` vs `EMAIL_PENDING` mean anything.
- Docs: [registration](docs/identity/registration.md), [invitations](docs/identity/invitations.md),
  [email-verification](docs/identity/email-verification.md).
  Backend 230/230 green; frontend 174/174 green.

### Part 4.2.2.3.2 — Enterprise password policy & credential management ✅

The full credential lifecycle on top of argon2id: a single-source policy (length,
character classes, common-password blocklist, keyboard/number sequences, repeats, and
your own name/email/org), **password history** (no reuse of the last 10), **90-day
expiration** with in-app warnings, **administrative reset** issuing a one-time temporary
password, and a **mandatory first-login change** the app cannot be skipped past.

- `password_history` table + `users` lifecycle columns (`password_changed_at`,
  `password_expires_at`, `must_change_password`); migration `0013`.
- One write path (`CredentialService`): verify current → min-age → complexity → no-reuse
  → argon2id → history → stamp → audit → revoke other sessions.
- Endpoints: change-password, admin/reset-password, validate-password, password-policy,
  password-expiration, and the org password dashboard. 9 audit events, reachability-grepped.
- Deviations documented: reused `users.password_hash` + `security_events` rather than the
  SRS's separate credential/policy/temp/event tables. Enforcement boundary (UI/session,
  not per-endpoint) documented as a known limitation.
- Docs: [password-policy](docs/identity/password-policy.md),
  [credential-management](docs/identity/credential-management.md),
  [password-history](docs/identity/password-history.md).

### Part 4.2.2.3.3 — Password reset, account recovery & email change ✅

Enterprise recovery that reuses the platform's discipline rather than a weaker parallel.

- **Forgot password**: `rst_` tokens (256-bit, SHA-256, single-use, 30 min), a
  non-enumerating uniform response (identical for known/unknown and even on error).
- **Reset** runs the full credential write path and **revokes every session** (§13);
  dead links are 410 and say which kind of dead.
- **Verified email change**: confirm the new address before it takes effect
  (`pending_email`); alert the old mailbox on completion.
- `password_reset_requests` table + `email_verifications.purpose/new_email`; migration
  `0014`. Rate limited; recovery-events dashboard (`recovery.view`). 9 audit events.
- Docs: [password-reset](docs/identity/password-reset.md), [recovery](docs/identity/recovery.md).

### Part 4.2.2.3.4 — Account protection & risk-based authentication ✅

Authentication becomes non-binary: every login is scored and the score plus admin rules
decide allow / challenge / MFA / lock / block.

- **Risk scoring** (0–100) from signals — new device/country, impossible travel, failed
  attempts, suspicious agent, blocked IP — with a first-login baseline guard so new
  accounts are not flagged.
- **Progressive lockout** (15m → 30m → 1h → 24h → security review) on a stateful
  `account_locks` table; **brute-force & credential-stuffing** detection per
  account/IP/target-set; **blocked IPs** refused before the password; **protection rules**
  (`conditions → decision`), **adaptive rate limits**, and a **CAPTCHA** seam.
- New tables `account_locks`, `identity_risk_events`, `blocked_ips`,
  `identity_protection_rules`; `login_history` extended with the risk columns; migration
  `0015`. Generic login errors preserved (no enumeration, no signal leak).
- Security console (Settings → Security → Account protection): dashboard, login attempts,
  risk events, locks with audited unlock, blocked IPs, rules. 14 audit events,
  reachability-grepped.
- Docs: [account-protection](docs/security/account-protection.md),
  [risk-based-authentication](docs/security/risk-based-authentication.md),
  [brute-force-protection](docs/security/brute-force-protection.md),
  [account-lockout](docs/security/account-lockout.md),
  [identity-protection-rules](docs/security/identity-protection-rules.md).
  Backend 338/338 green.

### Part 4.2.2.3.5 — Backend APIs, integration & release (Phase 4.2.2 close-out) ✅

The consolidation pass over the whole Enterprise Human Authentication subsystem
(4.2.2.1 → 4.2.2.3.4): verify the §4 API contract end-to-end, close the cross-cutting
HTTP-layer gaps, and record the release contract honestly.

- **HTTP hardening**: `RequestContextMiddleware` stamps every request/response with a
  correlation id (`X-Request-ID`, generated when absent) that flows into the error
  envelope (§15); `SecurityHeadersMiddleware` applies `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, a deny-by-default `Content-Security-Policy`,
  `Permissions-Policy` and opt-in HSTS to every response, errors included (§16, §23).
- **Standard response envelope (§5)**: `ResponseEnvelopeMiddleware` wraps every 2xx JSON
  response under `/api` as `{success, data, meta:{request_id, timestamp}}` (errors already
  carry a matching envelope); the SPA unwraps it centrally so no service code changed.
  `/health`, `/openapi.json` and file exports are left untouched.
- **Full-stack deployment (§24)**: `frontend/Dockerfile` (Vite build → nginx serving the
  SPA and reverse-proxying `/api`) + `web` service in `docker-compose.yml` (web + api + db,
  same-origin), with a release checklist in [deployment](docs/deployment.md).
- **Contract verified**: every §4 capability is implemented; the only remaining deviation
  is stable path placement (invitation/password/admin routes under `/identity` &
  `/security`). No unreachable `logout-all` / `device-delete` stubs.
- New `app/core/middleware.py`; `SECURITY_*` + `REQUEST_ID_HEADER` +
  `RESPONSE_ENVELOPE_ENABLED` settings; 11 new tests. Backend **352/352** green; frontend
  tsc + build clean; web Docker image builds.
- Docs: [http-conventions](docs/api/http-conventions.md), [testing](docs/testing/strategy.md),
  [deployment](docs/deployment.md), `CHANGELOG.md`.

## Phase 4.3 — Enterprise Authorization Platform 🚧

RBAC + ABAC + policy engine: centralized, auditable authorization for every request.

### Part 4.3.1 — Enterprise RBAC foundation ✅

Turns the flat Phase-1 RBAC into an enterprise foundation **by extension, not
replacement** — the existing `roles`/`rbac_permissions`/`user_roles` tables gain columns
and everything that already resolves permissions keeps working.

- **Roles** gain category (SYSTEM/CUSTOM/ORGANIZATION/PROJECT/RESOURCE), lifecycle status,
  `priority` (conflict resolution), `is_assignable` and audit columns; **permissions**
  gain a domain **group**, `resource_type`/`action` split and `is_system`.
- **Scoped assignments**: `user_roles` carries scope + org/department/team/project/
  resource targets and `expires_at` (time-boxed). **Role hierarchy** (`role_hierarchy`):
  a senior role inherits its descendants' permissions, kept acyclic by cycle detection.
- **18 built-in roles** (Platform / AI Ops / Organization / read-only) seeded globally
  with priorities + hierarchy, alongside the legacy four. **Authorization audit** table
  records every change and (from 4.3.2) every decision.
- New `app/authorization/` package (enums, catalog, repositories, services, schemas,
  routes) + migration `0016`; 15+ endpoints under `/api/v1` (`roles`, `permissions`,
  `permission-groups`, `role-assignments`, `role-hierarchy`, `authorization/audit`),
  permission-gated (`role.view`/`role.manage`/`role.assign`).
- Admin portal (Settings → Security → Authorization): Roles, Permissions, Permission
  groups, Assignments, Hierarchy, Audit. Backend **383** green (31 new); frontend **221**
  green (4 new); tsc + build clean.
- Docs: [rbac](docs/authorization/rbac.md), [roles](docs/authorization/roles.md),
  [permissions](docs/authorization/permissions.md),
  [role-hierarchy](docs/authorization/role-hierarchy.md).

### Part 4.3.2 — Enterprise Permission Engine ✅

Every authorization decision now flows through one centralized, cached engine — no
controller branches on role names.

- **Engine** (`app/authorization/engine.py`): small pure resolvers — Role (assigned +
  inherited via hierarchy), Permission (grant list = legacy fallback + scoped role
  grants), **Wildcard** (`resource.*` and the reserved global `*`), **Scope**
  (global→resource), **Conflict** (**explicit deny wins**, else allow, else default deny).
  Returns a structured `{allowed, reason, scope, source_role}`.
- **Cache**: resolved grants cached per identity in `permission_cache`, tagged with a
  per-org `permission_versions` counter; any role/permission/assignment change bumps the
  version and invalidates immediately (Postgres, ADR-0002). `role_permissions.effect`
  adds explicit DENY grants. Migration `0017`.
- **Centralization**: `require_permission` gates through the engine platform-wide (all
  408 existing checks unchanged — a faithful superset); `POST /api/v1/authorization/check`
  evaluates the caller's access with `evaluation_time_ms` + `cache_hit`; decisions are
  audited to `authorization_decisions` (denials always; allows opt-in).
- **Frontend**: `PermissionProvider`, `usePermissions`/`useCan`, `ProtectedComponent` /
  `RequirePermission` — wildcard-aware, server remains source of truth.
- Docs: [permission-engine](docs/authorization/permission-engine.md),
  [permission-resolution](docs/authorization/permission-resolution.md),
  [wildcards](docs/authorization/wildcards.md), [scopes](docs/authorization/scopes.md),
  [caching](docs/authorization/caching.md). Backend **408** green (25 new); frontend
  **232** green (8 new); tsc + build clean.

Next: 4.3.5 ABAC, 4.3.6 middleware, 4.3.7 portal, 4.3.8 production readiness.

### Part 4.3.3 — Enterprise organization hierarchy ✅

Authorization is now evaluated within the full enterprise structure — Platform →
Organization → Business Unit → Department → Team → Project → Resources — extending the
existing `organizations`/`departments`/`teams` in place.

- **Schema** (migration `0018`): new `business_units`, `projects`, `resource_ownership`,
  `delegations`; `organizations` +slug/owner, `departments` +business_unit/status,
  `teams` +status.
- **Services**: entity CRUD (org/BU/dept/team/project) with parent validation and
  child-deletion guards; `HierarchyResolverService` (parent chain / descendants / path);
  `ResourceOwnershipService` (assign/transfer/resolve); `OrganizationHierarchyService`
  (tree); `DelegationService` (delegate/revoke with boundary enforcement).
- **Engine integration (§14)**: a resource's ownership path is resolved into the check's
  `ResourceContext`, so a scoped grant applies via **downward inheritance**; **cross-org
  isolation (§9)** denies foreign-org resources unless the caller holds `*` or a delegation.
- 20+ `/api/v1` endpoints (organizations, business-units, departments, teams, projects,
  hierarchy/tree, resource-ownership, delegations) gated `organization.view`/`.manage`;
  10 audit events; new error codes (`CROSS_ORG_FORBIDDEN`, `ENTITY_HAS_CHILDREN`,
  `DELEGATION_EXCEEDS_AUTHORITY`, …).
- Admin portal (Settings → Security → Organization): Hierarchy explorer (searchable tree),
  Business units, Departments, Teams, Projects, Delegation. Backend **421** green (8 new);
  frontend **235** green (3 new).
- Docs: [organization-hierarchy](docs/authorization/organization-hierarchy.md),
  [hierarchy-resolution](docs/authorization/hierarchy-resolution.md),
  [resource-ownership](docs/authorization/resource-ownership.md),
  [delegated-administration](docs/authorization/delegated-administration.md).

### Part 4.3.4 — Enterprise resource-based authorization (RBAC + Resource ACL) ✅

Every managed object is now a first-class protected resource; access decisions layer
ownership, ACLs, delegation, sharing, visibility and resource policy over the role
decision — users with identical roles get different answers per resource.

- **Schema** (migration `0019`): `resources` (registry: owner + owner_type, visibility,
  status, JSONB policy), `resource_acl` (per-principal ALLOW/DENY with expiry),
  `resource_shares` (READ→MANAGE with expiry), `ownership_history` (transfers preserved),
  `resource_delegations` (time-boxed, revocable).
- **Services** (`app/authorization/resources/`): `ResourceAuthorizationService` runs the
  §5/§18 chain — identity → org scope → roles → **explicit deny** → policy → ownership →
  ACL allow → delegation → sharing → role allow → visibility → **default deny**;
  plus registry, ACL, sharing, ownership(+history), delegation, policy services and a
  `MembershipResolver` (user/role/team/department/org principals).
- **Engine integration (§18)**: `POST /api/v1/authorization/check` routes *registered*
  resources through the full resource chain; unregistered resources keep the 4.3.2/4.3.3
  path. Owners cannot bypass global denies; a DENY never binds a platform admin on
  SYSTEM resources (§22).
- 20 `/api/v1/resources` endpoints (registry, owner/transfer-ownership/history, acl,
  share, delegate, policy, authorize with identity simulation); 14 audit events
  (`RESOURCE_SHARED`, `RESOURCE_OWNER_CHANGED`, `RESOURCE_ACL_*`, `RESOURCE_DELEGATED`,
  `RESOURCE_ACCESS_GRANTED/DENIED`, …); 9 error codes (`RESOURCE_ACCESS_DENIED`,
  `OWNER_TRANSFER_NOT_ALLOWED`, `CROSS_ORGANIZATION_ACCESS_DENIED`, `DELEGATION_EXPIRED`,
  …); permissions `resource.view` / `resource.manage`.
- Admin portal (Settings → Security → Resources): Resource permissions (registry +
  visibility), ACL (search/filter, effect toggle), Sharing, Ownership transfer (+history),
  Delegation, and the **Authorization Inspector** (simulate identity × resource ×
  permission → ALLOW/DENY with reason, source, owner, visibility, steps).
- Docs: [resource-authorization](docs/authorization/resource-authorization.md),
  [resource-acl](docs/authorization/resource-acl.md),
  [resource-sharing](docs/authorization/resource-sharing.md),
  [delegation](docs/authorization/delegation.md),
  [resource-ownership](docs/authorization/resource-ownership.md) (updated); ERD updated.
  Backend **442** green (21 new); frontend **242** green (7 new); tsc + build clean.

## Future (Phase 4+)

Retiring the legacy `/auth/login` surface (now the platform's only non-revocable
credential), MFA, OAuth/SSO, enterprise IdPs, Slack/webhook notifications,
observability (Prometheus / OpenTelemetry), anomaly detection, and load testing.
