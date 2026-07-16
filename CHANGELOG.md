# Changelog

All notable changes to the AI Agent Control Tower are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/); the project is pre-1.0 and
versions track the roadmap phases rather than semver guarantees.

## [Unreleased] — Phase 4.3 · Enterprise Authorization Platform

### Part 4.3.7 — Enterprise authorization administration portal

- **Added** the `/api/v1/admin` control plane (§18) — 20 endpoints in
  `app/authorization/admin/`, each a thin, permission-gated delegation to the
  existing phase services (no duplicated authorization logic, all enforcement
  through the 4.3.6 gateway): dashboard, roles CRUD, the permission catalog,
  the organization tree, the resource registry, ABAC policy CRUD, the policy
  simulator, the authorization decision explorer, access reviews and security
  analytics.
- **Added** the administration dashboard (§6): twelve tenant-scoped widgets
  (users, roles, permissions, policies, sessions, requests/denied 24h, pending
  approvals, MFA challenges, high-risk decisions, cache hit ratio, evaluation
  latency) and five charts (authorization trend, top permissions, policy
  matches, decision breakdown, approval queue).
- **Added** **access review campaigns** (§14; migration `0021`):
  `access_review_campaigns` + `access_review_items` with the DRAFT → SCHEDULED
  → ACTIVE → COMPLETED → ARCHIVED lifecycle. Activation snapshots every
  in-scope role assignment; reviewers certify or revoke each item — a revoke
  removes the underlying assignment through the RBAC service (caches
  invalidate, `ROLE_REMOVED` fires); completion requires every item decided;
  reports export as JSON with an `AUDIT_EXPORTED` event.
- **Added** the **authorization decision explorer** (§13): filterable,
  tenant-isolated decision history (identity, permission, resource, outcome,
  time range) with per-row detail; every query emits `DECISION_VIEWED`.
- **Added** the **security analytics dashboard** (§17): denied trends,
  high-risk decisions, MFA/approval rates, latency (avg/p95), cache
  performance, ABAC denies/challenges, top denied permissions and resource
  sharing trends.
- **Added** 10 portal permissions (`admin.*`, §21 — separable from the raw
  `role.manage`/`authorization.abac.*` sets) and 8 audit events (§22:
  `ACCESS_REVIEW_*`, `SIMULATION_EXECUTED`, `DECISION_VIEWED`,
  `AUDIT_EXPORTED`).
- **Frontend**: `modules/admin` — AdminDashboardPage, DecisionExplorerPage,
  AccessReviewsPage (create/activate/decide/complete/export), 
  SecurityAnalyticsPage and the permission-aware `AdminNav` unifying the
  4.3.1–4.3.5 pages (roles, organization explorer, resources, ABAC builder,
  simulator, audit) into one §5 navigation; routes under `/admin`; portal
  entry card in Settings → Security.
- **Docs**: `docs/admin/{dashboard,roles,organization-explorer,
  resource-management,abac-builder,policy-simulator,decision-explorer,
  access-reviews,audit-center,security-analytics}.md`; ERD + README + ROADMAP
  updated.

### Part 4.3.6 — Enterprise authorization middleware & enforcement architecture

- **Added** `app/authorization/middleware/`: the **AuthorizationGateway** (§22) —
  the single coordination point through which every enforcement surface authorizes;
  an immutable **AuthorizationContext** (frozen dataclass + read-only mappings,
  `identity.*` spoofing stripped at build time) assembled only by the
  `AuthorizationContextBuilder`; a pinned ten-stage **pipeline** (AUTHENTICATION →
  IDENTITY_CONTEXT → SESSION_VALIDATION → ORGANIZATION_CONTEXT → RBAC →
  RESOURCE_AUTHORIZATION → ABAC → OBLIGATIONS → AUDIT → CACHE) whose trace service
  rejects out-of-order recording; an **ObligationExecutor** (approval / MFA /
  justification flags, recursive field masking, parameter clamping, security
  notification); a **DecisionCacheService** keyed by identity × permission ×
  resource × org × RBAC-version × ABAC-generation (+ TTL and per-identity epoch —
  role, policy, org and session-revocation changes all invalidate; challenges and
  dynamic contexts never cached); `PipelineMetricsService` (§34) and the six §24
  audit events (`AUTHORIZATION_STARTED/COMPLETED/FAILED`, `DECISION_GENERATED`
  with the full pipeline trace, `OBLIGATIONS_APPLIED`, `EXECUTION_COMPLETED`).
