# Entity Relationship Diagrams

> **123 tables** in `Base.metadata` (124 in a live database — Alembic manages
> `alembic_version` itself, and it is not a model). Generated from
> `Base.metadata` and verified against the live schema at migration head
> `0046_trace_explorer_index` (Phase 4.2 added one index and no table at all;
> Phase 4.1 before it added two nullable columns and no
> table, so the diagrams below are unchanged in shape:
> `agent_executions.request_id` and `runtime_events.span_id`). Split by bounded context because a single
> 123-table diagram is a poster, not a document.
>
> **Last regenerated 2026-08-24.** This document declared *24 tables* for a long
> while, covering only the Phase 4 identity and authorization contexts — it had
> drifted since roughly Phase 3.4 and was recorded as a known gap in
> `REPO_STATE.md` §9 before being closed here. If the count below stops
> matching the command, assume the diagrams have drifted too.

Verify the table count still matches:

```bash
cd backend && python -c "import app.main; from app.core.database import Base; print(len(Base.metadata.tables))"
```

**Column lists are truncated** where a table is wide — a `_N_more_columns` row
says how many were elided. Primary and foreign keys are always shown, because
those are what the diagram is *for*; `created_at`/`updated_at` are omitted
throughout (see the timestamps invariant below). The authority for any column
is the model, never this file.

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

### Resource-based authorization (Phase 4.3.4)

Fine-grained, per-resource authorization metadata. `resources` is the registry;
the four satellite tables cascade with it. `(resource_type, resource_id)` also
links to the Phase 4.3.3 `resource_ownership` hierarchy path (not shown).

```mermaid
erDiagram
    organizations ||--o{ resources : "owns"
    resources ||--o{ resource_acl : "controls"
    resources ||--o{ resource_shares : "shared via"
    resources ||--o{ ownership_history : "transfers"
    resources ||--o{ resource_delegations : "delegated via"

    resources {
        uuid id PK
        varchar resource_type "with resource_id: UK"
        uuid resource_id "the underlying object"
        uuid organization_id FK
        uuid owner_id "no FK: polymorphic by owner_type"
        varchar owner_type "USER / TEAM / DEPARTMENT / ORG / SVC"
        varchar visibility "PRIVATE..PUBLIC_INTERNAL"
        varchar status "ACTIVE / ARCHIVED / SYSTEM"
        jsonb policy "resource policy rules"
    }
    resource_acl {
        uuid id PK
        uuid resource_id FK
        varchar principal_type
        uuid principal_id "no FK: polymorphic"
        varchar permission "code, action or *"
        varchar effect "ALLOW / DENY"
        datetime expires_at "expired = ignored"
    }
    resource_shares {
        uuid id PK
        uuid resource_id FK
        varchar shared_with_type
        uuid shared_with_id "no FK: polymorphic"
        varchar access_level "READ..MANAGE"
        datetime expires_at
    }
    ownership_history {
        uuid id PK
        uuid resource_id FK
        uuid previous_owner
        uuid new_owner
        uuid changed_by
        varchar reason
    }
    resource_delegations {
        uuid id PK
        uuid resource_id FK
        uuid delegate_id FK
        jsonb permissions "actions or codes"
        datetime expires_at
        varchar status "ACTIVE / REVOKED"
    }
```

`owner_id`, `principal_id` and `shared_with_id` are polymorphic (typed by their
companion `*_type` column), so they carry no FK — the same pattern as
`audit_logs.actor_id`. Explicit DENY beats every allow; expired rows are ignored
at evaluation time — see [resource authorization](../../authorization/resource-authorization.md).

### ABAC engine (Phase 4.3.5)

Context-aware policies layered over RBAC + resource authorization. A row in
`abac_policies` is one *version*; versions of the same logical policy share
`policy_family_id` and at most one version per family is `ACTIVE`.
`organization_id IS NULL` marks a platform-level policy that applies to every
tenant and cannot be overridden by organization policies.

