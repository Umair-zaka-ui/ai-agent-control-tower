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

### Part 4.3.5 — Attribute-Based Access Control engine (ABAC) ✅

Authorization is now **context-aware**: after RBAC, the org hierarchy and the resource
chain say *allow*, the ABAC engine decides whether the action is safe **right now** —
considering identity, resource sensitivity (PII/PHI), action, environment (network zone,
device trust, business hours, risk score) and AI-specific attributes (autonomy level,
model, tool risk). ABAC can never grant what the baseline denied.

- **Schema** (migration `0020`): `abac_policies` (versioned + lifecycle DRAFT →
  VALIDATED → ACTIVE → DISABLED/DEPRECATED/ARCHIVED; NULL org = platform policy),
  `abac_policy_versions` (immutable snapshots), `attribute_definitions` (the registry —
  only registered attributes may be used), `abac_evaluations`, `abac_policy_exceptions`
  (time-boxed, auto-expiring).
- **Engine** (`app/authorization/abac/`): five attribute providers
  (subject/resource/action/environment/AI) → normalized context; 16 safe operators
  (typed, ReDoS-guarded, no dynamic code); nested ALL/ANY/NOT condition trees with
  per-condition traces; scope + target policy resolution (org hierarchy aware, per-org
  cached); five combining algorithms (default `DENY_OVERRIDES`: deny → approval → MFA →
  justification → mask/limit → allow); obligations (CREATE_APPROVAL, REQUIRE_MFA,
  REQUIRE_JUSTIFICATION, MASK_FIELDS, LIMIT_ACTION, LOG_ONLY); explainable decisions
  with RESTRICTED values redacted; §43 metrics.
- **Integration (§25)**: `POST /api/v1/authorization/check` runs RBAC → org scope →
  resource chain → ABAC and returns one normalized decision (`decision` +
  `obligations`); baseline deny is final; no applicable policy → baseline stands;
  callers can never spoof `identity.*` attributes.
- 26 `/api/v1/authorization` endpoints: policy CRUD + validate/publish/disable/archive/
  clone, versions + rollback, read-only simulation (stack-wide & single-policy),
  evaluate, evaluation log, metrics, attribute catalog, exceptions. 10 permissions
  (author/publisher separable), 17 audit events, 13 error codes.
- Admin portal (Settings → Security → Context policies): policy list/details/versions,
  **visual policy builder** (nested condition groups, typed values, human-readable
  preview, raw JSON), **Policy Simulator** (never executes the action), attribute
  catalog, evaluation viewer, exceptions.
- Docs: [overview](docs/authorization/abac/overview.md),
  [policy-language](docs/authorization/abac/policy-language.md),
  [attributes](docs/authorization/abac/attributes.md),
  [operators](docs/authorization/abac/operators.md),
  [combining-algorithms](docs/authorization/abac/combining-algorithms.md),
  [policy-lifecycle](docs/authorization/abac/policy-lifecycle.md),
  [policy-simulation](docs/authorization/abac/policy-simulation.md),
  [security](docs/authorization/abac/security.md); ERD updated.
  Backend **471** green (29 new); frontend **249** green (7 new); tsc + build clean.

Next: 4.3.6 authorization middleware, 4.3.7 admin portal, 4.3.8 production readiness.

### Part 4.3.6 — Enterprise authorization middleware & enforcement architecture ✅

Every protected operation now flows through **one enforcement pipeline** — REST
routes, the explicit check endpoint, background workers, scheduled jobs, workflow
nodes, the AI agent runtime and API-key integrations. No controller, service, agent
or job performs independent authorization checks.

- **Gateway** (`app/authorization/middleware/`): `AuthorizationGateway.authorize /
  authorize_background / authorize_agent` coordinates RBAC, org hierarchy, resource
  authorization, ABAC, obligations, audit, caching and metrics behind one call and
  returns one normalized decision (§17) with a stage-by-stage pipeline trace (§18).
  The ten-stage order (§9) is pinned and order-enforced. Baseline deny is final;
  ABAC errors fail closed.
- **Context** (§5): immutable `AuthorizationContext` (frozen dataclass, read-only
  mappings, append-only trace) built only by the `AuthorizationContextBuilder`;
  caller attributes can never spoof `identity.*`.
- **Decision cache** (§19, §23): identity × permission × resource × org ×
  RBAC-version × ABAC-generation keys + TTL + per-identity epoch — role changes,
  policy changes, org changes and session revocation invalidate instantly;
  challenges and dynamic contexts are never cached. Warm path <5ms.
- **Enforcement** (§27–§31): `require_permission` runs the pipeline on every route
  (challenges → typed errors `APPROVAL_REQUIRED` / `MFA_REQUIRED` /
  `JUSTIFICATION_REQUIRED`, the latter satisfiable in-band via `X-Justification`;
  constraints ride on `request.state.authorization`); the agent runtime layers ABAC
  over the Phase-2 governance baseline (deny → BLOCK, approval → the human-review
  queue); workers/schedulers/workflow nodes use `authorize_background`.
- **Obligations** (§16): approval routing, MFA, justification, recursive field
  masking, parameter clamping (rows/tokens/cost/export), security notification,
  LOG_ONLY — obligations modify execution, never replace authorization.
- **Audit & observability** (§24, §34, §35): six pipeline events incl.
  `DECISION_GENERATED` (with the full trace) and `EXECUTION_COMPLETED`;
  `GET /api/v1/authorization/middleware/metrics` (requests, denies, challenges,
  latency avg/p95, cache hit ratio, pipeline errors).
- **Frontend** (§32, §33): `AuthorizationProvider` (decision/error → dialog
  routing), `ApprovalRequiredDialog`, `MFAChallenge`, `ObligationDialog`,
  `AuthorizationErrorBoundary`, `PermissionGuard`, `useAuthorize`,
  `decisionToUi` / `maskFields` / `actionLimits`.
- Also fixed a concurrent get-or-create race in the permission-version bootstrap.
- Docs: [middleware](docs/authorization/middleware.md),
  [pipeline](docs/authorization/pipeline.md),
  [obligations](docs/authorization/obligations.md),
  [context](docs/authorization/context.md),
  [gateway](docs/authorization/gateway.md).
  Backend **518** green (47 new: 21 unit, 22 integration/security, 4 perf);
  frontend **259** green (10 new); tsc + build clean.

Next: 4.3.7 authorization admin portal, 4.3.8 production readiness.

### Part 4.3.7 — Enterprise authorization administration portal ✅

One web control plane for the whole authorization platform. The portal unifies
the 4.3.1–4.3.6 surfaces (roles, hierarchy, resources, ABAC builder/simulator,
audit) behind a permission-aware navigation and adds the operational pages that
were missing: dashboard, decision explorer, access reviews and analytics.

- **Admin API** (`app/authorization/admin/`, §18): 20 `/api/v1/admin` endpoints
  delegating to the existing phase services — dashboard, roles CRUD, permission
  catalog, organization tree, resource registry, ABAC policy CRUD, policy
  simulator (audited `SIMULATION_EXECUTED`, read-only), decision explorer,
  access reviews, analytics. Gated by 10 new separable `admin.*` permissions
  (§21); enforced through the 4.3.6 gateway like every route.
- **Dashboard** (§6): 12 widgets + 5 charts, tenant-scoped, <2 s (§24, tested).
- **Access reviews** (§14; migration `0021`): DRAFT → SCHEDULED → ACTIVE →
  COMPLETED → ARCHIVED; activation snapshots in-scope role assignments;
  certify/revoke per item with comments — **revoke removes the live assignment**
  via the RBAC service; completion blocked while items are pending; JSON report
  export; 6 audit events; lifecycle guards return 409.
- **Decision explorer** (§13): filterable tenant-isolated decision history with
  reasons/scope/latency/request-id detail; every view audited
  (`DECISION_VIEWED`).
- **Security analytics** (§17): denied trends, high-risk decisions, MFA and
  approval rates, latency avg/p95, cache performance, ABAC deny/challenge
  counters, top denied permissions, sharing trends.
- **Frontend** (`modules/admin`): AdminDashboardPage, DecisionExplorerPage,
  AccessReviewsPage, SecurityAnalyticsPage + `AdminNav` (§5 navigation across
  every authorization surface, permission-filtered); `/admin/*` routes; portal
  card in Settings → Security.
