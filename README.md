# AI Agent Control Tower

> A backend control plane that tracks, controls, approves, blocks and audits the actions performed by AI agents.
>
> **Phase 1** (MVP): agents, permissions, risk scoring, approvals, audit logs.
> **Phase 2** (production-oriented): agent API-key auth, a database-driven policy engine, advanced RBAC, email notifications, forensic audit, dashboard APIs, risk engine v2, and Docker. See the [Phase 2 guide](#phase-2--production-oriented-platform) below.
> **Phase 3** (enterprise dashboard UI): a React 19 + TypeScript web console (`frontend/`) that consumes the Phase 1/2 APIs. Delivered: **Part 1** (scaffold + dark theme + app-shell), **Part 2** (JWT auth + sidebar/top-nav + route guards), **Part 3.1** (live operational dashboard — KPIs, charts, approval queue, recent actions/audit, system health, 60s auto-refresh), **Part 3.2a** (agent-management module — server-driven table, create wizard, details + stats, edit, lifecycle), **Part 3.3** (policy-management module), **Part 3.4** (approval queue & human review workbench — statistics cards, filterable queue, detail page, review workbench with approve/reject/escalate/assign, risk breakdown, audit timeline, history & escalations boards), **Part 3.5** (enterprise Audit & Compliance Center — audit dashboard with statistics + activity timeline + recent events, a filterable/searchable/paginated events explorer, forensic event detail with request/response viewers and a related-events flow, plus RBAC-gated security & compliance dashboards and a multi-format export center), **Part 3.6** (enterprise Analytics & AI Operations Center — executive KPI grid with live trends, AI fleet health, an activity overview chart, a risk analytics dashboard with heatmap, a performance dashboard with agent ranking, policy & human-review analytics, an estimated cost dashboard, a reports center with export, rule-based AI insights, and role-gated executive/operations dashboards with auto-refresh). See [`frontend/README.md`](frontend/README.md) and [`ROADMAP.md`](ROADMAP.md).
>
> **Phase 4** (enterprise identity): **Part 4.1** (Enterprise Identity Platform foundation — an isolated `app/identity` package giving every human, AI agent, service account, organization and external application a formal identity model with a consistent lifecycle. Adds the org → department → team hierarchy, sessions/refresh-tokens/device-sessions and security events, a repository + service architecture, a versioned `/api/v1/identity` API with a standard error envelope, and identity audit integration; see [`docs/phase-4-part-1.md`](docs/phase-4-part-1.md)), **Part 4.2.1** (authentication architecture & trust model — an `app/identity/auth` layer with the `IdentityContext`, seven core auth services (authentication/token/refresh-token/credential/session/security-event/resolver) with real login → rotation → reuse-detection → logout, an authentication middleware dependency, auth enums/error codes/security-event types, a threat model and a token-table migration plan; see [`docs/identity/`](docs/identity/)), and **Part 4.2.2.1** (enterprise human authentication — the `/api/v1/auth/*` endpoints (login/refresh/logout/me/sessions) on those services, **argon2id** password hashing with legacy-bcrypt auto-upgrade, a full password-complexity policy, **account lockout** (5 failures/15 min) backed by a new `login_history` table, and a frontend with silent token refresh + a 401→refresh→retry interceptor + session-expired modal; see [`docs/identity/human-authentication.md`](docs/identity/human-authentication.md)). Later parts add the **permission engine**, **organization hierarchy**, **resource-based authorization**, **ABAC**, **authorization middleware**, the **admin portal**, and **identity governance** — see [`docs/authorization/`](docs/authorization/) and [`docs/governance/`](docs/governance/).
>
> **Phase 5** (agent runtime): agent lifecycle & execution, the enterprise agent **registry**, and immutable, checksummed, **cryptographically signed** versioning with in-toto/DSSE attestations. See [`docs/runtime/`](docs/runtime/).
>
> **Milestone 1** (real execution — **complete**): a model provider abstraction, a real OpenAI-compatible adapter, SSE streaming with real token/cost accounting, an eight-class error taxonomy with retry and circuit-breaking, per-organization encrypted provider credentials, HTTP tool execution behind a hardened SSRF egress guard, tool schema validation, and the model-driven tool invocation loop. An agent now genuinely executes end to end.
>
> **Milestone 2** (Enterprise Integration Framework — **complete, 9/9**): the connector abstraction & lifecycle, a pluggable authentication framework, registry & health, a connector SDK, four generic connectors (REST, database, storage, queue), and external identity federation (OIDC + SAML). See [`docs/integration/connectors.md`](docs/integration/connectors.md) and [`docs/identity/federation.md`](docs/identity/federation.md).
>
> **Milestone 3** (Deployment, Release & Operations — **COMPLETE, 10/10**): the deployment lifecycle core, governed environments & promotion, the release gate, weighted traffic allocation with a version resolver and fail-closed execution gate, the canary rollout engine with AI-aware release health, blue-green/recreate strategies, **automated rollback** — per-tenant trigger policies that roll a failing candidate back on their own, strictly subordinate to the kill switch — a **distributed scheduler** whose instances coordinate through Postgres leases so every due job runs exactly once, and a **distributed execution worker fleet** — agent executions now run on independently-operable worker processes that hold no database lock across model or tool network I/O, with **rolling deployment** defined over real worker cohorts rather than simulated counters, and the **Release Operations Center** — twelve operational views through which an operator sees and drives all of it, with dangerous actions confirmation-gated and unsafe state shown rather than smoothed over. See [`docs/deployment/`](docs/deployment/).
>
> **Current state at a glance** — [Where the project is now](#where-the-project-is-now) below, or [`REPO_STATE.md`](REPO_STATE.md) for the verified, exhaustive version.

As organizations hand more real-world tasks to autonomous AI agents (submitting claims, updating records, sending emails, moving money), they need a control plane that sits between the agent and the action. The **AI Agent Control Tower** is that control plane: every action an agent attempts is checked against permissions, scored for risk, and either **allowed**, **blocked**, or **routed to a human for approval** — and every decision is written to an immutable audit log.

This repository contains the FastAPI + PostgreSQL backend (`backend/`) and the React + TypeScript dashboard (`frontend/`). It is a personal learning / startup project and uses no company code, data, or infrastructure.

For machine-independent source and database backups, scheduled snapshots, and
new-system restore steps, see [`RECOVERY.md`](RECOVERY.md).

---

## Where the project is now

*Verified 2026-08-14 against `main` at `5b33f42`. The narrative sections further
down this file are a phase-by-phase historical log kept in build order; this
section is the current-state summary. For the exhaustive, mechanically-verified
state of the repository — live schema, migration chain, route table, per-module
inventory, known gaps — [`REPO_STATE.md`](REPO_STATE.md) is the authority, and it
is the document to trust if it and this README ever disagree.*

| | |
|---|---|
| Backend tests | **1,770 passed**, 0 failed, 1 deselected |
| Frontend tests | **327 passed** |
| Live schema | **124 tables**, migration head `0044_worker_fleet_rolling` |
| HTTP routes | **540** |

### Milestones

| Milestone | Status | What it delivers |
|---|---|---|
| **Phases 1–4** | Complete | Governance pipeline, dashboard UI, enterprise identity, RBAC/ABAC authorization, identity governance |
| **Phase 5.0–5.2** | Complete | Agent runtime & lifecycle, enterprise registry, immutable signed versioning |
| **Milestone 1** — real execution | **Complete** | Model provider abstraction, a real OpenAI-compatible adapter, streaming & token/cost accounting, an error taxonomy with retry/circuit-breaking, per-organization encrypted credentials, HTTP tool execution behind an SSRF egress guard, tool schema validation, and the model-driven tool invocation loop |
| **Milestone 2** — Enterprise Integration Framework | **Complete (9/9)** | Connector abstraction/lifecycle, a pluggable authentication framework, registry & health, a connector SDK, four generic connectors (REST, database, storage, queue), and external identity federation (OIDC + SAML) |
| **Milestone 3** — Deployment, Release & Operations | **Complete (10/10)** | Deployment lifecycle core, environments & promotion, the release gate, weighted traffic allocation + version resolver, the canary engine, blue-green/recreate/rolling strategies, automated rollback with per-tenant trigger policies, a distributed scheduler, a distributed execution worker fleet, and the Release Operations Center over all of it |

**What "complete" means for Milestone 1**: an agent that is registered,
versioned, signed and deployed genuinely executes end to end — it calls a real
model, the model requests a real tool, the tool runs behind an egress guard, the
result feeds back into the conversation, the loop resolves to a final answer, and
every token, call and decision is audited.

Deliberately not built, with the owning phase named rather than left vague:
vendor-specific connectors (SAP/Salesforce/ServiceNow — fast-follow work once a
real deployment names a vendor). Rolling deployment *was* on this list for three
phases, refusing to simulate itself over vestigial replica counters; Phase 3.9
built the worker fleet and implemented it for real, and Phase 3.10 put an
operator in front of the whole thing. [`REPO_STATE.md`](REPO_STATE.md) §9 keeps the full, honest gap
list, including things that are placeholders rather than features.

---

## How it works

```
AI Agent ── POST /agent-actions ──▶ Permission Check ──▶ Risk Score ──▶ Decision ──▶ Audit Log
                                                                           │
                                                                           ├─ ALLOW            (executed)
                                                                           ├─ BLOCK            (blocked)
                                                                           └─ PENDING_APPROVAL ─▶ Approval Queue ─▶ human approves/rejects
```

**Decision rules**

| Condition                                   | Decision           |
| ------------------------------------------- | ------------------ |
| Agent is not `ACTIVE`                       | `BLOCK`            |
| No permission rule, or rule is denied       | `BLOCK`            |
| Permission granted and `risk_score <= 40`   | `ALLOW`            |
| Permission granted and `41 <= risk <= 80`   | `PENDING_APPROVAL` |
| Permission granted and `risk_score > 80`    | `BLOCK`            |

Every decision — and every approval/rejection — writes an `audit_logs` entry.

**Risk scoring (Phase 1)** is a simple, deterministic table keyed by action (e.g. `READ` = 10, `SEND_EMAIL` = 35, `UPDATE_RECORD` = 55, `SUBMIT_CLAIM` = 75, `DELETE_RECORD` = 90, `TRANSFER_MONEY` = 95, unknown = 85), with a small bump for sensitive payloads (large money amounts).

---

## Tech stack

- **Backend:** Python 3.13 (3.11+ supported) / FastAPI
- **Database:** PostgreSQL 17 (local) — the sole datastore, by
  [ADR-0002](docs/architecture/adr/0002-postgresql-as-sole-datastore.md); no
  Redis, no queue broker, no separate cache
- **ORM:** SQLAlchemy 2.0
- **Migrations:** Alembic (42 revisions, head `0041_canary_rollout`)
- **Auth:** JWT bearer tokens with rotating refresh tokens; **argon2id** password
  hashing (legacy bcrypt auto-upgraded on login)
- **Frontend:** React 19 + TypeScript + Vite, tested with Vitest
- **Crypto:** Ed25519 version signing (in-toto / DSSE attestations), Fernet
  encryption for stored secrets
- **Federation:** OIDC via `python-jose`; SAML 2.0 via `python3-saml` + `xmlsec`
  (XML signature verification is delegated to the audited `libxmlsec1` C library,
  never hand-rolled)
- **Connectors:** `httpx` (REST), SQLAlchemy Core + `PyMySQL` (database), `boto3`
  (S3 storage / SQS), `pika` (AMQP)
- **Docs:** Swagger / OpenAPI (built into FastAPI)

---

## Project structure

```
ai-agent-control-tower/
├── docker-compose.yml          # local PostgreSQL
├── README.md
├── REPO_STATE.md               # verified state of the repository (the authority)
├── ROADMAP.md                  # phase-by-phase roadmap
├── CHANGELOG.md
├── RECOVERY.md                 # backup / restore / system migration
├── docs/                       # architecture, ADRs, and per-domain guides
│   ├── architecture/           # C4 views, ADRs, threat model, ERD
│   ├── identity/               # auth, sessions, credentials, federation
│   ├── authorization/          # RBAC, ABAC, resource authorization
│   ├── governance/             # access certification, SoD, risk scoring
│   ├── runtime/                # agents, versioning, providers, gateways
│   ├── integration/            # connectors (Milestone 2)
│   └── deployment/             # lifecycle, environments, gates, traffic,
│                               #   canary, strategies (Milestone 3)
├── scripts/backup/             # snapshot / verify / restore PowerShell scripts
├── frontend/                   # React 19 + TypeScript dashboard
└── backend/
    ├── alembic.ini
    ├── requirements.txt
    ├── .env.example
    ├── migrations/             # Alembic environment + versions
    ├── tests/                  # backend suite, mirroring the app packages
    └── app/
        ├── main.py             # FastAPI app
        ├── seed.py             # demo data seeder
        ├── core/               # config, database, security, enums
        ├── models/             # SQLAlchemy models (119 tables)
        ├── schemas/            # Pydantic request/response models
        ├── api/                # Phase 1/2 governance API
        ├── services/           # Phase 1/2 engines (permission, risk, decision,
        │                       #   approval, audit, orchestration)
        ├── identity/           # enterprise identity: users, orgs, sessions,
        │                       #   credentials, protection, federation
        ├── authorization/      # RBAC + ABAC engine, gateway, governance
        ├── runtime/            # the agent runtime
        │   ├── registry/       # agent registry
        │   ├── versioning/     # immutable versions, signing, attestation
        │   ├── providers/      # model provider abstraction + adapters
        │   ├── tools/          # egress guard, HTTP executor, concurrency
        │   ├── environment/    # environments & promotion policy
        │   ├── release_gate/   # preflight checks + PASS/WARNING/BLOCK verdict
        │   └── deployment/     # lifecycle, traffic, resolver, canary,
        │                       #   health, strategies
        └── integration/        # Milestone 2 — deliberately a sibling of
            ├── auth/           #   runtime, never imported by it
            ├── connectors/     #   REST, database, storage, queue
            └── sdk/            #   the connector-authoring surface
```

Two placements above are load-bearing rather than stylistic. `app/integration/`
sits beside `app/runtime/` rather than inside it because the runtime must never
know a connector exists — a test greps every file under `app/runtime/` for the
word "connector" and fails the build if it finds one. And
`app/identity/federation/` lives under identity, not integration, because it
authenticates a user *to* the platform rather than the platform *to* an external
system — the inverse trust direction from every connector.

---

## Setup

All commands below are run from the **`backend/`** directory unless noted.

### 1. Start PostgreSQL

**Option A — Docker (recommended):** from the repository root:

```bash
docker compose up -d
```

This starts PostgreSQL 17 on `localhost:5432` with database `ai_agent_control_tower` (user/password `postgres`/`postgres`).

> **Upgrading a checkout you started before Phase 3.9:** `act_pgdata` is a PostgreSQL
> major-version-specific data directory, so 17 will refuse to start against a volume
> written by 16. Dump anything you need, then `docker compose down && docker volume rm
> <project>_act_pgdata`. See [RECOVERY.md](RECOVERY.md) — deliberately not automated,
> because a script that silently dropped a database volume would be worse than the
> mismatch it fixed.

**Option B — local PostgreSQL install:** create the database manually:

```sql
CREATE DATABASE ai_agent_control_tower;
```

### 2. Create a virtual environment & install dependencies

```bash
cd backend
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

Then edit `backend/.env` if your PostgreSQL credentials differ. Key variables:

| Variable                      | Description                                   |
| ----------------------------- | --------------------------------------------- |
| `DATABASE_URL`                | PostgreSQL connection string                  |
| `JWT_SECRET_KEY`              | Secret used to sign JWTs (set a long random)  |
| `JWT_ALGORITHM`               | JWT algorithm (default `HS256`)               |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime (default `1440` = 1 day)       |
| `BACKEND_CORS_ORIGINS`        | Allowed origins for the future dashboard      |

Generate a strong secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 4. Run database migrations

```bash
alembic upgrade head
```

This creates all seven tables. Useful commands:

```bash
alembic current                              # show current revision
alembic history                              # list migrations
alembic downgrade -1                         # roll back one step
alembic revision --autogenerate -m "msg"     # generate a new migration after model changes
```

### 5. Seed demo data

```bash
python -m app.seed
```

This creates the demo organization, two users, three agents and their permission rules (see below).

### 6. Run the API

```bash
uvicorn app.main:app --reload
```

- API base: `http://localhost:8000`
- **Swagger UI:** `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Health check: `http://localhost:8000/health`

---

## Demo data

After running `python -m app.seed`:

**Organization:** `Demo Healthcare Org`

### Onboarding (Phase 4.2.2.3.1)

Organizations are **invitation only** by default. An administrator invites by email
(Settings → Security → Invitations); the invitee sets a password, confirms their email
address, and only then can sign in. Invitation links last 7 days, verification links 24
hours, and both are single-use and stored hashed. Public onboarding endpoints are rate
limited to 5 requests/minute/IP.

See [registration](docs/identity/registration.md), [invitations](docs/identity/invitations.md)
and [email verification](docs/identity/email-verification.md).

### Credential management (Phase 4.2.2.3.2)

Enterprise password lifecycle on top of the argon2id hashing from 4.2.2.1: a single-source
policy (length, character classes, common-password blocklist, keyboard/number sequences,
repeats, and your own name/email/org), **password history** (no reuse of the last 10),
**90-day expiration** with in-app warnings, **administrative reset** issuing a one-time
temporary password, and a **mandatory first-login change** the app cannot be skipped past.
Self-service change is at Settings → Security → Change password; admins get a
**password dashboard** (expired / expiring / temporary users). Every credential event is
audited. See [password policy](docs/identity/password-policy.md),
[credential management](docs/identity/credential-management.md) and
[password history](docs/identity/password-history.md).

### Account recovery (Phase 4.2.2.3.3)

Self-service **forgot password** (a hashed, single-use, 30-minute `rst_` token emailed
as a link), **reset** that runs the full credential discipline and revokes every session,
and **verified email change** (confirm the new address before it takes effect; alert the
old one when it does). Forgot-password is a non-enumerating uniform response; all public
recovery endpoints are rate limited (5/min/IP). Admins get a **recovery-events dashboard**
(Settings → Security → Recovery events). See [password reset](docs/identity/password-reset.md),
[recovery](docs/identity/recovery.md) and [email verification & change](docs/identity/email-verification.md).

### Account protection & risk-based auth (Phase 4.2.2.3.4)

Authentication is no longer binary. Every login is scored (0–100) from signals — new
device/country, impossible travel, failed-attempt count, suspicious agent, blocked IP —
and the score plus admin **protection rules** decide allow / challenge / MFA / lock /
block. **Progressive lockout** (15m → 30m → 1h → 24h → security review) backs a stateful
`account_locks` table; **brute-force & credential-stuffing** patterns are detected per
account/IP/target-set; **blocked IPs** are refused at the door; a **CAPTCHA** seam and
**adaptive rate limits** are in place. Failed logins stay generic (no enumeration, no
signal leak). A security console (Settings → Security → Account protection) shows the
dashboard, login attempts, risk events, locks (with audited unlock), blocked IPs and
rules. See [account protection](docs/security/account-protection.md),
[risk-based auth](docs/security/risk-based-authentication.md),
[brute-force protection](docs/security/brute-force-protection.md),
[account lockout](docs/security/account-lockout.md) and
[protection rules](docs/security/identity-protection-rules.md).

### API contract & HTTP hardening (Phase 4.2.2.3.5)

The Phase 4.2.2 close-out. Every request carries a correlation id (`X-Request-ID`,
generated when absent, echoed on the response and threaded into the error envelope), and
every response — success or error — carries standard security headers (`nosniff`,
`X-Frame-Options: DENY`, a deny-by-default CSP, `Referrer-Policy`, `Permissions-Policy`,
opt-in HSTS). Errors follow the `{success, error:{code,message}, request_id}` envelope;
success bodies stay bare by design. The consolidated endpoint map, response format and
error codes are in [HTTP API conventions](docs/api/http-conventions.md).

### Enterprise RBAC foundation (Phase 4.3.1)

Authorization becomes a first-class subsystem. Enterprise **roles** (with category,
lifecycle status and priority), a `resource.action` **permission catalog** grouped by
domain, **scoped role assignments** (global / organization / department / team / project
/ resource, optionally time-boxed), an acyclic **role hierarchy** (a senior role inherits
its children's permissions), and an **authorization audit** trail. 18 built-in roles ship
seeded alongside the legacy four. Business logic never branches on role names — it gates
on permission codes (`Depends(require_permission("agent.create"))`). Admin portal at
**Settings → Security → Authorization** (Roles, Permissions, Assignments, Hierarchy,
Audit). See [RBAC](docs/authorization/rbac.md), [roles](docs/authorization/roles.md),
[permissions](docs/authorization/permissions.md) and
[role hierarchy](docs/authorization/role-hierarchy.md).

### Permission Engine (Phase 4.3.2)

Every authorization decision flows through one centralized **PermissionEngine** — no
controller ever branches on a role name. It resolves an identity's roles (with
inheritance), collects allow/deny grants, expands **wildcards** (`agent.*`, and the
reserved global `*` for `ROLE_PLATFORM_OWNER`), applies **scope**, and resolves
**conflicts** (explicit deny always wins) before allowing or denying — default deny.
Resolved grants are **cached** per identity (Postgres-backed, version-invalidated on any
role/permission/assignment change) and every decision is auditable
(`authorization_decisions`, with timing). `require_permission` now gates through the
engine platform-wide; `POST /api/v1/authorization/check` answers "can I?" for the caller;
the SPA gets `useCan("agent.create")` and `<ProtectedComponent permission=…>`. See
[permission engine](docs/authorization/permission-engine.md),
[resolution](docs/authorization/permission-resolution.md),
[wildcards](docs/authorization/wildcards.md), [scopes](docs/authorization/scopes.md) and
[caching](docs/authorization/caching.md).

### Organization hierarchy (Phase 4.3.3)

Authorization is now evaluated **within a full organizational hierarchy**: Platform →
Organization → Business Unit → Department → Team → Project → Resources. Permissions flow
**downward** (a department-scoped role authorizes any team/project below it, resolved via
each resource's ownership path), isolation flows **upward** (cross-organization access is
denied by default — a foreign entity 404s), and **delegated administration** lets each
level grant authority only over its own scope (never exceeding the delegator's). Resource
ownership attaches agents/policies/workflows to the tree. Admin portal at
**Settings → Security → Organization** (Hierarchy explorer, Business units, Departments,
Teams, Projects, Delegation). See
[organization hierarchy](docs/authorization/organization-hierarchy.md),
[hierarchy resolution](docs/authorization/hierarchy-resolution.md),
[resource ownership](docs/authorization/resource-ownership.md) and
[delegated administration](docs/authorization/delegated-administration.md).

### Resource-based authorization (Phase 4.3.4)

Every managed object — agents, prompts, workflows, policies, datasets, dashboards,
connectors, … — is a **first-class protected resource** with its own authorization
metadata: an **owner** (user/team/department/organization, transfers audited with
preserved history), an **ACL** (per-principal allow/deny with expiry; explicit deny
always wins), **sharing** (READ → MANAGE levels for users/teams/departments/org, with
expiry), **time-boxed delegation**, **visibility levels** (PRIVATE → PUBLIC_INTERNAL)
and an optional **resource policy** ("only the Compliance team may publish"). The
Permission Engine layers all of this over the role decision, so two users with the same
role can get different answers for the same permission on different resources — default
deny, cross-tenant isolated, every decision auditable. Security admins simulate any
identity × resource × permission in the **Authorization Inspector**. Admin portal at
**Settings → Security → Resources** (Resource permissions, ACL, Sharing, Ownership,
Delegation, Inspector). See
[resource authorization](docs/authorization/resource-authorization.md),
[resource ACL](docs/authorization/resource-acl.md),
[resource sharing](docs/authorization/resource-sharing.md) and
[delegation](docs/authorization/delegation.md).

### Attribute-Based Access Control (Phase 4.3.5)

The final authorization layer is **context-aware**: after RBAC, the organization
hierarchy and the resource chain allow an action, the **ABAC engine** decides whether it
is safe *right now* — evaluating **subject** (roles, clearance, MFA, risk score),
**resource** (classification, PII/PHI flags, environment), **action** (destructive,
data-export, bulk), **environment** (network zone, device trust, business hours, session
risk) and **AI-specific** attributes (autonomy level, model, tool risk) against
versioned, lifecycle-managed policies. A policy's effect can deny, require **human
approval / MFA / justification**, **mask fields** or **limit the action** — and ABAC can
never grant what the baseline denied (default deny stands). Policies use nested
ALL/ANY/NOT conditions over **registered attributes only**, are combined with
deny-overrides precedence, and every decision is explainable (sensitive values redacted)
and audited. Admins get a **visual policy builder**, a read-only **Policy Simulator**,
an attribute catalog, an evaluation viewer and time-boxed policy exceptions at
**Settings → Security → Context policies**. See the
[ABAC overview](docs/authorization/abac/overview.md),
[policy language](docs/authorization/abac/policy-language.md),
[attributes](docs/authorization/abac/attributes.md),
[operators](docs/authorization/abac/operators.md),
[combining algorithms](docs/authorization/abac/combining-algorithms.md),
[lifecycle](docs/authorization/abac/policy-lifecycle.md),
[simulation](docs/authorization/abac/policy-simulation.md) and
[security](docs/authorization/abac/security.md).

### Authorization middleware & enforcement (Phase 4.3.6)

The whole authorization stack now runs behind **one enforcement pipeline**. The
**Authorization Gateway** coordinates authentication context, session state,
organization hierarchy, RBAC, resource authorization, ABAC, obligations, audit,
caching and metrics in a fixed ten-stage order, and every enforcement surface —
REST routes (`require_permission`), the explicit check endpoint, background
workers, scheduled jobs, workflow nodes, the **AI agent runtime** and API-key
integrations — calls the gateway; nothing calls RBAC or ABAC directly. Every
decision carries a stage-by-stage **pipeline trace** stored in the audit trail
(six events, from `AUTHORIZATION_STARTED` to `EXECUTION_COMPLETED`), challenges
surface as typed errors the SPA turns into approval / MFA / justification
flows, constraint decisions (mask fields, limit action) ride with the request,
and final decisions are **cached** with keys that rotate on any role, policy,
organization or session change (warm path <5ms, never caching challenges or
dynamic context). The context object is immutable and spoof-proof; evaluation
errors fail closed. See [middleware](docs/authorization/middleware.md),
[pipeline](docs/authorization/pipeline.md),
[gateway](docs/authorization/gateway.md),
[obligations](docs/authorization/obligations.md) and
[context](docs/authorization/context.md).

### Authorization administration portal (Phase 4.3.7)

A unified **IAM control plane** at `/admin`: an operational **dashboard**
(users, roles, policies, sessions, request/deny volumes, approval queue, MFA
challenges, cache and latency health, trend charts), the **decision explorer**
(searchable, tenant-isolated history of every authorization decision — viewing
is itself audited), **access review campaigns** (periodic certification with a
DRAFT → ACTIVE → COMPLETED → ARCHIVED lifecycle; activation snapshots every
in-scope role assignment, and a reviewer's *revoke* removes the live grant
immediately through the RBAC service), and **security analytics** (denied
trends, high-risk decisions, approval rates, latency percentiles, top denied
permissions). A permission-aware portal navigation unifies the existing roles,
organization, resources, ABAC builder/simulator and audit pages, and a
dedicated `/api/v1/admin` API (10 separable `admin.*` permissions) delegates
every operation to the underlying phase services — one implementation, fully
audited, enforced through the authorization gateway. See
[dashboard](docs/admin/dashboard.md),
[access reviews](docs/admin/access-reviews.md),
[decision explorer](docs/admin/decision-explorer.md),
[audit center](docs/admin/audit-center.md) and
[security analytics](docs/admin/security-analytics.md).

### Identity Governance & Administration (Phase 4.3.8)

A full **IGA** layer at `/governance`, built on the 4.3.1–4.3.7 authorization
platform: **access certification** (reuses the 4.3.7 campaign engine, adds
campaign types and MODIFIED/DELEGATED decisions), **Separation of Duties and
toxic-permission detection** (one rule engine — an identity trips a rule when
its effective, hierarchy-resolved permissions cover both of the rule's
permission sets; detection runs on demand *and* continuously on every role
assignment), **privileged access review** (risk-scored list of every identity
holding a tracked admin-tier role, with approve/revoke), **orphaned identity
detection** (disabled-but-granted, 90-day-inactive, stale API keys, unused
roles), **governance risk scoring** (0–100, five weighted factors → LOW/
MEDIUM/HIGH/CRITICAL), **automated remediation** (typed actions against a
finding — role removal, account/key disable and delegation expiry execute for
real; notify/approval-request/MFA/ticket actions are audit-tracked hooks with
no downstream system to call yet), and **compliance reporting** (SOC 2/ISO
27001/HIPAA/GDPR/NIST/CIS control → evidence mapping, immutable snapshots,
JSON/CSV export). See [docs/governance/](docs/governance/) for the full set —
dashboard, access-certification, sod-analysis, toxic-permissions,
privileged-access, orphaned-identities, risk-scoring, remediation and
compliance-reporting.

### Agent Runtime & Lifecycle Management (Phase 5.0)

The execution layer, at `/runtime`: **agent registry** (additive columns on
the existing Phase 1 `agents` table — no parallel registry), **immutable,
checksummed versioning** (DRAFT → READY_FOR_REVIEW → APPROVED → PUBLISHED,
tamper-detected by recomputing the checksum at publish), **deployments**
(RECREATE strategy across DEVELOPMENT/TEST/STAGING/PRODUCTION/SANDBOX, with
rollback), the **Runtime Gateway** (every execution request walks agent
state → deployment → version → idempotency → the existing
`AuthorizationGateway` RBAC/ABAC pipeline → runtime policy → approval →
queue, exactly as Phase 4.3.6's gateway was already designed to be called
by "agent runtime"), a **Postgres-backed execution queue** (`SELECT ... FOR
UPDATE SKIP LOCKED`, no Redis/Celery dependency, driven inline/eagerly in
this environment), **capability and tool registries** with per-agent
assignment and a default-deny Tool Gateway (only `FUNCTION`/`echo` actually
executes; every other tool type is fully authorized but fails closed),
runtime **approvals** (mission-critical + production always gates), a live
**dashboard** and **Operations Center**, and an **emergency kill switch**
(execution/agent/project/organization/platform scope — platform is
cross-tenant and requires `SUPER_ADMIN`). Runtime limits (concurrency,
per-minute rate, daily cost budget, per-execution token estimate),
execution timeouts, worker-crash recovery, tool-assignment constraints,
input/output contract validation and the execution state machine are all
enforced, not just modeled. See [docs/runtime/](docs/runtime/)
for the full set — architecture, agent-lifecycle, versioning, deployments,
executions, workers-and-queue, capabilities-and-tools, gateways,
runtime-policy-and-approvals, health-and-observability,
operations-and-kill-switch and security.

### Enterprise Agent Registry (Phase 5.1)

The registry gate every agent must pass before it can version, deploy or
execute: **accountable ownership** (business/technical/compliance owner,
with an immutable transfer history), a **mandatory machine identity**
(one per agent, DB-enforced), org-hierarchy scoping (business unit/
department/team, derived from project when not given explicitly), a
**13-state lifecycle** (register → validate → submit-for-approval →
approve/reject → activate/suspend/resume → deprecate/archive/restore →
retire, each transition its own audited event), a **validation-report
engine** (metadata/ownership/identity/definition/risk rules, JSON Schema
DoS guards, entrypoint format checks), **duplicate detection** (exact +
similarity, reviewer decisions), **JSON/YAML/CSV import & export** (imports
always land as DRAFT; exports always exclude secrets), a legacy-agent
migration/classification page, optimistic concurrency (`row_version`), and
a registration wizard with draft autosave. See
[docs/runtime/registry/](docs/runtime/registry/) for the full set.

### Enterprise Versioning & Release Management (Phase 5.2 Part 1)

Every agent version is an immutable, checksummed release artifact: enforced
**semantic versioning** (auto-derived or validated, strictly increasing), a
**snapshot builder** that freezes the complete release document (identity,
definition, runtime config, release metadata/artifacts/notes) at publish
time, **version lineage** (parent linking, supersession tracking, a
settable rollback-target pointer), a global **release-channel** catalog,
categorized **release notes** and **artifact references**, a version
**status-history** ledger, a new `RETIRED` terminal lifecycle state,
**version comparison** (a structural diff between any two versions), and
a **promotion-readiness** diagnostic (advisory, never a lifecycle gate).
See [docs/runtime/versioning.md](docs/runtime/versioning.md) for the full
set, including the deliberate scope decisions made against the SRS.

**Compatibility & breaking-change detection (Phase 5.2.6)** — the
`compatibility_level` column Part 1 reserved is now real: every publish
automatically classifies the new version against its resolved baseline as
`COMPATIBLE` / `BACKWARD_COMPATIBLE` / `BREAKING` / `UNKNOWN` (input/output
contract, tool/capability bindings, model config, resource limits, policy
tightening), records one finding per detected change, and checks the
declared semantic-version increment against what was actually detected —
reported as advisory, never a `publish()` blocker. See the "Compatibility &
breaking-change detection" section of
[docs/runtime/versioning.md](docs/runtime/versioning.md).

**Cryptographic signing, provenance & attestation (Phase 5.2.4)** — every
publish now produces a real signature: a canonical, cross-language-stable
serialization backs every checksum (replacing `json.dumps`'s
unspecified-across-languages defaults), a pluggable signing provider
(local Ed25519 today; Azure Key Vault a configuration change away) signs
the frozen snapshot, and a self-contained in-toto Statement v1 / DSSE
attestation document records exactly what was published and by whom — no
database lookup needed to interpret it. Signing is fail-closed: unlike
compatibility analysis, a signing failure aborts publication entirely. Key
rotation and revocation are supported; verification is internal-only for
now (deliberately deferred, not forgotten — see the "Known Deviations" in
[docs/runtime/versioning.md](docs/runtime/versioning.md)).

**Model provider abstraction (Phase 5.7a.1)** — the first step in
replacing the mock execution every layer above it has been tested
against: a real `ModelProvider` interface, an explicit registry, and a
provider-neutral internal representation (messages, requests, responses,
capabilities) that no future adapter's shape can leak outside its own
module. `MOCK` is migrated onto it with zero change in externally
observable behavior — proof the interface doesn't distort what it
expresses. No real provider yet; that's the next sub-phase. See
[docs/runtime/providers.md](docs/runtime/providers.md).

### Milestone 1 — real execution (complete)

The mock every layer above had been tested against is gone. `OpenAICompatible`
talks the OpenAI chat-completions wire protocol against any `base_url`
(Ollama / vLLM / LM Studio / OpenAI) — named for the protocol, not a vendor.
Real SSE **streaming** reassembles tool calls across fragmented chunks, and an
interruption persists a partial rather than raising. **Token and cost accounting**
is real: a provider that omits usage reports `{}` and is never zero-filled, and
prices live in an effective-dated table, so a local unpriced model honestly costs
zero rather than being estimated at something.

An eight-class, provider-neutral **error taxonomy** decides what is retryable;
classification lives in the adapter while retry, exponential backoff with jitter
and a three-state circuit breaker live in the service layer, so a second adapter
inherits all of it with no new retry code. **Per-organization credentials** are
encrypted at rest, resolved at execution time, with the environment variable kept
only as a fallback.

On the tool side, an `HTTP` action executes behind an SSRF **egress guard** that
validates addresses across decimal/octal/hex encodings, pins the connection to
the address it validated (defeating DNS rebinding, verified empirically against
the installed `httpx`/`httpcore`), and re-validates on redirect — reading its
allowlist from the *frozen version snapshot*, never live mutable state. Tool
arguments are validated against a declared JSON-Schema contract **before any side
effect**, and the resilience machinery is reused from the model side rather than
duplicated.

Finally the **tool invocation loop** joins them: the model requests a tool, the
tool runs through the unchanged gateway, the structured result feeds back, and
the loop resolves — bounded by four independent termination caps (iterations,
token budget, wall clock, repeated-identical-call). Tools the model requests
together run in parallel only when every one is declared idempotent. See
[docs/runtime/gateways.md](docs/runtime/gateways.md).

### Milestone 2 — Enterprise Integration Framework (complete, 9/9)

A `Connector` abstraction with a five-state tenant-instance lifecycle, six
authentication schemes (API key, bearer, basic, two OAuth2 flows, mTLS) with
encrypted credential storage and concurrency-safe token refresh, a registry that
fails fast on a disabled or failed instance, health probes, and an **SDK** whose
surface is the enforcement: an SDK-authored connector cannot make an undeclared
outbound call, receive a decrypted credential, suppress audit, or reach another
tenant's data — because no method exists to do any of those, not because an
author is asked not to.

Four generic connectors ship, each carrying one sharp containment rule:

- **REST** — injection-safe path/query/header rendering; `123/../admin` renders as
  a single escaped segment and never escapes to `/admin`
- **Database** — **the model never writes SQL.** It supplies bound parameters to
  pre-declared, reviewed queries; the executor has no parameter position a raw
  SQL string could occupy anywhere in the codebase
- **Storage** — **a model-supplied path can never escape its declared scope**,
  canonicalized (percent-decoding, Unicode normalization, symlink resolution)
  and *then* contains-checked, with no gap between validation and use
- **Queue** — publish is scoped to a queue fixed by the tool contract (no
  queue-name parameter exists to redirect through), and consume is always
  bounded on both batch size and wall clock

**External identity federation** (OIDC + SAML 2.0) completes the milestone, and
inverts the trust direction: it holds no user secret and verifies an assertion
inward. Accepted algorithms come from the organization's stored configuration and
never from the token's own header; SAML signature verification follows the
signature's own reference back to the exact ID-referenced element, tested against
deliberately-constructed signature-wrapping attacks. A federated login terminates
in the platform's *existing* session pipeline — never a parallel one.

### Milestone 3 — Deployment, Release & Operations (complete, 10/10)

Deployments became a governed domain: a 15-state lifecycle with a single
transition authority and optimistic concurrency, governed **environments** with
policy plus an immutability-preserving **promotion** operation, and a **release
gate** aggregating thirteen checks into one authoritative PASS / WARNING / BLOCK
verdict that fails closed — an unexpected exception in any check becomes a
blocking finding, never a silently skipped one.

On top of that sits **weighted traffic allocation**: a version resolver on the
execution hot path (≤3 indexed queries, no cache — deliberately, because every
candidate cache key is mutated by code across three phases and a stale cache
would be a fail-closed hazard *under the kill switch*), with concurrency settled
by a partial unique index rather than a lock, so nothing here can deadlock
against the execution path's own locks.

Three rollout patterns now drive that one allocation mechanism:

| Strategy | Pattern | The old version |
|---|---|---|
| **Canary** | 5 → 25 → 50 → 100, gated per stage | superseded at the end |
| **Recreate** | 0 → 100 in one cutover | superseded immediately |
| **Blue-green** | 0 (warm) → 100 in one atomic switch | **preserved at 0%** for instant rollback |

A canary stage clears only when its minimum duration, minimum sample count **and**
health requirement are all satisfied, judged by an **AI-aware health engine** that
aggregates real executions over a window rather than reading a liveness heartbeat
— a model version can be perfectly alive while refusing every third request.
`INSUFFICIENT_DATA` is first-class and satisfies no requirement at any level:
two successes out of two is not "healthy", because nothing bad *observed* is not
nothing bad *happening*.

**Rolling deployment was deferred until it could be real.** For three phases it
raised a real 501 naming Phase 3.9, because there was no worker fleet to roll
over and a handler that incremented the vestigial replica counters would have
reported progress while nothing rolled. Phase 3.9 built the fleet and
implemented it properly: steps are derived from *actual* registered capacity, so
a fleet holding 8 and 2 slots rolls 80% → 100% rather than an invented ladder.

**Automated rollback (3.7)** turns rollback from an operation into a safety
system. Per-tenant, per-environment trigger policies watch the same health
verdicts the canary engine uses and roll a failing candidate back **on their
own** — the milestone's headline proof, made automatic. `rollback_target_id` is
now authoritative: a rollback returns to the *designated* last-known-good, and
fails closed rather than guessing when none is designated, because a wrong
rollback looks like a successful one.

Three properties are worth stating because they are what make unattended
automation defensible:

- **Automation is subordinate to the kill switch; humans are not.** An automatic
  rollback on a killed agent does not run — automation must never quietly undo a
  human's kill. A *manual* rollback still runs, because a kill switch must never
  trap an operator on the version they are trying to leave.
- **Thin data never triggers.** Three failures out of three is a 100% error rate
  and still not evidence. `INSUFFICIENT_DATA` and `UNKNOWN` satisfy nothing.
- **Evidence survives the rollback.** The candidate's metrics at the moment it
  was rolled back are preserved — the rollback must not be the act that destroys
  the reason for it.

See [docs/deployment/](docs/deployment/), and
[docs/deployment/rollback.md](docs/deployment/rollback.md) in particular.

**Users** (password `DemoPass!2026`):

| Email                  | Role       |
| ---------------------- | ---------- |
| `admin@example.com`    | `ADMIN`    |
| `reviewer@example.com` | `REVIEWER` |

**Agents & permissions:**

| Agent                  | Resource         | Action          | Allowed |
| ---------------------- | ---------------- | --------------- | ------- |
| BillingAgent           | `CLAIM`          | `READ`          | ✅      |
| BillingAgent           | `CLAIM`          | `SUBMIT_CLAIM`  | ✅      |
| BillingAgent           | `PATIENT_RECORD` | `READ`          | ✅      |
| BillingAgent           | `PATIENT_RECORD` | `UPDATE_RECORD` | ❌      |
| SchedulingAgent        | `APPOINTMENT`    | `READ`          | ✅      |
| SchedulingAgent        | `APPOINTMENT`    | `CREATE`        | ✅      |
| SchedulingAgent        | `APPOINTMENT`    | `CANCEL`        | ✅      |
| ClinicalSummaryAgent   | `PATIENT_RECORD` | `READ`          | ✅      |
| ClinicalSummaryAgent   | `DIAGNOSIS`      | `CREATE`        | ❌      |
| ClinicalSummaryAgent   | `MEDICATION`     | `RECOMMEND`     | ❌      |

> Note: the seeder also prints a one-time API key for each agent. API-key auth for agents is planned for a later phase; Phase 1 uses JWT-authenticated endpoints.


**Phase 3.8 added a distributed scheduler** — instances coordinating through
`SELECT ... FOR UPDATE SKIP LOCKED` leases, with no broker anywhere. The claim
transaction commits *before* a handler dispatches, and exactly-once per
occurrence is a schema property (a unique index on the due-instant key) rather
than something detected afterwards.

**Phase 3.9 moved agent execution onto a real worker fleet, and made rolling
deployment real with it.** Workers are independently-operable processes
(`python -m app.workers.runner`) that claim executions with the same
`FOR UPDATE SKIP LOCKED` query Milestone 1 wrote — but the claim now **commits
before the execution runs**, so a worker holds no database lock across model or
tool network I/O. That was the one change to the execution path: the
model→tool→model loop, governance, retry policy, cost accounting and audit are
all exactly as Milestone 1 built them, and its entire execution suite passes
unchanged.

Rolling deployment finally has a substrate. A **cohort** is a declared
partition of the registered fleet, and each rolling step moves traffic to the
fraction of *real* capacity converted — a fleet holding 8 and 2 slots steps
80% → 100%, not an invented ladder. The honest limit is stated in the code and
the docs rather than discovered later: workers are not version-pinned, so what
rolls is the share of new work routed to the candidate, in units of real
capacity, with the fleet sizing and gating the rollout. A rolling deployment
that cannot see its next cohort refuses to advance rather than promoting
traffic onto machines that are not there.


**Phase 3.10 built the Release Operations Center** — twelve views at
`/operations` through which an operator can see every deployment across every
environment, watch a canary advance stage by stage with live health, read a
release gate's findings, promote through environments, roll back with one
guarded click, watch the worker fleet and scheduler, and reconstruct any
release from its timeline.

It adds **no deployment logic**. Every action dispatches to an endpoint Phases
3.1–3.9 already built and already authorize — a "roll back" button *calls* the
rollback engine, it does not perform one. That is enforced rather than
promised: the read-model module makes no write call and imports no mutating
service, both checked against the parsed source, and a test pins twelve engine
modules byte-identical to the previous release.

The property that makes it trustworthy is honesty about unsafe state. An
active kill switch, a BLOCK verdict, INSUFFICIENT_DATA health and a paused or
rolling-back deployment are all surfaced as first-class facts rather than
inferred from strings — because the UI can only show what the server tells it,
and a read model that omitted them would *make* the interface present a killed
release as deployable. Dangerous actions are confirmation-gated in two tiers,
with the heavier friction reserved for the genuinely irreversible: uniform
friction is friction people learn to click through.

**With 3.10 merged, Milestone 3 is complete.** The platform executes real
governed AI, integrates with the enterprise in both directions, and deploys,
releases, monitors, routes, rolls back and operates agent versions safely at
production scale.

---

## Demo testing flow

You can do all of this interactively in Swagger (`/docs`) — click **Authorize** and paste the token. Below is the equivalent using `curl`.

### 1. Log in as the admin

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"DemoPass!2026"}'
# => {"access_token":"<TOKEN>","token_type":"bearer"}
```

Save the token:

```bash
TOKEN="<paste access_token here>"
```

### 2. List agents (to get their IDs)

```bash
curl http://localhost:8000/agents -H "Authorization: Bearer $TOKEN"
```

### 3. Run the expected scenarios

```bash
# Scenario 1 — SchedulingAgent creates an appointment -> ALLOW
curl -X POST http://localhost:8000/agent-actions -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"<SCHEDULING_AGENT_ID>","resource":"APPOINTMENT","action":"CREATE",
       "input_payload":{"patient_id":"PAT-2001","slot":"2026-07-01T10:00"}}'

# Scenario 2 — BillingAgent submits a claim -> PENDING_APPROVAL
curl -X POST http://localhost:8000/agent-actions -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"<BILLING_AGENT_ID>","resource":"CLAIM","action":"SUBMIT_CLAIM",
       "input_payload":{"claim_id":"CLM-1001","amount":1200,"patient_id":"PAT-2001"}}'