```mermaid
erDiagram
    organizations ||--o{ abac_policies : "scopes"
    organizations ||--o{ abac_evaluations : "scopes"
    abac_policies ||--o{ abac_policy_exceptions : "exempted via"

    abac_policies {
        uuid id PK
        uuid policy_family_id "versions share this"
        uuid organization_id FK "NULL = platform"
        varchar status "DRAFT..ARCHIVED"
        int version
        int priority
        varchar combining_algorithm "DENY_OVERRIDES default"
        varchar scope_type "PLATFORM..RESOURCE"
        uuid scope_id
        jsonb target "resource_types / actions / ..."
        jsonb conditions "nested all-any-not tree"
        varchar effect "ALLOW..LOG_ONLY"
        jsonb obligations
        datetime valid_from
        datetime valid_until
        datetime published_at
    }
    abac_policy_versions {
        uuid id PK
        uuid policy_family_id "no FK: history is immutable"
        int version
        jsonb snapshot "full policy at publish"
        uuid created_by
    }
    attribute_definitions {
        uuid id PK
        varchar name UK "e.g. resource.contains_phi"
        varchar category "SUBJECT..AI"
        varchar data_type "STRING..OBJECT"
        varchar sensitivity "RESTRICTED = redacted"
        jsonb supported_operators
        boolean is_system
        boolean enabled
    }
    abac_evaluations {
        uuid id PK
        uuid organization_id FK
        uuid identity_id "no FK: survives deletion"
        varchar resource_type
        uuid resource_id
        varchar action
        varchar decision "ALLOW / DENY / REQUIRE_*"
        jsonb matched_policy_ids
        jsonb obligations
        jsonb explanation "redacted trace"
        float evaluation_time_ms
        varchar request_id
        varchar correlation_id
    }
    abac_policy_exceptions {
        uuid id PK
        uuid policy_id FK
        varchar subject_type
        uuid subject_id
        varchar reason
        uuid approved_by
        datetime valid_until "expires automatically"
        varchar status "ACTIVE / REVOKED"
    }
```

`abac_policy_versions` deliberately carries **no FK** to `abac_policies`:
published history must survive even if the working row is deleted (§40.13).
Only names registered in `attribute_definitions` may appear in `conditions`;
`RESTRICTED` attributes are redacted from user-facing explanations and logs —
see [ABAC overview](../../authorization/abac/overview.md).

### Access reviews (Phase 4.3.7)

Periodic access certification. Activating a campaign snapshots every in-scope
role assignment as an item; a REVOKED decision removes the underlying
`user_roles` row through the RBAC service.

```mermaid
erDiagram
    organizations ||--o{ access_review_campaigns : "runs"
    access_review_campaigns ||--o{ access_review_items : "reviews"

    access_review_campaigns {
        uuid id PK
        uuid organization_id FK
        varchar name
        varchar status "DRAFT..ARCHIVED"
        jsonb scope "role_ids / include_system_roles"
        uuid reviewer_id
        datetime due_at
        datetime activated_at
        datetime completed_at
    }
    access_review_items {
        uuid id PK
        uuid campaign_id FK
        uuid subject_id "no FK: survives user deletion"
        varchar subject_label
        uuid assignment_id "the user_roles row under review"
        varchar role_name "kept legible after revoke"
        varchar decision "PENDING / CERTIFIED / REVOKED"
        uuid decided_by
        datetime decided_at
        varchar comment
    }
```

`subject_id`, `assignment_id` and the label columns are deliberately
denormalized: a completed campaign is a compliance record and must stay
readable after the user, role or assignment it certified is gone — see
[access reviews](../../admin/access-reviews.md).

### Identity Governance & Administration (Phase 4.3.8)

SoD and toxic-permission detection share one rule table (`rule_type`
discriminates them). A rule match creates a `governance_findings` row;
findings drive `remediation_actions`. Risk scores, compliance reports and
privileged-account reviews are independent snapshot tables, each keyed to an
identity or organization rather than to one another.