- **Changed** every enforcement point onto the gateway (§27–§31):
  `require_permission` (all routes) now runs the full pipeline — ABAC challenges
  surface as typed errors (`APPROVAL_REQUIRED` 403, `MFA_REQUIRED` 401,
  `JUSTIFICATION_REQUIRED` 403, satisfiable in-band via `X-Justification`),
  constraint decisions ride on `request.state.authorization`, and plain denials
  keep the legacy 403 contract; `POST /api/v1/authorization/check` became a thin
  gateway call; the **agent runtime** (`process_agent_action`) applies the ABAC
  layer for agent principals (deny → BLOCK, approval → PENDING_APPROVAL into the
  human-review queue) and reports EXECUTION_COMPLETED; background workers,
  schedulers and workflow nodes authorize via `authorize_background(...)` (no
  session; account state still enforced).
- **Added** `evaluate_for_agent` to the ABAC engine (subject = AI_AGENT built
  server-side; `ai_context` may only contribute `ai.*` / `environment.*` keys) and
  a monotonic `generation` to the policy cache powering decision-cache rotation.
- **Fixed** a get-or-create race in the permission-version bootstrap (concurrent
  first requests for one org) with `ON CONFLICT DO NOTHING`.
- **Security (§36)**: middleware mandatory (bypass test proves routes fail without
  it); default deny preserved; ABAC evaluation errors **fail closed**; immutable
  context; challenge errors leak no policy internals; cached decisions are
  per-identity (poisoning impossible by key construction) and tamper-proof
  (copies out); session revocation invalidates instantly.
- **Added** `GET /api/v1/authorization/middleware/metrics` (§34) and error codes
  `ABAC_DENIED`, `APPROVAL_REQUIRED`, `JUSTIFICATION_REQUIRED` (§25).
- **Frontend (§32, §33)**: `AuthorizationProvider` (wraps the 4.3.2
  PermissionProvider; routes gateway decisions and typed API errors to the
  matching UI), `ApprovalRequiredDialog`, `MFAChallenge`, `ObligationDialog`
  (justification capture, mask/limit display), `AuthorizationErrorBoundary`,
  `PermissionGuard`, `useAuthorize` (live gateway check) and
  `decisionToUi` / `maskFields` / `actionLimits` utilities.
- **Docs**: `docs/authorization/{middleware,pipeline,obligations,context,gateway}.md`;
  README + ROADMAP updated.

### Part 4.3.5 — Attribute-Based Access Control engine (ABAC)

- **Added** the ABAC schema (migration `0020`): `abac_policies` (versioned,
  lifecycle-managed context policies — a NULL `organization_id` marks a platform policy
  no tenant can override), `abac_policy_versions` (immutable published snapshots, no FK
  so history survives deletion), `attribute_definitions` (the attribute registry),
  `abac_evaluations` (one row per decision with the redacted explanation) and
  `abac_policy_exceptions` (time-boxed, approved, auto-expiring exemptions).
- **Added** `app/authorization/abac/`: attribute registry + five providers
  (subject/resource/action/environment/AI) behind an `AttributeContextBuilder` — only
  registered attributes may appear in policies; an `OperatorRegistry` mapping all 16
  comparison operators to safe functions (no dynamic code execution, regex length +
  nested-quantifier guards against ReDoS); a recursive `ConditionEvaluator` for nested
  ALL/ANY/NOT trees (depth-capped, with a per-condition trace);
  `PolicyValidationService` (schema, attribute existence, data types, operators,
  effects, obligations); policy lifecycle DRAFT → VALIDATED → ACTIVE →
  DISABLED/DEPRECATED/ARCHIVED with publish-time snapshots, clone and rollback;
  a `PolicyResolver` (scope + target matching over the org hierarchy, per-org cache
  invalidated on any policy/attribute change); five combining algorithms
  (`DENY_OVERRIDES` default — deny → approval → MFA → justification → mask/limit →
  allow); an `ObligationService` (CREATE_APPROVAL, REQUIRE_MFA, REQUIRE_JUSTIFICATION,
  MASK_FIELDS, LIMIT_ACTION, LOG_ONLY) and a `DecisionExplanationService` that redacts
  RESTRICTED attribute values from user-facing output.
- **Changed** `POST /api/v1/authorization/check` to run ABAC **after** the baseline:
  RBAC/resource deny is final (ABAC can never grant); on baseline allow ABAC may deny,
  challenge (`REQUIRE_APPROVAL` / `REQUIRE_MFA` / `REQUIRE_JUSTIFICATION`) or constrain
  (`MASK_FIELDS` / `LIMIT_ACTION`); no applicable policy → the baseline decision stands.
  Responses now carry `decision` + `obligations`.