# Scenario 3 — BillingAgent updates a patient record -> BLOCK (permission denied)
curl -X POST http://localhost:8000/agent-actions -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"<BILLING_AGENT_ID>","resource":"PATIENT_RECORD","action":"UPDATE_RECORD",
       "input_payload":{"patient_id":"PAT-2001"}}'

# Scenario 4 — ClinicalSummaryAgent recommends medication -> BLOCK (permission denied)
curl -X POST http://localhost:8000/agent-actions -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"<CLINICAL_AGENT_ID>","resource":"MEDICATION","action":"RECOMMEND",
       "input_payload":{"patient_id":"PAT-2001","drug":"X"}}'

# Scenario 5 — Unknown action -> BLOCK (risk 85 > 80, or no permission)
curl -X POST http://localhost:8000/agent-actions -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"<BILLING_AGENT_ID>","resource":"CLAIM","action":"FRobNICATE",
       "input_payload":{}}'
```

Scenario 2 produces a response like:

```json
{
  "agent_action_id": "…",
  "decision": "PENDING_APPROVAL",
  "risk_score": 75,
  "decision_reason": "Permission exists but action requires human approval due to medium/high risk (risk score: 75).",
  "status": "CREATED",
  "approval_id": "…"
}
```

### 4. Review the approval queue (as reviewer)

```bash
# Log in as reviewer, then:
curl http://localhost:8000/approvals/pending -H "Authorization: Bearer $REVIEWER_TOKEN"