```mermaid
erDiagram
    organizations ||--o{ sod_rules : "defines"
    organizations ||--o{ governance_findings : "detects"
    sod_rules ||--o{ governance_findings : "matched by"
    governance_findings ||--o{ remediation_actions : "remediated by"
    organizations ||--o{ governance_risk_scores : "scores"
    organizations ||--o{ compliance_reports : "generates"
    organizations ||--o{ privileged_account_reviews : "reviews"

    sod_rules {
        uuid id PK
        uuid organization_id FK
        varchar rule_type "SOD / TOXIC_PERMISSION"
        varchar name
        varchar risk_level "LOW..CRITICAL"
        jsonb permissions_a
        jsonb permissions_b
        varchar status "DRAFT / ACTIVE / DISABLED"
        uuid approved_by
    }
    governance_findings {
        uuid id PK
        uuid organization_id FK
        varchar finding_type "SOD_VIOLATION / TOXIC_PERMISSION / ORPHANED_ACCOUNT / PRIVILEGED_REVIEW_DUE"
        varchar severity
        uuid identity_id "nullable: resource-scoped findings"
        varchar identity_label
        uuid resource_id "stale key / unused role"
        uuid rule_id FK "nullable"
        jsonb details
        varchar status "OPEN..DISMISSED"
    }
    remediation_actions {
        uuid id PK
        uuid organization_id FK
        uuid finding_id FK
        varchar action_type
        varchar status "PENDING..CANCELLED"
        varchar mode "MANUAL / APPROVAL / AUTOMATIC"
        jsonb payload
    }
    governance_risk_scores {
        uuid id PK
        uuid organization_id FK
        uuid identity_id "unique per org"
        int score "0-100"
        varchar band "LOW..CRITICAL"
        jsonb factors
    }
    compliance_reports {
        uuid id PK
        uuid organization_id FK
        varchar framework "SOC2 / ISO27001 / HIPAA / GDPR / NIST / CIS / INTERNAL"
        varchar report_type
        jsonb payload "immutable evidence snapshot"
    }
    privileged_account_reviews {
        uuid id PK
        uuid organization_id FK
        uuid identity_id
        varchar role_name
        int risk_score
        varchar status "PENDING / APPROVED / REVOKED"
        datetime due_at
    }
```

Findings are the hub: SoD/toxic detection, orphaned-identity scans and
privileged-review-due checks all write to the same `governance_findings`
table, so the findings explorer and the remediation queue see every
governance issue regardless of source — see
[docs/governance/](../../governance/).

---

### Agent Runtime & Lifecycle Management (Phase 5.0)

`agents` (§1 above) gains additive runtime-lifecycle columns rather than a
parallel registry: `slug`, `project_id`, `owner_type`/`owner_id`,
`criticality`, `data_classification`, `default_environment`,
`lifecycle_status`, `archived_at`. Everything below hangs off
`agents.id`. `agent_executions` doubles as the execution queue — a worker
claims a row with `SELECT ... FOR UPDATE SKIP LOCKED` and takes a lease in
`execution_locks`; there is no separate queue table. See
[docs/runtime/architecture.md](../../runtime/architecture.md).