- **Added** 26 `/api/v1/authorization` endpoints (§30): policy CRUD, validate / publish /
  disable / archive / clone, versions + rollback, simulate (stack-wide and single-policy,
  read-only — the simulator never executes the action and is the only place subject
  attributes may be overridden), evaluate, the evaluation log, ABAC metrics, the
  attribute catalog and policy exceptions (expiry mandatory).
- **Security (§40)**: default deny preserved; only registered operators/attributes;
  caller context can never spoof `identity.*` attributes; platform policies are not
  overridable; published history is immutable; cross-tenant policies and evaluations are
  invisible; sensitive values masked in explanations and logs; 13 error codes; 17 audit
  events; 10 permissions (`authorization.abac.*`, `authorization.attribute.manage`,
  `authorization.exception.manage`) with authoring and publishing separable for
  segregation of duties.
- **Added** the admin portal (Settings → Security → Context policies): ABAC policies
  (list/detail/create/edit with the **visual policy builder** — nested condition groups,
  attribute/operator/typed-value selectors, human-readable preview, raw JSON for
  advanced admins), version history, the **Policy Simulator**, the attribute catalog,
  the evaluation viewer and policy exceptions.
- **Docs**: `docs/authorization/abac/{overview,policy-language,attributes,operators,
  combining-algorithms,policy-lifecycle,policy-simulation,security}.md`; ERD + README +
  ROADMAP updated.

### Part 4.3.4 — Enterprise resource-based authorization (RBAC + Resource ACL)

- **Added** the protected-resource registry and per-resource authorization metadata
  (migration `0019`): `resources` (owner + owner_type, visibility PRIVATE→PUBLIC_INTERNAL,
  status, JSONB resource policy), `resource_acl`, `resource_shares`, `ownership_history`,
  `resource_delegations` — all org-anchored, satellites cascading with the registry.
- **Added** `app/authorization/resources/`: `ResourceAuthorizationService` (the §5/§18
  evaluation chain — org scope → roles → explicit deny → policy → ownership → ACL →
  delegation → sharing → visibility → default deny, with a step trace), plus registry,
  ACL, sharing, ownership (audited transfers + preserved history), delegation and policy
  services and a `MembershipResolver` for USER/ROLE/TEAM/DEPARTMENT/ORGANIZATION
  principals.
- **Changed** the Permission Engine check (`POST /api/v1/authorization/check`) to route
  **registered** resources through the resource-level chain — identical roles, different
  per-resource answers; unregistered resources keep the 4.3.2/4.3.3 path.
- **Added** 20 `/api/v1/resources` endpoints (§19): registry CRUD + types,
  owner / transfer-ownership / ownership-history, ACL CRUD, share/update/revoke,
  delegate/revoke/list, policy, and `POST /resources/{id}/authorize` with identity
  simulation (`resource.manage`) powering the **Authorization Inspector**.
- **Security (§22)**: default deny; explicit deny overrides every allow; owners cannot
  bypass global denies or resource policies; platform admins cannot be ACL-denied on
  SYSTEM resources; cross-org lookups 404 and cross-org sharing is rejected; expired
  ACL entries/shares/delegations are ignored. 14 audit events
  (`RESOURCE_SHARED/UNSHARED`, `RESOURCE_OWNER_CHANGED`, `RESOURCE_ACL_CREATED/UPDATED/
  DELETED`, `RESOURCE_DELEGATED/DELEGATION_REVOKED`, `RESOURCE_POLICY_UPDATED`,
  `RESOURCE_ACCESS_GRANTED/DENIED`, …); 9 error codes; permissions
  `resource.view` / `resource.manage`.
- **Added** the admin portal (Settings → Security → Resources): Resource permissions,
  Resource ACL (search/filter + effect toggle), Sharing, Ownership transfer (+history),
  Delegation management, Authorization Inspector.
- **Docs**: `docs/authorization/{resource-authorization,resource-acl,resource-sharing,
  delegation}.md`, `resource-ownership.md` + ERD + README updated.
- **Tests**: backend **442** green (21 new: ownership/transfer, ACL deny precedence +
  expiry, sharing levels + cross-tenant, delegation lifecycle + expiry, visibility,
  policy, inspector, audit, §25 perf); frontend **242** green (7 new). tsc + build clean.

### Part 4.3.3 — Enterprise organization hierarchy

- **Added** the full hierarchy — Platform → Organization → Business Unit → Department →
  Team → Project → Resources — extending existing tables (migration `0018`): new
  `business_units`, `projects`, `resource_ownership`, `delegations`; `organizations`
  +slug/owner, `departments` +business_unit/status, `teams` +status.
