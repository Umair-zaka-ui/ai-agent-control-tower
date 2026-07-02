# AI Agent Control Tower

> A backend control plane that tracks, controls, approves, blocks and audits the actions performed by AI agents.
>
> **Phase 1** (MVP): agents, permissions, risk scoring, approvals, audit logs.
> **Phase 2** (production-oriented): agent API-key auth, a database-driven policy engine, advanced RBAC, email notifications, forensic audit, dashboard APIs, risk engine v2, and Docker. See the [Phase 2 guide](#phase-2--production-oriented-platform) below.
> **Phase 3** (enterprise dashboard UI): a React 19 + TypeScript web console (`frontend/`) that consumes the Phase 1/2 APIs. Delivered: **Part 1** (scaffold + dark theme + app-shell), **Part 2** (JWT auth + sidebar/top-nav + route guards), **Part 3.1** (live operational dashboard — KPIs, charts, approval queue, recent actions/audit, system health, 60s auto-refresh), **Part 3.2a** (agent-management module — server-driven table, create wizard, details + stats, edit, lifecycle), **Part 3.3** (policy-management module), **Part 3.4** (approval queue & human review workbench — statistics cards, filterable queue, detail page, review workbench with approve/reject/escalate/assign, risk breakdown, audit timeline, history & escalations boards), **Part 3.5** (enterprise Audit & Compliance Center — audit dashboard with statistics + activity timeline + recent events, a filterable/searchable/paginated events explorer, forensic event detail with request/response viewers and a related-events flow, plus RBAC-gated security & compliance dashboards and a multi-format export center), **Part 3.6** (enterprise Analytics & AI Operations Center — executive KPI grid with live trends, AI fleet health, an activity overview chart, a risk analytics dashboard with heatmap, a performance dashboard with agent ranking, policy & human-review analytics, an estimated cost dashboard, a reports center with export, rule-based AI insights, and role-gated executive/operations dashboards with auto-refresh). See [`frontend/README.md`](frontend/README.md) and [`ROADMAP.md`](ROADMAP.md).
>
> **Phase 4** (enterprise identity): **Part 4.1** (Enterprise Identity Platform foundation — an isolated `app/identity` package giving every human, AI agent, service account, organization and external application a formal identity model with a consistent lifecycle. Adds the org → department → team hierarchy, sessions/refresh-tokens/device-sessions and security events, a repository + service architecture, a versioned `/api/v1/identity` API with a standard error envelope, and identity audit integration). See [`docs/phase-4-part-1.md`](docs/phase-4-part-1.md).

As organizations hand more real-world tasks to autonomous AI agents (submitting claims, updating records, sending emails, moving money), they need a control plane that sits between the agent and the action. The **AI Agent Control Tower** is that control plane: every action an agent attempts is checked against permissions, scored for risk, and either **allowed**, **blocked**, or **routed to a human for approval** — and every decision is written to an immutable audit log.

This repository contains the FastAPI + PostgreSQL backend (`backend/`) and the React + TypeScript dashboard (`frontend/`). It is a personal learning / startup project and uses no company code, data, or infrastructure.

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

- **Backend:** Python 3.11+ / FastAPI
- **Database:** PostgreSQL (local)
- **ORM:** SQLAlchemy 2.0
- **Migrations:** Alembic
- **Auth:** JWT (bearer tokens), bcrypt password hashing
- **Docs:** Swagger / OpenAPI (built into FastAPI)

---

## Project structure

```
ai-agent-control-tower/
├── docker-compose.yml          # local PostgreSQL
├── README.md
├── ROADMAP.md                  # phase-by-phase roadmap
├── docs/                       # phase notes (e.g. phase-3-part-1.md)
├── frontend/                   # Phase 3 — React 19 + TypeScript dashboard
└── backend/
    ├── alembic.ini
    ├── requirements.txt
    ├── .env.example
    ├── migrations/             # Alembic environment + versions
    ├── tests/                  # unit tests for the engines
    └── app/
        ├── main.py             # FastAPI app
        ├── seed.py             # demo data seeder
        ├── core/               # config, database, security, enums
        ├── models/             # SQLAlchemy models (7 tables)
        ├── schemas/            # Pydantic request/response models
        ├── api/
        │   ├── deps.py         # auth + DB dependencies
        │   ├── router.py       # aggregates all routes
        │   └── routes/         # one module per resource
        └── services/           # business logic
            ├── permission_engine.py
            ├── risk_engine.py
            ├── decision_engine.py
            ├── approval_service.py
            ├── audit_service.py
            └── agent_action_service.py   # orchestration pipeline
```

---

## Setup

All commands below are run from the **`backend/`** directory unless noted.

### 1. Start PostgreSQL

**Option A — Docker (recommended):** from the repository root:

```bash
docker compose up -d
```

This starts PostgreSQL 16 on `localhost:5432` with database `agent_control_tower` (user/password `postgres`/`postgres`).

**Option B — local PostgreSQL install:** create the database manually:

```sql
CREATE DATABASE agent_control_tower;
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

**Users** (password `password123`):

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

---

## Demo testing flow

You can do all of this interactively in Swagger (`/docs`) — click **Authorize** and paste the token. Below is the equivalent using `curl`.

### 1. Log in as the admin

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"password123"}'
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

The engine logic is unit-tested and requires no database:

```bash
cd backend
pytest
```

---

## API reference (summary)

| Area          | Endpoints                                                                              |
| ------------- | -------------------------------------------------------------------------------------- |
| Auth          | `POST /auth/register`, `POST /auth/login`, `GET /auth/me`                               |
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

Set these in `.env` to enable real sends:

```env
NOTIFICATIONS_ENABLED=true
SMTP_HOST=sandbox.smtp.mailtrap.io
SMTP_PORT=587
SMTP_USERNAME=<your mailtrap user>
SMTP_PASSWORD=<your mailtrap pass>
SMTP_FROM=no-reply@control-tower.local
```

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

## Future roadmap (Phase 3+)

Delivered in Phase 2: agent API-key auth, DB-driven policy engine, advanced RBAC,
notifications, forensic audit, dashboard APIs, risk engine v2, Docker.

Next:

- **Real action execution & callbacks** — execute approved actions and capture `output_payload`.
- **Dashboard frontend** — React/Next.js console for the approval queue, agents, policies and audit timeline (the APIs are already designed for it).
- **Richer notifications** — Slack/webhooks in addition to email; SLA-breach alerts.
- **Policy authoring UX** — versioning, dry-run/simulation, and a visual rule builder.
- **Key lifecycle** — automatic rotation, scoped keys, and per-key rate limits.
- **Observability** — Prometheus metrics, OpenTelemetry tracing (trace ids already captured).
- **Anomaly detection** — flag unusual agent behaviour from the audit stream.
- **Multi-tenant isolation tests** and load testing for pilot customers.