```mermaid
erDiagram
    agents ||--o{ agent_definitions : "describes"
    agents ||--o{ agent_versions : "versions"
    agent_definitions ||--o{ agent_versions : "snapshotted by"
    agents ||--o{ agent_deployments : "deployed as"
    agent_versions ||--o{ agent_deployments : "runs"
    agents ||--o{ agent_executions : "executes"
    agent_versions ||--o{ agent_executions : "runs under"
    agent_deployments ||--o{ agent_executions : "queued on"
    agent_executions ||--o{ execution_attempts : "attempted"
    agent_executions ||--o| execution_locks : "leased by"
    agents ||--o{ agent_capabilities : "assigned"
    capabilities ||--o{ agent_capabilities : "granted as"
    agents ||--o{ agent_tools : "assigned"
    tools ||--o{ agent_tools : "granted as"
    agent_executions ||--o{ tool_calls : "invokes"
    tools ||--o{ tool_calls : "called via"
    organizations ||--o{ runtime_events : "streams"
    organizations ||--o{ runtime_approvals : "gates"
    organizations ||--o{ idempotency_records : "dedupes"

    agent_definitions {
        uuid id PK
        uuid agent_id FK
        varchar framework
        varchar entrypoint
        jsonb configuration_schema
        jsonb input_schema
        jsonb output_schema
    }
    agent_versions {
        uuid id PK
        uuid agent_id FK
        uuid definition_id FK
        int version "monotonic per agent"
        varchar semantic_version
        varchar status "DRAFT..PUBLISHED..REVOKED"
        varchar checksum "sha256, verified at publish"
        jsonb model_configuration
        jsonb capabilities_snapshot
        jsonb tools_snapshot
        jsonb policy_snapshot
        datetime published_at
    }
    agent_deployments {
        uuid id PK
        uuid agent_id FK
        uuid agent_version_id FK
        uuid organization_id FK
        varchar environment "DEVELOPMENT..SANDBOX"
        varchar deployment_strategy "RECREATE / CANARY / ROLLING / BLUE_GREEN"
        varchar status "CREATED..ACTIVE..RETIRED"
        jsonb runtime_limits
        varchar health_status
    }
    agent_executions {
        uuid id PK
        uuid organization_id FK
        uuid agent_id FK
        uuid agent_version_id FK
        uuid deployment_id FK "nullable"
        uuid parent_execution_id FK "nullable: replay lineage"
        varchar idempotency_key "nullable"
        jsonb input_payload
        jsonb output_payload
        varchar status "CREATED..QUEUED..SUCCEEDED..DEAD_LETTERED"
        varchar decision "ALLOW / DENY / REQUIRE_APPROVAL"
        int risk_score
        int attempt_count
        numeric cost
    }
    execution_attempts {
        uuid id PK
        uuid execution_id FK
        int attempt_number
        varchar worker_id
        varchar status
        varchar error_code
    }
    execution_locks {
        uuid id PK
        uuid execution_id FK "unique: one lease at a time"
        varchar worker_id
        datetime expires_at
    }
    capabilities {
        uuid id PK
        varchar name "unique, global catalog"
        varchar risk_level
        boolean requires_approval
    }
    agent_capabilities {
        uuid id PK
        uuid agent_id FK
        uuid agent_version_id FK "nullable"
        uuid capability_id FK
        varchar status "REQUESTED..APPROVED..REVOKED"
    }
    tools {
        uuid id PK
        uuid organization_id FK "nullable: platform-wide tool"
        varchar name
        varchar tool_type "FUNCTION / INTERNAL_API / EXTERNAL_API / ..."
        boolean requires_approval
        boolean enabled
    }
    agent_tools {
        uuid id PK
        uuid agent_id FK
        uuid agent_version_id FK "nullable"
        uuid tool_id FK
        jsonb allowed_actions
        jsonb constraints
        varchar status "REQUESTED..APPROVED..REVOKED"
    }
    tool_calls {
        uuid id PK
        uuid execution_id FK
        uuid agent_id FK
        uuid tool_id FK
        varchar action
        varchar status "ALLOWED / DENIED"
    }
    runtime_events {
        uuid id PK
        uuid organization_id FK
        uuid agent_id FK "nullable"
        uuid deployment_id FK "nullable"
        uuid execution_id FK "nullable"
        varchar event_type
        varchar severity
    }
    runtime_approvals {
        uuid id PK
        uuid organization_id FK
        uuid agent_id FK "nullable"
        uuid deployment_id FK "nullable"
        uuid execution_id FK "nullable"
        varchar requested_action "DEPLOYMENT / EXECUTION"
        varchar status "PENDING / APPROVED / REJECTED"
    }
    idempotency_records {
        uuid id PK
        uuid organization_id FK
        uuid agent_id FK
        varchar idempotency_key
        varchar request_hash
        uuid execution_id FK
        datetime expires_at
    }
```

`deployment_health` (one row per heartbeat sample, FK to
`agent_deployments`) is omitted above for readability — see
[docs/runtime/health-and-observability.md](../../runtime/health-and-observability.md).

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


---

## 4. Identity lifecycle (Phases 4.2.2.3.1–4.2.2.3.4)

Registration, verification and the invitation flow. `rate_limit_hits` is the
only table here that is deliberately *not* tenant-scoped: it counts attempts
against an endpoint and an identifier before anyone is authenticated, so there
is no organization to scope it to yet.

```mermaid
erDiagram
    invitations {
        uuid id PK
        uuid organization_id FK
        uuid role_id FK
        uuid department_id FK
        uuid team_id FK
        uuid invited_by FK
        string email
        string token_hash UK
        string status
        datetime expires_at
        string _5_more_columns
    }
    email_verifications {
        uuid id PK
        uuid user_id FK
        string verification_token_hash UK
        datetime expires_at
        datetime verified_at
        datetime superseded_at
        string purpose
        string new_email
    }
    user_profiles {
        uuid id PK
        uuid user_id FK
        string first_name
        string last_name
        string job_title
        string department
        string phone
        string timezone
        string language
        string avatar_url
    }
    rate_limit_hits {
        uuid id PK
        string bucket
    }
```

Recovery and account protection. `password_history` exists so a reset cannot
reuse a recent password; `account_locks` and `blocked_ips` are the two
enforcement surfaces, and `identity_risk_events` is the evidence behind them.

