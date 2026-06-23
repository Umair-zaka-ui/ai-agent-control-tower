# AI Agent Control Tower

> Phase 1 MVP — a backend system that tracks, controls, approves, blocks and audits the actions performed by AI agents.

As organizations hand more real-world tasks to autonomous AI agents (submitting claims, updating records, sending emails, moving money), they need a control plane that sits between the agent and the action. The **AI Agent Control Tower** is that control plane: every action an agent attempts is checked against permissions, scored for risk, and either **allowed**, **blocked**, or **routed to a human for approval** — and every decision is written to an immutable audit log.

This repository contains the Phase 1 backend (FastAPI + PostgreSQL). It is a personal learning / startup project and uses no company code, data, or infrastructure.

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

## Future roadmap

- **Agent authentication via API keys** — let agents call `/agent-actions` directly with their issued key (hash already stored).
- **Configurable risk & policy engine** — rules stored in the DB, per-resource thresholds, payload-aware scoring.
- **Real action execution & callbacks** — execute approved actions and capture `output_payload`.
- **Dashboard frontend** — React/Next.js console for the approval queue, agents, and audit timeline (the APIs are already designed for it).
- **Notifications** — alert reviewers when an action is pending (email/Slack/webhooks).
- **Per-organization RBAC hardening** and fine-grained roles.
- **Rate limiting, anomaly detection, and observability** (metrics/tracing).
- **Multi-tenant isolation tests** and full API integration test suite.
```