- Docs: [dashboard](docs/admin/dashboard.md), [roles](docs/admin/roles.md),
  [organization-explorer](docs/admin/organization-explorer.md),
  [resource-management](docs/admin/resource-management.md),
  [abac-builder](docs/admin/abac-builder.md),
  [policy-simulator](docs/admin/policy-simulator.md),
  [decision-explorer](docs/admin/decision-explorer.md),
  [access-reviews](docs/admin/access-reviews.md),
  [audit-center](docs/admin/audit-center.md),
  [security-analytics](docs/admin/security-analytics.md); ERD updated.
  Backend **530** green (12 new); frontend **267** green (8 new); tsc + build
  clean.

Next: 4.3.8 Identity Governance & Administration.

### Part 4.3.8 — Identity Governance & Administration (IGA) ✅

Extends the authorization platform with continuous governance: SoD/toxic
permission detection, privileged access review, orphaned-identity detection,
risk scoring, automated remediation and compliance reporting, over the
existing 4.3.1–4.3.7 authorization/certification foundation.

- **Governance API** (`app/governance/`, §19): 40 `/api/v1/governance`
  endpoints. Certification campaigns (§5-§7) are a thin proxy over the 4.3.7
  `AccessReviewService` — same engine, extended with `campaign_type` and
  MODIFIED/DELEGATED decisions — everything else is new. Gated by 11 new
  `governance.*` permissions (§18); new builtin `ROLE_COMPLIANCE_ADMIN`.
- **SoD / toxic permission detection** (§9, §10; migration `0022`): one
  `sod_rules` engine (`rule_type=SOD|TOXIC_PERMISSION`) — an identity trips a
  rule when its effective permissions (role hierarchy resolved) intersect
  both of the rule's permission sets. Detection is continuous: an org-wide
  scan endpoint, plus a best-effort scan on every `POST /role-assignments`.
- **Privileged access governance** (§11): lists identities holding a tracked
  privileged role with a live risk score and last activity; review/approve/
  revoke workflow — revoke removes the grant through the RBAC service.
- **Orphaned identity detection** (§12): disabled-but-still-granted users,
  90-day-inactive users, stale API keys, unused roles — deduplicated findings.
- **Governance risk scoring** (§13): 0-100 score from five weighted factors
  (privileged roles, open toxic/SoD findings, inactivity, failed
  certifications, outstanding approvals) → LOW/MEDIUM/HIGH/CRITICAL band.
- **Remediation** (§14): typed actions against a finding; REMOVE_ROLE/
  DISABLE_ACCOUNT/DISABLE_API_KEY/EXPIRE_DELEGATION execute against live
  state; NOTIFY_MANAGER/CREATE_APPROVAL_REQUEST/REQUIRE_MFA/
  CREATE_SECURITY_TICKET are audit-tracked hooks (no manager hierarchy,
  ticketing, or per-user MFA-required flag exists yet to wire into).
- **Compliance reporting** (§15, §16): SOC 2/ISO 27001/HIPAA/GDPR/NIST/CIS/
  Internal control → evidence mapping; immutable evidence snapshots; JSON/CSV
  export (PDF/Excel via client-side conversion, matching the existing export
  pattern elsewhere in this app).
- **Governance dashboard + analytics** (§21, §26): 10 widgets, 5 charts,
  computed live (no caching layer yet).
- **Frontend** (`modules/governance`): 12 pages + `GovernanceNav`
  (permission-filtered, mirrors `AdminNav`); `/governance/*` routes; linked
  from `AdminNav` and the Settings → Security governance card.
- Docs: [governance-dashboard](docs/governance/governance-dashboard.md),
  [access-certification](docs/governance/access-certification.md),
  [sod-analysis](docs/governance/sod-analysis.md),
  [toxic-permissions](docs/governance/toxic-permissions.md),
  [privileged-access](docs/governance/privileged-access.md),
  [orphaned-identities](docs/governance/orphaned-identities.md),
  [risk-scoring](docs/governance/risk-scoring.md),
  [remediation](docs/governance/remediation.md),
  [compliance-reporting](docs/governance/compliance-reporting.md).
  Backend **544** green (14 new); frontend **267** green, tsc + build clean;
  verified end-to-end in a real browser (registration → login → create/
  activate an SoD rule → create/launch/review a certification campaign).

Next: 5.0 Agent Runtime & Lifecycle Management.

### Part 5.0 — Agent Runtime & Lifecycle Management ✅

The execution layer: register, version, deploy and execute real AI agents
under the same governance and security controls as the rest of the
platform, over the existing agent registry and authorization gateway.

- **Agent registry** (migration `0023`): additive columns on the existing
  Phase 1 `agents` table (`slug`, `project_id`, `owner_type`/`owner_id`,
  `criticality`, `data_classification`, `default_environment`,
  `lifecycle_status`, `archived_at`) — no parallel registry. New
  `agent_definitions` table; DRAFT → VALIDATED → APPROVED → ACTIVE →
  SUSPENDED/DEPRECATED/ARCHIVED/RETIRED lifecycle.
- **Immutable versioning** (`agent_versions`): checksummed snapshots
  (config, prompt, model config, capability/tool refs, policy);
  DRAFT → READY_FOR_REVIEW → APPROVED → PUBLISHED → DEPRECATED/REVOKED;
  publish recomputes the checksum and blocks on tamper.
- **Deployments** (`agent_deployments`): DEVELOPMENT/TEST/STAGING/
  PRODUCTION/SANDBOX; RECREATE strategy (CANARY/ROLLING/BLUE_GREEN modeled,
  not yet executed); mission-critical + production deployments gate on
  approval; rollback to any prior published/deprecated version.
- **Runtime Gateway** (`app/runtime/services.py::ExecutionRequestService`):
  the only entry point for execution — agent/deployment/version state →
  idempotency (`idempotency_records`) → the existing 4.3.6
  `AuthorizationGateway` (RBAC/ABAC) → runtime policy (concurrency limits,
  approved models, environment restrictions) → approval → queue. Denials
  and policy blocks are saved as inspectable execution rows, not thrown.
- **Postgres-backed queue & worker** (`agent_executions` +
  `execution_locks`, no Redis/Celery): `SELECT ... FOR UPDATE SKIP LOCKED`
  claim, per-attempt retry with a non-retryable error allowlist, dead-
  lettering after `maximum_retries`. Driven inline/eagerly in this
  environment (see [docs/runtime/workers-and-queue.md](docs/runtime/workers-and-queue.md)).
- **Capabilities & tools** (`capabilities`/`agent_capabilities`,
  `tools`/`agent_tools`/`tool_calls`): declare-then-assign-then-authorize;
  the Tool Gateway default-denies everything except the built-in
  `FUNCTION`/`echo` action (no outbound network/code-execution surface in
  this build).
- **Model Gateway**: provider-neutral contract; only `MOCK` is a working
  adapter (deterministic, no network call); any other provider fails
  closed with `MODEL_PROVIDER_UNAVAILABLE`.