```mermaid
erDiagram
    password_reset_requests {
        uuid id PK
        uuid user_id FK
        uuid organization_id FK
        string token_hash UK
        string status
        datetime expires_at
        datetime used_at
        string created_ip
        string created_user_agent
    }
    password_history {
        uuid id PK
        uuid user_id FK
        string password_hash
    }
    account_locks {
        uuid id PK
        uuid user_id FK
        uuid organization_id FK
        uuid unlocked_by FK
        string reason
        string status
        datetime locked_at
        datetime expires_at
        datetime unlocked_at
        jsonb meta
    }
    blocked_ips {
        uuid id PK
        uuid organization_id FK
        uuid created_by FK
        string ip_address
        string reason
        datetime expires_at
    }
    identity_protection_rules {
        uuid id PK
        uuid organization_id FK
        string name
        string description
        jsonb conditions
        string decision
        bool enabled
        int priority
    }
    identity_risk_events {
        uuid id PK
        uuid organization_id FK
        uuid user_id FK
        string event_type
        int risk_score
        string risk_level
        jsonb signals
        string decision
        string ip_address
        string user_agent
    }
```

## 5. External identity federation (Phase 2.3.1)

The inversion that makes federation different from every connector: the
platform holds **no** user secret here. It verifies an assertion arriving
inward, rather than presenting a credential outward.

```mermaid
erDiagram
    identity_federation_configs {
        uuid id PK
        uuid organization_id FK
        uuid default_role_id FK
        uuid created_by FK
        string protocol
        string provider_type
        string display_name
        jsonb configuration
        string encrypted_client_secret
        bool jit_provisioning_enabled
        string _4_more_columns
    }
    federated_identities {
        uuid id PK
        uuid user_id FK
        uuid organization_id FK
        uuid federation_config_id FK
        string external_subject_id
        datetime last_federated_login_at
    }
    identity_federation_configs ||--o{ federated_identities : "federation_config_id"
```

## 6. Authorization engine internals (Phases 4.3.1–4.3.6)

The tables behind permission resolution rather than its inputs.
`permission_cache` is derived state and safe to truncate; `permission_versions`
is what invalidates it. `authorization_decisions` and `authorization_audit` are
append-only records of what the gateway decided and why.

```mermaid
erDiagram
    permission_groups {
        uuid id PK
        string name UK
        string display_name
        string description
        int sort_order
    }
    permission_versions {
        uuid id PK
        uuid organization_id
        int version
    }
    permission_cache {
        uuid id PK
        uuid identity_id
        uuid organization_id
        jsonb grants_json
        int version
        datetime expires_at
    }
    role_hierarchy {
        uuid id PK
        uuid parent_role_id FK
        uuid child_role_id FK
    }
    authorization_decisions {
        uuid id PK
        uuid identity_id
        uuid organization_id
        string permission
        string resource_type
        uuid resource_id
        bool allowed
        string reason
        string scope
        string source_role
        string _3_more_columns
    }
    authorization_audit {
        uuid id PK
        uuid organization_id FK
        uuid actor_id
        uuid identity_id
        string event_type
        string permission
        string resource_type
        uuid resource_id
        string decision
        string reason
        string _2_more_columns
    }
```

## 7. Organization hierarchy (Phase 4.3.3)

`business_units` and `projects` form the scope tree that
`resource_ownership` (section 1) resolves paths against; `delegations` grants
authority down it for a bounded period.

```mermaid
erDiagram
    business_units {
        uuid id PK
        uuid organization_id FK
        uuid manager_id FK
        string name
        string status
    }
    projects {
        uuid id PK
        uuid team_id FK
        uuid owner_id FK
        string name
        string status
    }
    delegations {
        uuid id PK
        uuid organization_id FK
        uuid delegatee_id FK
        uuid delegator_id
        string scope_type
        uuid scope_id
        string permission
        datetime revoked_at
    }
```

## 8. Enterprise agent registry (Phase 5.1)

Accountable ownership and a 13-state lifecycle, plus the import/export and
duplicate-detection machinery. `agent_lifecycle_events` is append-only.

