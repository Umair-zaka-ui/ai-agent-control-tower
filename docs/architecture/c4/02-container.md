# C4 Level 2 — Containers

> **Scope:** the deployable/runnable units inside the Control Tower, and the
> protocols between them. Reflects `docker-compose.yml` and `backend/Dockerfile`
> as they exist on `main`.

## Diagram

```mermaid
flowchart TB
    admin(["Platform Admin / Approver / Auditor"])
    agent(["AI Agent"])

    subgraph tower["AI Agent Control Tower"]
        direction TB

        spa["<b>Dashboard SPA</b><br/>React 19 + TypeScript + Vite<br/>TanStack Query, Axios, Tailwind<br/><i>dev server :5173 — not containerised</i>"]

        subgraph api_c["API container (act_api, :8000)"]
            api["<b>Control Plane API</b><br/>FastAPI + SQLAlchemy 2.0<br/>uvicorn"]
            entry["<b>Entrypoint</b><br/>alembic upgrade head<br/>+ optional seed"]
        end

        db[("<b>PostgreSQL 16</b><br/>act_postgres, :5432<br/>volume act_pgdata<br/>24 tables")]
    end

    smtp["SMTP<br/><i>(default off)</i>"]

    admin -->|"HTTPS/JSON<br/>Bearer JWT"| spa
    spa -->|"JSON over HTTP<br/>Authorization: Bearer"| api
    agent -->|"JSON over HTTP<br/>X-API-Key: agt_live_…"| api
    entry -->|"DDL at boot"| db
    api -->|"SQL / psycopg2<br/>connection pool"| db
    api -.->|"SMTP, if enabled"| smtp

    classDef c fill:#0d1117,stroke:#30363d,color:#fff
    classDef store fill:#0b4fc4,stroke:#1f6feb,color:#fff
    classDef ext fill:#484f58,stroke:#30363d,color:#fff
    class spa,api,entry c
    class db store
    class smtp,admin,agent ext
```

## Containers

| Container | Technology | Ships in compose? | Responsibility |
| --------- | ---------- | ----------------- | -------------- |
| Dashboard SPA | React 19, TS (strict), Vite | **No** — dev server only | Renders the control plane; holds tokens in `localStorage` |
| Control Plane API | FastAPI, SQLAlchemy 2.0, uvicorn | Yes (`act_api`) | Authn/authz, governance pipeline, audit |
| PostgreSQL | `postgres:16-alpine` | Yes (`act_postgres`) | Sole system of record |

The SPA has **no Dockerfile**. It is a real gap for production, tracked in
[deployment](../deployment/deployment.md#gaps-before-production), not an
oversight this document should paper over.

## The three API surfaces

The API exposes three prefixes, which is a deliberate migration seam, not an
accident. `settings.API_PREFIX` is `""`, so the legacy surface sits at the root.

```mermaid
flowchart LR
    subgraph api["Control Plane API"]
        legacy["<b>Legacy surface</b> — /<br/>/auth, /agents, /policies,<br/>/approvals, /audit, /dashboard…<br/><i>24h JWT, no session, not revocable</i>"]
        ident["<b>Identity surface</b> — /api/v1/identity<br/>orgs, users, departments, roles,<br/>agent identities, service accounts"]
        authv1["<b>Auth surface</b> — /api/v1/auth<br/>login, mfa/verify, refresh,<br/>logout, me, sessions<br/><i>15m access + 7d rotating refresh</i>"]
    end
    legacy -.->|"migrates onto<br/>(planned)"| authv1

    classDef old fill:#6e2b2b,stroke:#a03030,color:#fff
    classDef new fill:#0d4429,stroke:#2ea043,color:#fff
    class legacy old
    class ident,authv1 new
```

Two authentication systems coexist today. This is the single most important
thing to understand about the current architecture, and the reason for
[ADR-0005](../adr/0005-additive-identity-layer-alongside-legacy-auth.md):

| | Legacy `/auth/login` | `/api/v1/auth/login` |
| --- | --- | --- |
| Access token | JWT, **24h** (`ACCESS_TOKEN_EXPIRE_MINUTES=1440`) | JWT, **15 min** |
| Refresh token | None | Opaque `rt_…`, 7d, rotating, hashed at rest |
| Session record | None | `auth_sessions` row, revocable |
| Lockout | No | Yes — 5 failures / 15 min |
| Login history | No | Yes |
| Security events | No (audit log only) | Yes |

A token minted by the legacy route cannot be revoked and lives for a day. Since
Part 4.2.2.2 the `/api/v1/auth` surface revalidates its session on every request, so
revocation there is immediate — which makes the legacy route **the platform's only
non-revocable credential**, and its true worst-case session lifetime.

## Cross-cutting middleware

```mermaid
flowchart LR
    req(["Request"]) --> cors["CORSMiddleware"] --> route["Route + Depends(authenticate)"] --> handler["Exception handlers<br/>IdentityError → envelope<br/>PasswordPolicyError → 422"] --> resp(["Response"])
```

That is the entire middleware stack. There is **no** rate limiting, no security-
headers middleware, no request-ID middleware, and no HTTPS redirect. Forensic
context (`request_id`, `trace_id`) is read from client-supplied headers by
`RequestContext`, which means it is useful for correlation and **must not be
trusted for attribution**. See [threat model](../security/threat-model.md).

## Data flow summary

- The SPA never talks to PostgreSQL. All access is mediated by the API.
- Agents never receive a session or a refresh token.
- Migrations are applied by the API container's entrypoint (`alembic upgrade
  head`) before uvicorn starts — so a rolling deploy of >1 API replica would
  race. Single-replica assumption, documented in
  [deployment](../deployment/deployment.md).