- **Runtime approvals** (`runtime_approvals`, new — the existing
  `Approval` model is 1:1 with `agent_action_id` and doesn't fit): gates
  mission-critical/production deployments and executions.
- **Kill switch**: execution/agent/organization scope, always audited,
  always reason-required and confirmed in the UI.
- Gated by 32 new `runtime.*` permissions; new builtin roles
  `ROLE_RUNTIME_ADMIN` (full control) and `ROLE_RUNTIME_OPERATOR`
  (register/version/run, no publish/kill-switch).
- **Frontend** (`modules/runtime`): 11 pages + `RuntimeNav`
  (permission-filtered, mirrors `GovernanceNav`); `/runtime/*` routes;
  linked from `AdminNav`.
- Docs: [docs/runtime/](docs/runtime/) — overview, architecture,
  agent-lifecycle, versioning, deployments, executions, workers-and-queue,
  capabilities-and-tools, gateways, runtime-policy-and-approvals,
  health-and-observability, operations-and-kill-switch, security.
  Backend **561** green (17 new); frontend tsc + build clean; verified
  end-to-end in a real browser (register → validate/approve/activate an
  agent → create/publish a version → deploy → run an execution to
  `SUCCEEDED`).

#### Part 5.0 hardening — closing the acceptance-criteria gaps

A follow-up pass against the SRS's acceptance criteria and Definition of
Done, closing every item that was only partially met:

- **Runtime limits fully enforced** (§46-§48): `maximum_executions_per_minute`
  and `maximum_cost` (rolling daily budget) join the already-enforced
  `maximum_concurrent_executions`; `maximum_tokens` is checked pre-flight
  against an estimate of the input alone. Every count excludes the
  execution being evaluated (it's already flushed when the check runs) —
  without that exclusion, a request always counted against its own limit.
- **Execution timeout** (§36): `maximum_execution_seconds` now actually
  bounds the model call (`ThreadPoolExecutor` + `future.result(timeout=)`,
  not `signal.alarm`, so it works cross-platform); exhausting retries after
  a timeout reports `TIMED_OUT`, not a generic `DEAD_LETTERED`.
- **Worker crash recovery** (§32): `ExecutionWorkerService.reap_expired_locks`
  finds any `execution_locks` row past its `expires_at` (a worker that
  claimed an execution and never finished), applies the normal retry
  policy to the execution it was guarding, and drops the stale lock —
  called opportunistically before every claim, plus a
  `POST /runtime/workers/reap` endpoint for operator-triggered recovery.
- **Tool constraints enforced** (§23): `read_only`,
  `maximum_calls_per_execution` and `allowed_domains` are now real checks
  in the Tool Gateway, not just stored JSONB.
- **Kill switch PROJECT and PLATFORM scopes** (§60): PROJECT resolves
  every agent under a project in the actor's org; PLATFORM is cross-tenant
  and additionally requires the actor's role to be `SUPER_ADMIN` — a
  permission scoped to one organization must never be enough, alone, to
  halt every organization's executions.
- **Input/output contract validation** (§7.2): execution input is
  validated against the agent definition's `input_schema` before an
  execution row is even created (`jsonschema`, new dependency); output is
  validated against `output_schema` before an attempt is allowed to report
  `SUCCEEDED`.
- **Execution state machine, actually validated** (§27): every
  `AgentExecution.status` assignment goes through one guarded helper
  (`_set_execution_status` / `_EXECUTION_TRANSITIONS`) that rejects any
  transition not in the documented machine, instead of trusting each call
  site to only ever assign a legal value.
- 16 new backend tests (577 total green) covering all of the above,
  including two genuine bugs the new tests caught and fixed: an off-by-one
  in the per-minute rate limit (a request counted against its own limit
  before being decided) and a test-isolation leak where a manually
  reaped-and-requeued execution could be claimed by an unrelated later
  test ahead of its own (the global, non-tenant-scoped claim query is
  correct production behavior — see
  [docs/runtime/workers-and-queue.md](docs/runtime/workers-and-queue.md) —
  but requires tests not to leave orphaned `QUEUED` rows behind).

Next: 5.1 Enterprise Agent Registry.

### Part 5.1 — Enterprise Agent Registry, Definitions & Lifecycle ✅

The registry gate every agent must pass before it can version, deploy or
execute:

- **Full 13-state lifecycle** (§18-§21), replacing Phase 5.0's collapsed
  8-state one: `DRAFT → REGISTERED → VALIDATING → {VALIDATED,
  VALIDATION_FAILED} → PENDING_APPROVAL → {APPROVED, REJECTED} → ACTIVE →
  {SUSPENDED, DEPRECATED} → {ARCHIVED, RETIRED}`, with a dedicated audit
  event per action instead of borrowing a neighbor's.
- **Accountable ownership** (§12, §13): business/technical/compliance
  owner, transfer with cross-tenant scope checks, an immutable
  `agent_ownership_history` ledger.
- **Mandatory machine identity** (§11): `agent_identities` gains a
  one-per-agent unique constraint and real eligibility enforcement
  (active, unexpired) — both stored but never checked in Phase 5.0.
- **Validation-report engine** (§25-§31): metadata/organization/ownership/
  identity/definition/risk rules, JSON Schema DoS guards (size/depth
  limits jsonschema doesn't enforce on its own), entrypoint format
  validation per type, sample-payload testing.
- **Duplicate detection** (§32, §33, §64): exact-match + `difflib`
  similarity scoring, reviewer decisions, confirmed duplicates block
  registration.
- **JSON/YAML/CSV import & export** (§39-§45): imports always land as
  DRAFT; exports always exclude secrets (allowlist, not denylist) and
  neutralize CSV formula injection; both run synchronously inline (no
  background worker in this environment, same "eager" trick the execution
  queue already uses).
- **Legacy migration classification** (§70-§73) for agents created under
  Phase 5.0's simpler registry.
- **Optimistic concurrency** (§53): `row_version`, both a client-visible
  check and SQLAlchemy's native `version_id_col` as defense-in-depth.
- Frontend: a 10-step registration wizard (with draft autosave), the agent
  detail page reworked into 12 tabs (Overview/Definition/Ownership/
  Identity/Contracts/Risk & Data/Capabilities/Tools/Validation/Lifecycle/
  Audit/Settings), a duplicate-review page, import/export pages, and a
  legacy-migration page.
- Migration `0024_agent_registry`; ~25 new `runtime.agent.*` permissions;
  41 new backend tests incl. 2 performance tests (636 total green) plus
  the existing 593 updated for the new lifecycle; 290 frontend tests
  green (23 new, covering all 5 registry pages); clean typecheck and
  build. See [docs/runtime/registry/](docs/runtime/registry/) for the
  full set.

Next: 5.2 Enterprise Versioning & Release Management.

### Part 5.2 Part 1 — Enterprise Versioning & Release Management Foundation ✅

Extends Phase 5.0's already-immutable, checksummed `agent_versions` rather
than forking a second version table:

- **Enforced semantic versioning** (§15-16): auto-derived or validated
  strictly-increasing MAJOR.MINOR.PATCH, replacing Phase 5.0's accept-any
  string.
- **Snapshot builder** (§10-14): one frozen, checksummed document per
  version (registry identity + definition + runtime config + every
  release-management attachment), built once, at publish — the true
  immutability boundary.
- **Version lineage** (§17-18): parent linking, supersession tracking, and
  a settable rollback-target pointer (foundation only; executing a
  rollback is still `DeploymentService`'s existing job).
- **Release channels, artifacts, categorized notes** (§9, §26-28), and a
  version status-history ledger (§19, §25) — all locked once PUBLISHED.
- **New `RETIRED` terminal state** (DEPRECATED → RETIRED).
- **Version comparison** (§3): a read-only structural diff between any two
  versions of the same agent.
- **Promotion readiness** (§3, §30): a read-only diagnostic evaluating the
  SRS's full readiness checklist — advisory only, never a lifecycle gate.
- **Deliberately not enforced**: the SRS's "cannot publish two active
  releases" per channel — conflicts with this platform's existing
  rollback/canary deployment strategies, which require multiple
  simultaneously-PUBLISHED versions. See
  [docs/runtime/versioning.md](docs/runtime/versioning.md) for the full
  rationale and every other scope decision made in this part.
- Migration `0025_agent_versioning`; 1 new `runtime.version.retire`
  permission; 25 new backend tests (661 total green); 7 new frontend
  tests (297 total green); clean typecheck and build.

### Part 5.2.6 — Compatibility & Breaking-Change Detection ✅

Makes the `compatibility_level` column Part 1 reserved (but never
computed) real:

- **Compatibility classification** (ACT-VER-FR-100..108): a candidate
  version vs. a resolved baseline into `COMPATIBLE` /
  `BACKWARD_COMPATIBLE` / `BREAKING` / `UNKNOWN` — input/output contract
  (JSON Schema diff), tool/capability bindings, model provider/config,
  resource limits (heuristic), policy tightening, prompt/metadata. One
  breaking finding makes the whole version `BREAKING`.
- **Baseline resolution**: explicit override → `parent_version_id` →
  highest `PUBLISHED` predecessor → `UNKNOWN` if none exist.
- **Findings table** (`agent_version_compatibility_findings`, migration
  `0026_version_compatibility`): one row per detected change, consequence-
  oriented description, replaced (not accumulated) on re-analysis.
- **Semver-consistency check**: declared MAJOR/MINOR/PATCH increment vs.
  the detected level's expected minimum — **reported, not enforced**;
  publication never blocks on it (see
  [docs/runtime/versioning.md](docs/runtime/versioning.md) for why this
  deliberately deviates from the SRS's "reject on inconsistency").
- **Readiness's `compatibility_analysis` check is real** — no longer
  `skipped: true`; warns (doesn't fail) on a correctly major-bumped
  breaking change, fails only on a genuine inconsistency, and — like every
  readiness check — never gates a lifecycle action.
- Triggered automatically as a failure-tolerant follow-up right after
  `publish()`; also on demand via `POST .../compatibility/analyze`
  (backfills versions published before this phase existed).
- Migration `0026_version_compatibility`; no new permission (reuses
  `runtime.version.view`); 35 new backend tests (696 total green); backend
  only — frontend untouched, still 297 green.

### Part 5.2.4 — Cryptographic Signing, Provenance & Portable Attestation ✅

The final Phase 5.2 sub-phase — closes the platform's integrity story:

- **Required refactor**: a single canonical serialization
  (`app/runtime/versioning/canonical.py` — sorted keys, NFC strings, UTF-8,
  no whitespace, floats rejected outright) now backs both checksum
  routines, replacing `json.dumps`'s unspecified-across-languages defaults.
  Legacy rows keep verifying via the original (renamed, deprecated)
  routines, tracked per-row by a new `checksum_algorithm` column; the
  migration itself never rewrites an existing checksum —
  `scripts/recompute_checksums.py --dry-run`/live is the explicit, audited
  upgrade path.
- **Signing provider abstraction**: `SigningProvider` (local Ed25519 today;
  Azure Key Vault a configuration change away) — private key material
  never crosses the interface.
- **Portable attestation**: an in-toto Statement v1 / DSSE-enveloped
  document per published version, self-contained (no predicate field needs
  a database lookup), signed over the DSSE Pre-Authentication Encoding.
- **Fail-closed signing**: wired into `publish()` so a signing failure
  aborts publication entirely — the opposite policy from 5.2.6's advisory
  compatibility analysis, and deliberately so.
- **Key rotation & revocation**: revoking a key marks affected signatures
  `KEY_REVOKED` without touching the version record or signature bytes;
  rotation keeps old key versions verifiable.
- **Deliberately deferred**: a public/unauthenticated verification
  endpoint (every route here is authenticated + org-scoped) and Azure Key
  Vault itself — both documented as Known Deviations with closure
  conditions in [docs/runtime/versioning.md](docs/runtime/versioning.md).
- Migration `0027_version_signing`; 2 new permissions
  (`runtime.signing.view`/`.manage`); 47 new backend tests (743 total
  green); backend only — frontend untouched, still 297 green.

## Milestone 1 — Real Model Provider Integration (Phase 5.7a)

Closes the gap every phase above rested on an untested assumption about:
the platform can register, version, sign, authorize, govern and audit an
agent — and then executes a *mock*. Eight sub-phases were originally
planned, built in order so each interface is proven by a trivial
implementation before a real one leans on it; the first five (5.7a.1-5)
closed "the model half" of Milestone 1 completely — 5.7a.6-5.7a.8 remain
NOT STARTED and were not required for Milestone 1 to complete (see
below; Phase 5.6a's tool-execution half was the other, and last,
prerequisite).

### Part 5.7a.1 — Model Provider Abstraction & Registry ✅

Abstraction only — no real provider yet (that's 5.7a.2, deliberately kept
separate so its shape doesn't leak into the interface while it's still
being designed):

- **`ModelProvider`** abstract interface (`complete()`/`stream()`/
  `describe()` abstract; `supports()` concrete, derived from `describe()`
  so it can never contradict its own capability declaration).
- **Provider-neutral internal representation** (`ModelMessage`,
  `ModelRequest`, `ModelResponse`, `ModelToolDefinition`, `ModelToolCall`,
  `ModelCapabilities`, `FinishReason`) — immutable, no provider-specific
  field name anywhere, sampling parameters a free-form dict since
  providers accept different sets.
- **Explicit provider registry** (`register()`/`resolve()`) — greppable,
  not directory-scanning discovery; adding a provider is one line.
- **Capability enforcement**: a request for something a provider doesn't
  support (per its own `describe()`) raises `MODEL_CAPABILITY_UNSUPPORTED`
  rather than being silently mishandled.
- **`MOCK` migrated onto the interface**, externally observable behavior
  unchanged (exact echo, `provider == "MOCK"`, positive token count) —
  proof the interface doesn't need to distort a real provider's shape to
  express it. `ModelGatewayService.invoke()` keeps its exact signature;
  only what happens inside changed.
- **Reusable, parameterized conformance test suite** — every future
  adapter (5.7a.2 onward) is validated against it in one line, no copied
  tests.
- No schema migration (pure application-layer abstraction). 23 new
  backend tests (766 total green); backend only — frontend untouched,
  still 297 green.

### Part 5.7a.2 — First Real Provider Adapter ✅

The first real, network-calling provider — no longer just an interface:

- **`OpenAICompatibleProvider`** (`app/runtime/providers/openai_compatible.py`)
  speaks the OpenAI chat-completions wire protocol against any `base_url`
  — Ollama, vLLM, LM Studio, or OpenAI itself. Registered as
  `"OPENAI_COMPATIBLE"` (names the protocol, not a vendor — `"OPENAI"`
  stays free for a future vendor-specific adapter).
- **Registry gained real `model`/`api_key` forwarding** to the provider
  instance — a genuine 5.7a.1 gap where neither reached further than
  usage-reporting strings.
- Message/tool-call/finish-reason translation, sampling-parameter
  filtering, tolerant parsing of responses missing optional fields.
- **Fixture-replay test infrastructure**: `httpx.MockTransport`, six
  committed wire-format fixtures, a manual recorder script, and a
  `live_provider` pytest marker excluded by default.
- One coarse `MODEL_PROVIDER_REQUEST_FAILED` error code — classifying
  failure modes for retry is 5.7a.4's job, deliberately not this one's.
- 34 new backend tests (800 total green, 1 deselected); backend only —
  frontend untouched, still 297 green.

### Part 5.7a.3 — Streaming & Token Accounting ✅

- **Real SSE streaming** replaces 5.7a.2's placeholder: incremental
  content deltas, tool-call reassembly across fragmented/interleaved
  chunks; an interrupted stream persists a partial (`FinishReason.ERROR`)
  rather than raising.
- **`ModelGatewayService.invoke()` gained an opt-in streaming path**
  (`model_configuration.stream=true`) — the `(output_payload, usage)`
  contract stays unchanged for every non-streaming caller.
- **Real token/cost accounting**: new `model_pricing` table with
  effective dating (a price change inserts and closes a row, never
  mutates one in place) backs `PricingService`, replacing the flat
  placeholder rate. A provider that omits usage now honestly reports
  `{}` — never zero-filled or estimated (`ACT-MDL-FR-046`).
- Migration `0028_streaming_and_pricing`: new `model_pricing` table
  (seeded), 12 new columns on `agent_executions`, 4 on
  `execution_attempts`; 1,538 pre-existing non-zero-cost rows marked
  `cost_is_estimated=true`, never recomputed.
- 22 new backend tests (822 total green, 1 deselected); backend only.

### Part 5.7a.4 — Error Taxonomy & Resilience ✅

- **Eight-class provider-neutral error taxonomy** (`ProviderErrorClass`):
  `RATE_LIMITED`/`PROVIDER_UNAVAILABLE`/`TIMEOUT` retryable;
  `CONTEXT_LENGTH_EXCEEDED`/`CONTENT_FILTERED`/`AUTHENTICATION_FAILED`/
  `INVALID_REQUEST`/`UNKNOWN` never retried.
- Classification lives in the adapter; retry/backoff/circuit-breaking
  live in the service layer, so a future second adapter inherits both
  with zero new retry code of its own.
- Exponential-with-jitter backoff, a provider's own `Retry-After` header
  honored over computed backoff, a per-provider three-state circuit
  breaker, and a streaming pre-/post-first-token retry boundary.
- Credential/base-URL scrubbing before anything reaches a log or caller.
- No schema migration — `error_code` (already present) now stores the
  taxonomy class string in place of a generic code.
- 36 new backend tests plus 9 committed error fixtures (858 total green,
  1 deselected); backend only.

### Part 5.7a.5 — Per-Organization Provider Credentials ✅

**Completes the model half of Milestone 1** — only tool execution
(Phase 5.6a) remained before the platform genuinely executes end to end:

- New `provider_credentials` table (migration `0029_provider_credentials`):
  one row per `(organization_id, provider)`, Fernet-encrypted at rest
  (`credential_crypto.py`).
- **Resolution order**: this org's own stored credential →
  `MODEL_PROVIDER_API_KEYS` fallback → none. A real provider rejecting an
  unauthenticated call with nothing configured anywhere reports the new,
  specific `PROVIDER_CREDENTIAL_REQUIRED` rather than a generic auth
  failure.
- Resolved synchronously on the worker's own thread, before the model
  call crosses into its `ThreadPoolExecutor` — only the resulting plain
  `ResolvedCredential` value crosses the thread boundary, never a live
  `Session`.
- 4 new routes under `/api/v1/runtime/providers/{provider}/credentials`,
  2 new permissions (`runtime.provider.view`/`.manage`).
- 25 new backend tests (883 total green, 1 deselected); backend only.

Next: the tool-execution half of Milestone 1 (Phase 5.6a).

## Milestone 1 — Tool Execution (Phase 5.6a)

Closes the other half of the same untested assumption every phase above
rested on: every agent so far could only call the built-in `FUNCTION`/
`echo` action. Three sub-phases, built in the same "prove the interface
with a trivial case first" order as the model half.

### Part 5.6a.1 — HTTP Tool Execution & Egress Control ✅

- **`ToolGatewayService` gains a real `HTTP` action** behind a hardened,
  exhaustively-tested SSRF egress guard (`app/runtime/tools/egress_guard.py`)
  — address validation across encodings (decimal/octal/hex loopback),
  DNS-rebinding connection pinning (verified empirically against the
  installed `httpx`/`httpcore`), redirect re-validation.
- Egress policy is read from the version's *frozen* snapshot
  (`tool_configs`), never live, mutable `Tool` state.
- New `tool_credentials` table, reusing 5.7a.5's `credential_crypto.py`
  directly.
- New `TOOL_EGRESS_DENIED` error code; an egress denial is
  `CRITICAL`-severity audited (a signal someone may be probing the SSRF
  boundary).
- Migration `0030_http_tool_egress`; 51 new backend tests (934 total
  green, 1 deselected); backend only.

### Part 5.6a.2 — Tool Schema Validation & Resilience ✅

- **Argument validation against `Tool.input_schema`** runs before any
  side effect; a response is validated against an optional
  `output_schema`. Both frozen into the version snapshot at publish time.
- **Reuses — never duplicates —** 5.7a.4's error taxonomy and
  retry/circuit-breaker machinery for a tool's own HTTP-level failures.
- **Idempotency is explicit, opt-in** (`http_config.idempotent`) — never
  inferred from HTTP method; undeclared or `false` means a transient
  failure is never retried.
- New per-execution concurrency ceiling (not genuinely contended until
  5.6a.3's parallel execution).
- **Behavior change**: a `FAILED` tool call no longer aborts the whole
  execution — only a `DENIED` one (egress/authorization) still does.
- Migration `0031_tool_resilience`; 19 new backend tests (953 total
  green, 1 deselected); backend only.

### Part 5.6a.3 — Model-Driven Tool Invocation Loop ✅

**Completes Milestone 1** — an agent registered, versioned, signed and
deployed now genuinely executes end to end (calls a real model, the
model requests a real tool, the tool runs safely, the result feeds back,
the loop resolves to a final answer, every token/call/decision audited):

- **`ToolLoopOrchestrator`** drives model → tool → model, reusing
  `ModelGatewayService.invoke()` and `ToolGatewayService.invoke()`
  entirely unchanged for every call.
- **Four independent termination caps**: max iterations, token budget,
  wall-clock, repeated-identical-call (reusing Phase 5.2.4's canonical
  serialization) — each ends in a distinct, audited outcome.
- **Real parallel execution** of tool calls the model requests together,
  gated by the same `idempotent` flag 5.6a.2 introduced, reused for a
  second purpose (safe-to-retry ⟺ safe-to-run-alongside-siblings).
- A tool named outside the version's frozen `tools_snapshot` is a scope
  violation (`TOOL_NOT_BOUND_TO_VERSION`), not a recoverable mistake —
  this is also where "no agent-to-agent chaining" is structurally
  enforced, since a tool is the only thing this loop can ever name.
- New `execution_messages` table — the full conversation transcript,
  exposed at `GET /executions/{id}/messages`.
- **A genuine deadlock was found and fixed**, not merely designed
  around: the first parallel-execution version deadlocked a fresh
  per-thread `Session`'s insert against the still-held `claim_next` lock
  — reproduced directly against `pg_stat_activity`, fixed by committing
  the claiming session before any parallel dispatch.
- Migration `0032_tool_loop`; 17 new backend tests (970 total green, 1
  deselected); backend only.

**Milestone 1 is complete.** See
[docs/runtime/gateways.md](docs/runtime/gateways.md)'s "Milestone 1 —
complete" section.

Next: Milestone 2 — Enterprise Integration Framework.

## Milestone 2 — Enterprise Integration Framework (Phase 2.x)

*Revises the prior roadmap: the former Milestone 2 (deployment &
release strategies) moves to Milestone 3 — controlled rollout only
matters once agents do consequential things against real enterprise
systems, which integration is what creates. See `ACT-SRS-M2` §2.3.*

The platform never replaces an enterprise's SAP/Salesforce/database
estate — it becomes the governed AI layer on top, and every external
system is reached through a Connector that becomes a Tool the runtime
already knows how to invoke. Nine sub-phases: the connector framework
(2.1.x), four universal generic connectors (2.2.x — REST, database,
storage, queue; vendor-specific connectors like SAP/Salesforce are
deliberate fast-follow work per named buyer demand, never built
speculatively), and external identity federation (2.3.1).

### Part 2.1.1 — Connector Abstraction & Lifecycle ✅

**Milestone 2's first sub-phase**, structural twin of 5.7a.1 — interface
first, proven by a trivial implementation, before any real connector
leans on it:

- **`Connector` ABC** (`app/integration/base.py`) — abstract
  `describe()`/`validate_configuration()` only; deliberately no
  `authenticate()`/`execute()`/`health_check()`, all left to the
  sub-phases that actually need them (2.1.2/2.1.3/the tool bridge).
- **Five-state tenant-instance lifecycle**
  (`registered → configured → active → disabled → failed`), one
  authority (`lifecycle.py`), never inlined elsewhere.
- **`MockConnector`** — trivial reference implementation, proving the
  ABC without distortion, exactly as `MockProvider` did for 5.7a.1.
- **Runtime-never-knows enforced by construction**: a test greps every
  file under `app/runtime/` for the substring `"connector"` and fails
  the build if it finds one (`ACT-INT-FR-006`).
- New tables `connectors` (registered types), `connector_instances`
  (tenant-scoped), `connector_lifecycle_events` (append-only audit) — no
  credential column; that's 2.1.2.
- 8 routes under `/api/v1/integration`, 2 new permissions.
- Migration `0033_connector_core`; 24 new backend tests (994 total
  green, 1 deselected); backend only. See
  [docs/integration/connectors.md](docs/integration/connectors.md).

### Part 2.1.2 — Connector Authentication Framework ✅

Connector instances can now hold real, encrypted credentials — six
pluggable schemes, including transparent OAuth2. The hard reuse
mandate this sub-phase had to satisfy: extend 5.7a.5's
`credential_crypto.py`, never build a second encrypted-secret store.

- **`AuthScheme` ABC + explicit registry** (`app/integration/auth/`) —
  static API key, bearer token, HTTP basic, OAuth2 client-credentials,
  OAuth2 authorization-code, mTLS. Adding a 7th scheme is a new
  registered subclass and nothing else — mechanically proven, not just
  claimed.
- **Credential storage reuses `credential_crypto.py` directly** — no
  extraction needed, since `encrypt_secret`/`decrypt_secret`/`mask_hint`
  already had zero provider-specific logic in their own bodies. The
  same three functions Phase 5.6a.1's `ToolCredentialService` already
  reused, now a second time. The platform-held-Fernet-key Known
  Deviation is inherited from 5.7a.5, not a new one.
- **OAuth2 acquisition, caching and transparent refresh**
  (`token_manager.py`) across all three grant types.
  **Concurrency-safe by design**: a `SELECT ... FOR UPDATE` lock on the
  *parent* `connector_instances` row (not the token row, which can't be
  locked before it exists) serializes concurrent refreshers — proven
  with real threads against real Postgres, not just argued.
- **Authorization-code, built vs. stubbed, stated plainly**: client
  config storage, authorization-URL construction, the callback code→
  token exchange, and refresh-and-apply are built; the interactive
  consent-redirect UI itself is an explicit front-end deferral.
- **Rotation, mTLS, validation**: rotating a credential re-encrypts in
  place without disrupting an in-flight invocation (mirrors 5.7a.5's
  semantics exactly); an mTLS cert/key pair gets signing-key-grade
  protection; `validate` records status without ever returning the
  credential.
- New tables `connector_credentials`/`connector_oauth_tokens`
  (migration `0034_connector_auth`) — no structured plaintext credential
  field on either. 7 new routes, reusing 2.1.1's two permissions.
  `MockAuthenticatedConnector` added alongside `MockConnector` to
  exercise the framework end to end.
- 31 new backend tests, including a real-thread OAuth2 concurrency
  proof and a full credential-redaction sweep (logs, audit `meta`, API
  responses). Backend **1,025** total green (994 + 31), 1 deselected;
  backend only. See
  [docs/integration/connectors.md](docs/integration/connectors.md)'s
  "Authentication" section.

### Part 2.1.3 — Connector Registry & Health ✅

A connector is now *discoverable and monitored* — the missing piece
between "configured and authenticated" (2.1.1/2.1.2) and "invocable"
(2.2.x). A broken connector goes `failed` with a recorded cause instead
of silently hanging every agent execution that touches it.

- **`ConnectorRegistry`** (`app/integration/registry.py`) — the single
  lookup surface for type resolution/listing and tenant-scoped instance
  resolution/listing, wrapping 2.1.1's own services rather than
  duplicating them. Its `resolve_instance_for_invocation` is the
  **fail-fast wiring point**: raises `CONNECTOR_UNAVAILABLE` immediately
  for a `failed`/`disabled` instance, before any real call is ever
  attempted — Phase 2.2.x's tool bridge inherits the guarantee for free,
  with no fail-fast logic of its own to write.
- **`Connector.health_check(configuration)`** — a new, additive ABC
  method (expected and deliberate this sub-phase, unlike the still-absent
  `authenticate()`/`execute()`). Answers reachability only, **never
  handed a credential** — auth validity is checked entirely separately,
  reusing `ConnectorCredentialService.validate()` (2.1.2) whole, not
  duplicated. A genuine security property: nothing in a connector's own
  code, or in the new `ConnectorHealthService`, ever sees a decrypted
  secret.
- **`HEALTHY`/`UNHEALTHY`/`ERROR`, three distinct outcomes**: `ERROR`
  (a probe raised) surfaces `CONNECTOR_HEALTH_CHECK_FAILED` (502) —
  distinct from a completed, negative `UNHEALTHY` result (200).
- **Automated `active -> failed` / `failed -> active`**, through the
  unchanged 2.1.1 state machine, never bypassed: a failing check calls
  the pre-existing `mark_failed`; a passing check calls a new `recover`
  event this sub-phase added.
- **Alerting reuses the existing precedent — no new channel built**:
  `INTEGRATION_CONNECTOR_STATE_CHANGED` (unchanged event) now carries
  `severity: CRITICAL` on a failed transition, the same pattern Phase
  5.6a.1's `RUNTIME_TOOL_EGRESS_DENIED` already established.
  `notification_service.py` was examined and rejected — no
  subscription/recipient-list concept to hook a connector event into.
- **Interim in-process scheduler**, off by default everywhere including
  every test run, explicitly documented as Milestone-3-replaceable —
  REPO_STATE §10.2's no-distributed-scheduler constraint honored, not
  worked around.
- New table `connector_health_checks` (append-only, capped at 200
  rows/instance) plus a two-column health cache on `connector_instances`.
  3 new routes reusing 2.1.1/2.1.2's permissions. One pre-existing 2.1.1
  test updated, not weakened, to match the ABC's deliberate growth.
- 24 new backend tests. Backend **1,049** total green (1,025 + 24), 1
  deselected; backend only. See
  [docs/integration/connectors.md](docs/integration/connectors.md)'s
  "Registry & Health" section.

### Part 2.1.4 — Connector SDK ✅

**Completes the connector framework (Phase 2.1) in full.** Not a new
capability so much as a formalization and hardening of the surface
`MockConnector` was already using — the boundary between "our
connectors" and "anyone's connectors," and the precondition for the
connector marketplace in Milestone 12.

- **`app/integration/sdk/`** — the author-facing surface, explicit
  `__all__` re-exports only: `Connector`, the declaration types,
  `SUPPORTED_AUTH_SCHEMES`, config validation, one governed network
  primitive (`GovernedHttpClient`), and a testing harness
  (`ConnectorTestHarness`). Importing from `app.integration.sdk` is the
  supported contract; every other internal import is not.
- **The containment core, proven not asserted**: the surface exposes no
  database session, no credential-resolution machinery, no raw HTTP
  client, no audit-suppression hook, no route-registration mechanism —
  a dedicated governance-inheritance test suite (AC-10..AC-15) proves an
  SDK connector *cannot* make an undeclared outbound call, receive a
  decrypted credential, suppress audit, or reach another tenant's data,
  because the SDK offers no method to do any of those.
- **`GovernedHttpClient`** — the only network primitive on the surface,
  reusing Milestone 1's `egress_guard`/`http_executor` directly.
  `allowed_hosts` is fixed at construction, never a per-call argument.
- **Completeness enforcement**: one function,
  `validate_declaration_complete()`, called both at real registration
  and by the SDK harness's own pre-flight check — an incompletely
  declared connector fails loudly, at registration, naming exactly
  what's missing (`CONNECTOR_DECLARATION_INCOMPLETE`).
- **Registration parity proven by construction**: the worked example,
  `WebhookConnector` (`SDK_EXAMPLE_WEBHOOK`), sits in the *same*
  `_CONNECTOR_TYPES` dict as `MOCK`/`MOCK_AUTH` and registers through
  the identical path — there is one registration mechanism, not two
  kept in sync.
- **The worked example is built and tested using only the SDK
  surface** — one tool contract, `BEARER` auth, a governed health
  check — verified by an AST-based import-inspection test, not just by
  behavior.
- **Scope stated explicitly**: trusted, first-party/enterprise authors
  only — not a sandbox for adversarial third-party code. That
  containment problem is Milestone 12's, building on these guarantees
  but assuming hostile intent this sub-phase does not.
- No migration; no new HTTP route (a code-authoring capability, not an
  API).
- 31 new backend tests. Backend **1,080** total green (1,049 + 31), 1
  deselected; backend only. See
  [docs/integration/connectors.md](docs/integration/connectors.md)'s
  "Connector SDK" section.

Next: 2.2.1 (Generic REST Connector) — the SDK's own real proving
ground. 5 of 9 Milestone 2 sub-phases remain.

### Part 2.2.1 — Generic REST Connector ✅

**Milestone 2's first real connector, and the SDK's first real proving
ground.** Everything through 2.1.4 built the connector *framework*; this
is the first proof it actually does a job — any typical HTTP/JSON API
becomes governed tools by declaration, no code.

- **`RestConnector`** (`app/integration/connectors/rest/`) built entirely
  through the 2.1.4 SDK surface. A configured instance declares a base
  URL, a per-instance authentication scheme, and one or more endpoints
  (method, path template, argument mapping, response extraction, optional
  pagination) — each endpoint becomes one distinct tool contract
  (`ACT-INT-FR-102`).
- **Injection-safe templating**: a path argument is percent-encoded with
  no safe characters (`"123/../admin"` renders as the single, inert
  segment `"123%2F..%2Fadmin"` — never escapes the declared endpoint); a
  header/query value containing a control character is rejected outright.
- **Bounded pagination** — offset/limit, page-number, cursor — hard-capped
  at `min(declared max_pages, 100)` regardless of server behavior.
- **The first tool-invocation bridge built anywhere in this codebase**
  (`invoker.py`): fail-fast resolves an instance, applies its declared
  auth scheme via the existing 2.1.2 framework, dispatches through
  `GovernedHttpClient`, drives pagination, extracts the result — proven
  end to end against a real local server, including a genuine stored,
  encrypted credential reaching the server as a real header.
  **Deliberately not wired into the model-driven tool loop** — Milestone 1
  stays untouched.
- **One real SDK-surface fix, found by real use**: `GovernedHttpClient
  .request()` was silently dropping a query string embedded in its URL —
  invisible to 2.1.4's query-free worked example, fatal to a paginated
  endpoint. Fixed with a new, optional, backward-compatible `query`
  parameter.
- A realistic four-endpoint vendor-like declaration (a support-ticketing
  CRM API) is the concrete proof that a typical vendor REST integration
  is a configuration document, not an engineering project.
- No migration; no new HTTP route (instance configuration reuses the
  existing connector endpoints; the invocation bridge is a direct Python
  entry point).
- 41 new backend tests. Backend **1,121** total green (1,080 + 41), 1
  deselected; backend only. See
  [docs/integration/connectors.md](docs/integration/connectors.md)'s
  "Generic REST Connector" section.

Next: 2.2.2 (Generic Database Connector). 4 of 9 Milestone 2 sub-phases
remain.

### Part 2.2.2 — Generic Database Connector ✅

**Milestone 2's second real connector — and the one carrying its single
sharpest security rule.** The model never writes SQL. Not sanitized, not
escaped, not validated-then-run — absent. There is no code path anywhere
in this codebase that takes model-derived text and places it into SQL
structure.

- **`DatabaseConnector`** (`app/integration/connectors/database/`) turns
  declared, parameterized queries against PostgreSQL/MySQL into governed
  tools. SQL Server is recognized but driver-pending (`pyodbc` needs a
  system ODBC driver, not added this phase).
- **The executor's only public entry point takes a declared query object
  and a parameter mapping — never a raw string.** No parameter position
  anywhere in this connector could accept SQL text from a caller —
  containment by absence, the same principle the SDK used for the raw
  HTTP client and 2.2.1 used for request templating, applied here at its
  most consequential.
- **Proven against this platform's own real dev Postgres, not mocked**: a
  bound parameter value of `"'; DROP TABLE users; --"` (plus the classic
  UNION/comment/stacked-query/boolean-blind injection family) comes back
  as an inert literal string every time.
- **Read-only by default** (`ACT-INT-FR-125`) — a read-only instance
  declaring a mutating query (classified by inspecting its own *declared,
  trusted* SQL, never model output) is rejected outright at configuration
  time.
- **Row limit and timeout, enforced twice each** — rows fetched
  incrementally and rejected (never truncated) past the limit; timeout
  enforced by both a server-side database GUC and a client-side backstop.
- **The first tool-invocation bridge for a database connector**
  (`invoker.py`, mirroring 2.2.1's own exactly) — proven end to end
  against this platform's own dev Postgres, including a genuine stored,
  encrypted credential actually authenticating the connection.
  **Deliberately not wired into the model-driven tool loop** — Milestone
  1 stays untouched.
- One new dependency (`PyMySQL`, pure-Python, no system client library)
  for the MySQL dialect; no new dependency needed for PostgreSQL.
- No migration; no new HTTP route.
- 42 new backend tests. Backend **1,163** total green (1,121 + 42), 1
  deselected; backend only. See
  [docs/integration/connectors.md](docs/integration/connectors.md)'s
  "Generic Database Connector" section.

Next: 2.2.3 (Generic File & Object Storage Connector). 3 of 9 Milestone 2
sub-phases remain.

### Part 2.2.3 — Generic File & Object Storage Connector ✅

**Milestone 2's third real connector — carrying this milestone's second
sharpest security rule.** A model-supplied path can never escape its
declared scope. Not sanitized, not best-effort cleaned up and let
through — a supplied path is canonicalized, then proven to resolve
inside its declared boundary, before any read or write is attempted;
anything that cannot be proven in-scope is denied outright.

- **`StorageConnector`** (`app/integration/connectors/storage/`) turns
  declared, scoped filesystem/S3-compatible access into governed tools.
  Azure Blob is recognized but backend-pending (`azure-storage-blob`
  deliberately not added this phase).
- **The scope enforcer (`scope.py`) has zero dependencies on this
  platform — not even the SDK.** Its one public function canonicalizes
  (percent-decoding, Unicode normalization, then `os.path.realpath` for
  filesystem or `posixpath.normpath` for object storage) and only then
  contains-checks — the canonicalized result, never the raw string, is
  what a caller ever receives. No TOCTOU gap.
- **Proven against every named traversal vector with no live storage
  anywhere in the test file**: relative, absolute (POSIX/Windows-drive/
  UNC), single- and double-percent-encoded, backslash, null-byte
  (literal and encoded), Unicode homoglyph, object-store prefix/bucket
  escape — plus a filesystem symlink escape using a real temporary
  symlink (or, on this environment's unprivileged Windows user, a
  directory junction — genuinely exercised, not skipped).
- **Read-only by default** (`ACT-INT-FR-144`) — a read-only instance
  declaring a write scope is rejected outright at configuration time.
- **Size limits checked via metadata before any full transfer** — never
  loads an oversized object to find out it's too large.
- **New this phase: every object access is audited** — allowed or
  denied, read or write, via a `finally` block, carrying the validated
  path (never the raw supplied string) and never a credential. 2.2.x's
  first invocation-level audit event.
- **The second tool-invocation bridge to reuse `resolve_credential_bundle()`
  unchanged** (`invoker.py`, mirroring 2.2.2's own exactly) — proven end
  to end against this platform's own dev database, including a genuine
  stored, encrypted credential. **Deliberately not wired into the
  model-driven tool loop** — Milestone 1 stays untouched.
- One new dependency (`boto3`) for the S3-compatible backend; no new
  dependency needed for the filesystem backend.
- No migration; no new HTTP route.
- 82 new backend tests. Backend **1,245** total green (1,163 + 82), 1
  deselected; backend only. See
  [docs/integration/connectors.md](docs/integration/connectors.md)'s
  "Generic File & Object Storage Connector" section.

Next: 2.2.4 (Generic Message Queue Connector). 2 of 9 Milestone 2
sub-phases remain.

### Part 2.2.4 — Generic Message Queue Connector ✅

**Milestone 2's fourth and last generic connector — completing the
connector framework and every generic connector.** Two-sided
containment: publish is scoped to a queue fixed by the tool contract
itself (never a model-supplied name), and consume is always bounded to
at most N messages within a bounded wait, never an unbounded stream.

- **`QueueConnector`** (`app/integration/connectors/queue/`) turns
  declared queue bindings into governed publish/consume tools. AMQP
  (RabbitMQ) and SQS fully supported; Azure Service Bus recognized but
  backend-pending.
- **A publish tool contract has no queue-name parameter at all** — the
  target is fixed by the tool contract itself, so "the model cannot
  redirect a publish outside its declared queue" holds by absence of the
  affordance, not by validating a supplied name.
- **The scope check (`scope.py`) has zero imports of any kind** —
  simpler than 2.2.3's path enforcer by design, since there is no
  queue-name value to canonicalize. Its one job: does a resolved
  binding's declared operation match what is being attempted against it.
- **Consume is bounded on two axes, proven live against a fixtured
  transport**: never more than the binding's batch cap regardless of how
  many messages the queue holds, never past its wait timeout regardless
  of what the caller asks for.
- **An oversized consumed message is truncated and flagged, not
  discarded** — a deliberate departure from the database/storage
  connectors' own "reject the whole operation" precedent, since a
  consume batch is a set of otherwise-independent messages.
- **Acknowledgment policy is explicit: ack-on-retrieve, at-most-once** —
  documented per backend (AMQP `auto_ack=True`; SQS `delete_message`
  right after `receive_message`), not left implicit.
- **Zero SDK-surface deviations** — a first among the generic
  connectors, since this phase's own error codes are entirely
  invocation-time.
- **The fourth tool-invocation bridge, reusing 2.2.3's audit event** —
  two entry points (`publish_message`/`consume_messages`) rather than
  one, each checking permission before touching a broker. **Deliberately
  not wired into the model-driven tool loop** — Milestone 1 stays
  untouched.
- One new dependency (`pika`) for AMQP; SQS reuses 2.2.3's `boto3`.
- No migration; no new HTTP route.
- 50 new backend tests. Backend **1,295** total green (1,245 + 50), 1
  deselected; backend only. See
  [docs/integration/connectors.md](docs/integration/connectors.md)'s
  "Generic Message Queue Connector" section.

**Milestone 2's connector framework and all four generic connectors are
now complete — 8 of 9 sub-phases done.**

Next: 2.3.1 (External Identity Federation) — the last Milestone 2
sub-phase.

### Part 2.3.1 — External Identity Federation ✅

**Milestone 2's ninth and final sub-phase — the Enterprise Integration
Framework is now complete.** The inversion from every 2.2.x connector:
a connector authenticates the *platform* outward to an external system,
holding a platform secret and presenting it; federation authenticates a
*user* inward to the platform, verifying a signed assertion, and holds
none of the user's own credential, ever.

- **OIDC (authorization-code flow) and SAML 2.0 (web-browser SSO)**,
  configurable per organization for Entra ID, Okta, or generic
  OIDC/SAML providers. Lives under `app/identity/federation/`, not
  `app/integration/` — this is identity's own concern, not the
  connector framework's.
- **Neither protocol's signature verification is hand-rolled.** OIDC
  via `python-jose` (already a dependency): the accepted algorithm set
  is fixed by the org's own stored config, never the token's own `alg`
  header (closing algorithm-confusion); the signing key is resolved
  from the IdP's JWKS by `kid`, no fallback. SAML via
  `python3-saml`/`xmlsec`: signature verification delegated entirely to
  the security-audited `libxmlsec1` C library, `strict: True` always
  set. Both proven against real cryptographic material — a freshly
  generated RSA keypair for OIDC, real `xmlsec`-signed XML (including
  two distinct signature-wrapping attack shapes) for SAML — never a
  mock signer.
- **Maps into the platform's existing user/RBAC model, never a parallel
  one.** Linked by stable subject id (OIDC `sub`/SAML `NameID`), never
  email. An existing local account is always linked by email on first
  login; JIT-provisioning a genuinely *new* user is gated per-org by a
  `jit_provisioning_enabled` flag, reusing the existing
  `UserProvisioningService` seam verbatim.
- **Session issuance terminates in the platform's existing pipeline** —
  the same `SessionLifecycleService`/`RefreshRotationService`/
  `IdentityContextResolver`/`TokenService` quartet password login uses
  — never a parallel session/token mechanism. Always `AAL1`: the
  platform cannot verify what MFA the IdP itself enforced, and never
  claims a stronger assurance level than it can stand behind.
- **Stateless CSRF/replay defense** — OIDC `state`/SAML `RelayState` are
  short-lived, platform-signed JWTs reusing the existing
  `JWT_SECRET_KEY`, not a new "pending requests" table.
- 4 public routes (login/callback/SAML ACS/metadata) + 6 admin CRUD
  routes; two new permissions. Two new tables
  (`identity_federation_configs`, `federated_identities` — the latter
  with **no credential column of any kind**); migration
  `0036_identity_federation`. Route count 474 → 484; schema 107 → 109
  tables.
- **Local authentication keeps working unchanged, proven, alongside
  federation.**
- New dependencies: `python3-saml`, `xmlsec`, `lxml`, `isodate`.
- 57 new backend tests. Backend **1,352** total green (1,295 + 57), 1
  deselected; backend only. See
  [docs/identity/federation.md](docs/identity/federation.md).

**Milestone 2 — the Enterprise Integration Framework — is now COMPLETE:
9 of 9 sub-phases done.**

Next: Milestone 3 (Deployment & Release).

## Milestone 3 — Deployment & Release (Phase 3.x)

Ten sub-phases (`ACT-SRS-M3`): the deployment lifecycle core (3.1),
environments/promotion (3.2), preflight/release gates (3.3), traffic
allocation and the version-resolver/execution gate (3.4), canary/
progressive rollout (3.5), blue-green/recreate strategies (3.6),
rollback (3.7), a real distributed scheduler (3.8), distributed
workers and the rolling strategy (3.9), and an operator frontend
(3.10).

### Part 3.1 — Enterprise Deployment Core ✅

**The first sub-phase — builds the deployment state machine and its
authority, not traffic, not canary, not workers.** Turns the existing,
partially-wired `agent_deployments` table into a governed domain: a
real 15-state lifecycle with one transition authority, append-only
event lineage, optimistic-concurrency protection, and idempotent
commands — while leaving the pre-existing `status` field, every legacy
`DeploymentService` method, and the Milestone 1 execution gate
completely untouched.

- **`lifecycle_state`** (new, second, independent field on
  `agent_deployments`) — 15 states, one transition authority
  (`DeploymentLifecycleService.transition()`), mechanically checked as
  the only write site. The pre-existing `status` column keeps being
  read/written, unmodified, by every legacy method, including the one
  place execution actually gates on deployment state.
- **Ruling #6 (suspension/kill integration)**: reads — never writes —
  the platform's existing `Agent.lifecycle_status == "SUSPENDED"`
  mechanism every time a deployment would reach `ACTIVE`. No parallel
  kill-switch built.
- **The reusable `Idempotency-Key` contract**, claim-then-poll (not
  naive check-then-act) — closes a genuine TOCTOU race under real
  concurrency, proven with two real threads racing the same key.
- **Optimistic concurrency** via a genuine SQLAlchemy `version_id_col`
  — proven live with two threads racing one transition, exactly one
  succeeds.
- **Two real conflicts between the build prompt and the shipped
  codebase, found and resolved, not silently redesigned around**: the
  literal `/pause`/`/resume`/`/retire` paths collide with routes
  already shipped in Phase 5.0 (resolved by nesting the new routes
  under `/lifecycle/...`); the suggested permission names don't match
  this platform's actual `runtime.deployment.*` convention (resolved
  by reuse).
- New tables `deployment_events` (append-only lineage) and
  `idempotency_keys`; four new `agent_deployments` columns; the §15
  deterministic migration backfilling every existing deployment's
  legacy `status` into an initial `lifecycle_state`, once, live.
- 5 new routes; no new permissions. Route count 484 → 489.
- 27 new backend tests. Backend **1,379** total green (1,352 + 27), 1
  deselected; backend only. See
  [docs/deployment/lifecycle.md](docs/deployment/lifecycle.md).

**Milestone 3 now has 1 of 10 sub-phases done.**

### Part 3.2 — Environment & Promotion Model ✅

**The second sub-phase.** Turns `agent_deployments.environment` — a
bare, unvalidated string — into a governed, tenant-scoped `Environment`
entity with real policy, and adds a promotion operation that moves a
version's deployment eligibility between environments while
**preserving the exact same immutable version**, never cloning, never
modifying.

- **`environment_id`** (new, second, additive field on
  `agent_deployments`) — a real FK to the new `environments` table.
  The pre-existing `environment` string keeps being read, unmodified,
  by the one place execution actually reads it (the Milestone 1
  policy engine).
- **Governed `Environment` entities**: tenant-scoped, standard
  `DEVELOPMENT`/`TEST`/`STAGING`/`PRODUCTION`/`SANDBOX` plus custom,
  each carrying a policy document (allowed models/data
  classifications, required approvals, concurrency limits, change
  windows). `PromotionPath` — the org-configured graph of legal
  promotions.
- **Immutability preserved by construction, not just by test**: the
  source version is loaded once and passed straight into the
  pre-existing deployment constructor — nothing in the new module can
  construct, copy, or mutate a version row. Verified live: same
  version id, unchanged version count, byte-identical
  checksum/digest/signature before and after.
- **Both mandatory inspections completed and integrated, not
  paralleled**: `prohibited_environments` reads the exact same
  version-policy field the Milestone 1 execution-time policy engine
  already reads; release channels found orthogonal to environments (a
  stability track vs. a deployment target) — promotion never touches
  a version's channel.
- **Approval folded into the existing single funnel** — a governed
  environment's own approval requirement is one more condition on the
  same reroute Phase 3.1 already built, never a second mechanism.
- **The previously declared-but-undriven `ACTIVE`/`PAUSED` →
  `SUPERSEDED` lifecycle edge is now driven** by promotion, when a
  newer deployment lands in the same agent+environment slot.
- New tables `environments`/`promotion_paths`; one new
  `agent_deployments` column; the §15 deterministic migration seeding
  the standard environments and a default promotion chain, and
  backfilling every existing deployment's `environment_id`, once,
  live, for 4,559 organizations.
- 10 new routes; two new permissions
  (`runtime.environment.view`/`.manage`). Route count 489 → 499.
- 29 new backend tests. Backend **1,408** total green (1,379 + 29), 1
  deselected; backend only. See
  [docs/deployment/environments.md](docs/deployment/environments.md).

**Milestone 3 now has 2 of 10 sub-phases done.**

Next: 3.3 (preflight/release gates).

## Future (Phase 3+)

**Milestone 3, remaining**: preflight/release gates (3.3), traffic
allocation and the version-resolver/execution gate (3.4 — the one
change to the Milestone 1 execution entry path this whole milestone
builds toward), canary/progressive rollout (3.5), blue-green/recreate
strategies (3.6), rollback (3.7), a real distributed job scheduler
(3.8 — 2.1.3's own health-check scheduler is explicitly interim and
built to be replaced, not extended, when this lands), distributed
workers and the rolling strategy (3.9), an operator frontend (3.10).
**Milestone 2 is complete** (connector framework, all four generic
connectors — REST, database, storage, queue — and external identity
federation). SQL Server support for the database connector, Azure Blob
support for the storage connector, and Azure Service Bus support for
the queue connector all remain driver-/backend-pending, not yet
scheduled. Beyond that: retiring the legacy
`/auth/login` surface (now the platform's only non-revocable
credential), platform-layer MFA, SCIM bulk sync, Slack/webhook
notifications, observability (Prometheus / OpenTelemetry), anomaly
detection, load testing, a connector marketplace (Milestone 12), the
visual Studio.