```mermaid
erDiagram
    agent_lifecycle_events {
        uuid id PK
        uuid agent_id FK
        uuid organization_id FK
        string previous_status
        string new_status
        string reason
        uuid requested_by
        uuid approved_by
        uuid authorization_decision_id
        string request_id
        string _3_more_columns
    }
    agent_validation_runs {
        uuid id PK
        uuid agent_id FK
        string status
        string validator_version
        jsonb summary
        jsonb errors
        jsonb warnings
        jsonb checks
        datetime started_at
        datetime completed_at
        string _2_more_columns
    }
    agent_duplicate_matches {
        uuid id PK
        uuid source_agent_id FK
        uuid candidate_agent_id FK
        string match_type
        decimal confidence_score
        jsonb matching_fields
        string status
        uuid reviewed_by
        string review_decision
        string review_reason
        string _2_more_columns
    }
    agent_ownership_history {
        uuid id PK
        uuid agent_id FK
        string owner_role
        string previous_owner_type
        uuid previous_owner_id
        string new_owner_type
        uuid new_owner_id
        string reason
        uuid changed_by
        uuid approved_by
        string _1_more_columns
    }
    agent_import_jobs {
        uuid id PK
        uuid organization_id FK
        string file_name
        string format
        string mode
        string status
        int total_records
        int successful_records
        int failed_records
        int warning_records
        string _4_more_columns
    }
    agent_import_items {
        uuid id PK
        uuid import_job_id FK
        uuid agent_id FK
        string record_identifier
        string status
        jsonb errors
        jsonb warnings
    }
    agent_export_jobs {
        uuid id PK
        uuid organization_id FK
        string export_type
        string format
        jsonb filters
        string status
        int record_count
        string storage_reference
        string payload
        datetime expires_at
        string _3_more_columns
    }
    agent_migration_records {
        uuid id PK
        uuid agent_id FK
        string migration_batch_id
        string legacy_source
        string legacy_id
        string migration_status
        jsonb mapping_warnings
        uuid migrated_by
        datetime migrated_at
    }
    agent_import_jobs ||--o{ agent_import_items : "import_job_id"
```

## 9. Versioning, signing & release (Phases 5.2.x)

An `agent_versions` row is immutable once published, which is why so much here
is a satellite table rather than a column: a snapshot, a signature, a
provenance record and a compatibility finding all describe a version without
being able to alter it.

`signing_keys`/`signing_key_versions` hold **public** key material and
metadata only — the private key lives in `backend/.keys/` or a vault, never in
the database. See `RECOVERY.md` on why that directory is the one thing no
backup script captures by default.

```mermaid
erDiagram
    agent_version_snapshots {
        uuid id PK
        uuid agent_version_id FK
        jsonb snapshot
        string checksum
        string checksum_algorithm
    }
    agent_version_status_history {
        uuid id PK
        uuid agent_version_id FK
        string previous_status
        string new_status
        string reason
        uuid changed_by
    }
    agent_version_signatures {
        uuid id PK
        uuid agent_version_id FK
        uuid signing_key_id FK
        uuid signed_by FK
        string manifest_digest
        string signature
        string algorithm
        int signing_key_version
        string signature_type
        jsonb dsse_envelope
        string _2_more_columns
    }
    agent_version_provenance {
        uuid id PK
        uuid agent_version_id FK
        uuid actor_id
        string actor_type
        string source_repository
        string source_commit
        string source_ref
        string build_environment
        string builder_identity
        string source_ip
        string _3_more_columns
    }
    agent_version_compatibility_findings {
        uuid id PK
        uuid agent_version_id FK
        uuid baseline_version_id FK
        string category
        string path
        string change_type
        string materiality
        string baseline_value
        string candidate_value
        string description
    }
    signing_keys {
        uuid id PK
        string key_id UK
        string provider
        string algorithm
        int current_version
        string status
        string public_key_pem
        datetime revoked_at
        string revocation_reason
    }
    signing_key_versions {
        uuid id PK
        uuid signing_key_id FK
        int version
        string public_key_pem
        datetime retired_at
    }
    agent_release_channels {
        uuid id PK
        string name UK
        string description
        bool is_default
    }
    agent_release_metadata {
        uuid id PK
        uuid agent_version_id FK
        string release_name
        string release_description
        string business_justification
        string change_category
        datetime release_window_start
        datetime release_window_end
        datetime support_end_date
        string approval_ticket
        string _7_more_columns
    }
    agent_release_notes {
        uuid id PK
        uuid agent_version_id FK
        string category
        string note
        uuid created_by
    }
    agent_release_artifacts {
        uuid id PK
        uuid agent_version_id FK
        string artifact_type
        string reference
        uuid created_by
    }
    signing_keys ||--o{ agent_version_signatures : "signing_key_id"
    signing_keys ||--o{ signing_key_versions : "signing_key_id"
```

## 10. Deployment, release & operations (Milestone 3)

The milestone's whole data model. Three things are worth reading off the
diagram rather than the prose:

- **`deployment_traffic_allocations` is revisioned, not mutated.** Each change
  writes a new row and retires the previous one, so the allocation history *is*
  the record of what traffic looked like when. `deployment_traffic_weights`
  hangs off it.
