# AI Agent Control Tower

> A backend control plane that tracks, controls, approves, blocks and audits the actions performed by AI agents.
>
> **Phase 1** (MVP): agents, permissions, risk scoring, approvals, audit logs.
> **Phase 2** (production-oriented): agent API-key auth, a database-driven policy engine, advanced RBAC, email notifications, forensic audit, dashboard APIs, risk engine v2, and Docker. See the [Phase 2 guide](#phase-2--production-oriented-platform) below.
> **Phase 3** (enterprise dashboard UI): a React 19 + TypeScript web console (`frontend/`) that consumes the Phase 1/2 APIs. Delivered: **Part 1** (scaffold + dark theme + app-shell), **Part 2** (JWT auth + sidebar/top-nav + route guards), **Part 3.1** (live operational dashboard — KPIs, charts, approval queue, recent actions/audit, system health, 60s auto-refresh). See [`frontend/README.md`](frontend/README.md) and [`ROADMAP.md`](ROADMAP.md).

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
| Approvals     | `GET /approvals/pending`, `POST /approvals/{id}/approve`, `POST /approvals/{id}/reject` |
| Audit logs    | `GET /audit-logs`, `GET /audit-logs/entity/{entity_type}/{entity_id}`                   |

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
