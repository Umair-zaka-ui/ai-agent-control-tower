# Entity Relationship Diagrams

> **24 tables**, generated from `Base.metadata` and verified against
> `backend/migrations/versions/0001…0009`. Split by bounded context because a
> single 24-table diagram is a poster, not a document.

Verify the table count still matches:

```bash
cd backend && python -c "import app.main; from app.core.database import Base; print(len(Base.metadata.tables))"
```

## Global invariants

- **Every primary key is a UUID.** No sequential integer IDs are exposed.
- **`organizations` is the tenancy root.** Nearly every table carries
  `organization_id` with `ON DELETE CASCADE`. Multi-tenancy is enforced in the
  service layer by filtering on the caller's org — **not** by Postgres row-level
  security. See [threat model](../security/threat-model.md#t-tampering).
- **Secrets are never stored in plaintext.** `password_hash` (argon2id),
  `token_hash` / `key_hash` / `secret_hash` (SHA-256 of a high-entropy token).
- Timestamps are `TimestampMixin` (`created_at`, `updated_at`) except on
  append-only tables, which carry `created_at` only.

---

## 1. Identity & Access

The Phase 4 identity platform. `users` predates it; everything else here was
added by migrations `0006`–`0009`.

```mermaid
erDiagram
    organizations ||--o{ users : "employs"
    organizations ||--o{ departments : "contains"
    organizations ||--o{ roles : "scopes"
    organizations ||--o{ service_accounts : "owns"
    organizations ||--o{ external_clients : "registers"
    organizations ||--o{ security_events : "records"

    departments ||--o{ teams : "contains"
    departments ||--o| users : "manager_id"
    users ||--o{ departments : "manages"

    users ||--o{ user_roles : "assigned"
    roles ||--o{ user_roles : "grants"
    roles ||--o{ role_permissions : "has"
    rbac_permissions ||--o{ role_permissions : "granted via"

    users ||--o{ auth_sessions : "opens"
    users ||--o{ auth_devices : "uses"
    users ||--o{ login_history : "attempts"
    users ||--o{ service_accounts : "owns"
    auth_sessions ||--o{ refresh_tokens : "one family"
    auth_devices ||--o{ auth_sessions : "hosts"

    organizations {
        uuid id PK
        varchar name
        varchar status "ACTIVE"
    }
    users {
        uuid id PK
        uuid organization_id FK
        uuid department_id FK "nullable, SET NULL"
        varchar email UK
        varchar password_hash "argon2id"
        varchar role "legacy enum"
        boolean is_active
        varchar status "IdentityStatus"
    }
    auth_sessions {
        uuid id PK
        uuid user_id FK
        uuid organization_id FK
        uuid device_id FK
        varchar status "SessionStatus"
        varchar ip_address
        varchar country
        varchar city
        varchar browser
        varchar operating_system
        varchar login_method
        datetime last_activity_at
        datetime idle_expires_at "30 min sliding"
        datetime absolute_expires_at "12 h ceiling"
        datetime revoked_at "null = active"
        varchar revoked_reason "SessionRevocationReason"
        int security_score "100 = healthy"
        boolean is_trusted
        uuid refresh_token_family_id "one family per session"
    }
    refresh_tokens {
        uuid id PK
        uuid session_id FK
        uuid family_id "denormalised: no join on reuse sweep"
        varchar token_hash UK "SHA-256, never plaintext"
        datetime expires_at
        datetime revoked_at
        uuid rotated_to_id "rotation chain"
        datetime reuse_detected_at "the replayed token"
    }
    login_history {
        uuid id PK
        uuid user_id FK "nullable: unknown email"
        varchar email
        boolean success
        varchar failure_reason
        varchar ip_address
        varchar country
        varchar city
    }
    security_events {
        uuid id PK
        uuid organization_id FK
        varchar event_type
        varchar actor_type
        uuid actor_id
        varchar request_id
        varchar correlation_id
        jsonb meta
    }
    auth_devices {
        uuid id PK
        uuid user_id FK
        varchar fingerprint "advisory, forgeable"
        varchar device_name
        varchar device_type
        varchar browser
        varchar operating_system
        varchar status "UNKNOWN / TRUSTED / BLOCKED"
        varchar last_ip
        datetime last_seen_at
    }
    roles {
        uuid id PK
        uuid organization_id FK "null = system role"
        varchar name
        boolean is_system
    }
    rbac_permissions {
        uuid id PK
        varchar code UK "e.g. agents:write"
    }
    role_permissions {
        uuid id PK
        uuid role_id FK
        uuid permission_id FK
    }
    user_roles {
        uuid id PK
        uuid user_id FK
        uuid role_id FK
    }
    departments {
        uuid id PK
        uuid organization_id FK
        uuid manager_id FK
    }
    teams {
        uuid id PK
        uuid department_id FK
        uuid lead_id FK
    }
    service_accounts {
        uuid id PK
        uuid organization_id FK
        uuid owner_id FK
        varchar client_secret_hash
        jsonb permissions
    }
    external_clients {
        uuid id PK
        uuid organization_id FK
        varchar client_id UK
        varchar secret_hash
        jsonb allowed_scopes
    }
```

### Notes that matter

- **`refresh_tokens.rotated_to_id` + `revoked_at` encode reuse detection.** A
  token that is *revoked and already rotated* has been replayed → theft signal →
  the family is revoked and the session becomes `SUSPICIOUS`. Requiring *both*
  conditions is what stops an ordinary logout from being reported as theft.
- **`family_id` is first-class and denormalised** onto `refresh_tokens`, so a reuse
  sweep never needs a join and a family survives its session row forensically.
- **`auth_sessions` carries two deadlines.** `idle_expires_at` slides forward on
  activity; `absolute_expires_at` never moves. Both are enforced on every request
  — see [session lifecycle](../../identity/session-lifecycle.md).
- **`auth_devices.fingerprint` is advisory.** It is derived from client-supplied
  headers, so it can be forged; it recognises a device for UX and risk scoring and
  is never an authentication factor. `BLOCKED` can only deny, never grant.
- **`login_history.user_id` is nullable on purpose.** A failed login for an
  unknown email must still be recorded without leaking that the email is unknown.
- `users.role` (legacy enum) and `user_roles` (RBAC) both exist. The enum is the
  legacy coarse role; RBAC is the real authorization source. Another artefact of
  the [additive migration](../adr/0005-additive-identity-layer-alongside-legacy-auth.md).

---

## 2. Agent Governance

The product's core domain: what an agent tried to do, and what we decided.

```mermaid
erDiagram
    organizations ||--o{ agents : "owns"
    organizations ||--o{ policies : "defines"
    organizations ||--o{ agent_actions : "scopes"
    organizations ||--o{ approvals : "scopes"

    agents ||--o{ agent_api_keys : "authenticates with"
    agents ||--o{ permissions : "granted"
    agents ||--o{ agent_actions : "attempts"
    agents ||--o{ agent_identities : "Phase 4 identity"

    agent_actions ||--o| approvals : "may require"
    approvals ||--o{ approval_comments : "discussion"
    users ||--o{ approval_comments : "writes"
    users ||--o{ approvals : "reviews / assigned"
    users ||--o{ policies : "created_by"

    agents {
        uuid id PK
        uuid organization_id FK
        varchar name
        varchar agent_type
        varchar api_key_hash
        varchar status "AgentStatus"
        jsonb capabilities
        int default_risk_score
        int max_allowed_risk
        boolean human_approval_required
        int auto_suspend_threshold
        varchar risk_level
        varchar health
    }
    agent_api_keys {
        uuid id PK
        uuid agent_id FK
        varchar key_hash "SHA-256"
        varchar key_prefix "agt_live_"
        datetime expires_at
        datetime last_used_at
    }
    permissions {
        uuid id PK
        uuid organization_id FK
        uuid agent_id FK
        varchar resource
        varchar action
        boolean allowed
    }
    agent_actions {
        uuid id PK
        uuid organization_id FK
        uuid agent_id FK
        varchar resource
        varchar action
        jsonb input_payload "treated as hostile"
        jsonb output_payload
        int risk_score
        varchar decision "ALLOW / BLOCK / PENDING_APPROVAL"
        text decision_reason
        varchar status
    }
    policies {
        uuid id PK
        uuid organization_id FK
        uuid created_by FK
        varchar resource
        varchar action
        jsonb conditions
        varchar decision
        int priority "lower = evaluated first"
        boolean enabled
        varchar severity
        int trigger_count
        datetime last_triggered_at
    }
    approvals {
        uuid id PK
        uuid organization_id FK
        uuid agent_action_id FK
        uuid requested_by_agent_id FK
        uuid reviewed_by_user_id FK
        uuid assigned_to_user_id FK
        varchar decision
        varchar priority
        datetime sla_due_at
        datetime escalated_at
        datetime reviewed_at
    }
    approval_comments {
        uuid id PK
        uuid approval_id FK
        uuid user_id FK
        text comment
    }
    agent_identities {
        uuid id PK
        uuid agent_id FK
        varchar client_id UK
        varchar credential_type
        varchar status
        datetime expires_at
    }
```

### Notes that matter

- **`agent_actions.input_payload` is attacker-controlled JSONB.** It is stored
  verbatim for forensics and rendered in the dashboard. Any consumer must treat
  it as untrusted — see [threat model](../security/threat-model.md#s-spoofing).
- **`agents.max_allowed_risk`, `human_approval_required`, `auto_suspend_threshold`
  and `default_risk_score` are written but never read.** No engine consumes them;
  `decision_engine` uses global constants. Setting them has no effect today — see
  [the governance sequence](../sequences/03-agent-action-governance.md#configured-but-unused-agent-columns).
- `policies.priority` orders evaluation (lower first); `conditions` is a JSONB
  predicate tree interpreted by `policy_engine`.
- `approvals` carries SLA + escalation fields; `agent_actions` ↔ `approvals` is
  0..1 — only `PENDING_APPROVAL` decisions create a row.
- `agents.api_key_hash` (Phase 1) and `agent_api_keys` (Phase 2, rotatable)
  coexist. New code should use `agent_api_keys`.

---

## 3. Audit

One table. Deliberately isolated: it references `organizations` and nothing else,
so it can be moved to cold storage or a separate database without a schema change.

```mermaid
erDiagram
    organizations ||--o{ audit_logs : "records"

    audit_logs {
        uuid id PK
        uuid organization_id FK
        varchar actor_type "USER / AGENT / SYSTEM"
        uuid actor_id "no FK: actor may be deleted"
        varchar event_type
        varchar entity_type
        uuid entity_id "no FK: polymorphic"
        jsonb before_state
        jsonb after_state
        jsonb metadata
        varchar ip_address
        varchar user_agent
        varchar request_id "client-supplied"
        varchar trace_id "client-supplied"
        datetime created_at
    }
```

`actor_id` and `entity_id` intentionally carry **no foreign key**: an audit
record must survive the deletion of the thing it describes. This is the standard
trade-off for audit tables and is why cascading deletes cannot erase history.

`request_id` and `trace_id` come from request headers. They are correlation aids,
**not** evidence of identity.