- **`rollout_plans` serves two operations.** `kind` is `CANARY` or `ROLLING`;
  they share the seven-state machine, the per-stage gates and the optimistic
  `revision`, and differ only in where the stage weights come from —
  operator-declared for a canary, derived from real fleet capacity for a
  rolling deployment (recorded in `cohort_plan`).
- **`deployment_events` is append-only at the database level**, not merely by
  convention: migration `0031` revokes UPDATE and DELETE on it.

```mermaid
erDiagram
    environments {
        uuid id PK
        uuid organization_id FK
        string name
        string display_name
        bool is_production
        jsonb policy
    }
    promotion_paths {
        uuid id PK
        uuid organization_id FK
        uuid from_environment_id FK
        uuid to_environment_id FK
        bool requires_approval
    }
    deployment_events {
        uuid id PK
        uuid deployment_id FK
        uuid organization_id FK
        string from_state
        string to_state
        string event_type
        string reason
        uuid actor_id
        string idempotency_key
    }
    deployment_preflight_results {
        uuid id PK
        uuid deployment_id FK
        uuid organization_id FK
        string verdict
        jsonb findings
        datetime evaluated_at
        uuid evaluated_by
    }
    deployment_traffic_allocations {
        uuid id PK
        uuid organization_id FK
        uuid agent_id FK
        uuid environment_id FK
        int revision
        bool is_current
        string reason
        uuid created_by
    }
    deployment_traffic_weights {
        uuid id PK
        uuid allocation_id FK
        uuid agent_version_id FK
        uuid deployment_id FK
        int weight
    }
    rollout_plans {
        uuid id PK
        uuid organization_id FK
        uuid agent_id FK
        uuid environment_id FK
        uuid candidate_version_id FK
        uuid stable_version_id FK
        string kind
        string state
        int current_stage_index
        jsonb cohort_plan
        string _5_more_columns
    }
    rollout_stages {
        uuid id PK
        uuid rollout_plan_id FK
        int stage_index
        int target_weight
        int min_duration_seconds
        int min_samples
        string health_requirement
        string advance_mode
        datetime entered_at
    }
    deployment_health_evaluations {
        uuid id PK
        uuid organization_id FK
        uuid deployment_id FK
        uuid agent_version_id FK
        uuid rollout_plan_id FK
        string health_state
        int sample_count
        jsonb metrics
        jsonb baseline_ref
        datetime window_start
        string _3_more_columns
    }
    rollback_trigger_policies {
        uuid id PK
        uuid organization_id FK
        uuid environment_id FK
        uuid agent_id FK
        jsonb thresholds
        string mode
        int min_samples
        int cooldown_seconds
        bool enabled
        uuid created_by
    }
    rollback_events {
        uuid id PK
        uuid organization_id FK
        uuid deployment_id FK
        uuid agent_id FK
        uuid environment_id FK
        uuid rollout_plan_id FK
        uuid from_version_id FK
        uuid to_version_id FK
        uuid policy_id FK
        string trigger
        string _8_more_columns
    }
    environments ||--o{ promotion_paths : "from_environment_id"
    environments ||--o{ deployment_traffic_allocations : "environment_id"
    deployment_traffic_allocations ||--o{ deployment_traffic_weights : "allocation_id"
    environments ||--o{ rollout_plans : "environment_id"
    rollout_plans ||--o{ rollout_stages : "rollout_plan_id"
    rollout_plans ||--o{ deployment_health_evaluations : "rollout_plan_id"
    environments ||--o{ rollback_trigger_policies : "environment_id"
    environments ||--o{ rollback_events : "environment_id"
    rollout_plans ||--o{ rollback_events : "rollout_plan_id"
    rollback_trigger_policies ||--o{ rollback_events : "policy_id"
```

## 11. Scheduler & execution worker fleet (Phases 3.8–3.9)

Both coordinate through PostgreSQL alone — `FOR UPDATE SKIP LOCKED` leases, no
broker (ADR-0002).

`uq_job_runs_occurrence` on `(job_definition_id, occurrence_key)` is the
exactly-once guard, and the key derives from the instant a job was *due* rather
than when it was claimed — a claim-time key would differ per instance and
defeat the constraint entirely.

`worker_registrations` is **ephemeral**: it describes running operating-system
processes, so after a restore every row names a process that no longer exists.
Nothing needs clearing by hand. The execution *lease* is not here — it is
`execution_locks` (section 3), whose `execution_id` UNIQUE constraint is the
structural guarantee that no two workers run one claimed execution, and which
is why Phase 3.9 added no second lease table.