# Approve it:
curl -X POST http://localhost:8000/approvals/<APPROVAL_ID>/approve \
  -H "Authorization: Bearer $REVIEWER_TOKEN" -H "Content-Type: application/json" \
  -d '{"review_comment":"Looks legitimate."}'
```

### 5. Inspect the audit trail

```bash
curl http://localhost:8000/audit-logs -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/audit-logs/entity/agent_action/<AGENT_ACTION_ID> \
  -H "Authorization: Bearer $TOKEN"
```

---

## Running tests

The Phase 1 engine logic is pure and needs no database, but **the suite as a
whole does** — most of it runs against a real local PostgreSQL, deliberately, so
that concurrency races, index behaviour and migration reversibility are tested
against the real thing rather than a mock.

```bash
cd backend
pytest -q
# 1,575 passed, 1 deselected
```

The one deselected test is marked `live_provider` — a genuinely live Ollama
check, excluded by default via `backend/pytest.ini`. It is a deselection, not a
failure or a skip; the suite contains no `skip` or `xfail` markers.

```bash
cd frontend
npm test
# 297 passed
```

---

## API reference (summary)

| Area          | Endpoints                                                                              |
| ------------- | -------------------------------------------------------------------------------------- |
| Auth          | `POST /auth/register`, `POST /auth/login`, `GET /auth/me`                               |
| Auth (v1)     | `POST /api/v1/auth/{login,refresh,logout,mfa/verify}`, `GET /api/v1/auth/{me,sessions}`, `DELETE /api/v1/auth/sessions/{id}` — Phase 4 Part 4.2.2.1: argon2id, rotating refresh tokens, account lockout, login history, silent refresh. See [`docs/identity/human-authentication.md`](docs/identity/human-authentication.md). |
| Organizations | `POST /organizations`, `GET /organizations/{id}`                                       |
| Users         | `POST /users`, `GET /users`, `GET /users/{id}`                                          |
| Agents        | `POST /agents`, `GET /agents`, `GET /agents/{id}`, `PATCH /agents/{id}/status`          |
| Permissions   | `POST /permissions`, `GET /permissions`, `GET /permissions/agent/{agent_id}`           |
| Agent actions | `POST /agent-actions`, `GET /agent-actions`, `GET /agent-actions/{id}`                  |
| Approvals     | `GET /approvals`, `GET /approvals/{id}`, `GET /approvals/statistics`, `GET /approvals/history`, `GET /approvals/escalations`, `POST /approvals/{id}/approve\|reject\|escalate\|assign` |
| Audit logs    | `GET /audit-logs`, `GET /audit-logs/entity/{entity_type}/{entity_id}`                   |
| Audit center  | `GET /audit`, `GET /audit/{id}`, `GET /audit/statistics`, `GET /audit/timeline`, `GET /audit/events`, `GET /audit/security`, `GET /audit/compliance`, `GET /audit/export` (Part 3.5; `audit.view` for the table/detail, `audit.export` for security/compliance/export and raw payloads) |
| Analytics     | `GET /analytics/overview`, `GET /analytics/kpis`, `GET /analytics/activity`, `GET /analytics/fleet-health`, `GET /analytics/risk`, `GET /analytics/performance`, `GET /analytics/policies`, `GET /analytics/review`, `GET /analytics/cost`, `GET /analytics/insights`, `GET /analytics/reports` (Part 3.6; `analytics.view` gates the surfaces, `analytics.executive` / `analytics.operations` gate those dashboards) |
| Identity (v1) | `GET/POST /api/v1/identity/users` (+ `/{id}/activate\|suspend\|status`), `GET/POST /api/v1/identity/organizations` (+ `/{id}/status`), `GET/POST /api/v1/identity/departments`, `GET /api/v1/identity/roles`, `GET /api/v1/identity/sessions`, and machine identities `GET/POST /api/v1/identity/{agent-identities,service-accounts,external-clients}` (+ `/{id}/status`). Phase 4 Part 4.1/4.1a; versioned, standard error envelope, RBAC-gated. Every identity (human, agent, service account, organization, external client) shares one `IdentityStatus` lifecycle. |

`POST /auth/register` bootstraps a brand-new organization plus its first `SUPER_ADMIN` user and returns a JWT — handy for creating your own tenant outside the demo seed.

---

## Phase 2 — production-oriented platform

Phase 2 builds on the Phase 1 MVP. Run the new migration to add its tables:

```bash
cd backend
alembic upgrade head      # applies migration 0002 (Phase 2 schema)
python -m app.seed        # adds API keys, policies and RBAC to the demo org
```

### What's new

| Module | Summary |
| ------ | ------- |
| **Agent API keys** | Each agent gets one-or-more `agt_live_…` keys (only the SHA-256 hash is stored). Agents authenticate directly via `Authorization: Bearer agt_live_…`. |
| **Policy engine** | Database-driven rules (`policies` table). A policy targets a `resource`/`action` and a JSON `conditions` object (e.g. `{"amount_gt": 10000}`) and yields a decision. Matching policies **override** the raw risk thresholds; highest `priority` wins. |
| **Advanced RBAC** | `roles`, `rbac_permissions`, `role_permissions`, `user_roles`. Routes are guarded by fine-grained permission codes (e.g. `policy.create`, `approval.review`). Backward-compatible with the Phase 1 role enum. |
| **Approval queue+** | Approvals now carry a `priority` (LOW/MEDIUM/HIGH/CRITICAL derived from risk), an SLA deadline (`sla_due_at`), and a comment thread. |
| **Notifications** | Email via SMTP (Mailtrap for dev) sent through FastAPI background tasks on approval requested/decided and agent suspension. Disabled by default (`NOTIFICATIONS_ENABLED=false`) — sends are logged instead. |
| **Audit++** | Audit logs capture `ip_address`, `user_agent`, `request_id`, `trace_id`, plus `before_state`/`after_state` and a risk breakdown. |
| **Dashboard APIs** | `/dashboard/summary`, `/dashboard/recent-actions`, `/dashboard/high-risk-actions`, `/dashboard/pending-approvals`. |
| **Risk engine v2** | `risk = clamp(action_score + resource_score + modifiers)` (e.g. PHI access `+20`, large amount `+10`). |
| **Docker** | `Dockerfile` + `docker-compose.yml` run `api` + `postgres`; the api container migrates on start. |

### New / changed endpoints

```
# Agent API keys
POST   /agents/{id}/generate-api-key      issue a key (shown once)
GET    /agents/{id}/api-keys              list an agent's keys (no hashes)
POST   /api-keys/{id}/revoke              revoke a key