- **Added** services: entity CRUD (org/BU/dept/team/project) with parent validation and
  child-deletion guards, `HierarchyResolverService`, `ResourceOwnershipService`,
  `OrganizationHierarchyService` (tree), `DelegationService` (with boundary enforcement).
- **Changed** the Permission Engine to resolve a resource's ownership path into the
  check's `ResourceContext` — scoped grants now apply via **downward inheritance** — and
  to enforce **cross-organization isolation** (foreign-org resources denied unless the
  caller holds `*` or an active delegation).
- **Added** 20+ `/api/v1` endpoints (organizations, business-units, departments, teams,
  projects, hierarchy/tree, resource-ownership, delegations) gated
  `organization.view`/`.manage`; 10 org audit events; error codes `CROSS_ORG_FORBIDDEN`,
  `ENTITY_HAS_CHILDREN`, `DELEGATION_EXCEEDS_AUTHORITY`, `BUSINESS_UNIT_NOT_FOUND`, ….
- **Added** the admin portal (Settings → Security → Organization): a searchable Hierarchy
  Explorer tree plus Business units, Departments, Teams, Projects and Delegation pages.
- **Docs**: `docs/authorization/{organization-hierarchy,hierarchy-resolution,
  resource-ownership,delegated-administration}.md`.
- **Tests**: backend **421** (8 new: CRUD/tree, department inheritance, cross-org
  isolation, delegation boundary, resolver); frontend **235** (3 new). tsc + build clean.

### Part 4.3.2 — Enterprise Permission Engine

- **Added** a centralized `PermissionEngine` (`app/authorization/engine.py`) with pure
  resolvers: Role (assigned + inherited), Permission (grant list), Wildcard (`resource.*`
  + global `*`), Scope (global→resource), Conflict (**explicit deny wins**, default deny).
- **Added** a Postgres permission cache: `permission_cache` (resolved grants per identity)
  + `permission_versions` (per-org invalidation token, bumped on any role/permission/
  assignment change) + `role_permissions.effect` (ALLOW/DENY) + `authorization_decisions`
  (decision audit with timing). Migration `0017`.
- **Changed** `require_permission` to gate through the engine platform-wide — inheritance,
  wildcards, scope and deny now apply on every endpoint (all existing checks preserved).
- **Added** `POST /api/v1/authorization/check` (evaluate the caller's access;
  `evaluation_time_ms`, `cache_hit`), role create/update `denied_permissions`, and error
  codes `ROLE_NOT_ASSIGNED`, `RESOURCE_FORBIDDEN`, `EXPLICIT_DENY`, `AUTHORIZATION_FAILED`,
  `PERMISSION_CACHE_MISS` (§28).
- **Added** the frontend permission layer: `PermissionProvider`, `usePermissions`/`useCan`,
  `ProtectedComponent` / `RequirePermission` (wildcard-aware; server is source of truth).
- **Docs**: `docs/authorization/{permission-engine,permission-resolution,wildcards,scopes,
  caching}.md`.
- **Tests**: backend **408** (25 new: wildcards, scope, conflict/deny, cache invalidation,
  `/check`, decision audit); frontend **232** (8 new). tsc + build clean.

### Part 4.3.1 — Enterprise RBAC foundation

- **Added** a new `app/authorization/` package extending the existing flat RBAC:
  role category/status/priority/assignability, a domain-grouped `resource.action`
  permission catalog, scoped role assignments (global → resource, time-boxed), an acyclic
  role hierarchy (senior inherits descendants), and an `authorization_audit` trail.
- **Added** three tables (`permission_groups`, `role_hierarchy`, `authorization_audit`)
  and columns on `roles`/`rbac_permissions`/`role_permissions`/`user_roles` — migration
  `0016`, additive. 18 built-in roles seeded globally alongside the legacy four.
- **Added** 15+ `/api/v1` endpoints (roles, permissions, permission-groups,
  role-assignments, role-hierarchy, authorization/audit) gated on
  `role.view`/`role.manage`/`role.assign`, and error codes `ROLE_ALREADY_EXISTS`,
  `CIRCULAR_ROLE_HIERARCHY`, `SYSTEM_ROLE_PROTECTED`, `ROLE_HAS_ASSIGNMENTS`,
  `INVALID_PERMISSION_NAME`, `INVALID_SCOPE`, … (§24).
- **Added** the admin portal (Settings → Security → Authorization): Roles, Permissions,
  Permission groups, Assignments, Hierarchy, Audit.
- **Docs**: `docs/authorization/{rbac,roles,permissions,role-hierarchy}.md`.
- **Tests**: backend **383** (31 new: cycle detection, scope validation, CRUD, inheritance,
  audit); frontend **221** (4 new). tsc + build clean.