```mermaid
erDiagram
    job_definitions {
        uuid id PK
        uuid organization_id FK
        string name
        string handler_key
        string schedule_kind
        jsonb schedule_spec
        jsonb params
        bool enabled
        int timeout_seconds
        jsonb retry_policy
        string _6_more_columns
    }
    job_runs {
        uuid id PK
        uuid job_definition_id FK
        uuid organization_id FK
        string occurrence_key
        string status
        int attempt
        string lease_owner
        datetime lease_expires_at
        datetime heartbeat_at
        datetime started_at
        string _5_more_columns
    }
    worker_registrations {
        uuid id PK
        string worker_id
        string cohort
        string status
        int concurrency
        int active_count
        string hostname
        datetime heartbeat_at
        datetime registered_at
        datetime stopped_at
    }
    job_definitions ||--o{ job_runs : "job_definition_id"
```

## 12. Runtime supporting tables

`provider_credentials` and `tool_credentials` store **encrypted** values with a
plaintext hint only; the Fernet key lives in `backend/.keys/`.
`idempotency_keys` is Phase 3.1's replay guard for deployment operations —
distinct from M1's older `idempotency_records` (section 3), which the two
phases deliberately did not merge.

```mermaid
erDiagram
    execution_messages {
        uuid id PK
        uuid execution_id FK
        int sequence
        string role
        string content
        string tool_call_id
        string tool_name
        jsonb tool_calls_requested
        int loop_iteration
        int prompt_tokens
        string _5_more_columns
    }
    model_pricing {
        uuid id PK
        string provider
        string model_name
        decimal prompt_cost_per_1k
        decimal completion_cost_per_1k
        string currency
        string pricing_version
        datetime effective_from
        datetime effective_to
    }
    provider_credentials {
        uuid id PK
        uuid organization_id FK
        uuid created_by FK
        string provider
        string encrypted_secret
        string secret_hint
        string base_url
        string status
        datetime last_used_at
    }
    tool_credentials {
        uuid id PK
        uuid organization_id FK
        uuid tool_id FK
        uuid created_by FK
        string encrypted_secret
        string secret_hint
        string status
    }
    idempotency_keys {
        uuid id PK
        uuid organization_id FK
        string operation
        string idempotency_key
        string request_fingerprint
        jsonb result_ref
        datetime expires_at
    }
```

## 13. Enterprise integration / connectors (Milestone 2)

`connectors` is a **platform-wide catalog** — the one table here without an
`organization_id`. Everything a tenant configures hangs off
`connector_instances`, which is tenant-scoped and is what actually holds
credentials.

```mermaid
erDiagram
    connectors {
        uuid id PK
        string connector_type
        string version
        jsonb capabilities
        jsonb config_schema
        jsonb auth_requirements
        jsonb tool_contracts
    }
    connector_instances {
        uuid id PK
        uuid organization_id FK
        uuid connector_id FK
        string name
        jsonb configuration
        string lifecycle_state
        string state_reason
        uuid created_by
        datetime last_health_check_at
        string current_health
    }
    connector_credentials {
        uuid id PK
        uuid connector_instance_id FK
        uuid organization_id FK
        uuid created_by FK
        string auth_scheme
        string encrypted_secret
        string secret_hint
        string status
        datetime last_validated_at
        string validation_status
    }
    connector_oauth_tokens {
        uuid id PK
        uuid connector_instance_id FK
        uuid organization_id FK
        string encrypted_access_token
        string encrypted_refresh_token
        datetime expires_at
    }
    connector_health_checks {
        uuid id PK
        uuid connector_instance_id FK
        uuid organization_id FK
        string check_type
        bool reachable
        bool auth_valid
        string result
        string reason
        int latency_ms
        datetime checked_at
    }
    connector_lifecycle_events {
        uuid id PK
        uuid connector_instance_id FK
        string from_state
        string to_state
        string reason
        uuid actor_id
    }
    connectors ||--o{ connector_instances : "connector_id"
    connector_instances ||--o{ connector_credentials : "connector_instance_id"
    connector_instances ||--o{ connector_oauth_tokens : "connector_instance_id"
    connector_instances ||--o{ connector_health_checks : "connector_instance_id"
    connector_instances ||--o{ connector_lifecycle_events : "connector_instance_id"
```