# Policies
POST   /policies                          create a policy
GET    /policies                          list (filter by ?resource= &action=)
GET    /policies/{id}                     fetch
PATCH  /policies/{id}                     update
DELETE /policies/{id}                     delete

# RBAC
GET    /rbac/permissions                  permission catalog
GET    /rbac/roles                        roles + their permission codes
GET    /rbac/me                           caller's effective permissions
POST   /rbac/users/{user_id}/roles        assign a role to a user

# Approvals (additions)
GET    /approvals/{id}/comments           comment thread
POST   /approvals/{id}/comments           add a comment

# Dashboard
GET    /dashboard/summary
GET    /dashboard/recent-actions
GET    /dashboard/high-risk-actions
GET    /dashboard/pending-approvals

# Dashboard + system (added in Phase 3 Part 3.1)
GET    /dashboard/activity            7-day agent-action counts
GET    /dashboard/risk-trend          30-day average risk score
GET    /system/health                 subsystem health for the dashboard
# /dashboard/summary also returns today_actions

# Agent management (added in Phase 3 Part 3.2a)
GET    /agents                        paginated list: search/status/type/risk/sort
PUT    /agents/{id}                   update agent metadata + config
DELETE /agents/{id}                   delete an agent
GET    /agents/{id}/stats             per-agent operational statistics
# agents now carry owner, department, version, capabilities, risk config;
# statuses add ARCHIVED and BLOCKED