## [0.4.0] — Phase 4.2.2 · Enterprise Human Authentication

The identity platform now spans authentication → sessions → registration → password
policy → recovery → account protection, closed out by an integration & release pass.

### Part 4.2.2.3.5 — Backend APIs, integration & release (close-out)

- **Added** cross-cutting HTTP middleware (`app/core/middleware.py`):
  - `RequestContextMiddleware` — a stable `X-Request-ID` on every request/response
    (inbound if supplied, else a generated UUID4), threaded into the error envelope (§15).
  - `SecurityHeadersMiddleware` — `X-Content-Type-Options: nosniff`, `X-Frame-Options:
    DENY`, `Referrer-Policy`, deny-by-default `Content-Security-Policy`,
    `Permissions-Policy`, and opt-in HSTS on every response, errors included (§16, §23).
- **Added** the standard §5 **response envelope**: `ResponseEnvelopeMiddleware` wraps
  every 2xx JSON response under `/api` as `{success, data, meta:{request_id, timestamp}}`
  (leaving `/health`, `/openapi.json` and file exports untouched); errors gain a matching
  `meta`. The SPA unwraps it centrally (`services/envelope.ts`, used by the axios
  interceptor and the bare refresh client), so no service code changed. Toggle:
  `RESPONSE_ENVELOPE_ENABLED`.
- **Added** a full-stack deployment: `frontend/Dockerfile` (Vite build → nginx serving the
  SPA and reverse-proxying `/api`), `frontend/nginx.conf`, a `web` service in
  `docker-compose.yml` (web + api + db, same-origin, no CORS), and `docs/deployment.md`
  with the §24 release checklist (provided vs operator-supplied).
- **Added** `SECURITY_*`, `REQUEST_ID_HEADER`, `RESPONSE_ENVELOPE_ENABLED` settings;
  `docs/api/http-conventions.md`, `docs/testing/strategy.md`, this changelog.
- **Verified** the §4 API contract end-to-end. Remaining honest deviation:
  admin/invitation/password routes live under `/identity` & `/security` (stable paths);
  no unreachable `logout-all`/`device-delete` stubs added.
- **Tests**: backend **352 passing** (+11 hardening/envelope tests); measured **92%** line
  coverage on `app.identity` + `app.core`. Frontend tsc + production build clean; web
  Docker image builds.

### Part 4.2.2.3.4 — Account protection & risk-based authentication

- **Added** risk scoring (0–100), progressive lockout (15m→30m→1h→24h→review),
  brute-force/credential-stuffing detection, blocked IPs, protection-rule engine, adaptive
  rate limiting and a CAPTCHA seam. Tables `account_locks`, `identity_risk_events`,
  `blocked_ips`, `identity_protection_rules` (migration `0015`). Security console UI.
- **Known limitations**: MFA `CHALLENGE` decisions fail-safe **deny** until MFA enrolment
  lands; CAPTCHA is a disabled, provider-agnostic seam.

### Part 4.2.2.3.3 — Password reset, account recovery & email change

- **Added** forgot/reset password (30-min single-use tokens, non-enumerating responses,
  revokes all sessions), verified email change, recovery-events dashboard (migration `0014`).

### Part 4.2.2.3.2 — Enterprise password policy & credential management

- **Added** single-source password policy, password history (no reuse of last 10), 90-day
  expiration with warnings, admin temporary-password reset, mandatory first-login change
  (migration `0013`).

### Part 4.2.2.3.1 — Registration, invitations & email verification

- **Added** invited + self-serve registration, invitation lifecycle, email verification,
  Postgres-backed rate limiting (migrations `0011`–`0012`).

### Part 4.2.2.2 — Login, logout & session lifecycle

- **Added** stateful session validation on every request (immediate revocation), device
  trust/block, refresh-token families with reuse detection, admin session management
  (migrations `0009`–`0010`).

### Part 4.2.2.1 — Enterprise human authentication

- **Added** `/api/v1/auth/*` on argon2id, rotating refresh tokens, account lockout, login
  history, silent refresh (migration `0008`).

## [0.3.0] — Phase 3 · Enterprise Dashboard UI

- React 19 + TypeScript SPA: agents, policies, approvals, audit, analytics dashboards.

## [0.2.0] — Phase 2 · Production-oriented platform

- Agent API-key auth, database-driven policy engine, advanced RBAC, email notifications,
  forensic audit, dashboard APIs, risk engine v2, Docker.

## [0.1.0] — Phase 1 · Backend MVP

- FastAPI + PostgreSQL control plane: agents, permissions, risk scoring, approvals,
  immutable audit logs, JWT auth.