# Policy management (added in Phase 3 Part 3.3)
GET    /policies                      list: search + resource/action/decision/severity/status
PUT    /policies/{id}                 update a policy (PATCH also accepted)
PATCH  /policies/{id}/enable          enable a policy
PATCH  /policies/{id}/disable         disable a policy
POST   /policies/{id}/test            simulate an action against the policy
GET    /policies/{id}/audit           policy lifecycle audit events
GET    /policies/templates            built-in policy templates
# policies now carry priority, severity, status, trigger_count, last_triggered_at

# Approval queue & review workbench (added in Phase 3 Part 3.4)
GET    /approvals                      filterable queue: status/priority/risk range/search
GET    /approvals/statistics          pending / approved today / rejected today / escalated / avg review time
GET    /approvals/{id}                full detail: agent, policy, risk breakdown, payload, comments
GET    /approvals/{id}/timeline       audit-derived review timeline
POST   /approvals/{id}/escalate       escalate to reviewer/manager/compliance/security (reason required)
POST   /approvals/{id}/assign         assign or reassign the responsible reviewer
GET    /approvals/history             resolved approvals (approved/rejected/escalated/expired)
GET    /approvals/escalations         active escalations with SLA countdown
# approvals now carry assigned_to_user_id, escalation_target, escalated_at;
# approval_decision adds ESCALATED and EXPIRED; new RBAC codes approval.view/escalate/assign
```

### Authenticating as an agent (Phase 2)

```bash
# 1. As an admin, issue a key for an agent:
curl -X POST http://localhost:8000/agents/<AGENT_ID>/generate-api-key \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{}'
# => {"api_key":"agt_live_xxxxxxxx", ...}   (store it now — shown once)

# 2. The agent calls /agent-actions with its own key (no user JWT needed):
curl -X POST http://localhost:8000/agent-actions \
  -H "Authorization: Bearer agt_live_xxxxxxxx" -H "Content-Type: application/json" \
  -d '{"agent_id":"<AGENT_ID>","resource":"CLAIM","action":"SUBMIT_CLAIM","input_payload":{"amount":50000}}'
# => decision PENDING_APPROVAL, matched_policy "Large Claim Approval"
```

`/agent-actions` accepts **either** an agent API key **or** a user JWT (keys carry the `agt_live_` prefix). With a key, the acting agent is taken from the key.

### Policy example

```json
{
  "name": "Large Claim Approval",
  "resource": "CLAIM",
  "action": "SUBMIT_CLAIM",
  "conditions": { "amount_gt": 10000 },
  "decision": "PENDING_APPROVAL",
  "priority": 100
}
```

Supported condition operators (keys are `"<field>_<op>"`): `_gt`, `_gte`, `_lt`, `_lte`, `_eq`, `_ne`, `_in`, `_contains`. A bare `"field": value` is an equality check. Empty `conditions` = always matches. All conditions are AND-ed.

### Policy management UI (Phase 3 Part 3.3)

The dashboard ships a full policy-authoring module at `/policies`
(`frontend/src/modules/policies/`):

- **Policy list** (`/policies`) — enterprise table with 300ms debounced search
  (name/resource/action/description/decision), status/decision/severity/resource
  filters, decision/severity/status badges, trigger counts, row actions
  (View, Edit, Test, Duplicate, Enable/Disable, Delete) and CSV export.
  Skeleton, empty and error states included.
- **Create / Edit** (`/policies/new`, `/policies/:id/edit`) — a six-step builder
  (Basic → Scope → Trigger → Conditions → Decision → Review) with a JSON
  condition editor and a live plain-English preview; "Save as Draft" or publish.
- **Details** (`/policies/:id`) — Overview, Conditions (human-readable + raw
  JSON), Assigned Agents, Trigger History, Audit timeline and a Settings tab
  with a danger-zone delete.
- **Test** (`/policies/:id/test`) — simulate an agent action and inspect
  matched / decision / risk score / triggered conditions / explanation.
- **Templates** (`/policies/templates`) — gallery of built-in governance
  templates; "Use Template" pre-seeds the builder.

Role-based UI: ADMIN / SUPER_ADMIN can create, edit, enable/disable and delete;
REVIEWER can view and test; everyone else is read-only. Deletes require typing
`DELETE` to confirm. The backend RBAC layer remains the source of truth.

Decision/severity/status badges degrade gracefully — an unrecognized value
renders a neutral "Unknown" badge rather than breaking the page, so older or
partially-migrated policy rows never blank the table. Restart the API after
applying migration `0004` so `/policies` serves the new `severity`/`status`/
`trigger_count` fields the UI reads.

> Screenshots (policy list, builder and test page) can be captured from a local
> `npm run dev` session and dropped into `docs/`.

### Approval queue & review workbench UI (Phase 3 Part 3.4)

The dashboard ships the operational heart of AI governance at `/approvals`
(`frontend/src/modules/approvals/`) — where humans inspect, approve, reject,
escalate and audit AI agent decisions:

- **Approval dashboard** (`/approvals`) — five statistics cards (Pending,
  Approved Today, Rejected Today, Escalated, Avg Review Time), 300ms debounced
  search (ID/agent/resource/reviewer), status/priority/risk-range filters,
  colour-coded status/priority/risk badges, row-level Approve/Reject and bulk
  approve with checkbox selection, plus CSV export. Skeleton, empty and error
  states included.
- **Approval details** (`/approvals/:id`) — summary card, agent information,
  policy explanation (matched rule + conditions), risk assessment with a
  recharts pie breakdown, a collapsible JSON payload viewer (copy/download),
  the decision-history timeline and reviewer notes. Export the full payload as
  JSON.
- **Review workbench** (`/approvals/:id/review`) — the most important page: a
  sticky decision panel (Approve, Reject, Escalate, Assign/Reassign) beside the
  payload, risk analysis, policy explanation and a live comment composer.
  Approve requires a note; reject requires a ≥20-character reason; escalate
  routes to Reviewer/Manager/Compliance Officer/Security Team with a reason.
- **History** (`/approvals/history`) — every resolved decision, searchable and
  filterable by status, with CSV export.
- **Escalations** (`/approvals/escalations`) — active escalations as cards with
  live SLA countdowns (overdue/urgent highlighting) and the responsible reviewer.

Role-based UI: the queue is visible to anyone with `approval.view`; Approve /
Reject (and commenting) require `approval.review`, Escalate requires
`approval.escalate`, and Assign requires `approval.assign`. Restricted actions
are hidden in the UI, and the backend RBAC layer still enforces them. Restart
the API after applying migration `0005` so `/approvals` serves the new
`assigned_to_user_id` / `escalation_target` columns and the `ESCALATED` /
`EXPIRED` decision states the UI reads.

Architecture, data-flow diagrams (Mermaid) and the endpoint→UI map for this
module live in [`docs/phase-3-part-4.md`](docs/phase-3-part-4.md).

> Screenshots (approval queue, review workbench, details and timeline) can be
> captured from a local `npm run dev` session and dropped into `docs/`.

### Audit & Compliance Center UI (Phase 3 Part 3.5)

The audit module at `/audit` (`frontend/src/modules/audit/`) gives every
significant platform event complete traceability — who/what/when/why and what
happened — over the immutable `audit_logs` trail. Severity, category, decision
and human status are *derived* on the backend (`audit_view`); no new columns are
stored.

- **Audit dashboard** (`/audit`) — six statistics cards (Total Events, Security
  Events, Policy Evaluations, Approval Events, Authentication, Config Changes),
  an activity timeline (clickable, newest first), a Recent Events list, and —
  for `audit.export` holders — security and compliance snapshots.
- **Events explorer** (`/audit/events`) — the full enriched table (Timestamp,
  Event ID, Actor, Event Type, Resource, Decision, Severity, Status) with 300ms
  debounced search, filters (event type/category/actor/severity/decision/date
  range) and server-side pagination. Skeleton, empty and error states included.
- **Event detail** (`/audit/:id`) — forensic summary (actor, request/correlation/
  session ids, IP, policy, risk, reason), a Request viewer and a Response &
  Decision viewer (collapsible JSON with copy/download), and a Related Events
  flow tracing the shared correlation id (request → policy → approval →
  execution). Raw payloads and JSON export are gated on `audit.export`.
- **Security dashboard** (`/audit/security`) — failed logins, blocked agents,
  disabled API keys, permission violations, suspicious activity and critical
  alerts, plus a recent security-events table. Requires `audit.export`.
- **Compliance dashboard** (`/audit/compliance`) — informational HIPAA / SOC 2 /
  ISO 27001 readiness with policy, approval and audit-completeness coverage bars.
  Requires `audit.export`.
- **Export center** (`/audit/export`) — apply filters, preview the selection,
  then export the full matching set as CSV or JSON (PDF is a placeholder).
  Requires `audit.export`.

Role-based UI: the dashboard, events table and event detail are visible to
anyone with `audit.view` (all built-in roles); the export center, security and
compliance dashboards, and raw request/response payloads require `audit.export`
(SUPER_ADMIN / ADMIN). Restricted surfaces render an access-denied state and the
backend RBAC layer still enforces every call.

> Screenshots (audit dashboard, event detail, security and compliance
> dashboards) can be captured from a local `npm run dev` session and dropped
> into `docs/`.

### Analytics & AI Operations Center UI (Phase 3 Part 3.6)

The analytics module at `/analytics` (`frontend/src/modules/analytics/`) is the
"mission control" for enterprise AI — an executive/operations view over the same
operational tables (agents, agent_actions, approvals, policies, audit_logs).
Metrics are derived at read time; latency and cost figures the platform does not
record are deterministic estimates, flagged with a `*` and an explanatory note.

- **Overview** (`/analytics`) — ten animated executive KPI cards (agents, actions,
  approvals, success/failure rate, avg risk, avg decision time, policies,
  compliance) with period-over-period trends, AI fleet-health cards, an activity
  overview chart (daily/weekly/monthly/yearly), a risk-distribution donut and
  rule-based AI insights. Auto-refreshes every 15s.
- **Executive** (`/analytics/executive`) — high-level posture (KPIs, 30-day risk
  trend, key insights) for leadership. Requires `analytics.executive`.
- **Operations** (`/analytics/operations`) — live agent activity feed (10s),
  fleet health, review queue stats and reviewer workload. Requires
  `analytics.operations`.
- **Risk** (`/analytics/risk`) — distribution, 30-day trend, a colour-intensity
  heatmap (agent type × band), risk by department/agent-type, and the
  highest-risk agents.
- **Performance** (`/analytics/performance`) — latency/processing metrics,
  failure vs retry, and a sortable/searchable agent performance ranking.
- **Agents** (`/analytics/agents`) — fleet composition + the agent ranking.
- **Policies** (`/analytics/policies`) — coverage/effectiveness stats, most
  triggered / most blocking / most approval-routing / least used policies.
- **Costs** (`/analytics/costs`) — estimated compute, API, LLM, human-review,
  policy-evaluation and storage spend with a composition donut.
- **Reports** (`/analytics/reports`) — generate daily→annual reports and export
  as CSV or JSON (PDF placeholder).

Role-based UI: general analytics needs `analytics.view` (SUPER_ADMIN / ADMIN /
REVIEWER); the executive and operations dashboards need `analytics.executive` /
`analytics.operations`. Restricted surfaces render an access-denied state and the
backend RBAC layer enforces every call. Restart the API after pulling so the new
`analytics.*` permissions seed for freshly registered organizations.

Architecture, data-flow diagram and the endpoint→UI map live in
[`docs/phase-3-part-6.md`](docs/phase-3-part-6.md).

> Screenshots (analytics overview, executive, fleet health, risk, performance,
> reports) can be captured from a local `npm run dev` session and dropped into
> `docs/`.

### Email notifications (Mailtrap)

Onboarding emails (invitations, verification links) carry the **only** copy of a
single-use token — the database stores just its SHA-256. So delivery matters:

- **Off (default, `NOTIFICATIONS_ENABLED=false`)** — nothing is sent. The full
  message, link included, is appended to a git-ignored dev outbox
  (`EMAIL_DEV_OUTBOX_PATH`, default `var/dev-outbox.log`) so the link stays
  recoverable, and the Invitations panel shows a "delivery disabled" warning.
- **On (`NOTIFICATIONS_ENABLED=true`)** — mail goes to SMTP; the outbox is no
  longer written (a plaintext token must never hit disk in a sending deploy).

**To send through Mailtrap Sandbox** (safe testing — captures mail, does **not**
deliver to real inboxes):

1. mailtrap.io → **Email Testing → Sandboxes → your sandbox → SMTP Settings**
2. Set the code dropdown to **Nodemailer** to reveal the per-inbox credentials
   (a random username/password — *not* your Mailtrap account login).
3. Put them in `.env`:

```env
NOTIFICATIONS_ENABLED=true
SMTP_HOST=sandbox.smtp.mailtrap.io
SMTP_PORT=587
SMTP_USERNAME=<random sandbox username>
SMTP_PASSWORD=<random sandbox password>
SMTP_USE_TLS=true
SMTP_FROM=no-reply@control-tower.local
```

Restart the backend, then create/resend an invitation — it appears in the Mailtrap
sandbox inbox. Free plan throttles to a few emails/second (`550 Too many emails
per second`); `EmailResult` reports that as a failure rather than a false success.

> **Real delivery to actual inboxes** (e.g. real Gmail) is a *different* Mailtrap
> product — **Email API/SMTP** live sending (`live.smtp.mailtrap.io`, its own
> credentials, requires domain verification). Sandbox alone never leaves Mailtrap.

### Run with Docker

```bash
docker compose up -d --build      # builds the api image, starts api + postgres
# api migrates on start; SEED_ON_START=true (compose default) loads demo data
# Swagger: http://localhost:8000/docs
```

### Tests & coverage

```bash
cd backend
pytest --cov=app --cov-report=term-missing     # ~83% coverage, 33 tests
```

Unit tests cover the risk, decision and policy engines; integration tests
(`tests/test_integration.py`) exercise the full Phase 2 flow against PostgreSQL
(register → agent → API key → permission → policy → action → approval → revoke).

---

## What's next

*This section previously listed the Phase 3+ wish-list. Most of it has since
shipped — real action execution, the dashboard frontend, policy simulation, key
lifecycle — so it is replaced here with the actual current queue rather than left
to read as pending. [`ROADMAP.md`](ROADMAP.md) is the maintained plan and
[`REPO_STATE.md`](REPO_STATE.md) §9 the honest gap list.*

**Milestone 3 is complete.** Next on the roadmap: Runtime Governance &
Observability.

**Known gaps, stated plainly** (the full list is [`REPO_STATE.md`](REPO_STATE.md)
§9): CAPTCHA verification is a placeholder; the Phase 3 analytics cost figures are
deterministic estimates unrelated to the real per-execution cost accounting added
in Milestone 1; signing keys and the credential-encryption key live on local disk
rather than in a vault (deferred, documented, and closing at Milestone 13); the
frontend production bundle is a single ~1.65 MB chunk with no route-level code
splitting; and vendor-specific connectors (SAP/Salesforce/ServiceNow) are
deliberately fast-follow work rather than speculative build-ahead.

**Deliberately out of scope entirely**: a visual workflow builder, hyperscale
event streaming, automated model optimization, reinforcement learning, autonomous
agent creation, a marketplace, multi-cloud federation, a Kubernetes operator, and
GPU scheduling — see "What's deliberately not here" in
[docs/runtime/overview.md](docs/runtime/overview.md).
