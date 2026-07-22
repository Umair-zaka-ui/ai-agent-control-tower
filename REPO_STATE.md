# REPO_STATE.md

**Purpose**: a factual, verified state document for `ai-agent-control-tower`. Every claim below was extracted directly from the codebase, the live local Postgres database (after `alembic upgrade head` to `0025_agent_versioning`), the running FastAPI app object, or `git` — not from memory, changelog prose, or inference. Where something could not be mechanically verified, it is marked **UNVERIFIED**.

**Generated**: 2026-07-23, on branch `main` at commit `8092be1ac5b07ce1744ace5b7d0615835ed2c219` (2026-07-22 22:20:54 +0500), with uncommitted working-tree changes for Phase 5.2 Part 1 (see `git status` note in §8).

**Verification methods used**:
- Directory tree: `find` (depth 4, pruned `node_modules`/`__pycache__`/`.git`/`.venv`/`dist`/`.pytest_cache`).
- Database schema: live `sqlalchemy.inspect()` introspection against the actual Postgres instance (`ai_agent_control_tower`, `127.0.0.1:5432`) — this is what the migration chain has *actually produced*, not a re-read of the migration source.
- Migration chain: `alembic history` + `alembic current` + `ls backend/migrations/versions/`.
- API surface: introspection of the live `app.main:app` FastAPI object (`app.routes`), extracting each route's HTTP methods, path, and — where present — the RBAC permission code captured in `require_permission(code)`'s closure.
- Implemented modules: AST-parsed (`ast.parse`) every non-`__init__.py` file under `backend/app/`, extracting the module docstring's first line and every top-level class/public-function name — not a manual read, so nothing was skipped or summarized from memory.
- Tests: full suite actually executed (`pytest -q`, `vitest run`) at generation time, not carried forward from an earlier run.
- Branches: `git branch -a --sort=-committerdate` with `--format` adding ISO committer dates (the bare command has no date column; dates were explicitly requested).

---

## 1. Project Structure

Directory tree, 4 levels deep, from the repository root. `node_modules`, `__pycache__`, `.git`, `.venv`/`venv`, `dist`, and `.pytest_cache` are pruned. Files and directories are shown together, alphabetically within each level.

```
.agents
.gitattributes
.gitignore
CHANGELOG.md
README.md
RECOVERY.md
ROADMAP.md
backend
  .coverage
  .dockerignore
  .env
  .env.example
  .gitignore
  Dockerfile
  README.md
  alembic.ini
  app
    __init__.py
    api
      __init__.py
      deps.py
      router.py
      routes
    authorization
      __init__.py
      abac
      admin
      cache.py
      catalog.py
      decisions.py
      engine.py
      enums.py
      hierarchy
      middleware
      repositories.py
      resources
      routes.py
      schemas.py
      seeding.py
      services.py
    core
      __init__.py
      config.py
      database.py
      enums.py
      middleware.py
      policy_templates.py
      security.py
    governance
      __init__.py
      routes.py
      schemas.py
      services.py
    identity
      __init__.py
      api
      audit
      auth
      credentials
      email
      errors.py
      models
      permissions
      protection
      ratelimit
      recovery
      registration
      repositories
      roles
      schemas
      security
      services
      sessions
      tokens
    main.py
    models
      __init__.py
      abac.py
      access_review.py
      agent.py
      agent_action.py
      agent_registry.py
      api_key.py
      approval.py
      audit_log.py
      governance.py
      mixins.py
      organization.py
      organization_hierarchy.py
      permission.py
      policy.py
      rbac.py
      resource_authorization.py
      runtime.py
      user.py
    runtime
      __init__.py
      registry
      routes.py
      schemas.py
      services.py
      versioning
    schemas
      __init__.py
      agent.py
      agent_action.py
      analytics.py
      api_key.py
      approval.py
      audit.py
      audit_log.py
      auth.py
      dashboard.py
      organization.py
      permission.py
      policy.py
      rbac.py
      user.py
    seed.py
    services
      __init__.py
      agent_action_service.py
      analytics_service.py
      api_key_service.py
      approval_service.py
      audit_service.py
      audit_view.py
      auth_service.py
      decision_engine.py
      notification_service.py
      permission_engine.py
      policy_engine.py
      rbac_service.py
      risk_engine.py
  docker-entrypoint.sh
  migrations
    env.py
    script.py.mako
    versions
      0001_initial_schema.py
      0002_phase2_schema.py
      0003_agent_management.py
      0004_policy_management.py
      0005_approval_workbench.py
      0006_identity_foundation.py
      0007_identity_lifecycle.py
      0008_auth_login_history.py
      0009_session_lifecycle.py
      0010_session_admin_permissions.py
      0011_security_event_read_indexes.py
      0012_registration_invites.py
      0013_credential_management.py
      0014_password_reset_recovery.py
      0015_account_protection.py
      0016_rbac_foundation.py
      0017_permission_engine.py
      0018_org_hierarchy.py
      0019_resource_authorization.py
      0020_abac_engine.py
      0021_access_reviews.py
      0022_governance_iga.py
      0023_agent_runtime.py
      0024_agent_registry.py
      0025_agent_versioning.py
  requirements.txt
  tests
    __init__.py
    authorization
      conftest.py
      test_abac.py
      test_abac_perf.py
      test_abac_unit.py
      test_admin_portal.py
      test_agent_registry.py
      test_agent_registry_perf.py
      test_agent_versioning.py
      test_governance.py
      test_hierarchy.py
      test_hierarchy_unit.py
      test_middleware.py
      test_middleware_perf.py
      test_middleware_unit.py
      test_permission_engine.py
      test_permission_engine_perf.py
      test_permission_engine_unit.py
      test_rbac_endpoints.py
      test_rbac_unit.py
      test_resource_authorization.py
      test_resource_authorization_perf.py
      test_runtime.py
    conftest.py
    identity
      __init__.py
      auth
      credentials
      integration
      protection
      recovery
      registration
      unit
    test_agents_part32.py
    test_analytics_part36.py
    test_approvals_part34.py
    test_audit_part35.py
    test_dashboard_part3.py
    test_decision_engine.py
    test_http_hardening.py
    test_integration.py
    test_policies_part33.py
    test_policy_engine.py
    test_response_envelope.py
    test_risk_engine.py
  var
    dev-outbox.log
backups
  README.md
  ai_agent_control_tower_20260717-021359.dump
  ai_agent_control_tower_20260717-021359.dump.sha256
  backup-manifest.txt
  recovery-tool-test
    .act-backup-target
    20260717T121100Z
      COMPLETE
      SHA256SUMS.txt
      database
      manifest.json
      secrets-inventory.txt
      source
      tools
  seed-credentials.txt
docker-compose.yml
docs
  admin
    abac-builder.md
    access-reviews.md
    audit-center.md
    dashboard.md
    decision-explorer.md
    organization-explorer.md
    policy-simulator.md
    resource-management.md
    roles.md
    security-analytics.md
  api
    http-conventions.md
  architecture
    README.md
    adr
      0001-record-architecture-decisions.md
      0002-postgresql-as-sole-datastore.md
      0003-stateless-jwt-with-rotating-refresh-tokens.md
      0004-single-source-password-policy.md
      0005-additive-identity-layer-alongside-legacy-auth.md
      0006-deterministic-governance-pipeline.md
      0007-stateful-session-validation.md
      README.md
      _template.md
    c4
      01-context.md
      02-container.md
      03-component-backend.md
    data
      erd.md
    deployment
      deployment.md
    security
      threat-model.md
    sequences
      01-human-login.md
      02-token-refresh-and-reuse.md
      03-agent-action-governance.md
  authorization
    abac
      attributes.md
      combining-algorithms.md
      operators.md
      overview.md
      policy-language.md
      policy-lifecycle.md
      policy-simulation.md
      security.md
    caching.md
    context.md
    delegated-administration.md
    delegation.md
    gateway.md
    hierarchy-resolution.md
    middleware.md
    obligations.md
    organization-hierarchy.md
    permission-engine.md
    permission-resolution.md
    permissions.md
    pipeline.md
    rbac.md
    resource-acl.md
    resource-authorization.md
    resource-ownership.md
    resource-sharing.md
    role-hierarchy.md
    roles.md
    scopes.md
    wildcards.md
  deployment.md
  governance
    access-certification.md
    compliance-reporting.md
    governance-dashboard.md
    orphaned-identities.md
    privileged-access.md
    remediation.md
    risk-scoring.md
    sod-analysis.md
    toxic-permissions.md
  identity
    authentication-architecture.md
    credential-management.md
    device-management.md
    email-verification.md
    human-authentication.md
    invitations.md
    migration-plan.md
    password-history.md
    password-policy.md
    password-reset.md
    recovery.md
    registration.md
    security-events.md
    session-lifecycle.md
    token-rotation.md
    token-strategy.md
    trust-model.md
  phase-3-part-1.md
  phase-3-part-4.md
  phase-3-part-5.md
  phase-3-part-6.md
  phase-4-part-1.md
  runtime
    agent-lifecycle.md
    architecture.md
    capabilities-and-tools.md
    deployments.md
    executions.md
    gateways.md
    health-and-observability.md
    operations-and-kill-switch.md
    overview.md
    registry
      agent-definitions.md
      api.md
      domain-model.md
      duplicate-detection.md
      identity-association.md
      import-export.md
      json-schema.md
      lifecycle.md
      migration.md
      overview.md
      ownership.md
      registration.md
      security.md
      validation.md
    runtime-policy-and-approvals.md
    security.md
    versioning.md
    workers-and-queue.md
  security
    account-lockout.md
    account-protection.md
    brute-force-protection.md
    identity-protection-rules.md
    risk-based-authentication.md
  testing
    strategy.md
frontend
  .dockerignore
  .env
  .env.example
  .gitignore
  .oxlintrc.json
  CODING_STANDARDS.md
  Dockerfile
  README.md
  components.json
  index.html
  nginx.conf
  package-lock.json
  package.json
  postcss.config.js
  public
    favicon.svg
    icons.svg
  src
    App.tsx
    authorization
      PermissionContext.tsx
      ProtectedComponent.tsx
      hooks.ts
      index.ts
      middleware
      permissions.ts
      tests
    components
      auth
      common
      dashboard
      layout
      ui
    config
      env.ts
      queryClient.ts
    constants
      app.ts
      index.ts
      navigation.ts
      permissions.ts
      queryKeys.ts
      roles.ts
      routes.ts
    contexts
      AuthContext.tsx
      NotificationsContext.tsx
      ThemeContext.tsx
    hooks
      index.ts
      useAgentActivity.ts
      useApprovals.ts
      useAuth.ts
      useDashboardSummary.ts
      useDebouncedValue.ts
      useNotifications.ts
      useRecentActions.ts
      useRecentAuditLogs.ts
      useRiskTrend.ts
      useSystemHealth.ts
      useTheme.ts
    index.css
    layouts
      AuthLayout.tsx
      DashboardLayout.tsx
      ErrorLayout.tsx
      index.ts
    main.tsx
    modules
      abac
      admin
      agents
      analytics
      approvals
      audit
      authorization
      governance
      hierarchy
      identity
      policies
      protection
      resources
      runtime
      security
    pages
      DashboardPage.tsx
      NotFoundPage.tsx
      ProfilePage.tsx
      SettingsPage.tsx
      UsersPage.tsx
      auth
      index.ts
    routes
      AppRoutes.tsx
      index.ts
    services
      abacService.ts
      adminService.ts
      apiClient.ts
      approvalService.ts
      auditService.ts
      authService.ts
      authorizationService.ts
      credentialService.ts
      dashboardService.test.ts
      dashboardService.ts
      envelope.ts
      governanceService.ts
      hierarchyService.ts
      index.ts
      protectionService.ts
      recoveryService.ts
      registrationService.ts
      resourceAuthzService.ts
      runtimeService.ts
      systemService.ts
      tests
      tokenRefresh.ts
      userService.ts
    styles
    test
      setup.ts
    types
      abac.ts
      admin.ts
      agent.ts
      agentAction.ts
      approval.ts
      audit.ts
      auth.ts
      authorization.ts
      common.ts
      dashboard.ts
      governance.ts
      hierarchy.ts
      index.ts
      policy.ts
      resourceAuthz.ts
      runtime.ts
    utils
      cn.ts
      error.ts
      format.ts
      index.ts
      permissions.ts
      risk.test.ts
      risk.ts
      tokenStorage.ts
      validation.ts
  tailwind.config.js
  tsconfig.app.json
  tsconfig.json
  tsconfig.node.json
  vite.config.ts
  vitest.config.ts
scripts
  backup
    Backup-ControlTower.ps1
    Export-ControlTowerSecrets.ps1
    Initialize-BackupTarget.ps1
    Register-BackupTask.ps1
    Restore-ControlTower.ps1
    Verify-ControlTowerBackup.ps1
```

## 2. Database Schema

**92 tables**, extracted via live `sqlalchemy.inspect()` against the local Postgres database after running every migration through `0025_agent_versioning` (head). This reflects exactly what the migration chain produces — cross-checked spot-wise against the SQLAlchemy model definitions in `backend/app/models/` and `backend/app/identity/models/` during construction of this document. `alembic_version` (Alembic's own bookkeeping table, one column, no app data) is included below for completeness since it is a real table in the database.

For each table: every column with its Postgres type, nullability and default; primary key; foreign keys (with `ondelete` behavior); unique constraints; and indexes (including the unique ones, which Postgres also surfaces as indexes).

#### abac_evaluations
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - identity_id: UUID NULL
  - resource_type: VARCHAR(50) NULL
  - resource_id: UUID NULL
  - action: VARCHAR(100) NOT NULL
  - decision: VARCHAR(30) NOT NULL
  - matched_policy_ids: JSONB NULL
  - obligations: JSONB NULL
  - explanation: JSONB NULL
  - evaluation_time_ms: DOUBLE PRECISION NULL
  - request_id: VARCHAR(100) NULL
  - correlation_id: VARCHAR(100) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=abac_evaluations_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=abac_evaluations_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_abac_evaluations_decision: ['decision']
  - ix_abac_evaluations_org: ['organization_id']

#### abac_policies
Columns:
  - id: UUID NOT NULL
  - policy_family_id: UUID NOT NULL
  - organization_id: UUID NULL
  - name: VARCHAR(255) NOT NULL
  - description: TEXT NULL
  - version: INTEGER NOT NULL DEFAULT 1
  - status: VARCHAR(20) NOT NULL DEFAULT 'DRAFT'::character varying
  - priority: INTEGER NOT NULL DEFAULT 100
  - combining_algorithm: VARCHAR(30) NOT NULL DEFAULT 'DENY_OVERRIDES'::character varying
  - scope_type: VARCHAR(20) NOT NULL DEFAULT 'ORGANIZATION'::character varying
  - scope_id: UUID NULL
  - target: JSONB NULL
  - conditions: JSONB NULL
  - effect: VARCHAR(30) NOT NULL DEFAULT 'DENY'::character varying
  - obligations: JSONB NULL
  - valid_from: TIMESTAMP NULL
  - valid_until: TIMESTAMP NULL
  - created_by: UUID NULL
  - updated_by: UUID NULL
  - published_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=abac_policies_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=abac_policies_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_abac_policies_family: ['policy_family_id']
  - ix_abac_policies_org: ['organization_id']
  - ix_abac_policies_status: ['status']

#### abac_policy_exceptions
Columns:
  - id: UUID NOT NULL
  - policy_id: UUID NOT NULL
  - subject_type: VARCHAR(30) NOT NULL DEFAULT 'USER'::character varying
  - subject_id: UUID NOT NULL
  - resource_type: VARCHAR(50) NULL
  - resource_id: UUID NULL
  - reason: VARCHAR(500) NULL
  - approved_by: UUID NULL
  - valid_from: TIMESTAMP NULL
  - valid_until: TIMESTAMP NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=abac_policy_exceptions_pkey)
Foreign keys:
  - ['policy_id'] -> abac_policies.['id'] (name=abac_policy_exceptions_policy_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_abac_policy_exceptions_policy: ['policy_id']
  - ix_abac_policy_exceptions_subject: ['subject_id']

#### abac_policy_versions
Columns:
  - id: UUID NOT NULL
  - policy_family_id: UUID NOT NULL
  - version: INTEGER NOT NULL
  - snapshot: JSONB NOT NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=abac_policy_versions_pkey)
Indexes:
  - ix_abac_policy_versions_family: ['policy_family_id']

#### access_review_campaigns
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - description: TEXT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'DRAFT'::character varying
  - scope: JSONB NULL
  - reviewer_id: UUID NULL
  - due_at: TIMESTAMP NULL
  - created_by: UUID NULL
  - activated_at: TIMESTAMP NULL
  - completed_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - campaign_type: VARCHAR(30) NOT NULL DEFAULT 'QUARTERLY'::character varying
Primary key: ['id'] (name=access_review_campaigns_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=access_review_campaigns_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_access_review_campaigns_org: ['organization_id']
  - ix_access_review_campaigns_status: ['status']

#### access_review_items
Columns:
  - id: UUID NOT NULL
  - campaign_id: UUID NOT NULL
  - subject_id: UUID NOT NULL
  - subject_label: VARCHAR(255) NOT NULL
  - assignment_id: UUID NULL
  - role_id: UUID NULL
  - role_name: VARCHAR(255) NOT NULL
  - scope_label: VARCHAR(255) NULL
  - decision: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - decided_by: UUID NULL
  - decided_at: TIMESTAMP NULL
  - comment: VARCHAR(500) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=access_review_items_pkey)
Foreign keys:
  - ['campaign_id'] -> access_review_campaigns.['id'] (name=access_review_items_campaign_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_access_review_items_campaign: ['campaign_id']
  - ix_access_review_items_decision: ['decision']
  - ix_access_review_items_subject: ['subject_id']

#### account_locks
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - reason: VARCHAR(40) NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - locked_at: TIMESTAMP NOT NULL DEFAULT now()
  - expires_at: TIMESTAMP NULL
  - unlocked_at: TIMESTAMP NULL
  - unlocked_by: UUID NULL
  - meta: JSONB NOT NULL DEFAULT '{}'::jsonb
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=account_locks_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=account_locks_organization_id_fkey, ondelete=CASCADE)
  - ['unlocked_by'] -> users.['id'] (name=account_locks_unlocked_by_fkey, ondelete=SET NULL)
  - ['user_id'] -> users.['id'] (name=account_locks_user_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_account_locks_organization_id: ['organization_id']
  - ix_account_locks_status: ['status']
  - ix_account_locks_user_id: ['user_id']
  - ix_account_locks_user_status: ['user_id', 'status']

#### agent_actions
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - resource: VARCHAR(100) NOT NULL
  - action: VARCHAR(100) NOT NULL
  - input_payload: JSONB NOT NULL
  - output_payload: JSONB NULL
  - risk_score: INTEGER NOT NULL
  - decision: VARCHAR(16) NOT NULL
  - decision_reason: TEXT NOT NULL
  - status: VARCHAR(8) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_actions_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_actions_agent_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=agent_actions_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_actions_agent_id: ['agent_id']
  - ix_agent_actions_organization_id: ['organization_id']

#### agent_api_keys
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - key_hash: VARCHAR(128) NOT NULL
  - key_prefix: VARCHAR(20) NOT NULL
  - status: VARCHAR(7) NOT NULL
  - last_used_at: TIMESTAMP NULL
  - expires_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_api_keys_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_api_keys_agent_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_agent_api_keys_key_hash: ['key_hash']
Indexes:
  - ix_agent_api_keys_agent_id: ['agent_id']
  - ix_agent_api_keys_key_hash: ['key_hash']
  - uq_agent_api_keys_key_hash UNIQUE: ['key_hash']

#### agent_capabilities
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - agent_version_id: UUID NULL
  - capability_id: UUID NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'REQUESTED'::character varying
  - constraints: JSONB NULL
  - approved_by: UUID NULL
  - approved_at: TIMESTAMP NULL
  - expires_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_capabilities_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_capabilities_agent_id_fkey, ondelete=CASCADE)
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_capabilities_agent_version_id_fkey, ondelete=CASCADE)
  - ['capability_id'] -> capabilities.['id'] (name=agent_capabilities_capability_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_capabilities_agent: ['agent_id']
  - ix_agent_capabilities_capability: ['capability_id']
  - ix_agent_capabilities_status: ['status']

#### agent_definitions
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - description: TEXT NULL
  - framework: VARCHAR(50) NOT NULL DEFAULT 'CUSTOM'::character varying
  - entrypoint_type: VARCHAR(30) NOT NULL DEFAULT 'FUNCTION'::character varying
  - entrypoint: VARCHAR(500) NOT NULL
  - system_instructions: TEXT NULL
  - configuration_schema: JSONB NULL
  - input_schema: JSONB NULL
  - output_schema: JSONB NULL
  - metadata: JSONB NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - framework_version: VARCHAR(50) NULL
  - runtime_language: VARCHAR(50) NULL
  - capability_declarations: JSONB NOT NULL DEFAULT '[]'::jsonb
  - tool_declarations: JSONB NOT NULL DEFAULT '[]'::jsonb
  - model_requirements: JSONB NOT NULL DEFAULT '{}'::jsonb
  - memory_requirements: JSONB NOT NULL DEFAULT '{}'::jsonb
  - data_requirements: JSONB NOT NULL DEFAULT '{}'::jsonb
  - network_requirements: JSONB NOT NULL DEFAULT '{}'::jsonb
  - secret_requirements: JSONB NOT NULL DEFAULT '{}'::jsonb
  - runtime_requirements: JSONB NOT NULL DEFAULT '{}'::jsonb
  - created_by: UUID NULL
  - updated_by: UUID NULL
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_definitions_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_definitions_agent_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_definitions_agent: ['agent_id']

#### agent_deployments
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - environment: VARCHAR(20) NOT NULL DEFAULT 'DEVELOPMENT'::character varying
  - deployment_strategy: VARCHAR(20) NOT NULL DEFAULT 'RECREATE'::character varying
  - status: VARCHAR(20) NOT NULL DEFAULT 'CREATED'::character varying
  - desired_replicas: INTEGER NOT NULL DEFAULT 1
  - active_replicas: INTEGER NOT NULL DEFAULT 0
  - configuration: JSONB NOT NULL DEFAULT '{}'::jsonb
  - secret_references: JSONB NOT NULL DEFAULT '{}'::jsonb
  - runtime_limits: JSONB NOT NULL DEFAULT '{}'::jsonb
  - health_status: VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN'::character varying
  - deployed_by: UUID NULL
  - deployed_at: TIMESTAMP NULL
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - retired_at: TIMESTAMP NULL
Primary key: ['id'] (name=agent_deployments_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_deployments_agent_id_fkey, ondelete=CASCADE)
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_deployments_agent_version_id_fkey, ondelete=RESTRICT)
  - ['organization_id'] -> organizations.['id'] (name=agent_deployments_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_deployments_agent: ['agent_id']
  - ix_agent_deployments_org: ['organization_id']
  - ix_agent_deployments_status: ['status']
  - ix_agent_deployments_version: ['agent_version_id']

#### agent_duplicate_matches
Columns:
  - id: UUID NOT NULL
  - source_agent_id: UUID NOT NULL
  - candidate_agent_id: UUID NOT NULL
  - match_type: VARCHAR(20) NOT NULL
  - confidence_score: NUMERIC(5, 2) NOT NULL
  - matching_fields: JSONB NOT NULL DEFAULT '[]'::jsonb
  - status: VARCHAR(30) NOT NULL DEFAULT 'POSSIBLE_DUPLICATE'::character varying
  - reviewed_by: UUID NULL
  - review_decision: VARCHAR(30) NULL
  - review_reason: TEXT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - reviewed_at: TIMESTAMP NULL
Primary key: ['id'] (name=agent_duplicate_matches_pkey)
Foreign keys:
  - ['candidate_agent_id'] -> agents.['id'] (name=agent_duplicate_matches_candidate_agent_id_fkey, ondelete=CASCADE)
  - ['source_agent_id'] -> agents.['id'] (name=agent_duplicate_matches_source_agent_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_duplicate_matches_candidate: ['candidate_agent_id']
  - ix_agent_duplicate_matches_source: ['source_agent_id']
  - ix_agent_duplicate_matches_status: ['status']

#### agent_executions
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - deployment_id: UUID NULL
  - trigger_type: VARCHAR(20) NOT NULL DEFAULT 'API'::character varying
  - triggered_by_identity_id: UUID NULL
  - parent_execution_id: UUID NULL
  - correlation_id: VARCHAR(100) NULL
  - idempotency_key: VARCHAR(150) NULL
  - input_payload: JSONB NOT NULL DEFAULT '{}'::jsonb
  - output_payload: JSONB NULL
  - status: VARCHAR(24) NOT NULL DEFAULT 'CREATED'::character varying
  - decision: VARCHAR(24) NULL
  - risk_score: INTEGER NULL
  - priority: VARCHAR(20) NOT NULL DEFAULT 'NORMAL'::character varying
  - queued_at: TIMESTAMP NULL
  - started_at: TIMESTAMP NULL
  - completed_at: TIMESTAMP NULL
  - duration_ms: INTEGER NULL
  - attempt_count: INTEGER NOT NULL DEFAULT 0
  - cancel_requested: BOOLEAN NOT NULL DEFAULT false
  - error_code: VARCHAR(50) NULL
  - error_message: TEXT NULL
  - model_usage: JSONB NULL
  - tool_usage: JSONB NULL
  - cost: NUMERIC(12, 6) NOT NULL DEFAULT '0'::numeric
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_executions_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_executions_agent_id_fkey, ondelete=CASCADE)
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_executions_agent_version_id_fkey, ondelete=RESTRICT)
  - ['deployment_id'] -> agent_deployments.['id'] (name=agent_executions_deployment_id_fkey, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=agent_executions_organization_id_fkey, ondelete=CASCADE)
  - ['parent_execution_id'] -> agent_executions.['id'] (name=agent_executions_parent_execution_id_fkey, ondelete=SET NULL)
Indexes:
  - ix_agent_executions_agent: ['agent_id']
  - ix_agent_executions_correlation: ['correlation_id']
  - ix_agent_executions_idempotency: ['idempotency_key']
  - ix_agent_executions_org: ['organization_id']
  - ix_agent_executions_queue: ['status', 'priority', 'queued_at']
  - ix_agent_executions_status: ['status']
  - ix_agent_executions_version: ['agent_version_id']

#### agent_export_jobs
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - export_type: VARCHAR(30) NOT NULL
  - format: VARCHAR(10) NOT NULL
  - filters: JSONB NOT NULL DEFAULT '{}'::jsonb
  - status: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - record_count: INTEGER NOT NULL DEFAULT 0
  - storage_reference: VARCHAR(500) NULL
  - payload: TEXT NULL
  - expires_at: TIMESTAMP NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - completed_at: TIMESTAMP NULL
Primary key: ['id'] (name=agent_export_jobs_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=agent_export_jobs_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_export_jobs_org: ['organization_id']

#### agent_identities
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - client_id: VARCHAR(100) NOT NULL
  - credential_type: VARCHAR(30) NOT NULL
  - status: VARCHAR(30) NOT NULL
  - last_used_at: TIMESTAMP NULL
  - expires_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_identities_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_identities_agent_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_agent_identities_agent: ['agent_id']
  - uq_agent_identities_client_id: ['client_id']
Indexes:
  - ix_agent_identities_agent_id: ['agent_id']
  - ix_agent_identities_client_id: ['client_id']
  - uq_agent_identities_agent UNIQUE: ['agent_id']
  - uq_agent_identities_client_id UNIQUE: ['client_id']

#### agent_import_items
Columns:
  - id: UUID NOT NULL
  - import_job_id: UUID NOT NULL
  - record_identifier: VARCHAR(255) NOT NULL
  - status: VARCHAR(20) NOT NULL
  - agent_id: UUID NULL
  - errors: JSONB NOT NULL DEFAULT '[]'::jsonb
  - warnings: JSONB NOT NULL DEFAULT '[]'::jsonb
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_import_items_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_import_items_agent_id_fkey, ondelete=SET NULL)
  - ['import_job_id'] -> agent_import_jobs.['id'] (name=agent_import_items_import_job_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_import_items_job: ['import_job_id']

#### agent_import_jobs
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - file_name: VARCHAR(255) NOT NULL
  - format: VARCHAR(10) NOT NULL
  - mode: VARCHAR(30) NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - total_records: INTEGER NOT NULL DEFAULT 0
  - successful_records: INTEGER NOT NULL DEFAULT 0
  - failed_records: INTEGER NOT NULL DEFAULT 0
  - warning_records: INTEGER NOT NULL DEFAULT 0
  - created_by: UUID NULL
  - started_at: TIMESTAMP NULL
  - completed_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_import_jobs_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=agent_import_jobs_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_import_jobs_org: ['organization_id']

#### agent_lifecycle_events
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - previous_status: VARCHAR(20) NULL
  - new_status: VARCHAR(20) NOT NULL
  - reason: TEXT NULL
  - requested_by: UUID NOT NULL
  - approved_by: UUID NULL
  - authorization_decision_id: UUID NULL
  - request_id: VARCHAR(100) NOT NULL
  - correlation_id: VARCHAR(100) NOT NULL
  - metadata: JSONB NOT NULL DEFAULT '{}'::jsonb
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_lifecycle_events_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_lifecycle_events_agent_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=agent_lifecycle_events_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_lifecycle_events_agent: ['agent_id']
  - ix_agent_lifecycle_events_org: ['organization_id']

#### agent_migration_records
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - migration_batch_id: VARCHAR(100) NOT NULL
  - legacy_source: VARCHAR(100) NOT NULL
  - legacy_id: VARCHAR(100) NOT NULL
  - migration_status: VARCHAR(30) NOT NULL
  - mapping_warnings: JSONB NOT NULL DEFAULT '[]'::jsonb
  - migrated_by: UUID NULL
  - migrated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_migration_records_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_migration_records_agent_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_migration_records_agent: ['agent_id']
  - ix_agent_migration_records_batch: ['migration_batch_id']

#### agent_ownership_history
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - owner_role: VARCHAR(30) NOT NULL
  - previous_owner_type: VARCHAR(30) NULL
  - previous_owner_id: UUID NULL
  - new_owner_type: VARCHAR(30) NOT NULL
  - new_owner_id: UUID NOT NULL
  - reason: TEXT NOT NULL
  - changed_by: UUID NOT NULL
  - approved_by: UUID NULL
  - changed_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_ownership_history_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_ownership_history_agent_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_ownership_history_agent: ['agent_id']

#### agent_release_artifacts
Columns:
  - id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - artifact_type: VARCHAR(30) NOT NULL
  - reference: VARCHAR(500) NOT NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_release_artifacts_pkey)
Foreign keys:
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_release_artifacts_agent_version_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_release_artifacts_version: ['agent_version_id']

#### agent_release_channels
Columns:
  - id: UUID NOT NULL
  - name: VARCHAR(30) NOT NULL
  - description: TEXT NULL
  - is_default: BOOLEAN NOT NULL DEFAULT false
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_release_channels_pkey)
Unique constraints:
  - agent_release_channels_name_key: ['name']
Indexes:
  - agent_release_channels_name_key UNIQUE: ['name']

#### agent_release_metadata
Columns:
  - id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - release_name: VARCHAR(255) NULL
  - release_description: TEXT NULL
  - business_justification: TEXT NULL
  - change_category: VARCHAR(20) NULL
  - release_window_start: TIMESTAMP NULL
  - release_window_end: TIMESTAMP NULL
  - support_end_date: TIMESTAMP NULL
  - approval_ticket: VARCHAR(100) NULL
  - source_branch: VARCHAR(200) NULL
  - commit_reference: VARCHAR(100) NULL
  - build_reference: VARCHAR(200) NULL
  - risk_score: INTEGER NULL
  - documentation_url: VARCHAR(500) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_release_metadata_pkey)
Foreign keys:
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_release_metadata_agent_version_id_fkey, ondelete=CASCADE)
Unique constraints:
  - agent_release_metadata_agent_version_id_key: ['agent_version_id']
Indexes:
  - agent_release_metadata_agent_version_id_key UNIQUE: ['agent_version_id']
  - ix_agent_release_metadata_version: ['agent_version_id']

#### agent_release_notes
Columns:
  - id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - category: VARCHAR(20) NOT NULL DEFAULT 'CHANGED'::character varying
  - note: TEXT NOT NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_release_notes_pkey)
Foreign keys:
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_release_notes_agent_version_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_release_notes_version: ['agent_version_id']

#### agent_tools
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - agent_version_id: UUID NULL
  - tool_id: UUID NOT NULL
  - allowed_actions: JSONB NOT NULL DEFAULT '[]'::jsonb
  - constraints: JSONB NULL
  - environment: VARCHAR(20) NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'REQUESTED'::character varying
  - approved_by: UUID NULL
  - approved_at: TIMESTAMP NULL
  - expires_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_tools_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_tools_agent_id_fkey, ondelete=CASCADE)
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_tools_agent_version_id_fkey, ondelete=CASCADE)
  - ['tool_id'] -> tools.['id'] (name=agent_tools_tool_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_tools_agent: ['agent_id']
  - ix_agent_tools_status: ['status']
  - ix_agent_tools_tool: ['tool_id']

#### agent_validation_runs
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'RUNNING'::character varying
  - validator_version: VARCHAR(20) NOT NULL
  - summary: JSONB NOT NULL DEFAULT '{}'::jsonb
  - errors: JSONB NOT NULL DEFAULT '[]'::jsonb
  - warnings: JSONB NOT NULL DEFAULT '[]'::jsonb
  - checks: JSONB NOT NULL DEFAULT '[]'::jsonb
  - started_at: TIMESTAMP NOT NULL DEFAULT now()
  - completed_at: TIMESTAMP NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_validation_runs_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_validation_runs_agent_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_validation_runs_agent: ['agent_id']

#### agent_version_snapshots
Columns:
  - id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - snapshot: JSONB NOT NULL DEFAULT '{}'::jsonb
  - checksum: VARCHAR(64) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_version_snapshots_pkey)
Foreign keys:
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_version_snapshots_agent_version_id_fkey, ondelete=CASCADE)
Unique constraints:
  - agent_version_snapshots_agent_version_id_key: ['agent_version_id']
Indexes:
  - agent_version_snapshots_agent_version_id_key UNIQUE: ['agent_version_id']
  - ix_agent_version_snapshots_version: ['agent_version_id']

#### agent_version_status_history
Columns:
  - id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - previous_status: VARCHAR(20) NULL
  - new_status: VARCHAR(20) NOT NULL
  - reason: TEXT NULL
  - changed_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_version_status_history_pkey)
Foreign keys:
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_version_status_history_agent_version_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_version_status_history_version: ['agent_version_id']

#### agent_versions
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - definition_id: UUID NOT NULL
  - version: INTEGER NOT NULL
  - semantic_version: VARCHAR(20) NOT NULL DEFAULT '0.1.0'::character varying
  - status: VARCHAR(20) NOT NULL DEFAULT 'DRAFT'::character varying
  - configuration_snapshot: JSONB NOT NULL DEFAULT '{}'::jsonb
  - prompt_snapshot: JSONB NULL
  - model_configuration: JSONB NOT NULL DEFAULT '{}'::jsonb
  - capabilities_snapshot: JSONB NOT NULL DEFAULT '[]'::jsonb
  - tools_snapshot: JSONB NOT NULL DEFAULT '[]'::jsonb
  - policy_snapshot: JSONB NULL
  - checksum: VARCHAR(64) NOT NULL
  - release_notes: TEXT NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - published_at: TIMESTAMP NULL
  - deprecated_at: TIMESTAMP NULL
  - release_channel_id: UUID NULL
  - compatibility_level: VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN'::character varying
  - signature_id: VARCHAR(255) NULL
  - snapshot_reference: VARCHAR(255) NULL
  - parent_version_id: UUID NULL
  - rollback_target_id: UUID NULL
  - superseded_by_id: UUID NULL
  - release_branch: VARCHAR(100) NOT NULL DEFAULT 'main'::character varying
  - reviewed_by: UUID NULL
  - revoked_reason: TEXT NULL
  - retired_at: TIMESTAMP NULL
Primary key: ['id'] (name=agent_versions_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_versions_agent_id_fkey, ondelete=CASCADE)
  - ['definition_id'] -> agent_definitions.['id'] (name=agent_versions_definition_id_fkey, ondelete=RESTRICT)
  - ['parent_version_id'] -> agent_versions.['id'] (name=fk_agent_versions_parent_version, ondelete=SET NULL)
  - ['release_channel_id'] -> agent_release_channels.['id'] (name=fk_agent_versions_release_channel, ondelete=SET NULL)
  - ['rollback_target_id'] -> agent_versions.['id'] (name=fk_agent_versions_rollback_target, ondelete=SET NULL)
  - ['superseded_by_id'] -> agent_versions.['id'] (name=fk_agent_versions_superseded_by, ondelete=SET NULL)
Unique constraints:
  - uq_agent_versions_agent_version: ['agent_id', 'version']
Indexes:
  - ix_agent_versions_agent: ['agent_id']
  - ix_agent_versions_parent_version: ['parent_version_id']
  - ix_agent_versions_release_channel: ['release_channel_id']
  - ix_agent_versions_status: ['status']
  - uq_agent_versions_agent_version UNIQUE: ['agent_id', 'version']

#### agents
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - description: TEXT NULL
  - agent_type: VARCHAR(100) NOT NULL
  - api_key_hash: VARCHAR(255) NOT NULL
  - status: VARCHAR(9) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - owner: VARCHAR(255) NULL
  - department: VARCHAR(255) NULL
  - version: VARCHAR(50) NOT NULL DEFAULT '1.0.0'::character varying
  - capabilities: JSONB NOT NULL DEFAULT '[]'::jsonb
  - default_risk_score: INTEGER NOT NULL DEFAULT 0
  - max_allowed_risk: INTEGER NOT NULL DEFAULT 100
  - human_approval_required: BOOLEAN NOT NULL DEFAULT false
  - auto_suspend_threshold: INTEGER NULL
  - risk_level: VARCHAR(20) NOT NULL DEFAULT 'LOW'::character varying
  - health: VARCHAR(20) NOT NULL DEFAULT 'HEALTHY'::character varying
  - slug: VARCHAR(150) NULL
  - project_id: UUID NULL
  - owner_type: VARCHAR(30) NULL
  - owner_id: UUID NULL
  - criticality: VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'::character varying
  - data_classification: VARCHAR(30) NOT NULL DEFAULT 'INTERNAL'::character varying
  - default_environment: VARCHAR(20) NOT NULL DEFAULT 'DEVELOPMENT'::character varying
  - lifecycle_status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - archived_at: TIMESTAMP NULL
  - business_unit_id: UUID NULL
  - department_id: UUID NULL
  - team_id: UUID NULL
  - identity_id: UUID NULL
  - display_name: VARCHAR(255) NULL
  - business_purpose: TEXT NULL
  - autonomy_level: VARCHAR(30) NOT NULL DEFAULT 'ASSISTIVE'::character varying
  - technical_owner_id: UUID NULL
  - compliance_owner_id: UUID NULL
  - support_contact: VARCHAR(255) NULL
  - documentation_url: VARCHAR(500) NULL
  - repository_url: VARCHAR(500) NULL
  - tags: JSONB NOT NULL DEFAULT '[]'::jsonb
  - metadata: JSONB NOT NULL DEFAULT '{}'::jsonb
  - registration_source: VARCHAR(30) NOT NULL DEFAULT 'MANUAL'::character varying
  - external_reference: VARCHAR(255) NULL
  - created_by: UUID NULL
  - updated_by: UUID NULL
  - validated_at: TIMESTAMP NULL
  - approved_at: TIMESTAMP NULL
  - activated_at: TIMESTAMP NULL
  - suspended_at: TIMESTAMP NULL
  - retired_at: TIMESTAMP NULL
  - row_version: INTEGER NOT NULL DEFAULT 1
Primary key: ['id'] (name=agents_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=agents_organization_id_fkey, ondelete=CASCADE)
  - ['business_unit_id'] -> business_units.['id'] (name=fk_agents_business_unit, ondelete=SET NULL)
  - ['compliance_owner_id'] -> users.['id'] (name=fk_agents_compliance_owner, ondelete=SET NULL)
  - ['department_id'] -> departments.['id'] (name=fk_agents_department, ondelete=SET NULL)
  - ['identity_id'] -> agent_identities.['id'] (name=fk_agents_identity, ondelete=SET NULL)
  - ['project_id'] -> projects.['id'] (name=fk_agents_project, ondelete=SET NULL)
  - ['team_id'] -> teams.['id'] (name=fk_agents_team, ondelete=SET NULL)
  - ['technical_owner_id'] -> users.['id'] (name=fk_agents_technical_owner, ondelete=SET NULL)
Unique constraints:
  - uq_agents_org_external_ref: ['organization_id', 'external_reference']
  - uq_agents_org_slug: ['organization_id', 'slug']
Indexes:
  - ix_agents_autonomy_level: ['autonomy_level']
  - ix_agents_business_unit: ['business_unit_id']
  - ix_agents_created_at: ['created_at']
  - ix_agents_criticality: ['criticality']
  - ix_agents_data_classification: ['data_classification']
  - ix_agents_department: ['department_id']
  - ix_agents_fulltext: [None]
  - ix_agents_identity: ['identity_id']
  - ix_agents_lifecycle_status: ['lifecycle_status']
  - ix_agents_metadata_gin: ['metadata']
  - ix_agents_organization_id: ['organization_id']
  - ix_agents_owner: ['owner_id']
  - ix_agents_project: ['project_id']
  - ix_agents_risk_level: ['risk_level']
  - ix_agents_slug: ['slug']
  - ix_agents_tags_gin: ['tags']
  - ix_agents_team: ['team_id']
  - ix_agents_updated_at: ['updated_at']
  - uq_agents_org_external_ref UNIQUE: ['organization_id', 'external_reference']
  - uq_agents_org_slug UNIQUE: ['organization_id', 'slug']

#### alembic_version
Columns:
  - version_num: VARCHAR(32) NOT NULL
Primary key: ['version_num'] (name=alembic_version_pkc)

#### approval_comments
Columns:
  - id: UUID NOT NULL
  - approval_id: UUID NOT NULL
  - user_id: UUID NULL
  - comment: TEXT NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=approval_comments_pkey)
Foreign keys:
  - ['approval_id'] -> approvals.['id'] (name=approval_comments_approval_id_fkey, ondelete=CASCADE)
  - ['user_id'] -> users.['id'] (name=approval_comments_user_id_fkey, ondelete=SET NULL)
Indexes:
  - ix_approval_comments_approval_id: ['approval_id']

#### approvals
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - agent_action_id: UUID NOT NULL
  - requested_by_agent_id: UUID NOT NULL
  - reviewed_by_user_id: UUID NULL
  - decision: VARCHAR(9) NOT NULL
  - review_comment: TEXT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - reviewed_at: TIMESTAMP NULL
  - priority: VARCHAR(8) NOT NULL DEFAULT 'MEDIUM'::approval_priority
  - sla_due_at: TIMESTAMP NULL
  - assigned_to_user_id: UUID NULL
  - escalation_target: TEXT NULL
  - escalated_at: TIMESTAMP NULL
Primary key: ['id'] (name=approvals_pkey)
Foreign keys:
  - ['agent_action_id'] -> agent_actions.['id'] (name=approvals_agent_action_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=approvals_organization_id_fkey, ondelete=CASCADE)
  - ['requested_by_agent_id'] -> agents.['id'] (name=approvals_requested_by_agent_id_fkey, ondelete=CASCADE)
  - ['reviewed_by_user_id'] -> users.['id'] (name=approvals_reviewed_by_user_id_fkey, ondelete=SET NULL)
  - ['assigned_to_user_id'] -> users.['id'] (name=fk_approvals_assigned_to_users, ondelete=SET NULL)
Unique constraints:
  - uq_approvals_agent_action_id: ['agent_action_id']
Indexes:
  - ix_approvals_agent_action_id: ['agent_action_id']
  - ix_approvals_assigned_to_user_id: ['assigned_to_user_id']
  - ix_approvals_organization_id: ['organization_id']
  - ix_approvals_priority: ['priority']
  - uq_approvals_agent_action_id UNIQUE: ['agent_action_id']

#### attribute_definitions
Columns:
  - id: UUID NOT NULL
  - name: VARCHAR(120) NOT NULL
  - category: VARCHAR(20) NOT NULL
  - data_type: VARCHAR(20) NOT NULL
  - description: TEXT NULL
  - sensitivity: VARCHAR(20) NOT NULL DEFAULT 'INTERNAL'::character varying
  - supported_operators: JSONB NULL
  - source: VARCHAR(50) NULL
  - is_system: BOOLEAN NOT NULL DEFAULT false
  - enabled: BOOLEAN NOT NULL DEFAULT true
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=attribute_definitions_pkey)
Unique constraints:
  - uq_attribute_definitions_name: ['name']
Indexes:
  - uq_attribute_definitions_name UNIQUE: ['name']

#### audit_logs
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - actor_type: VARCHAR(6) NOT NULL
  - actor_id: UUID NULL
  - event_type: VARCHAR(100) NOT NULL
  - entity_type: VARCHAR(100) NOT NULL
  - entity_id: UUID NULL
  - metadata: JSONB NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - ip_address: VARCHAR(64) NULL
  - user_agent: VARCHAR(512) NULL
  - request_id: VARCHAR(64) NULL
  - trace_id: VARCHAR(64) NULL
  - before_state: JSONB NULL
  - after_state: JSONB NULL
Primary key: ['id'] (name=audit_logs_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=audit_logs_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_audit_logs_entity_id: ['entity_id']
  - ix_audit_logs_entity_type: ['entity_type']
  - ix_audit_logs_event_type: ['event_type']
  - ix_audit_logs_organization_id: ['organization_id']
  - ix_audit_logs_request_id: ['request_id']
  - ix_audit_logs_trace_id: ['trace_id']

#### auth_devices
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - fingerprint: VARCHAR(128) NOT NULL
  - device_name: VARCHAR(255) NULL
  - device_type: VARCHAR(32) NULL
  - browser: VARCHAR(64) NULL
  - browser_version: VARCHAR(32) NULL
  - operating_system: VARCHAR(64) NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN'::character varying
  - last_ip: VARCHAR(64) NULL
  - last_seen_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL
Primary key: ['id'] (name=auth_devices_pkey)
Foreign keys:
  - ['user_id'] -> users.['id'] (name=auth_devices_user_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_auth_devices_user_fingerprint: ['user_id', 'fingerprint']
Indexes:
  - ix_auth_devices_fingerprint: ['fingerprint']
  - ix_auth_devices_status: ['status']
  - ix_auth_devices_user_id: ['user_id']
  - uq_auth_devices_user_fingerprint UNIQUE: ['user_id', 'fingerprint']

#### auth_sessions
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - ip_address: VARCHAR(64) NULL
  - user_agent: VARCHAR(512) NULL
  - created_at: TIMESTAMP NOT NULL
  - last_seen_at: TIMESTAMP NULL
  - revoked_at: TIMESTAMP NULL
  - organization_id: UUID NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - device_id: UUID NULL
  - device_name: VARCHAR(255) NULL
  - device_type: VARCHAR(32) NULL
  - browser: VARCHAR(64) NULL
  - browser_version: VARCHAR(32) NULL
  - operating_system: VARCHAR(64) NULL
  - country: VARCHAR(64) NULL
  - city: VARCHAR(128) NULL
  - timezone: VARCHAR(64) NULL
  - login_method: VARCHAR(32) NULL
  - last_activity_at: TIMESTAMP NULL
  - idle_expires_at: TIMESTAMP NOT NULL
  - absolute_expires_at: TIMESTAMP NOT NULL
  - revoked_reason: VARCHAR(32) NULL
  - security_score: INTEGER NOT NULL DEFAULT 100
  - is_trusted: BOOLEAN NOT NULL DEFAULT false
  - refresh_token_family_id: UUID NOT NULL
Primary key: ['id'] (name=sessions_pkey)
Foreign keys:
  - ['device_id'] -> auth_devices.['id'] (name=fk_auth_sessions_device_id, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=fk_auth_sessions_organization_id, ondelete=CASCADE)
  - ['user_id'] -> users.['id'] (name=sessions_user_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_auth_sessions_device_id: ['device_id']
  - ix_auth_sessions_family: ['refresh_token_family_id']
  - ix_auth_sessions_organization_id: ['organization_id']
  - ix_auth_sessions_status: ['status']
  - ix_auth_sessions_user_status: ['user_id', 'status']
  - ix_sessions_user_id: ['user_id']

#### authorization_audit
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - actor_id: UUID NULL
  - identity_id: UUID NULL
  - event_type: VARCHAR(50) NOT NULL
  - permission: VARCHAR(100) NULL
  - resource_type: VARCHAR(50) NULL
  - resource_id: UUID NULL
  - decision: VARCHAR(10) NULL
  - reason: TEXT NULL
  - meta: JSONB NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=authorization_audit_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=authorization_audit_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_authorization_audit_actor: ['actor_id']
  - ix_authorization_audit_created_at: ['created_at']
  - ix_authorization_audit_event_type: ['event_type']
  - ix_authorization_audit_identity: ['identity_id']
  - ix_authorization_audit_org: ['organization_id']

#### authorization_decisions
Columns:
  - id: UUID NOT NULL
  - identity_id: UUID NULL
  - organization_id: UUID NULL
  - permission: VARCHAR(100) NOT NULL
  - resource_type: VARCHAR(50) NULL
  - resource_id: UUID NULL
  - allowed: BOOLEAN NOT NULL
  - reason: TEXT NULL
  - scope: VARCHAR(20) NULL
  - source_role: VARCHAR(100) NULL
  - evaluation_time_ms: DOUBLE PRECISION NULL
  - request_id: VARCHAR(128) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=authorization_decisions_pkey)
Indexes:
  - ix_authz_decisions_allowed: ['allowed']
  - ix_authz_decisions_created_at: ['created_at']
  - ix_authz_decisions_identity: ['identity_id']
  - ix_authz_decisions_org: ['organization_id']

#### blocked_ips
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - ip_address: VARCHAR(64) NOT NULL
  - reason: VARCHAR(255) NULL
  - expires_at: TIMESTAMP NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=blocked_ips_pkey)
Foreign keys:
  - ['created_by'] -> users.['id'] (name=blocked_ips_created_by_fkey, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=blocked_ips_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_blocked_ips_ip_address: ['ip_address']
  - ix_blocked_ips_org_ip: ['organization_id', 'ip_address']
  - ix_blocked_ips_organization_id: ['organization_id']

#### business_units
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - manager_id: UUID NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=business_units_pkey)
Foreign keys:
  - ['manager_id'] -> users.['id'] (name=business_units_manager_id_fkey, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=business_units_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_business_unit_org_name: ['organization_id', 'name']
Indexes:
  - ix_business_units_org: ['organization_id']
  - uq_business_unit_org_name UNIQUE: ['organization_id', 'name']

#### capabilities
Columns:
  - id: UUID NOT NULL
  - name: VARCHAR(100) NOT NULL
  - display_name: VARCHAR(150) NOT NULL
  - description: TEXT NULL
  - category: VARCHAR(50) NULL
  - risk_level: VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'::character varying
  - requires_approval: BOOLEAN NOT NULL DEFAULT false
  - required_permissions: JSONB NOT NULL DEFAULT '[]'::jsonb
  - prohibited_environments: JSONB NOT NULL DEFAULT '[]'::jsonb
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=capabilities_pkey)
Unique constraints:
  - uq_capabilities_name: ['name']
Indexes:
  - uq_capabilities_name UNIQUE: ['name']

#### compliance_reports
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - framework: VARCHAR(30) NOT NULL
  - report_type: VARCHAR(50) NOT NULL
  - scope: JSONB NULL
  - payload: JSONB NOT NULL
  - version: VARCHAR(20) NOT NULL DEFAULT 'v1'::character varying
  - generated_by: UUID NULL
  - generated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=compliance_reports_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=compliance_reports_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_compliance_reports_framework: ['framework']
  - ix_compliance_reports_org: ['organization_id']

#### delegations
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - delegator_id: UUID NULL
  - delegatee_id: UUID NOT NULL
  - scope_type: VARCHAR(20) NOT NULL
  - scope_id: UUID NULL
  - permission: VARCHAR(100) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - revoked_at: TIMESTAMP NULL
Primary key: ['id'] (name=delegations_pkey)
Foreign keys:
  - ['delegatee_id'] -> users.['id'] (name=delegations_delegatee_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=delegations_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_delegations_delegatee: ['delegatee_id']
  - ix_delegations_org: ['organization_id']

#### departments
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - manager_id: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - business_unit_id: UUID NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
Primary key: ['id'] (name=departments_pkey)
Foreign keys:
  - ['manager_id'] -> users.['id'] (name=departments_manager_id_fkey, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=departments_organization_id_fkey, ondelete=CASCADE)
  - ['business_unit_id'] -> business_units.['id'] (name=fk_departments_business_unit_id, ondelete=SET NULL)
Indexes:
  - ix_departments_business_unit: ['business_unit_id']
  - ix_departments_organization_id: ['organization_id']

#### deployment_health
Columns:
  - id: UUID NOT NULL
  - deployment_id: UUID NOT NULL
  - worker_id: VARCHAR(100) NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN'::character varying
  - metrics: JSONB NULL
  - checked_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=deployment_health_pkey)
Foreign keys:
  - ['deployment_id'] -> agent_deployments.['id'] (name=deployment_health_deployment_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_deployment_health_deployment: ['deployment_id']

#### email_verifications
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - verification_token_hash: VARCHAR(255) NOT NULL
  - expires_at: TIMESTAMP NOT NULL
  - verified_at: TIMESTAMP NULL
  - superseded_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - purpose: VARCHAR(20) NOT NULL DEFAULT 'ACTIVATION'::character varying
  - new_email: VARCHAR(320) NULL
Primary key: ['id'] (name=email_verifications_pkey)
Foreign keys:
  - ['user_id'] -> users.['id'] (name=email_verifications_user_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_email_verifications_token_hash: ['verification_token_hash']
Indexes:
  - ix_email_verifications_token_hash: ['verification_token_hash']
  - ix_email_verifications_user_id: ['user_id']
  - uq_email_verifications_token_hash UNIQUE: ['verification_token_hash']

#### execution_attempts
Columns:
  - id: UUID NOT NULL
  - execution_id: UUID NOT NULL
  - attempt_number: INTEGER NOT NULL
  - worker_id: VARCHAR(100) NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'RUNNING'::character varying
  - started_at: TIMESTAMP NULL
  - completed_at: TIMESTAMP NULL
  - duration_ms: INTEGER NULL
  - error_code: VARCHAR(50) NULL
  - error_message: TEXT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=execution_attempts_pkey)
Foreign keys:
  - ['execution_id'] -> agent_executions.['id'] (name=execution_attempts_execution_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_execution_attempts_execution: ['execution_id']

#### execution_locks
Columns:
  - id: UUID NOT NULL
  - execution_id: UUID NOT NULL
  - worker_id: VARCHAR(100) NOT NULL
  - acquired_at: TIMESTAMP NOT NULL DEFAULT now()
  - expires_at: TIMESTAMP NOT NULL
  - heartbeat_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=execution_locks_pkey)
Foreign keys:
  - ['execution_id'] -> agent_executions.['id'] (name=execution_locks_execution_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_execution_locks_execution: ['execution_id']
Indexes:
  - uq_execution_locks_execution UNIQUE: ['execution_id']

#### external_clients
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - client_name: VARCHAR(255) NOT NULL
  - client_id: VARCHAR(100) NOT NULL
  - redirect_uri: VARCHAR(2048) NULL
  - secret_hash: VARCHAR(255) NOT NULL
  - allowed_scopes: JSONB NOT NULL
  - status: VARCHAR(30) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=external_clients_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=external_clients_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_external_clients_client_id: ['client_id']
Indexes:
  - ix_external_clients_client_id: ['client_id']
  - ix_external_clients_organization_id: ['organization_id']
  - uq_external_clients_client_id UNIQUE: ['client_id']

#### governance_findings
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - finding_type: VARCHAR(30) NOT NULL
  - severity: VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'::character varying
  - identity_id: UUID NULL
  - identity_label: VARCHAR(255) NULL
  - resource_id: UUID NULL
  - rule_id: UUID NULL
  - details: JSONB NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'OPEN'::character varying
  - detected_at: TIMESTAMP NOT NULL DEFAULT now()
  - resolved_at: TIMESTAMP NULL
  - resolved_by: UUID NULL
Primary key: ['id'] (name=governance_findings_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=governance_findings_organization_id_fkey, ondelete=CASCADE)
  - ['rule_id'] -> sod_rules.['id'] (name=governance_findings_rule_id_fkey, ondelete=SET NULL)
Indexes:
  - ix_governance_findings_identity: ['identity_id']
  - ix_governance_findings_org: ['organization_id']
  - ix_governance_findings_status: ['status']
  - ix_governance_findings_type: ['finding_type']

#### governance_risk_scores
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - identity_id: UUID NOT NULL
  - identity_label: VARCHAR(255) NOT NULL
  - score: INTEGER NOT NULL DEFAULT 0
  - band: VARCHAR(20) NOT NULL DEFAULT 'LOW'::character varying
  - factors: JSONB NULL
  - computed_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=governance_risk_scores_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=governance_risk_scores_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_governance_risk_identity: ['organization_id', 'identity_id']
Indexes:
  - ix_governance_risk_scores_band: ['band']
  - ix_governance_risk_scores_org: ['organization_id']
  - uq_governance_risk_identity UNIQUE: ['organization_id', 'identity_id']

#### idempotency_records
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - identity_id: UUID NULL
  - agent_id: UUID NOT NULL
  - idempotency_key: VARCHAR(150) NOT NULL
  - request_hash: VARCHAR(64) NOT NULL
  - execution_id: UUID NOT NULL
  - expires_at: TIMESTAMP NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=idempotency_records_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=idempotency_records_agent_id_fkey, ondelete=CASCADE)
  - ['execution_id'] -> agent_executions.['id'] (name=idempotency_records_execution_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=idempotency_records_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_idempotency_key: ['organization_id', 'agent_id', 'idempotency_key']
Indexes:
  - uq_idempotency_key UNIQUE: ['organization_id', 'agent_id', 'idempotency_key']

#### identity_protection_rules
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(150) NOT NULL
  - description: VARCHAR(500) NULL
  - conditions: JSONB NOT NULL DEFAULT '[]'::jsonb
  - decision: VARCHAR(30) NOT NULL
  - enabled: BOOLEAN NOT NULL DEFAULT true
  - priority: INTEGER NOT NULL DEFAULT 100
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=identity_protection_rules_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=identity_protection_rules_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_identity_protection_rules_organization_id: ['organization_id']

#### identity_risk_events
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - user_id: UUID NULL
  - event_type: VARCHAR(64) NOT NULL
  - risk_score: INTEGER NOT NULL DEFAULT 0
  - risk_level: VARCHAR(20) NOT NULL
  - signals: JSONB NOT NULL DEFAULT '{}'::jsonb
  - decision: VARCHAR(30) NOT NULL
  - ip_address: VARCHAR(64) NULL
  - user_agent: VARCHAR(512) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=identity_risk_events_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=identity_risk_events_organization_id_fkey, ondelete=CASCADE)
  - ['user_id'] -> users.['id'] (name=identity_risk_events_user_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_identity_risk_events_created_at: ['created_at']
  - ix_identity_risk_events_event_type: ['event_type']
  - ix_identity_risk_events_org_created: ['organization_id', 'created_at']
  - ix_identity_risk_events_organization_id: ['organization_id']
  - ix_identity_risk_events_risk_level: ['risk_level']
  - ix_identity_risk_events_user_id: ['user_id']

#### invitations
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - email: VARCHAR(320) NOT NULL
  - role_id: UUID NULL
  - department_id: UUID NULL
  - team_id: UUID NULL
  - invited_by: UUID NULL
  - token_hash: VARCHAR(255) NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - expires_at: TIMESTAMP NOT NULL
  - accepted_at: TIMESTAMP NULL
  - cancelled_at: TIMESTAMP NULL
  - resent_count: INTEGER NOT NULL DEFAULT 0
  - last_sent_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=invitations_pkey)
Foreign keys:
  - ['department_id'] -> departments.['id'] (name=invitations_department_id_fkey, ondelete=SET NULL)
  - ['invited_by'] -> users.['id'] (name=invitations_invited_by_fkey, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=invitations_organization_id_fkey, ondelete=CASCADE)
  - ['role_id'] -> roles.['id'] (name=invitations_role_id_fkey, ondelete=SET NULL)
  - ['team_id'] -> teams.['id'] (name=invitations_team_id_fkey, ondelete=SET NULL)
Unique constraints:
  - uq_invitations_token_hash: ['token_hash']
Indexes:
  - ix_invitations_email: ['email']
  - ix_invitations_org_status: ['organization_id', 'status']
  - ix_invitations_organization_id: ['organization_id']
  - ix_invitations_status: ['status']
  - ix_invitations_token_hash: ['token_hash']
  - uq_invitations_pending_email UNIQUE: ['organization_id', None]
  - uq_invitations_token_hash UNIQUE: ['token_hash']

#### login_history
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NULL
  - email: VARCHAR(320) NOT NULL
  - success: BOOLEAN NOT NULL
  - failure_reason: VARCHAR(64) NULL
  - ip_address: VARCHAR(64) NULL
  - user_agent: VARCHAR(512) NULL
  - country: VARCHAR(64) NULL
  - city: VARCHAR(128) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - organization_id: UUID NULL
  - device_fingerprint: VARCHAR(128) NULL
  - risk_score: INTEGER NULL
  - decision: VARCHAR(30) NULL
Primary key: ['id'] (name=login_history_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=fk_login_history_organization_id, ondelete=CASCADE)
  - ['user_id'] -> users.['id'] (name=login_history_user_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_login_history_created_at: ['created_at']
  - ix_login_history_email: ['email']
  - ix_login_history_organization_id: ['organization_id']
  - ix_login_history_success: ['success']
  - ix_login_history_user_id: ['user_id']

#### organizations
Columns:
  - id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - status: VARCHAR(30) NOT NULL DEFAULT 'ACTIVE'::character varying
  - registration_mode: VARCHAR(20) NOT NULL DEFAULT 'INVITE_ONLY'::character varying
  - slug: VARCHAR(120) NULL
  - owner_id: UUID NULL
Primary key: ['id'] (name=organizations_pkey)
Foreign keys:
  - ['owner_id'] -> users.['id'] (name=fk_organizations_owner_id, ondelete=SET NULL)
Indexes:
  - ix_organizations_slug UNIQUE: ['slug']

#### ownership_history
Columns:
  - id: UUID NOT NULL
  - resource_id: UUID NOT NULL
  - previous_owner: UUID NULL
  - previous_owner_type: VARCHAR(20) NULL
  - new_owner: UUID NOT NULL
  - new_owner_type: VARCHAR(20) NOT NULL DEFAULT 'USER'::character varying
  - changed_by: UUID NULL
  - reason: VARCHAR(500) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=ownership_history_pkey)
Foreign keys:
  - ['resource_id'] -> resources.['id'] (name=ownership_history_resource_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_ownership_history_resource: ['resource_id']

#### password_history
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - password_hash: VARCHAR(255) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=password_history_pkey)
Foreign keys:
  - ['user_id'] -> users.['id'] (name=password_history_user_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_password_history_user_created: ['user_id', 'created_at']

#### password_reset_requests
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - token_hash: VARCHAR(255) NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - expires_at: TIMESTAMP NOT NULL
  - used_at: TIMESTAMP NULL
  - created_ip: VARCHAR(64) NULL
  - created_user_agent: VARCHAR(512) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=password_reset_requests_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=password_reset_requests_organization_id_fkey, ondelete=CASCADE)
  - ['user_id'] -> users.['id'] (name=password_reset_requests_user_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_password_reset_requests_token_hash: ['token_hash']
Indexes:
  - ix_password_reset_requests_organization_id: ['organization_id']
  - ix_password_reset_requests_status: ['status']
  - ix_password_reset_requests_token_hash: ['token_hash']
  - ix_password_reset_requests_user_id: ['user_id']
  - ix_password_reset_requests_user_status: ['user_id', 'status']
  - uq_password_reset_requests_token_hash UNIQUE: ['token_hash']

#### permission_cache
Columns:
  - id: UUID NOT NULL
  - identity_id: UUID NOT NULL
  - organization_id: UUID NULL
  - grants_json: JSONB NOT NULL
  - version: INTEGER NOT NULL DEFAULT 0
  - expires_at: TIMESTAMP NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=permission_cache_pkey)
Unique constraints:
  - uq_permission_cache_identity: ['identity_id']
Indexes:
  - ix_permission_cache_org: ['organization_id']
  - uq_permission_cache_identity UNIQUE: ['identity_id']

#### permission_groups
Columns:
  - id: UUID NOT NULL
  - name: VARCHAR(50) NOT NULL
  - display_name: VARCHAR(100) NOT NULL
  - description: TEXT NULL
  - sort_order: INTEGER NOT NULL DEFAULT 0
Primary key: ['id'] (name=permission_groups_pkey)
Unique constraints:
  - uq_permission_group_name: ['name']
Indexes:
  - ix_permission_groups_name: ['name']
  - uq_permission_group_name UNIQUE: ['name']

#### permission_versions
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - version: INTEGER NOT NULL DEFAULT 1
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=permission_versions_pkey)
Unique constraints:
  - uq_permission_version_org: ['organization_id']
Indexes:
  - uq_permission_version_org UNIQUE: ['organization_id']

#### permissions
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - resource: VARCHAR(100) NOT NULL
  - action: VARCHAR(100) NOT NULL
  - allowed: BOOLEAN NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=permissions_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=permissions_agent_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=permissions_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_permission_agent_resource_action: ['agent_id', 'resource', 'action']
Indexes:
  - ix_permissions_agent_id: ['agent_id']
  - ix_permissions_organization_id: ['organization_id']
  - uq_permission_agent_resource_action UNIQUE: ['agent_id', 'resource', 'action']

#### policies
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - description: TEXT NULL
  - resource: VARCHAR(100) NOT NULL
  - action: VARCHAR(100) NOT NULL
  - conditions: JSONB NOT NULL
  - decision: VARCHAR(30) NOT NULL
  - priority: INTEGER NOT NULL DEFAULT 0
  - enabled: BOOLEAN NOT NULL DEFAULT true
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - severity: VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'::character varying
  - status: VARCHAR(20) NOT NULL DEFAULT 'ENABLED'::character varying
  - created_by: UUID NULL
  - trigger_count: INTEGER NOT NULL DEFAULT 0
  - last_triggered_at: TIMESTAMP NULL
Primary key: ['id'] (name=policies_pkey)
Foreign keys:
  - ['created_by'] -> users.['id'] (name=fk_policies_created_by_users, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=policies_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_policies_action: ['action']
  - ix_policies_enabled: ['enabled']
  - ix_policies_organization_id: ['organization_id']
  - ix_policies_resource: ['resource']

#### privileged_account_reviews
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - identity_id: UUID NOT NULL
  - identity_label: VARCHAR(255) NOT NULL
  - role_name: VARCHAR(255) NOT NULL
  - risk_score: INTEGER NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - reviewed_by: UUID NULL
  - reviewed_at: TIMESTAMP NULL
  - due_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=privileged_account_reviews_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=privileged_account_reviews_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_privileged_account_reviews_identity: ['identity_id']
  - ix_privileged_account_reviews_org: ['organization_id']
  - ix_privileged_account_reviews_status: ['status']

#### projects
Columns:
  - id: UUID NOT NULL
  - team_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - owner_id: UUID NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=projects_pkey)
Foreign keys:
  - ['owner_id'] -> users.['id'] (name=projects_owner_id_fkey, ondelete=SET NULL)
  - ['team_id'] -> teams.['id'] (name=projects_team_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_project_team_name: ['team_id', 'name']
Indexes:
  - ix_projects_team: ['team_id']
  - uq_project_team_name UNIQUE: ['team_id', 'name']

#### rate_limit_hits
Columns:
  - id: UUID NOT NULL
  - bucket: VARCHAR(255) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=rate_limit_hits_pkey)
Indexes:
  - ix_rate_limit_hits_bucket_created: ['bucket', 'created_at']

#### rbac_permissions
Columns:
  - id: UUID NOT NULL
  - code: VARCHAR(100) NOT NULL
  - description: TEXT NULL
  - display_name: VARCHAR(150) NULL
  - group_id: UUID NULL
  - resource_type: VARCHAR(50) NULL
  - action: VARCHAR(50) NULL
  - is_system: BOOLEAN NOT NULL DEFAULT true
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=rbac_permissions_pkey)
Foreign keys:
  - ['group_id'] -> permission_groups.['id'] (name=fk_rbac_permissions_group_id, ondelete=SET NULL)
Unique constraints:
  - uq_rbac_permissions_code: ['code']
Indexes:
  - ix_rbac_permissions_code: ['code']
  - ix_rbac_permissions_group_id: ['group_id']
  - ix_rbac_permissions_resource_type: ['resource_type']
  - uq_rbac_permissions_code UNIQUE: ['code']

#### refresh_tokens
Columns:
  - id: UUID NOT NULL
  - session_id: UUID NOT NULL
  - token_hash: VARCHAR(255) NOT NULL
  - created_at: TIMESTAMP NOT NULL
  - expires_at: TIMESTAMP NOT NULL
  - revoked_at: TIMESTAMP NULL
  - rotated_to_id: UUID NULL
  - family_id: UUID NOT NULL
  - reuse_detected_at: TIMESTAMP NULL
Primary key: ['id'] (name=refresh_tokens_pkey)
Foreign keys:
  - ['session_id'] -> auth_sessions.['id'] (name=refresh_tokens_session_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_refresh_tokens_token_hash: ['token_hash']
Indexes:
  - ix_refresh_tokens_family_id: ['family_id']
  - ix_refresh_tokens_session_id: ['session_id']
  - ix_refresh_tokens_token_hash: ['token_hash']
  - uq_refresh_tokens_token_hash UNIQUE: ['token_hash']

#### remediation_actions
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - finding_id: UUID NOT NULL
  - action_type: VARCHAR(30) NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - mode: VARCHAR(20) NOT NULL DEFAULT 'MANUAL'::character varying
  - payload: JSONB NULL
  - created_by: UUID NULL
  - approved_by: UUID NULL
  - executed_by: UUID NULL
  - executed_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=remediation_actions_pkey)
Foreign keys:
  - ['finding_id'] -> governance_findings.['id'] (name=remediation_actions_finding_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=remediation_actions_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_remediation_actions_finding: ['finding_id']
  - ix_remediation_actions_org: ['organization_id']
  - ix_remediation_actions_status: ['status']

#### resource_acl
Columns:
  - id: UUID NOT NULL
  - resource_id: UUID NOT NULL
  - principal_type: VARCHAR(20) NOT NULL
  - principal_id: UUID NOT NULL
  - permission: VARCHAR(100) NOT NULL
  - effect: VARCHAR(5) NOT NULL DEFAULT 'ALLOW'::character varying
  - expires_at: TIMESTAMP NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=resource_acl_pkey)
Foreign keys:
  - ['resource_id'] -> resources.['id'] (name=resource_acl_resource_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_resource_acl_principal: ['principal_id']
  - ix_resource_acl_resource: ['resource_id']

#### resource_delegations
Columns:
  - id: UUID NOT NULL
  - resource_id: UUID NOT NULL
  - delegate_id: UUID NOT NULL
  - permissions: JSONB NOT NULL DEFAULT '[]'::jsonb
  - expires_at: TIMESTAMP NULL
  - status: VARCHAR(10) NOT NULL DEFAULT 'ACTIVE'::character varying
  - reason: VARCHAR(500) NULL
  - approved_by: UUID NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=resource_delegations_pkey)
Foreign keys:
  - ['delegate_id'] -> users.['id'] (name=resource_delegations_delegate_id_fkey, ondelete=CASCADE)
  - ['resource_id'] -> resources.['id'] (name=resource_delegations_resource_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_resource_delegations_delegate: ['delegate_id']
  - ix_resource_delegations_resource: ['resource_id']

#### resource_ownership
Columns:
  - id: UUID NOT NULL
  - resource_type: VARCHAR(50) NOT NULL
  - resource_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - business_unit_id: UUID NULL
  - department_id: UUID NULL
  - team_id: UUID NULL
  - project_id: UUID NULL
  - owner_id: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=resource_ownership_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=resource_ownership_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_resource_ownership: ['resource_type', 'resource_id']
Indexes:
  - ix_resource_ownership_lookup: ['resource_type', 'resource_id']
  - ix_resource_ownership_org: ['organization_id']
  - uq_resource_ownership UNIQUE: ['resource_type', 'resource_id']

#### resource_shares
Columns:
  - id: UUID NOT NULL
  - resource_id: UUID NOT NULL
  - shared_with_type: VARCHAR(20) NOT NULL
  - shared_with_id: UUID NOT NULL
  - access_level: VARCHAR(10) NOT NULL DEFAULT 'READ'::character varying
  - expires_at: TIMESTAMP NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=resource_shares_pkey)
Foreign keys:
  - ['resource_id'] -> resources.['id'] (name=resource_shares_resource_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_resource_shares_resource: ['resource_id']
  - ix_resource_shares_with: ['shared_with_id']

#### resources
Columns:
  - id: UUID NOT NULL
  - resource_type: VARCHAR(50) NOT NULL
  - resource_id: UUID NOT NULL
  - name: VARCHAR(255) NULL
  - organization_id: UUID NOT NULL
  - project_id: UUID NULL
  - owner_id: UUID NOT NULL
  - owner_type: VARCHAR(20) NOT NULL DEFAULT 'USER'::character varying
  - created_by: UUID NULL
  - visibility: VARCHAR(20) NOT NULL DEFAULT 'PRIVATE'::character varying
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - policy: JSONB NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=resources_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=resources_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_resources_type_id: ['resource_type', 'resource_id']
Indexes:
  - ix_resources_lookup: ['resource_type', 'resource_id']
  - ix_resources_org: ['organization_id']
  - ix_resources_owner: ['owner_id']
  - uq_resources_type_id UNIQUE: ['resource_type', 'resource_id']

#### role_hierarchy
Columns:
  - id: UUID NOT NULL
  - parent_role_id: UUID NOT NULL
  - child_role_id: UUID NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=role_hierarchy_pkey)
Foreign keys:
  - ['child_role_id'] -> roles.['id'] (name=role_hierarchy_child_role_id_fkey, ondelete=CASCADE)
  - ['parent_role_id'] -> roles.['id'] (name=role_hierarchy_parent_role_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_role_hierarchy_edge: ['parent_role_id', 'child_role_id']
Indexes:
  - ix_role_hierarchy_child: ['child_role_id']
  - ix_role_hierarchy_parent: ['parent_role_id']
  - uq_role_hierarchy_edge UNIQUE: ['parent_role_id', 'child_role_id']

#### role_permissions
Columns:
  - id: UUID NOT NULL
  - role_id: UUID NOT NULL
  - permission_id: UUID NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - effect: VARCHAR(10) NOT NULL DEFAULT 'ALLOW'::character varying
Primary key: ['id'] (name=role_permissions_pkey)
Foreign keys:
  - ['permission_id'] -> rbac_permissions.['id'] (name=role_permissions_permission_id_fkey, ondelete=CASCADE)
  - ['role_id'] -> roles.['id'] (name=role_permissions_role_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_role_permission: ['role_id', 'permission_id']
Indexes:
  - ix_role_permissions_permission_id: ['permission_id']
  - ix_role_permissions_role_id: ['role_id']
  - uq_role_permission UNIQUE: ['role_id', 'permission_id']

#### roles
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - name: VARCHAR(100) NOT NULL
  - description: TEXT NULL
  - is_system: BOOLEAN NOT NULL DEFAULT false
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - display_name: VARCHAR(150) NULL
  - category: VARCHAR(20) NOT NULL DEFAULT 'CUSTOM'::character varying
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - is_assignable: BOOLEAN NOT NULL DEFAULT true
  - priority: INTEGER NOT NULL DEFAULT 50
  - created_by: UUID NULL
  - updated_by: UUID NULL
Primary key: ['id'] (name=roles_pkey)
Foreign keys:
  - ['created_by'] -> users.['id'] (name=fk_roles_created_by, ondelete=SET NULL)
  - ['updated_by'] -> users.['id'] (name=fk_roles_updated_by, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=roles_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_role_org_name: ['organization_id', 'name']
Indexes:
  - ix_roles_organization_id: ['organization_id']
  - ix_roles_status: ['status']
  - uq_role_org_name UNIQUE: ['organization_id', 'name']

#### runtime_approvals
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - agent_id: UUID NULL
  - agent_version_id: UUID NULL
  - deployment_id: UUID NULL
  - execution_id: UUID NULL
  - requested_action: VARCHAR(30) NOT NULL
  - risk_score: INTEGER NULL
  - reason: TEXT NULL
  - matched_policies: JSONB NOT NULL DEFAULT '[]'::jsonb
  - request_summary: JSONB NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - requested_by: UUID NULL
  - reviewed_by: UUID NULL
  - decision_comment: TEXT NULL
  - expires_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - reviewed_at: TIMESTAMP NULL
Primary key: ['id'] (name=runtime_approvals_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=runtime_approvals_agent_id_fkey, ondelete=CASCADE)
  - ['agent_version_id'] -> agent_versions.['id'] (name=runtime_approvals_agent_version_id_fkey, ondelete=CASCADE)
  - ['deployment_id'] -> agent_deployments.['id'] (name=runtime_approvals_deployment_id_fkey, ondelete=CASCADE)
  - ['execution_id'] -> agent_executions.['id'] (name=runtime_approvals_execution_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=runtime_approvals_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_runtime_approvals_org: ['organization_id']
  - ix_runtime_approvals_status: ['status']

#### runtime_events
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - agent_id: UUID NULL
  - deployment_id: UUID NULL
  - execution_id: UUID NULL
  - event_type: VARCHAR(50) NOT NULL
  - severity: VARCHAR(20) NOT NULL DEFAULT 'INFO'::character varying
  - payload: JSONB NULL
  - request_id: VARCHAR(100) NULL
  - correlation_id: VARCHAR(100) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=runtime_events_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=runtime_events_agent_id_fkey, ondelete=CASCADE)
  - ['deployment_id'] -> agent_deployments.['id'] (name=runtime_events_deployment_id_fkey, ondelete=CASCADE)
  - ['execution_id'] -> agent_executions.['id'] (name=runtime_events_execution_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=runtime_events_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_runtime_events_agent: ['agent_id']
  - ix_runtime_events_execution: ['execution_id']
  - ix_runtime_events_org: ['organization_id']
  - ix_runtime_events_type: ['event_type']

#### security_events
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - event_type: VARCHAR(64) NOT NULL
  - actor_type: VARCHAR(30) NOT NULL
  - actor_id: UUID NULL
  - target_type: VARCHAR(30) NULL
  - target_id: UUID NULL
  - request_id: VARCHAR(64) NULL
  - correlation_id: VARCHAR(64) NULL
  - ip_address: VARCHAR(64) NULL
  - meta: JSONB NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=security_events_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=security_events_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_security_events_actor_created: ['actor_id', 'created_at']
  - ix_security_events_event_type: ['event_type']
  - ix_security_events_org_created: ['organization_id', 'created_at']
  - ix_security_events_organization_id: ['organization_id']
  - ix_security_events_request_id: ['request_id']
  - ix_security_events_session_id: [None]
  - ix_security_events_type_created: ['event_type', 'created_at']

#### service_accounts
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - client_secret_hash: VARCHAR(255) NOT NULL
  - permissions: JSONB NOT NULL
  - owner_id: UUID NULL
  - status: VARCHAR(30) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=service_accounts_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=service_accounts_organization_id_fkey, ondelete=CASCADE)
  - ['owner_id'] -> users.['id'] (name=service_accounts_owner_id_fkey, ondelete=SET NULL)
Indexes:
  - ix_service_accounts_organization_id: ['organization_id']

#### sod_rules
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - rule_type: VARCHAR(20) NOT NULL DEFAULT 'SOD'::character varying
  - name: VARCHAR(255) NOT NULL
  - description: TEXT NULL
  - risk_level: VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'::character varying
  - permissions_a: JSONB NOT NULL
  - permissions_b: JSONB NOT NULL
  - scope: JSONB NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'DRAFT'::character varying
  - created_by: UUID NULL
  - approved_by: UUID NULL
  - approved_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=sod_rules_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=sod_rules_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_sod_rules_org: ['organization_id']
  - ix_sod_rules_status: ['status']
  - ix_sod_rules_type: ['rule_type']

#### teams
Columns:
  - id: UUID NOT NULL
  - department_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - lead_id: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
Primary key: ['id'] (name=teams_pkey)
Foreign keys:
  - ['department_id'] -> departments.['id'] (name=teams_department_id_fkey, ondelete=CASCADE)
  - ['lead_id'] -> users.['id'] (name=teams_lead_id_fkey, ondelete=SET NULL)
Indexes:
  - ix_teams_department_id: ['department_id']

#### tool_calls
Columns:
  - id: UUID NOT NULL
  - execution_id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - tool_id: UUID NOT NULL
  - action: VARCHAR(50) NOT NULL
  - input_summary: JSONB NULL
  - output_summary: JSONB NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ALLOWED'::character varying
  - risk_score: INTEGER NULL
  - authorization_decision_id: UUID NULL
  - approval_id: UUID NULL
  - started_at: TIMESTAMP NULL
  - completed_at: TIMESTAMP NULL
  - duration_ms: INTEGER NULL
  - error_code: VARCHAR(50) NULL
  - cost: NUMERIC(12, 6) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=tool_calls_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=tool_calls_agent_id_fkey, ondelete=CASCADE)
  - ['execution_id'] -> agent_executions.['id'] (name=tool_calls_execution_id_fkey, ondelete=CASCADE)
  - ['tool_id'] -> tools.['id'] (name=tool_calls_tool_id_fkey, ondelete=RESTRICT)
Indexes:
  - ix_tool_calls_agent: ['agent_id']
  - ix_tool_calls_execution: ['execution_id']
  - ix_tool_calls_tool: ['tool_id']

#### tools
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - name: VARCHAR(100) NOT NULL
  - display_name: VARCHAR(150) NOT NULL
  - description: TEXT NULL
  - tool_type: VARCHAR(30) NOT NULL DEFAULT 'FUNCTION'::character varying
  - endpoint_reference: VARCHAR(500) NULL
  - input_schema: JSONB NULL
  - output_schema: JSONB NULL
  - risk_level: VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'::character varying
  - side_effect_level: VARCHAR(20) NOT NULL DEFAULT 'NONE'::character varying
  - data_classification: VARCHAR(30) NOT NULL DEFAULT 'INTERNAL'::character varying
  - requires_approval: BOOLEAN NOT NULL DEFAULT false
  - timeout_seconds: INTEGER NOT NULL DEFAULT 30
  - enabled: BOOLEAN NOT NULL DEFAULT true
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=tools_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=tools_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_tools_org: ['organization_id']

#### user_profiles
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - first_name: VARCHAR(100) NULL
  - last_name: VARCHAR(100) NULL
  - job_title: VARCHAR(150) NULL
  - department: VARCHAR(150) NULL
  - phone: VARCHAR(40) NULL
  - timezone: VARCHAR(64) NULL
  - language: VARCHAR(16) NULL
  - avatar_url: TEXT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=user_profiles_pkey)
Foreign keys:
  - ['user_id'] -> users.['id'] (name=user_profiles_user_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_user_profiles_user_id: ['user_id']
Indexes:
  - ix_user_profiles_user_id: ['user_id']
  - uq_user_profiles_user_id UNIQUE: ['user_id']

#### user_roles
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - role_id: UUID NOT NULL
  - scope: VARCHAR(20) NOT NULL DEFAULT 'GLOBAL'::character varying
  - organization_id: UUID NULL
  - department_id: UUID NULL
  - team_id: UUID NULL
  - project_id: UUID NULL
  - resource_type: VARCHAR(50) NULL
  - resource_id: UUID NULL
  - expires_at: TIMESTAMP NULL
  - assigned_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=user_roles_pkey)
Foreign keys:
  - ['assigned_by'] -> users.['id'] (name=fk_user_roles_assigned_by, ondelete=SET NULL)
  - ['department_id'] -> departments.['id'] (name=fk_user_roles_department_id, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=fk_user_roles_organization_id, ondelete=CASCADE)
  - ['team_id'] -> teams.['id'] (name=fk_user_roles_team_id, ondelete=CASCADE)
  - ['role_id'] -> roles.['id'] (name=user_roles_role_id_fkey, ondelete=CASCADE)
  - ['user_id'] -> users.['id'] (name=user_roles_user_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_user_role_scope: ['user_id', 'role_id', 'scope', 'organization_id', 'department_id', 'team_id', 'project_id', 'resource_type', 'resource_id']
Indexes:
  - ix_user_roles_organization_id: ['organization_id']
  - ix_user_roles_role_id: ['role_id']
  - ix_user_roles_scope: ['scope']
  - ix_user_roles_user_id: ['user_id']
  - uq_user_role_scope UNIQUE: ['user_id', 'role_id', 'scope', 'organization_id', 'department_id', 'team_id', 'project_id', 'resource_type', 'resource_id']

#### users
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - email: VARCHAR(320) NOT NULL
  - password_hash: VARCHAR(255) NOT NULL
  - role: VARCHAR(11) NOT NULL
  - is_active: BOOLEAN NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - department_id: UUID NULL
  - status: VARCHAR(30) NOT NULL DEFAULT 'ACTIVE'::character varying
  - password_changed_at: TIMESTAMP NULL
  - password_expires_at: TIMESTAMP NULL
  - must_change_password: BOOLEAN NOT NULL DEFAULT false
  - pending_email: VARCHAR(320) NULL
Primary key: ['id'] (name=users_pkey)
Foreign keys:
  - ['department_id'] -> departments.['id'] (name=fk_users_department_id, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=users_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_users_department_id: ['department_id']
  - ix_users_email UNIQUE: ['email']
  - ix_users_organization_id: ['organization_id']
  - ix_users_password_expires_at: ['password_expires_at']

## 3. Migration Chain

All 25 Alembic revisions in `backend/migrations/versions/`, in chain order (oldest → newest), verified via `alembic history` and `ls`. **Current head: `0025_agent_versioning`** (verified via `alembic current` against the live database).

| # | Revision file | Description (from the migration's own docstring) |
|---|---|---|
| 1 | `0001_initial_schema.py` | Initial schema: organizations, users, agents, permissions, agent_actions, approvals and audit_logs. |
| 2 | `0002_phase2_schema.py` | Phase 2 schema: agent API keys, policies, advanced RBAC, approval priority/SLA/comments and audit log forensic fields. |
| 3 | `0003_agent_management.py` | Phase 3 Part 3.2 - enterprise agent management fields + statuses. |
| 4 | `0004_policy_management.py` | Phase 3 Part 3.3 - policy management metadata. |
| 5 | `0005_approval_workbench.py` | Phase 3 Part 3.4 - approval queue & human review workbench. |
| 6 | `0006_identity_foundation.py` | Phase 4 Part 4.1 - Enterprise Identity Platform foundation. |
| 7 | `0007_identity_lifecycle.py` | Phase 4 Part 4.1a - unify the identity lifecycle across all identity types. |
| 8 | `0008_auth_login_history.py` | Phase 4 Part 4.2.2.1 - human authentication: login history + lockout window. |
| 9 | `0009_session_lifecycle.py` | Phase 4 Part 4.2.2.2 - login, logout & session lifecycle. |
| 10 | `0010_session_admin_permissions.py` | Phase 4 Part 4.2.2.2 - administrative session-management permissions. |
| 11 | `0011_security_event_read_indexes.py` | Phase 4 Part 4.2.2.2 - indexes for the security-event read path. |
| 12 | `0012_registration_invites.py` | Phase 4 Part 4.2.2.3.1 - enterprise registration, invitations & email verification. |
| 13 | `0013_credential_management.py` | Phase 4 Part 4.2.2.3.2 - enterprise password policy & credential management. |
| 14 | `0014_password_reset_recovery.py` | Phase 4 Part 4.2.2.3.3 - password reset, account recovery & email change. |
| 15 | `0015_account_protection.py` | Phase 4 Part 4.2.2.3.4 - enterprise account protection & risk-based auth. |
| 16 | `0016_rbac_foundation.py` | Phase 4.3.1 - Enterprise RBAC foundation. |
| 17 | `0017_permission_engine.py` | Phase 4.3.2 - Enterprise Permission Engine. |
| 18 | `0018_org_hierarchy.py` | Phase 4.3.3 - Enterprise organization authorization hierarchy. |
| 19 | `0019_resource_authorization.py` | Phase 4.3.4 - Enterprise resource-based authorization (RBAC + Resource ACL). |
| 20 | `0020_abac_engine.py` | Phase 4.3.5 - Attribute-Based Access Control engine. |
| 21 | `0021_access_reviews.py` | Phase 4.3.7 - Enterprise authorization administration portal. |
| 22 | `0022_governance_iga.py` | Phase 4.3.8 - Identity Governance & Administration (IGA). |
| 23 | `0023_agent_runtime.py` | Phase 5.0 - Enterprise AI Agent Runtime & Lifecycle Management. |
| 24 | `0024_agent_registry.py` | Phase 5.1 - Enterprise Agent Registry, Definitions & Lifecycle. |
| 25 | `0025_agent_versioning.py` | Phase 5.2 Part 1 - Enterprise Immutable Agent Versioning & Release Management. **(head)** |

## 4. Implemented Modules

**226 non-`__init__.py` Python files** under `backend/app/`, AST-parsed for their module docstring (first line shown) and every top-level class/public function. Grouped by domain (backend directory structure). Frontend module structure is summarized separately at the end of this section (file-count only — the frontend was not AST-parsed since the exhaustive symbol-level inventory the user asked for was scoped to "modules" in the module/class/function sense, which is the backend's organizing unit; the frontend's `src/modules/*` React component tree does not have an equivalent exported-symbol convention).

### api

**`backend/app/api/deps.py`** — Shared FastAPI dependencies: DB session, authentication, RBAC and context.
- Classes: `ActionPrincipal`
- Functions: `get_current_user,require_roles,require_permission,get_current_agent,get_action_principal,get_request_context`

**`backend/app/api/router.py`** — Aggregates every route module into a single API router.

**`backend/app/api/routes/agent_actions.py`** — Agent action routes - submit an action and inspect past actions.
- Functions: `submit_agent_action,list_agent_actions,get_agent_action`

**`backend/app/api/routes/agents.py`** — Agent management routes (scoped to the caller's organization).
- Functions: `create_agent,list_agents,get_agent,update_agent,delete_agent,agent_stats,update_agent_status`

**`backend/app/api/routes/analytics.py`** — Analytics & AI Operations Center routes (Phase 3 Part 3.6).
- Functions: `analytics_overview,analytics_kpis,analytics_activity,analytics_fleet_health,analytics_risk,analytics_performance,analytics_policies,analytics_review,analytics_cost,analytics_insights,analytics_reports`

**`backend/app/api/routes/api_keys.py`** — Agent API key routes - issue, list and revoke keys.
- Functions: `generate_api_key,list_api_keys,revoke_api_key`

**`backend/app/api/routes/approvals.py`** — Approval routes - the Human Review Workbench (Phase 3 Part 3.4).
- Functions: `list_approvals,list_pending_approvals,approval_statistics,approval_history,approval_escalations,get_approval,approval_timeline,list_comments,add_comment,approve,reject,escalate,assign`

**`backend/app/api/routes/audit.py`** — Audit & Compliance Center routes (Phase 3 Part 3.5).
- Functions: `list_audit,audit_statistics,audit_timeline,audit_event_catalog,audit_security,audit_compliance,audit_export,get_audit_event`

**`backend/app/api/routes/audit_logs.py`** — Audit log routes - read-only access to the event trail.
- Functions: `list_audit_logs,list_entity_audit_logs`

**`backend/app/api/routes/auth.py`** — Authentication routes: register, login and current-user.
- Functions: `register,login,me`

**`backend/app/api/routes/dashboard.py`** — Dashboard routes - aggregated metrics and feeds for the future frontend.
- Functions: `dashboard_summary,agent_activity,risk_trend,recent_actions,high_risk_actions,pending_approvals`

**`backend/app/api/routes/organizations.py`** — Organization routes.
- Functions: `create_organization,get_organization`

**`backend/app/api/routes/permissions.py`** — Permission management routes.
- Functions: `create_permission,list_permissions,list_agent_permissions`

**`backend/app/api/routes/policies.py`** — Policy routes - CRUD, lifecycle, simulation and audit for governance policies.
- Functions: `create_policy,list_policies,list_policy_templates,get_policy,update_policy,enable_policy,disable_policy,test_policy,policy_audit,delete_policy`

**`backend/app/api/routes/rbac.py`** — RBAC routes - inspect roles/permissions and assign roles to users.
- Functions: `list_permissions,list_roles,my_permissions,assign_role`

**`backend/app/api/routes/system.py`** — System routes - operational health of the platform's subsystems.
- Functions: `system_health`

**`backend/app/api/routes/users.py`** — User management routes (scoped to the caller's organization).
- Functions: `create_user,list_users,get_user`


### authorization (core)

**`backend/app/authorization/cache.py`** — Permission cache + version management (Phase 4.3.2 §10, §18).
- Classes: `PermissionCacheService`

**`backend/app/authorization/catalog.py`** — Permission groups, the enriched permission catalog, and the built-in role
- Classes: `PermissionGroupDef,BuiltinRoleDef`
- Functions: `split_code,group_for_code,display_name_for_code,legacy_role_priority`

**`backend/app/authorization/decisions.py`** — Authorization decision audit (Phase 4.3.2 §18, §20, §27).
- Classes: `AuthorizationDecisionService`

**`backend/app/authorization/engine.py`** — The Enterprise Permission Engine (Phase 4.3.2).
- Classes: `Grant,ResourceContext,AuthorizationResult,WildcardResolver,RoleResolver,ScopeResolver,ConflictResolver,PermissionResolver,PermissionEngine`

**`backend/app/authorization/enums.py`** — Authorization enums (Phase 4.3.1 §8, §9, §15, §23).
- Classes: `RoleCategory,RoleStatus,AssignmentScope,AuthorizationDecision,AuthorizationEngineEvent,AuthorizationAuditEvent`

**`backend/app/authorization/repositories.py`** — Authorization repositories (Phase 4.3.1 §19).
- Classes: `RoleRepository,PermissionRepository,PermissionGroupRepository,RoleAssignmentRepository,RoleHierarchyRepository,AuthorizationAuditRepository`

**`backend/app/authorization/routes.py`** — Enterprise authorization API (Phase 4.3.1 §20).
- Functions: `list_roles,create_role,get_role,update_role,delete_role,role_effective_permissions,list_permissions,create_permission,update_permission,delete_permission,list_permission_groups,list_role_assignments,create_role_assignment,delete_role_assignment,list_role_hierarchy,create_role_hierarchy,delete_role_hierarchy,authorization_check,list_authorization_audit`

**`backend/app/authorization/schemas.py`** — Authorization API schemas (Phase 4.3.1 §20).
- Classes: `PermissionGroupRead,PermissionRead,PermissionCreate,PermissionUpdate,RoleRead,RoleCreate,RoleUpdate,EffectivePermissionsRead,RoleAssignmentCreate,RoleAssignmentRead,RoleHierarchyCreate,RoleHierarchyRead,AuthorizationCheckRequest,AuthorizationCheckResponse,AuthorizationAuditRead`

**`backend/app/authorization/seeding.py`** — Idempotent seeding of the authorization foundation (Phase 4.3.1 §7, §12, §17).
- Functions: `seed_authorization`

**`backend/app/authorization/services.py`** — Authorization services (Phase 4.3.1 §18).
- Classes: `AuthorizationAuditService,PermissionService,PermissionGroupService,RoleService,RoleHierarchyService,RoleAssignmentService`


### authorization/abac

**`backend/app/authorization/abac/attributes.py`** — ABAC attribute system (Phase 4.3.5 §5, §18–§20).
- Classes: `AttributeRegistryService,AuthorizationAttributeContext,SubjectAttributeProvider,ResourceAttributeProvider,ActionAttributeProvider,EnvironmentAttributeProvider,AIAttributeProvider,AttributeContextBuilder`

**`backend/app/authorization/abac/conditions.py`** — ABAC condition evaluator (Phase 4.3.5 §9, §24).
- Classes: `ConditionTrace,ConditionEvaluator`

**`backend/app/authorization/abac/engine.py`** — The ABAC engine (Phase 4.3.5 §13–§17, §23–§26, §43).
- Classes: `ABACMetrics,MatchedPolicy,CombiningAlgorithmService,ObligationService,DecisionExplanationService,ABACResult,ABACEngine,PolicySimulationService`

**`backend/app/authorization/abac/enums.py`** — ABAC engine enums (Phase 4.3.5 §5, §7–§13, §38).
- Classes: `PolicyStatus,PolicyEffect,CombiningAlgorithm,PolicyScopeType,AttributeCategory,AttributeDataType,AttributeSensitivity,Operator,ABACDecision,ABACAuditEvent`

**`backend/app/authorization/abac/operators.py`** — ABAC operator registry (Phase 4.3.5 §9, §10, §24).
- Classes: `OperatorRegistry`
- Functions: `validate_regex_pattern,validate_condition_value`

**`backend/app/authorization/abac/policies.py`** — ABAC policy services (Phase 4.3.5 §6–§8, §11–§13, §21, §23–§24, §27–§28).
- Classes: `PolicyCache,PolicyValidationService,PolicyService,PolicyResolver`
- Functions: `record_abac_event`

**`backend/app/authorization/abac/routes.py`** — ABAC engine API (Phase 4.3.5 §30, §37).
- Functions: `list_policies,create_policy,get_policy,update_policy,delete_policy,validate_policy,publish_policy,disable_policy,archive_policy,clone_policy,list_versions,get_version,rollback_policy,simulate,simulate_policy,evaluate,list_evaluations,get_evaluation,abac_metrics,middleware_metrics,list_attributes,get_attribute,create_attribute,update_attribute,list_exceptions,create_exception,revoke_exception`

**`backend/app/authorization/abac/schemas.py`** — ABAC API schemas (Phase 4.3.5 §15, §30, §31).
- Classes: `PolicyRead,PolicyWrite,ValidationResult,PolicyVersionRead,AttributeRead,AttributeCreate,AttributeUpdate,ABACDecisionRead,EvaluateRequest,SimulateRequest,SimulationRead,EvaluationRead,ExceptionRead,ExceptionCreate`


### authorization/admin

**`backend/app/authorization/admin/routes.py`** — Administration portal API (Phase 4.3.7 §18) — /api/v1/admin.
- Functions: `dashboard,list_roles,create_role,update_role,delete_role,list_permissions,organization_tree,list_resources,list_policies,create_policy,update_policy,delete_policy,policy_simulator,authorization_decisions,list_campaigns,create_campaign,get_campaign,update_campaign,schedule_campaign,activate_campaign,campaign_items,decide_item,complete_campaign,archive_campaign,export_campaign,analytics`

**`backend/app/authorization/admin/schemas.py`** — Pydantic schemas for the administration portal API (Phase 4.3.7 §18).
- Classes: `DashboardWidgets,DashboardCharts,DashboardRead,DecisionRead,CampaignCreate,CampaignUpdate,ReviewItemRead,CampaignRead,ItemDecision,AnalyticsRead`

**`backend/app/authorization/admin/services.py`** — Administration portal services (Phase 4.3.7).
- Classes: `DashboardService,DecisionExplorerService,AccessReviewService,SecurityAnalyticsService`


### authorization/hierarchy

**`backend/app/authorization/hierarchy/enums.py`** — Organization hierarchy enums (Phase 4.3.3 §3, §18).
- Classes: `HierarchyLevel,OrgEntityStatus,OrgAuditEvent`

**`backend/app/authorization/hierarchy/routes.py`** — Organization hierarchy API (Phase 4.3.3 §15, §17).
- Functions: `list_organizations,create_organization,get_organization,update_organization,delete_organization,list_business_units,create_business_unit,get_business_unit,update_business_unit,delete_business_unit,list_departments,create_department,get_department,update_department,delete_department,list_teams,create_team,get_team,update_team,delete_team,list_projects,create_project,get_project,update_project,delete_project,hierarchy_tree,assign_ownership,transfer_ownership,get_ownership,list_delegations,create_delegation,revoke_delegation`

**`backend/app/authorization/hierarchy/schemas.py`** — Organization hierarchy API schemas (Phase 4.3.3 §15).
- Classes: `OrganizationRead,OrganizationWrite,BusinessUnitRead,BusinessUnitWrite,DepartmentRead,DepartmentWrite,TeamRead,TeamWrite,ProjectRead,ProjectWrite,ResourceOwnershipRead,ResourceOwnershipAssign,OwnershipTransfer,DelegationRead,DelegationCreate`

**`backend/app/authorization/hierarchy/services.py`** — Organization hierarchy services (Phase 4.3.3 §12, §13).
- Classes: `HierarchyResolverService,_OrgScoped,BusinessUnitService,DepartmentService,TeamService,ProjectService,ResourceOwnershipService,OrganizationHierarchyService,DelegationService`
- Functions: `record_org_event`


### authorization/middleware

**`backend/app/authorization/middleware/audit.py`** — Middleware audit integration (Phase 4.3.6 §24, §35).
- Classes: `AuthorizationAuditService`

**`backend/app/authorization/middleware/cache.py`** — Decision cache (Phase 4.3.6 §19, §23).
- Classes: `_Entry,DecisionCacheService`

**`backend/app/authorization/middleware/context.py`** — The authorization context (Phase 4.3.6 §5).
- Classes: `AuthorizationContext,AuthorizationContextBuilder`

**`backend/app/authorization/middleware/errors.py`** — Standard authorization exceptions (Phase 4.3.6 §25, §26).
- Classes: `AuthorizationMiddlewareError,AuthenticationFailed,SessionExpired,PermissionDenied,ResourceForbidden,ABACDenied,ApprovalRequired,MFARequired,JustificationRequired,PolicyEvaluationFailed`

**`backend/app/authorization/middleware/gateway.py`** — The Authorization Gateway (Phase 4.3.6 §21, §22).
- Classes: `GatewayDecision,AuthorizationGateway`

**`backend/app/authorization/middleware/metrics.py`** — Pipeline metrics (Phase 4.3.6 §34).
- Classes: `PipelineMetricsService`

**`backend/app/authorization/middleware/obligations.py`** — Obligation processing (Phase 4.3.6 §16).
- Classes: `ObligationOutcome,ObligationExecutor`

**`backend/app/authorization/middleware/pipeline.py`** — The authorization pipeline (Phase 4.3.6 §4, §9, §18).
- Classes: `AuthorizationPipeline,DecisionTrace,DecisionTraceService`


### authorization/resources

**`backend/app/authorization/resources/enums.py`** — Resource-based authorization enums (Phase 4.3.4 §3, §9, §10, §12, §23).
- Classes: `ResourceType,OwnerType,VisibilityLevel,PrincipalType,ACLEffect,ShareAccessLevel,ResourceStatus,DelegationStatus,ResourceAuditEvent`

**`backend/app/authorization/resources/routes.py`** — Resource-based authorization API (Phase 4.3.4 §19).
- Functions: `list_resource_types,list_resources,register_resource,get_resource,update_resource,get_owner,transfer_ownership,ownership_history,list_acl,add_acl_entry,update_acl_entry,delete_acl_entry,list_shares,share_resource,update_share,revoke_share,list_delegations,delegate_resource,revoke_delegation,set_policy,authorize`

**`backend/app/authorization/resources/schemas.py`** — Resource-based authorization API schemas (Phase 4.3.4 §19).
- Classes: `ResourceRead,ResourceRegister,ResourceUpdate,OwnerRead,OwnershipTransferRequest,OwnershipHistoryRead,ACLEntryRead,ACLEntryCreate,ACLEntryUpdate,ShareRead,ShareCreate,ShareUpdate,ResourceDelegationRead,ResourceDelegationCreate,PolicyWrite,AuthorizeRequest,AuthorizeResponse`

**`backend/app/authorization/resources/services.py`** — Resource-based authorization services (Phase 4.3.4 §16, §17).
- Classes: `MembershipResolver,ResourceRegistryService,_ResourceScoped,ResourceACLService,ResourceSharingService,ResourceOwnershipService,ResourceDelegationService,ResourcePolicyService,ResourceDecision,ResourceAuthorizationService`
- Functions: `action_of,permission_covers,record_resource_event`


### core

**`backend/app/core/config.py`** — Application configuration loaded from environment variables / .env file.
- Classes: `Settings`

**`backend/app/core/database.py`** — Database engine, session factory and declarative base.
- Classes: `Base`
- Functions: `get_db`

**`backend/app/core/enums.py`** — Enumerations shared between SQLAlchemy models and Pydantic schemas.
- Classes: `UserRole,AgentStatus,RiskLevel,AgentHealth,ActionDecision,ActionStatus,ApprovalDecision,ActorType,ApiKeyStatus,ApprovalPriority,PolicySeverity,PolicyStatus,EscalationTarget`

**`backend/app/core/middleware.py`** — Cross-cutting HTTP middleware (Phase 4.2.2.3.5 §13, §15, §16, §23).
- Classes: `RequestContextMiddleware,SecurityHeadersMiddleware,ResponseEnvelopeMiddleware`
- Functions: `install_http_middleware`

**`backend/app/core/policy_templates.py`** — Built-in policy templates surfaced in the dashboard's template gallery.

**`backend/app/core/security.py`** — Security helpers: password hashing, JWT tokens and API key handling.
- Functions: `hash_password,is_unusable_password,verify_password,needs_rehash,create_access_token,decode_access_token,generate_api_key,generate_agent_api_key,hash_api_key,verify_api_key`


### governance

**`backend/app/governance/routes.py`** — Identity Governance & Administration API (Phase 4.3.8 §19) — /api/v1/governance.
- Functions: `dashboard,analytics,list_campaigns,create_campaign,get_campaign,update_campaign,launch_campaign,campaign_items,complete_campaign,archive_campaign,export_campaign,approve_review,revoke_review,delegate_review,modify_review,list_sod_rules,create_sod_rule,update_sod_rule,activate_sod_rule,disable_sod_rule,list_sod_findings,scan_sod,list_toxic_rules,create_toxic_rule,activate_toxic_rule,disable_toxic_rule,list_toxic_findings,scan_toxic,list_findings,remediate_finding,list_privileged_accounts,request_privileged_review,list_privileged_reviews,decide_privileged_review,list_orphaned_accounts,scan_orphaned_accounts,list_risk_scores,recalculate_risk_scores,list_remediation_actions,create_remediation_action,execute_remediation_action,compliance_frameworks,list_compliance_reports,generate_compliance_report,get_compliance_report`

**`backend/app/governance/schemas.py`** — Pydantic schemas for the governance API (Phase 4.3.8 §19).
- Classes: `SoDRuleCreate,SoDRuleUpdate,SoDRuleRead,GovernanceFindingRead,FindingResolve,RemediationActionCreate,RemediationActionRead,GovernanceRiskScoreRead,PrivilegedAccountRead,PrivilegedReviewDecision,OrphanedScanResult,ComplianceReportGenerate,ComplianceReportRead,ComplianceFrameworkRead,GovernanceDashboardRead,GovernanceAnalyticsRead,CampaignCreate,CampaignUpdate,CampaignRead,ReviewItemRead,ReviewDecision`

**`backend/app/governance/services.py`** — Identity Governance & Administration services (Phase 4.3.8).
- Classes: `SoDAnalysisService,GovernanceFindingService,RemediationService,GovernanceRiskScoringService,PrivilegedAccessReviewService,OrphanedIdentityService,ComplianceReportingService,GovernanceDashboardService`


### identity/api

**`backend/app/identity/api/deps.py`** — Identity API dependencies.
- Functions: `get_identity_service,get_request_id`

**`backend/app/identity/api/router.py`** — Aggregates identity routes under the versioned prefix (SRS §17).

**`backend/app/identity/api/routes/agent_identities.py`** — AI agent identity endpoints (SRS §7). Identity of an agent, not the agent.
- Functions: `list_agent_identities,create_agent_identity,get_agent_identity,transition_agent_identity`

**`backend/app/identity/api/routes/departments.py`** — Identity department endpoints (SRS §9 api).
- Functions: `list_departments,create_department,get_department`

**`backend/app/identity/api/routes/external_clients.py`** — External client endpoints (SRS §7). Power BI, Zapier, Salesforce, Fabric…
- Functions: `list_external_clients,create_external_client,get_external_client,transition_external_client`

**`backend/app/identity/api/routes/invitations.py`** — Invitation endpoints (4.2.2.3.1 §15).
- Classes: `EmailDeliveryStatus`
- Functions: `create_invitation,list_invitations,resend_invitation,cancel_invitation,preview_invitation,approve_registration,email_delivery_status`

**`backend/app/identity/api/routes/organizations.py`** — Identity organization endpoints (SRS §9 api).
- Functions: `list_organizations,get_organization,transition_organization`

**`backend/app/identity/api/routes/registration.py`** — Public registration & email-verification endpoints (4.2.2.3.1 §15).
- Functions: `register_from_invitation,self_register,verify_email,resend_verification`

**`backend/app/identity/api/routes/roles.py`** — Identity role endpoints (SRS §9 api). Reuses the RBAC role engine.
- Functions: `list_roles`

**`backend/app/identity/api/routes/service_accounts.py`** — Service account endpoints (SRS §7). Backend automation identities.
- Functions: `list_service_accounts,create_service_account,get_service_account,transition_service_account`

**`backend/app/identity/api/routes/sessions.py`** — Administrative session & device management (SRS 4.2.2.2 §17, §18, §32).
- Classes: `AdminRevokeRequest,AdminRevokeResponse`
- Functions: `list_sessions,get_session,list_user_devices,admin_revoke_session,admin_revoke_all_sessions,list_security_events,list_security_event_types,list_session_events`

**`backend/app/identity/api/routes/users.py`** — Identity user endpoints (SRS §9 api). Thin controllers → IdentityService.
- Functions: `list_users,create_user,get_user,activate_user,suspend_user,transition_user`


### identity/audit

**`backend/app/identity/audit/events.py`** — Identity audit/security event recording (SRS §9 audit, §19).
- Functions: `record_security_event`


### identity/auth

**`backend/app/identity/auth/authentication_service.py`** — AuthenticationService — login / refresh / logout orchestration (SRS §16, §19–21).
- Classes: `RequestClient,LoginResult,RefreshResult,AuthenticationService`

**`backend/app/identity/auth/context.py`** — IdentityContext — the internal object every authenticated request carries.
- Classes: `IdentityContext`

**`backend/app/identity/auth/credential_service.py`** — CredentialService — verify secrets and credential status (SRS §11, §16).
- Classes: `CredentialService`

**`backend/app/identity/auth/dependency.py`** — Authentication middleware/dependency (SRS §17; 4.2.2.2 §5, §16, §28).
- Functions: `extract_credential,authenticate,require_scope,require_assurance`

**`backend/app/identity/auth/device_service.py`** — DeviceService — register, recognise, trust and block devices (SRS §13, §14).
- Classes: `ClientInfo,DeviceService`
- Functions: `parse_user_agent,fingerprint_for`

**`backend/app/identity/auth/enums.py`** — Authentication enumerations (SRS §3, §10, §13).
- Classes: `AuthIdentityType,AuthMethod,AuthAssuranceLevel,MfaMethod,AuthEventType`

**`backend/app/identity/auth/login_history_service.py`** — LoginHistoryService — record attempts and drive account lockout (SRS §10, §13, §14).
- Classes: `LockoutState,LoginHistoryService`

**`backend/app/identity/auth/password_service.py`** — PasswordService — hash, verify and enforce password complexity (SRS §9, §11, §14).
- Classes: `PasswordService`

**`backend/app/identity/auth/refresh_rotation_service.py`** — RefreshRotationService — rotate, detect reuse, revoke families (SRS §7, §8, §9).
- Classes: `IssuedToken,RefreshRotationService`

**`backend/app/identity/auth/resolver.py`** — IdentityContextResolver — validated credentials → IdentityContext (SRS §9, §16).
- Classes: `IdentityContextResolver`

**`backend/app/identity/auth/routes.py`** — Human authentication + session lifecycle endpoints (SRS §16, §23).
- Functions: `get_auth_service,login,mfa_verify,refresh,logout,me,list_sessions,get_session,revoke_session,delete_session,list_devices,trust_device,my_security_events,block_device`

**`backend/app/identity/auth/schemas.py`** — Request/response DTOs for the human-authentication endpoints (SRS §16, §17, §23).
- Classes: `LoginRequestDTO,TokenResponse,LoginResponse,MfaVerifyRequestDTO,RefreshRequestDTO,MeResponse,SessionRead,SessionDetail,RevokeSessionRequest,LogoutRequest,LogoutResponse,DeviceRead,SecurityEventRead,SecurityEventPage`

**`backend/app/identity/auth/security_event_service.py`** — SecurityEventService — record authentication/security events (SRS §13, §16).
- Classes: `SecurityEventService`

**`backend/app/identity/auth/session_lifecycle_service.py`** — SessionLifecycleService — create, touch, expire, revoke (SRS §4, §5, §11, §12).
- Classes: `SessionTimings,SessionLifecycleService`

**`backend/app/identity/auth/session_security_service.py`** — SessionSecurityService — score sessions and detect suspicious behaviour (SRS §15).
- Classes: `RiskAssessment,SessionSecurityService`

**`backend/app/identity/auth/token_service.py`** — TokenService — create / decode / validate access tokens (SRS §6, §7, §16).
- Classes: `TokenService`


### identity/credentials

**`backend/app/identity/credentials/audit.py`** — CredentialAuditService — one place every credential event is recorded (SRS §18).
- Classes: `CredentialContext,CredentialAuditService`

**`backend/app/identity/credentials/history_service.py`** — PasswordHistoryService — store past hashes, detect reuse, prune (SRS §10, §19).
- Classes: `PasswordHistoryService`

**`backend/app/identity/credentials/policy_service.py`** — PasswordPolicyService — validation, strength, expiration (SRS §5, §8, §11, §19).
- Classes: `PasswordPolicyService`

**`backend/app/identity/credentials/reset_service.py`** — PasswordResetService — administrative reset & temporary passwords (SRS §12, §16).
- Classes: `TemporaryCredential,PasswordResetService`

**`backend/app/identity/credentials/routes.py`** — Credential-management endpoints (SRS §22).
- Functions: `change_password,admin_reset_password,validate_password,password_policy,password_expiration,password_dashboard`

**`backend/app/identity/credentials/schemas.py`** — Request/response DTOs for the credential-management API (SRS §22).
- Classes: `ChangePasswordRequest,ChangePasswordResponse,AdminResetRequest,AdminResetResponse,ValidatePasswordRequest,ValidatePasswordResponse,PasswordPolicyResponse,PasswordExpirationResponse,PasswordDashboardUser,PasswordDashboardResponse`

**`backend/app/identity/credentials/service.py`** — CredentialService — the one place a human password is set or changed (SRS §9, §14, §15).
- Classes: `CredentialService`
- Functions: `generate_temporary_password`


### identity/email

**`backend/app/identity/email/service.py`** — Transactional email for onboarding (4.2.2.3.1 §6, §8, §12).
- Classes: `EmailResult,EmailService`
- Functions: `invitation_url,verification_url,reset_url,new_email_verification_url`


### identity/errors.py

**`backend/app/identity/errors.py`** — Standard identity error envelope and exception handling (SRS §18).
- Classes: `ErrorCode,IdentityError`
- Functions: `error_body,register_identity_exception_handlers`


### identity/models

**`backend/app/identity/models/agent_identity.py`** — AI Agent Identity — the *identity* of an agent, not the agent itself (SRS §7).
- Classes: `AgentIdentity`

**`backend/app/identity/models/credential.py`** — Credential-history ORM model (4.2.2.3.2 §10, §21).
- Classes: `PasswordHistory`

**`backend/app/identity/models/department.py`** — Organizational hierarchy below the tenant: Department → Team (SRS §7, §11).
- Classes: `Department,Team`

**`backend/app/identity/models/enums.py`** — Identity domain enumerations (Phase 4 Part 4.1).
- Classes: `IdentityType,IdentityStatus,InvitationStatus,RegistrationMode,PasswordResetStatus,EmailVerificationPurpose,CredentialType,SessionStatus,SessionRevocationReason,DeviceStatus,SessionSecurityBand,SecurityEventType`
- Functions: `can_transition`

**`backend/app/identity/models/external_client.py`** — External Client identity — Power BI, Zapier, Salesforce, Fabric, etc. (SRS §7).
- Classes: `ExternalClient`

**`backend/app/identity/models/login_history.py`** — Login history model (table ``login_history``, SRS §13).
- Classes: `LoginHistory`

**`backend/app/identity/models/protection.py`** — Account-protection ORM models (4.2.2.3.4 §17).
- Classes: `AccountLock,IdentityRiskEvent,BlockedIp,IdentityProtectionRule`

**`backend/app/identity/models/recovery.py`** — Password-reset request model (4.2.2.3.3 §5).
- Classes: `PasswordResetRequest`

**`backend/app/identity/models/registration.py`** — Invitation, email-verification, user-profile and rate-limit models (4.2.2.3.1 §5).
- Classes: `Invitation,EmailVerification,UserProfile,RateLimitHit`

**`backend/app/identity/models/security_event.py`** — Security event model (table ``security_events``, SRS §10, §19).
- Classes: `SecurityEvent`

**`backend/app/identity/models/service_account.py`** — Service Account identity — backend automation (SRS §7).
- Classes: `ServiceAccount`

**`backend/app/identity/models/session.py`** — Session, refresh-token and device models (SRS 4.2.2.2 §6, §7, §13).
- Classes: `UserSession,RefreshToken,UserDevice`


### identity/permissions

**`backend/app/identity/permissions/evaluator.py`** — Permission evaluator (SRS §9).
- Classes: `PermissionEvaluator`


### identity/protection

**`backend/app/identity/protection/alerts.py`** — SecurityAlertService — notify users and admins of protection events (§30).
- Classes: `SecurityAlertService`

**`backend/app/identity/protection/detection.py`** — Risk scoring, anomaly detection and brute-force detection (4.2.2.3.4 §9–§15).
- Classes: `LoginSignals,LoginAnomalyService,RiskScoringService,BruteForcePattern,BruteForceDetectionService`

**`backend/app/identity/protection/enums.py`** — Account-protection enumerations (4.2.2.3.4 §7, §8, §14).
- Classes: `AuthDecision,RiskLevel,AccountLockStatus,AccountLockReason`

**`backend/app/identity/protection/lockout.py`** — AccountLockoutService — progressive, stateful account locks (4.2.2.3.4 §8, §29).
- Classes: `LockResult,AccountLockoutService`

**`backend/app/identity/protection/policy.py`** — Blocked IPs, protection rules, adaptive rate limiting and CAPTCHA (§10, §16, §28).
- Classes: `BlockedIpService,CaptchaService,AdaptiveRateLimitService,IdentityProtectionRuleService`

**`backend/app/identity/protection/rate_limit.py`** — Adaptive rate limiting for the login endpoint (4.2.2.3.4 §10).
- Functions: `adaptive_login_rate_limit`

**`backend/app/identity/protection/repositories.py`** — Repositories for the account-protection tables (4.2.2.3.4 §17, §20).
- Classes: `AccountLockRepository,BlockedIpRepository,IdentityProtectionRuleRepository,IdentityRiskEventRepository,LoginAttemptQuery`

**`backend/app/identity/protection/routes.py`** — Account-protection admin endpoints (4.2.2.3.4 §20).
- Functions: `summary,login_attempts,risk_events,account_locks,unlock_lock,lock_user,unlock_user,list_blocked_ips,block_ip,unblock_ip,list_rules,create_rule,update_rule,delete_rule`

**`backend/app/identity/protection/schemas.py`** — Request/response DTOs for the account-protection API (4.2.2.3.4 §20).
- Classes: `LoginAttemptRead,RiskEventRead,AccountLockRead,BlockedIpRead,ProtectionRuleRead,UnlockRequest,LockUserRequest,BlockIpRequest,ProtectionRuleWrite,ProtectionRuleUpdate,ProtectionSummary`

**`backend/app/identity/protection/service.py`** — AccountProtectionService — coordinates protection during login (§6, §19, §21).
- Classes: `ProtectionOutcome,AccountProtectionService`


### identity/ratelimit

**`backend/app/identity/ratelimit/limiter.py`** — Rate limiting for public endpoints (4.2.2.3.1 §19).
- Classes: `RateLimitDecision,RateLimiter`
- Functions: `client_ip,rate_limit`


### identity/recovery

**`backend/app/identity/recovery/audit.py`** — RecoveryAuditService — one place recovery events are recorded (4.2.2.3.3 §24).
- Classes: `RecoveryContext,RecoveryAuditService`

**`backend/app/identity/recovery/email_change_service.py`** — EmailChangeService — verified email change (4.2.2.3.3 §12).
- Classes: `EmailChangeService`

**`backend/app/identity/recovery/password_reset_service.py`** — PasswordResetService — the forgot-password / reset flow (4.2.2.3.3 §9, §10, §19).
- Classes: `PasswordResetService`

**`backend/app/identity/recovery/repository.py`** — Password-reset repository (4.2.2.3.3 §20). Lookup is always by token hash.
- Classes: `PasswordResetRepository`

**`backend/app/identity/recovery/routes.py`** — Recovery endpoints (4.2.2.3.3 §21).
- Functions: `forgot_password,reset_password,change_email,verify_new_email,recovery_events`

**`backend/app/identity/recovery/schemas.py`** — Request/response DTOs for the recovery API (4.2.2.3.3 §21).
- Classes: `ForgotPasswordRequest,ResetPasswordRequest,ChangeEmailRequest,VerifyNewEmailRequest,RecoveryAck,RecoveryEventRead`

**`backend/app/identity/recovery/service.py`** — RecoveryService — coordinates the recovery workflow (4.2.2.3.3 §3, §19).
- Classes: `RecoveryService`


### identity/registration

**`backend/app/identity/registration/audit.py`** — RegistrationAuditService — one place that records onboarding events (§7, §13, §20).
- Classes: `RequestContext,RegistrationAuditService`

**`backend/app/identity/registration/invitation_service.py`** — InvitationService — create, validate, resend, revoke (4.2.2.3.1 §7, §8).
- Classes: `IssuedInvitation,InvitationService`

**`backend/app/identity/registration/provisioning_service.py`** — UserProvisioningService — turn an accepted invitation into an identity (§7).
- Classes: `ProvisionRequest,UserProvisioningService`

**`backend/app/identity/registration/registration_service.py`** — RegistrationService — the onboarding orchestrator (4.2.2.3.1 §7, §8).
- Classes: `RegistrationResult,RegistrationService`

**`backend/app/identity/registration/schemas.py`** — DTOs for registration, invitations and email verification (§10, §11, §15, §17).
- Classes: `_TrimmedNames,InvitationCreateRequest,InvitationActionRequest,InvitationRead,InvitationPreview,RegisterFromInvitationRequest,SelfRegisterRequest,RegistrationResponse,VerifyEmailRequest,ResendVerificationRequest,GenericAcknowledgement,UserProfileRead`

**`backend/app/identity/registration/tokens.py`** — Onboarding token generation (4.2.2.3.1 §9, §14).
- Functions: `generate_invitation_token,generate_verification_token,generate_reset_token,token_hash`

**`backend/app/identity/registration/verification_service.py`** — EmailVerificationService — issue, validate, redeem (4.2.2.3.1 §7, §12).
- Classes: `IssuedVerification,EmailVerificationService`


### identity/repositories

**`backend/app/identity/repositories/base.py`** — Generic repository base — one aggregate per repository (SRS §16).
- Classes: `BaseRepository`

**`backend/app/identity/repositories/department_repository.py`** — Department aggregate repository (SRS §16).
- Classes: `DepartmentRepository`

**`backend/app/identity/repositories/device_repository.py`** — Device repository (SRS 4.2.2.2 §22).
- Classes: `DeviceRepository`

**`backend/app/identity/repositories/identity_repositories.py`** — Repositories for the machine identity aggregates (SRS §16).
- Classes: `AgentIdentityRepository,ServiceAccountRepository,ExternalClientRepository`

**`backend/app/identity/repositories/login_history_repository.py`** — Login history repository (SRS §13, §15).
- Classes: `LoginHistoryRepository`

**`backend/app/identity/repositories/organization_repository.py`** — Organization aggregate repository (SRS §16).
- Classes: `OrganizationRepository`

**`backend/app/identity/repositories/permission_repository.py`** — Permission catalog repository (SRS §16). Reuses ``rbac_permissions``.
- Classes: `PermissionRepository`

**`backend/app/identity/repositories/refresh_token_repository.py`** — Refresh-token repository (SRS 4.2.2.2 §22).
- Classes: `RefreshTokenRepository`

**`backend/app/identity/repositories/registration_repositories.py`** — Repositories for invitations, email verifications and user profiles (§5).
- Classes: `InvitationRepository,EmailVerificationRepository,UserProfileRepository`

**`backend/app/identity/repositories/role_repository.py`** — Role aggregate repository (SRS §16). Reuses the existing RBAC roles table.
- Classes: `RoleRepository`

**`backend/app/identity/repositories/security_event_repository.py`** — Security-event repository — the read path over ``security_events`` (SRS §26).
- Classes: `SecurityEventRepository`

**`backend/app/identity/repositories/session_repository.py`** — Session aggregate repository (SRS 4.2.2.2 §22).
- Classes: `SessionRepository`

**`backend/app/identity/repositories/user_repository.py`** — User aggregate repository (SRS §16).
- Classes: `UserRepository`


### identity/roles

**`backend/app/identity/roles/engine.py`** — Role engine — assign/revoke/list roles (SRS §9 roles).
- Classes: `RoleEngine`


### identity/schemas

**`backend/app/identity/schemas/identity.py`** — Identity request/response schemas (SRS §9 schemas, §18 error format).
- Classes: `ErrorBody,ErrorEnvelope,LifecycleTransition,UserRead,UserCreate,OrganizationRead,DepartmentRead,DepartmentCreate,TeamRead,RoleRead,ServiceAccountRead,SessionRead,AgentIdentityCreate,AgentIdentityRead,ServiceAccountCreate,ServiceAccountCreated,ExternalClientCreate,ExternalClientRead,ExternalClientCreated`


### identity/security

**`backend/app/identity/security/passwords.py`** — Password policy + hashing/secret helpers (SRS §9, §11, §14).
- Classes: `PasswordPolicyError`
- Functions: `validate_password,hash_user_password,estimate_strength,policy_description,needs_password_upgrade,verify_user_password,hash_secret,verify_secret,generate_client_secret`


### identity/services

**`backend/app/identity/services/identity_service.py`** — IdentityService — the single entry point for identity operations (SRS §15).
- Classes: `IdentityService`


### main.py

**`backend/app/main.py`** — FastAPI application entry point.
- Functions: `health_check`


### models

**`backend/app/models/abac.py`** — ABAC engine models (Phase 4.3.5 §21).
- Classes: `ABACPolicy,ABACPolicyVersion,AttributeDefinition,ABACEvaluation,ABACPolicyException`

**`backend/app/models/access_review.py`** — Access review campaigns (Phase 4.3.7 §14).
- Classes: `AccessReviewCampaign,AccessReviewItem`

**`backend/app/models/agent.py`** — Agent model - the AI agents whose actions are governed.
- Classes: `Agent`

**`backend/app/models/agent_action.py`** — AgentAction model - a single attempted action and its governance outcome.
- Classes: `AgentAction`

**`backend/app/models/agent_registry.py`** — Phase 5.1 - Enterprise Agent Registry, Definitions & Lifecycle: ownership
- Classes: `AgentOwnershipHistory,AgentLifecycleEvent,AgentValidationRun,AgentDuplicateMatch,AgentImportJob,AgentImportItem,AgentExportJob,AgentMigrationRecord`

**`backend/app/models/api_key.py`** — AgentApiKey model - hashed, rotatable API keys for agent authentication.
- Classes: `AgentApiKey`

**`backend/app/models/approval.py`** — Approval model - the human review attached to a pending agent action.
- Classes: `Approval,ApprovalComment`

**`backend/app/models/audit_log.py`** — AuditLog model - an append-only record of every significant event.
- Classes: `AuditLog`

**`backend/app/models/governance.py`** — Identity Governance & Administration models (Phase 4.3.8 §17).
- Classes: `SoDRule,GovernanceFinding,RemediationAction,GovernanceRiskScore,ComplianceReport,PrivilegedAccountReview`

**`backend/app/models/mixins.py`** — Reusable column mixins for ORM models.
- Classes: `UUIDPrimaryKeyMixin,TimestampMixin`

**`backend/app/models/organization.py`** — Organization model - the top-level tenant boundary.
- Classes: `Organization`

**`backend/app/models/organization_hierarchy.py`** — Enterprise organization hierarchy models (Phase 4.3.3 §5, §6, §10, §11).
- Classes: `BusinessUnit,Project,ResourceOwnership,Delegation`

**`backend/app/models/permission.py`** — Permission model - per-agent allow/deny rules for resource + action pairs.
- Classes: `Permission`

**`backend/app/models/policy.py`** — Policy model - database-driven governance rules evaluated per action.
- Classes: `Policy`

**`backend/app/models/rbac.py`** — Advanced RBAC models: roles, permission catalog and their join tables.
- Classes: `Role,RbacPermission,PermissionGroup,RolePermission,UserRole,RoleHierarchy,AuthorizationAudit,PermissionVersion,PermissionCache,AuthorizationDecision`

**`backend/app/models/resource_authorization.py`** — Resource-based authorization models (Phase 4.3.4 §15).
- Classes: `ProtectedResource,ResourceACLEntry,ResourceShare,OwnershipHistory,ResourceDelegation`

**`backend/app/models/runtime.py`** — Agent Runtime & Lifecycle Management models (Phase 5.0 §62).
- Classes: `AgentDefinition,AgentVersion,AgentReleaseChannel,AgentVersionSnapshot,AgentReleaseMetadata,AgentReleaseArtifact,AgentReleaseNote,AgentVersionStatusHistory,AgentDeployment,AgentExecution,ExecutionAttempt,ExecutionLock,Capability,AgentCapability,Tool,AgentTool,ToolCall,RuntimeEvent,DeploymentHealth,IdempotencyRecord,RuntimeApproval`

**`backend/app/models/user.py`** — User model - human operators (admins, reviewers, viewers).
- Classes: `User`


### runtime (Phase 5.0 core)

**`backend/app/runtime/routes.py`** — Agent Runtime & Lifecycle Management API (Phase 5.0 §66) — /api/v1/runtime.
- Functions: `dashboard,list_agents,register_agent,get_agent,update_agent,delete_agent,list_definitions,register_lifecycle_action,validate_agent,submit_for_approval,approve_agent,reject_agent,activate_agent,suspend_agent,resume_agent,deprecate_agent,archive_agent,restore_agent,retire_agent,get_ownership,transfer_ownership,ownership_history,get_identity,associate_identity,create_and_associate_identity,replace_identity,list_validations,get_validation,run_validation,test_schema,duplicate_check,duplicate_matches,review_duplicate,agent_lifecycle_events,agent_runtime_events,import_agents,get_import_job,get_import_items,export_agents,get_export_job,download_export,classify_legacy_agents,list_migration_records,list_versions,create_version,get_version,validate_version,approve_version,publish_version,deprecate_version,revoke_version,retire_version,get_version_snapshot,get_version_status_history,set_version_rollback_target,get_release_metadata,upsert_release_metadata,list_release_artifacts,add_release_artifact,list_release_notes,add_release_note,list_release_channels,compare_versions,version_readiness,list_deployments,create_deployment,get_deployment,deploy,suspend_deployment,resume_deployment,rollback_deployment,retire_deployment,submit_heartbeat,deployment_health,request_execution,request_self_execution,list_executions,get_execution,cancel_execution,retry_execution,replay_execution,execution_attempts,execution_tool_calls,execution_events,list_capabilities,create_capability,agent_capabilities,assign_capability,decide_capability,revoke_capability,list_tools,create_tool,agent_tools,assign_tool,decide_tool,revoke_tool,list_approvals,decide_approval,platform_health,list_workers,reap_stale_locks,kill_execution,kill_agent,kill_project,kill_organization,kill_platform`

**`backend/app/runtime/schemas.py`** — Pydantic schemas for the Agent Runtime API (Phase 5.0 §66).
- Classes: `AgentDefinitionRead,AgentVersionCreate,AgentVersionRead,DeploymentCreate,DeploymentRollbackRequest,DeploymentRead,DeploymentHealthRead,HeartbeatSubmit,ExecutionCreate,AgentSelfExecutionCreate,ExecutionRead,ExecutionAttemptRead,ToolCallRead,RuntimeEventRead,CapabilityCreate,CapabilityRead,AgentCapabilityAssign,AgentCapabilityRead,ToolCreate,ToolRead,AgentToolAssign,AgentToolRead,RuntimeApprovalDecision,RuntimeApprovalRead,KillSwitchRequest,RuntimeDashboardRead`

**`backend/app/runtime/services.py`** — Agent Runtime & Lifecycle Management services (Phase 5.0).
- Classes: `AgentRegistryService,AgentVersionService,DeploymentService,CapabilityService,ToolRegistryService,ModelGatewayError,ModelGatewayService,ToolGatewayService,PolicyResult,RuntimePolicyService,IdempotencyService,ExecutionRequestService,ExecutionWorkerService,RuntimeApprovalService,HealthMonitoringService,KillSwitchService,RuntimeDashboardService`


### runtime/registry (Phase 5.1)

**`backend/app/runtime/registry/duplicates.py`** — Phase 5.1 SRS §32-§33, §64 — exact + similarity duplicate detection.
- Classes: `AgentDuplicateDetectionService`

**`backend/app/runtime/registry/identity.py`** — Phase 5.1 SRS §11 — mandatory machine-identity association, with the
- Classes: `AgentIdentityAssociationService`

**`backend/app/runtime/registry/imports_exports.py`** — Phase 5.1 SRS §39-§45 — JSON/YAML/CSV agent import & export.
- Classes: `AgentImportService,AgentExportService`

**`backend/app/runtime/registry/migration.py`** — Phase 5.1 SRS §70-§73 — legacy-agent migration classification.
- Classes: `AgentMigrationService`

**`backend/app/runtime/registry/ownership.py`** — Phase 5.1 SRS §12-§13 — accountable ownership + immutable ownership history.
- Classes: `AgentOwnershipService`

**`backend/app/runtime/registry/schemas.py`** — Pydantic schemas for the Phase 5.1 Enterprise Agent Registry (SRS 5.1).
- Classes: `AgentDefinitionRegistryCreate,AgentRegistrationCreate,AgentRegistryUpdate,AgentRegistryRead,AgentLifecycleActionRequest,OwnershipTransferRequest,OwnershipHistoryRead,AgentOwnershipRead,IdentityAssociateRequest,IdentityCreateAndAssociateRequest,IdentityReplaceRequest,AgentIdentityRead,ValidationFinding,ValidationRunRead,SchemaTestRequest,SchemaTestResponse,DuplicateMatchRead,DuplicateReviewRequest,ImportRequest,ImportItemRead,ImportJobRead,ExportRequest,ExportJobRead,AgentLifecycleEventRead,MigrationRecordRead`

**`backend/app/runtime/registry/services.py`** — Phase 5.1 SRS §18-§21 — the full registry lifecycle state machine, and
- Classes: `AgentLifecycleService,AgentSearchService`

**`backend/app/runtime/registry/validation.py`** — Phase 5.1 SRS §25-§31 — the agent-registry validation-report engine.
- Classes: `ValidationFinding,AgentValidationService`
- Functions: `check_schema_dos_guards,validate_sample_payload,validate_entrypoint,check_url_for_embedded_credentials,has_blocking_findings`


### runtime/versioning (Phase 5.2 Part 1)

**`backend/app/runtime/versioning/artifacts.py`** — Phase 5.2 Part 1 SRS §27 — release artifact references.
- Classes: `ReleaseArtifactService`

**`backend/app/runtime/versioning/channels.py`** — Phase 5.2 Part 1 SRS §9, §26 — release channel catalog.
- Classes: `ReleaseChannelService`

**`backend/app/runtime/versioning/compare.py`** — Phase 5.2 Part 1 SRS §3 — version comparison.
- Classes: `VersionComparisonService`

**`backend/app/runtime/versioning/lineage.py`** — Phase 5.2 Part 1 SRS §17-18 — version lineage.
- Classes: `VersionLineageService`

**`backend/app/runtime/versioning/locking.py`** — Phase 5.2 Part 1 SRS §14, §21 — the shared immutability gate.
- Functions: `ensure_not_locked`

**`backend/app/runtime/versioning/notes.py`** — Phase 5.2 Part 1 SRS §28 — structured, categorized release notes.
- Classes: `ReleaseNoteService`

**`backend/app/runtime/versioning/readiness.py`** — Phase 5.2 Part 1 SRS §3, §30 — promotion readiness.
- Classes: `VersionReadinessService`

**`backend/app/runtime/versioning/release_metadata.py`** — Phase 5.2 Part 1 SRS §26, §28 — release metadata (name, justification,
- Classes: `ReleaseMetadataService`

**`backend/app/runtime/versioning/schemas.py`** — Pydantic schemas for the Phase 5.2 Part 1 versioning foundation.
- Classes: `ReleaseChannelRead,VersionSnapshotRead,ReleaseMetadataUpsert,ReleaseMetadataRead,ReleaseArtifactCreate,ReleaseArtifactRead,ReleaseNoteCreate,ReleaseNoteRead,VersionStatusHistoryRead,RollbackTargetRequest,RevokeVersionRequest,VersionComparisonRead,ReadinessCheckRead,VersionReadinessRead`

**`backend/app/runtime/versioning/semantic_version.py`** — Phase 5.2 Part 1 SRS §15-16 — semantic versioning rules.
- Classes: `SemanticVersionService`
- Functions: `parse_semver`

**`backend/app/runtime/versioning/snapshot.py`** — Phase 5.2 Part 1 SRS §10-14 — the snapshot builder.
- Classes: `SnapshotBuilderService`
- Functions: `build_snapshot,checksum_of`

**`backend/app/runtime/versioning/status_history.py`** — Phase 5.2 Part 1 SRS §19, §25 — the version lifecycle transition ledger.
- Functions: `record_status_change,list_status_history`


### schemas

**`backend/app/schemas/agent.py`** — Agent schemas. ``api_key_hash`` is never exposed; the plaintext API key is
- Classes: `AgentCreate,AgentUpdate,AgentStatusUpdate,AgentRead,AgentCreateResponse,AgentListResponse,AgentStats`

**`backend/app/schemas/agent_action.py`** — Agent action schemas - the heart of the governance workflow.
- Classes: `AgentActionCreate,AgentActionDecisionResponse,AgentActionRead`

**`backend/app/schemas/analytics.py`** — Analytics & AI Operations Center schemas (Phase 3 Part 3.6).
- Classes: `KpiMetric,FleetHealth,ActivityPoint,RiskBands,RiskTrendPoint,RiskGroup,RiskHeatmapRow,HighRiskAgent,RiskAnalytics,PerformanceMetrics,AgentRanking,PerformanceAnalytics,PolicyStat,PolicyAnalytics,ReviewerStat,HumanReviewAnalytics,CostItem,CostAnalytics,Insight,ReportRow,ReportSection,AnalyticsReport,AnalyticsOverview`

**`backend/app/schemas/api_key.py`** — Agent API key schemas. The raw key is returned only once at creation.
- Classes: `ApiKeyCreate,ApiKeyRead,ApiKeyCreateResponse`

**`backend/app/schemas/approval.py`** — Approval schemas.
- Classes: `ApprovalReviewRequest,ApprovalEscalateRequest,ApprovalAssignRequest,ApprovalCommentCreate,ApprovalCommentRead,ApprovalRead,ApprovalListItem,ApprovalAgentInfo,ApprovalActionInfo,ApprovalPolicyInfo,ApprovalRiskAssessment,ApprovalDetail,ApprovalTimelineEvent,ApprovalStatistics`

**`backend/app/schemas/audit.py`** — Audit & Compliance Center schemas (Phase 3 Part 3.5).
- Classes: `AuditEventListItem,AuditRelatedEvent,AuditEventDetail,AuditTimelineItem,AuditStatistics,AuditEventTypeInfo,AuditSecuritySummary,ComplianceMetric,AuditComplianceSummary`

**`backend/app/schemas/audit_log.py`** — Audit log schemas.
- Classes: `AuditLogRead`

**`backend/app/schemas/auth.py`** — Authentication schemas: registration, login and tokens.
- Classes: `RegisterRequest,LoginRequest,Token`

**`backend/app/schemas/dashboard.py`** — Dashboard schemas - aggregated metrics for the future frontend.
- Classes: `DashboardSummary,ActivityPoint,RiskTrendPoint,SystemHealth,RecentActionItem,PendingApprovalItem`

**`backend/app/schemas/organization.py`** — Organization schemas.
- Classes: `OrganizationCreate,OrganizationRead`

**`backend/app/schemas/permission.py`** — Permission schemas.
- Classes: `PermissionCreate,PermissionRead`

**`backend/app/schemas/policy.py`** — Policy schemas.
- Classes: `PolicyCreate,PolicyUpdate,PolicyRead,PolicyTestRequest,PolicyTestResult,PolicyTemplate`

**`backend/app/schemas/rbac.py`** — RBAC schemas: roles, permissions and role assignment.
- Classes: `RbacPermissionRead,RoleRead,RoleWithPermissions,AssignRoleRequest,MyPermissionsResponse`

**`backend/app/schemas/user.py`** — User schemas. Password hashes are never exposed in any response model.
- Classes: `UserCreate,UserRead`


### seed.py

**`backend/app/seed.py`** — Seed the database with demo data (Phase 1 + Phase 2).
- Functions: `seed`


### services

**`backend/app/services/agent_action_service.py`** — Agent action orchestration.
- Classes: `RequestContext,ProcessResult`
- Functions: `process_agent_action`

**`backend/app/services/analytics_service.py`** — Analytics & AI Operations Center service (Phase 3 Part 3.6).
- Functions: `kpis,fleet_health,activity,risk_analytics,performance_analytics,policy_analytics,human_review_analytics,cost_analytics,insights,report,overview`

**`backend/app/services/api_key_service.py`** — Agent API key service: issuing, authenticating and revoking keys.
- Functions: `issue_api_key,authenticate,list_keys,revoke_key`

**`backend/app/services/approval_service.py`** — Approval service - creating approval requests and processing reviews.
- Functions: `priority_for_risk,create_pending_approval,approve_action,reject_action,escalate_action,assign_reviewer,add_comment`

**`backend/app/services/audit_service.py`** — Audit service - the single entry point for writing audit log entries.
- Functions: `log_event`

**`backend/app/services/audit_view.py`** — Audit view service (Phase 3 Part 3.5).
- Functions: `humanize,category_of,severity_of,is_security_event,name_maps,actor_name,to_list_item,related_events,event_catalog,timeline_label`

**`backend/app/services/auth_service.py`** — Authentication service - registration and credential verification.
- Functions: `email_exists,register_organization,authenticate_user`

**`backend/app/services/decision_engine.py`** — Decision engine.
- Classes: `DecisionResult`
- Functions: `make_decision`

**`backend/app/services/notification_service.py`** — Notification service - email notifications via SMTP (Mailtrap in dev).
- Functions: `delivery_enabled,outbox_path,send_email,notify_approval_requested,notify_approval_decided,notify_agent_suspended,notify_policy_violation`

**`backend/app/services/permission_engine.py`** — Permission engine.
- Classes: `PermissionResult`
- Functions: `check_permission`

**`backend/app/services/policy_engine.py`** — Policy engine: evaluate database-driven policies against an action.
- Classes: `PolicyResult`
- Functions: `evaluate_conditions,evaluate_policies`

**`backend/app/services/rbac_service.py`** — Advanced RBAC service.
- Functions: `seed_rbac,get_user_permissions,user_has_permission`

**`backend/app/services/risk_engine.py`** — Risk engine V2.
- Classes: `RiskBreakdown`
- Functions: `calculate_risk_breakdown,calculate_risk_score`


### frontend/src (summary — file counts only, verified via `find`)

Services (`frontend/src/services/*.ts`, one per backend domain): `abacService.ts`, `adminService.ts`, `apiClient.ts`, `approvalService.ts`, `auditService.ts`, `authService.ts`, `authorizationService.ts`, `credentialService.ts`, `dashboardService.ts`, `envelope.ts`, `governanceService.ts`, `hierarchyService.ts`, `index.ts`, `protectionService.ts`, `recoveryService.ts`, `registrationService.ts`, `resourceAuthzService.ts`, `runtimeService.ts`, `systemService.ts`, `tokenRefresh.ts`, `userService.ts`.

Modules (`frontend/src/modules/*`, `.ts`/`.tsx` file count excluding tests):

| Module | Files |
|---|---|
| `abac` | 13 |
| `admin` | 6 |
| `agents` | 25 |
| `analytics` | 40 |
| `approvals` | 39 |
| `audit` | 38 |
| `authorization` | 7 |
| `governance` | 15 |
| `hierarchy` | 8 |
| `identity` | 28 |
| `policies` | 36 |
| `protection` | 7 |
| `resources` | 8 |
| `runtime` | 19 |
| `security` | 11 |

## 5. API Surface

Extracted by importing the live `app.main:app` FastAPI object and iterating `app.routes` — every method, path, and (where the endpoint depends on `require_permission(code)`) the exact permission code, read out of that dependency's closure. This is the actual routing table the server would serve, not a manual transcription of 36 separate router files. `/docs`, `/openapi.json`, `/redoc` (FastAPI/Swagger-internal, not application routes) are excluded from the count and table below. A permission of `—` means the route has no `require_permission` dependency (either public — e.g. `/auth/login`, `/auth/register` — or gated by a different mechanism, e.g. API-key auth via `get_current_agent`, or session/JWT auth alone via `get_current_user` with no RBAC check).

Grouped by top-level path prefix for readability (444 raw route entries total; 440 after excluding the 4 framework-internal ones).

Total application routes (excluding /docs, /openapi.json, /redoc): **440**

#### `/agent-actions`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/agent-actions` | `—` | `app.api.routes.agent_actions::list_agent_actions` |
| POST | `/agent-actions` | `—` | `app.api.routes.agent_actions::submit_agent_action` |
| GET | `/agent-actions/{agent_action_id}` | `—` | `app.api.routes.agent_actions::get_agent_action` |

#### `/agents`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/agents` | `—` | `app.api.routes.agents::list_agents` |
| POST | `/agents` | `—` | `app.api.routes.agents::create_agent` |
| DELETE | `/agents/{agent_id}` | `—` | `app.api.routes.agents::delete_agent` |
| GET | `/agents/{agent_id}` | `—` | `app.api.routes.agents::get_agent` |
| PUT | `/agents/{agent_id}` | `—` | `app.api.routes.agents::update_agent` |
| GET | `/agents/{agent_id}/api-keys` | `agent.view` | `app.api.routes.api_keys::list_api_keys` |
| POST | `/agents/{agent_id}/generate-api-key` | `apikey.create` | `app.api.routes.api_keys::generate_api_key` |
| GET | `/agents/{agent_id}/stats` | `—` | `app.api.routes.agents::agent_stats` |
| PATCH | `/agents/{agent_id}/status` | `—` | `app.api.routes.agents::update_agent_status` |

#### `/analytics`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/analytics/activity` | `analytics.view` | `app.api.routes.analytics::analytics_activity` |
| GET | `/analytics/cost` | `analytics.view` | `app.api.routes.analytics::analytics_cost` |
| GET | `/analytics/fleet-health` | `analytics.view` | `app.api.routes.analytics::analytics_fleet_health` |
| GET | `/analytics/insights` | `analytics.view` | `app.api.routes.analytics::analytics_insights` |
| GET | `/analytics/kpis` | `analytics.view` | `app.api.routes.analytics::analytics_kpis` |
| GET | `/analytics/overview` | `analytics.view` | `app.api.routes.analytics::analytics_overview` |
| GET | `/analytics/performance` | `analytics.view` | `app.api.routes.analytics::analytics_performance` |
| GET | `/analytics/policies` | `analytics.view` | `app.api.routes.analytics::analytics_policies` |
| GET | `/analytics/reports` | `analytics.view` | `app.api.routes.analytics::analytics_reports` |
| GET | `/analytics/review` | `analytics.view` | `app.api.routes.analytics::analytics_review` |
| GET | `/analytics/risk` | `analytics.view` | `app.api.routes.analytics::analytics_risk` |

#### `/api-keys`

| Method | Path | Permission | Handler |
|---|---|---|---|
| POST | `/api-keys/{key_id}/revoke` | `apikey.revoke` | `app.api.routes.api_keys::revoke_api_key` |

#### `/api/v1/admin`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/admin/access-reviews` | `admin.reviews.manage` | `app.authorization.admin.routes::list_campaigns` |
| POST | `/api/v1/admin/access-reviews` | `admin.reviews.manage` | `app.authorization.admin.routes::create_campaign` |
| GET | `/api/v1/admin/access-reviews/{campaign_id}` | `admin.reviews.manage` | `app.authorization.admin.routes::get_campaign` |
| PUT | `/api/v1/admin/access-reviews/{campaign_id}` | `admin.reviews.manage` | `app.authorization.admin.routes::update_campaign` |
| POST | `/api/v1/admin/access-reviews/{campaign_id}/activate` | `admin.reviews.manage` | `app.authorization.admin.routes::activate_campaign` |
| POST | `/api/v1/admin/access-reviews/{campaign_id}/archive` | `admin.reviews.manage` | `app.authorization.admin.routes::archive_campaign` |
| POST | `/api/v1/admin/access-reviews/{campaign_id}/complete` | `admin.reviews.manage` | `app.authorization.admin.routes::complete_campaign` |
| GET | `/api/v1/admin/access-reviews/{campaign_id}/export` | `admin.reviews.manage` | `app.authorization.admin.routes::export_campaign` |
| GET | `/api/v1/admin/access-reviews/{campaign_id}/items` | `admin.reviews.manage` | `app.authorization.admin.routes::campaign_items` |
| POST | `/api/v1/admin/access-reviews/{campaign_id}/items/{item_id}/decide` | `admin.reviews.manage` | `app.authorization.admin.routes::decide_item` |
| POST | `/api/v1/admin/access-reviews/{campaign_id}/schedule` | `admin.reviews.manage` | `app.authorization.admin.routes::schedule_campaign` |
| GET | `/api/v1/admin/analytics` | `admin.analytics.view` | `app.authorization.admin.routes::analytics` |
| GET | `/api/v1/admin/authorization-decisions` | `admin.audit.view` | `app.authorization.admin.routes::authorization_decisions` |
| GET | `/api/v1/admin/dashboard` | `admin.dashboard.view` | `app.authorization.admin.routes::dashboard` |
| GET | `/api/v1/admin/organizations` | `admin.organizations.manage` | `app.authorization.admin.routes::organization_tree` |
| GET | `/api/v1/admin/permissions` | `admin.permissions.manage` | `app.authorization.admin.routes::list_permissions` |
| GET | `/api/v1/admin/policies` | `admin.policies.manage` | `app.authorization.admin.routes::list_policies` |
| POST | `/api/v1/admin/policies` | `admin.policies.manage` | `app.authorization.admin.routes::create_policy` |
| DELETE | `/api/v1/admin/policies/{policy_id}` | `admin.policies.manage` | `app.authorization.admin.routes::delete_policy` |
| PUT | `/api/v1/admin/policies/{policy_id}` | `admin.policies.manage` | `app.authorization.admin.routes::update_policy` |
| POST | `/api/v1/admin/policy-simulator` | `admin.simulator.use` | `app.authorization.admin.routes::policy_simulator` |
| GET | `/api/v1/admin/resources` | `admin.resources.manage` | `app.authorization.admin.routes::list_resources` |
| GET | `/api/v1/admin/roles` | `admin.roles.manage` | `app.authorization.admin.routes::list_roles` |
| POST | `/api/v1/admin/roles` | `admin.roles.manage` | `app.authorization.admin.routes::create_role` |
| DELETE | `/api/v1/admin/roles/{role_id}` | `admin.roles.manage` | `app.authorization.admin.routes::delete_role` |
| PUT | `/api/v1/admin/roles/{role_id}` | `admin.roles.manage` | `app.authorization.admin.routes::update_role` |

#### `/api/v1/auth`

| Method | Path | Permission | Handler |
|---|---|---|---|
| POST | `/api/v1/auth/admin/reset-password` | `credential.reset` | `app.identity.credentials.routes::admin_reset_password` |
| POST | `/api/v1/auth/change-email` | `—` | `app.identity.recovery.routes::change_email` |
| POST | `/api/v1/auth/change-password` | `—` | `app.identity.credentials.routes::change_password` |
| GET | `/api/v1/auth/devices` | `—` | `app.identity.auth.routes::list_devices` |
| POST | `/api/v1/auth/devices/{device_id}/block` | `—` | `app.identity.auth.routes::block_device` |
| POST | `/api/v1/auth/devices/{device_id}/trust` | `—` | `app.identity.auth.routes::trust_device` |
| POST | `/api/v1/auth/forgot-password` | `—` | `app.identity.recovery.routes::forgot_password` |
| POST | `/api/v1/auth/login` | `—` | `app.identity.auth.routes::login` |
| POST | `/api/v1/auth/logout` | `—` | `app.identity.auth.routes::logout` |
| GET | `/api/v1/auth/me` | `—` | `app.identity.auth.routes::me` |
| POST | `/api/v1/auth/mfa/verify` | `—` | `app.identity.auth.routes::mfa_verify` |
| GET | `/api/v1/auth/password-expiration` | `—` | `app.identity.credentials.routes::password_expiration` |
| GET | `/api/v1/auth/password-policy` | `—` | `app.identity.credentials.routes::password_policy` |
| POST | `/api/v1/auth/refresh` | `—` | `app.identity.auth.routes::refresh` |
| POST | `/api/v1/auth/register` | `—` | `app.identity.api.routes.registration::register_from_invitation` |
| POST | `/api/v1/auth/register/self` | `—` | `app.identity.api.routes.registration::self_register` |
| POST | `/api/v1/auth/resend-verification` | `—` | `app.identity.api.routes.registration::resend_verification` |
| POST | `/api/v1/auth/reset-password` | `—` | `app.identity.recovery.routes::reset_password` |
| GET | `/api/v1/auth/security-events` | `—` | `app.identity.auth.routes::my_security_events` |
| GET | `/api/v1/auth/sessions` | `—` | `app.identity.auth.routes::list_sessions` |
| DELETE | `/api/v1/auth/sessions/{session_id}` | `—` | `app.identity.auth.routes::delete_session` |
| GET | `/api/v1/auth/sessions/{session_id}` | `—` | `app.identity.auth.routes::get_session` |
| POST | `/api/v1/auth/sessions/{session_id}/revoke` | `—` | `app.identity.auth.routes::revoke_session` |
| POST | `/api/v1/auth/validate-password` | `—` | `app.identity.credentials.routes::validate_password` |
| POST | `/api/v1/auth/verify-email` | `—` | `app.identity.api.routes.registration::verify_email` |
| POST | `/api/v1/auth/verify-new-email` | `—` | `app.identity.recovery.routes::verify_new_email` |

#### `/api/v1/authorization`

| Method | Path | Permission | Handler |
|---|---|---|---|
| POST | `/api/v1/authorization/abac/evaluate` | `—` | `app.authorization.abac.routes::evaluate` |
| GET | `/api/v1/authorization/abac/evaluations` | `authorization.abac.audit` | `app.authorization.abac.routes::list_evaluations` |
| GET | `/api/v1/authorization/abac/evaluations/{evaluation_id}` | `authorization.abac.audit` | `app.authorization.abac.routes::get_evaluation` |
| GET | `/api/v1/authorization/abac/metrics` | `authorization.abac.view` | `app.authorization.abac.routes::abac_metrics` |
| GET | `/api/v1/authorization/abac/policies` | `authorization.abac.view` | `app.authorization.abac.routes::list_policies` |
| POST | `/api/v1/authorization/abac/policies` | `authorization.abac.create` | `app.authorization.abac.routes::create_policy` |
| DELETE | `/api/v1/authorization/abac/policies/{policy_id}` | `authorization.abac.archive` | `app.authorization.abac.routes::delete_policy` |
| GET | `/api/v1/authorization/abac/policies/{policy_id}` | `authorization.abac.view` | `app.authorization.abac.routes::get_policy` |
| PUT | `/api/v1/authorization/abac/policies/{policy_id}` | `authorization.abac.update` | `app.authorization.abac.routes::update_policy` |
| POST | `/api/v1/authorization/abac/policies/{policy_id}/archive` | `authorization.abac.archive` | `app.authorization.abac.routes::archive_policy` |
| POST | `/api/v1/authorization/abac/policies/{policy_id}/clone` | `authorization.abac.create` | `app.authorization.abac.routes::clone_policy` |
| POST | `/api/v1/authorization/abac/policies/{policy_id}/disable` | `authorization.abac.disable` | `app.authorization.abac.routes::disable_policy` |
| POST | `/api/v1/authorization/abac/policies/{policy_id}/publish` | `authorization.abac.publish` | `app.authorization.abac.routes::publish_policy` |
| POST | `/api/v1/authorization/abac/policies/{policy_id}/rollback/{version}` | `authorization.abac.publish` | `app.authorization.abac.routes::rollback_policy` |
| POST | `/api/v1/authorization/abac/policies/{policy_id}/simulate` | `authorization.abac.simulate` | `app.authorization.abac.routes::simulate_policy` |
| POST | `/api/v1/authorization/abac/policies/{policy_id}/validate` | `authorization.abac.update` | `app.authorization.abac.routes::validate_policy` |
| GET | `/api/v1/authorization/abac/policies/{policy_id}/versions` | `authorization.abac.view` | `app.authorization.abac.routes::list_versions` |
| GET | `/api/v1/authorization/abac/policies/{policy_id}/versions/{version}` | `authorization.abac.view` | `app.authorization.abac.routes::get_version` |
| POST | `/api/v1/authorization/abac/simulate` | `authorization.abac.simulate` | `app.authorization.abac.routes::simulate` |
| GET | `/api/v1/authorization/attributes` | `authorization.abac.view` | `app.authorization.abac.routes::list_attributes` |
| POST | `/api/v1/authorization/attributes` | `authorization.attribute.manage` | `app.authorization.abac.routes::create_attribute` |
| PUT | `/api/v1/authorization/attributes/{definition_id}` | `authorization.attribute.manage` | `app.authorization.abac.routes::update_attribute` |
| GET | `/api/v1/authorization/attributes/{name}` | `authorization.abac.view` | `app.authorization.abac.routes::get_attribute` |
| GET | `/api/v1/authorization/audit` | `role.view` | `app.authorization.routes::list_authorization_audit` |
| POST | `/api/v1/authorization/check` | `—` | `app.authorization.routes::authorization_check` |
| GET | `/api/v1/authorization/exceptions` | `authorization.exception.manage` | `app.authorization.abac.routes::list_exceptions` |
| POST | `/api/v1/authorization/exceptions` | `authorization.exception.manage` | `app.authorization.abac.routes::create_exception` |
| DELETE | `/api/v1/authorization/exceptions/{exception_id}` | `authorization.exception.manage` | `app.authorization.abac.routes::revoke_exception` |
| GET | `/api/v1/authorization/middleware/metrics` | `authorization.abac.view` | `app.authorization.abac.routes::middleware_metrics` |

#### `/api/v1/business-units`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/business-units` | `organization.view` | `app.authorization.hierarchy.routes::list_business_units` |
| POST | `/api/v1/business-units` | `organization.manage` | `app.authorization.hierarchy.routes::create_business_unit` |
| DELETE | `/api/v1/business-units/{bu_id}` | `organization.manage` | `app.authorization.hierarchy.routes::delete_business_unit` |
| GET | `/api/v1/business-units/{bu_id}` | `organization.view` | `app.authorization.hierarchy.routes::get_business_unit` |
| PUT | `/api/v1/business-units/{bu_id}` | `organization.manage` | `app.authorization.hierarchy.routes::update_business_unit` |

#### `/api/v1/delegations`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/delegations` | `organization.view` | `app.authorization.hierarchy.routes::list_delegations` |
| POST | `/api/v1/delegations` | `organization.manage` | `app.authorization.hierarchy.routes::create_delegation` |
| DELETE | `/api/v1/delegations/{delegation_id}` | `organization.manage` | `app.authorization.hierarchy.routes::revoke_delegation` |

#### `/api/v1/departments`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/departments` | `organization.view` | `app.authorization.hierarchy.routes::list_departments` |
| POST | `/api/v1/departments` | `organization.manage` | `app.authorization.hierarchy.routes::create_department` |
| DELETE | `/api/v1/departments/{dept_id}` | `organization.manage` | `app.authorization.hierarchy.routes::delete_department` |
| GET | `/api/v1/departments/{dept_id}` | `organization.view` | `app.authorization.hierarchy.routes::get_department` |
| PUT | `/api/v1/departments/{dept_id}` | `organization.manage` | `app.authorization.hierarchy.routes::update_department` |

#### `/api/v1/governance`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/governance/analytics` | `governance.analytics.view` | `app.governance.routes::analytics` |
| GET | `/api/v1/governance/campaigns` | `governance.certification.manage` | `app.governance.routes::list_campaigns` |
| POST | `/api/v1/governance/campaigns` | `governance.certification.manage` | `app.governance.routes::create_campaign` |
| GET | `/api/v1/governance/campaigns/{campaign_id}` | `governance.certification.manage` | `app.governance.routes::get_campaign` |
| PUT | `/api/v1/governance/campaigns/{campaign_id}` | `governance.certification.manage` | `app.governance.routes::update_campaign` |
| POST | `/api/v1/governance/campaigns/{campaign_id}/archive` | `governance.certification.manage` | `app.governance.routes::archive_campaign` |
| POST | `/api/v1/governance/campaigns/{campaign_id}/complete` | `governance.certification.manage` | `app.governance.routes::complete_campaign` |
| GET | `/api/v1/governance/campaigns/{campaign_id}/export` | `governance.certification.manage` | `app.governance.routes::export_campaign` |
| GET | `/api/v1/governance/campaigns/{campaign_id}/items` | `governance.certification.manage` | `app.governance.routes::campaign_items` |
| POST | `/api/v1/governance/campaigns/{campaign_id}/launch` | `governance.certification.manage` | `app.governance.routes::launch_campaign` |
| GET | `/api/v1/governance/compliance/frameworks` | `governance.compliance.view` | `app.governance.routes::compliance_frameworks` |
| GET | `/api/v1/governance/compliance/reports` | `governance.compliance.view` | `app.governance.routes::list_compliance_reports` |
| POST | `/api/v1/governance/compliance/reports` | `governance.compliance.view` | `app.governance.routes::generate_compliance_report` |
| GET | `/api/v1/governance/compliance/reports/{report_id}` | `governance.compliance.view` | `app.governance.routes::get_compliance_report` |
| GET | `/api/v1/governance/dashboard` | `governance.dashboard.view` | `app.governance.routes::dashboard` |
| GET | `/api/v1/governance/findings` | `governance.findings.manage` | `app.governance.routes::list_findings` |
| POST | `/api/v1/governance/findings/{finding_id}/remediate` | `governance.findings.manage` | `app.governance.routes::remediate_finding` |
| GET | `/api/v1/governance/orphaned-accounts` | `governance.orphaned.manage` | `app.governance.routes::list_orphaned_accounts` |
| POST | `/api/v1/governance/orphaned-accounts/scan` | `governance.orphaned.manage` | `app.governance.routes::scan_orphaned_accounts` |
| GET | `/api/v1/governance/privileged-accounts` | `governance.privileged.manage` | `app.governance.routes::list_privileged_accounts` |
| GET | `/api/v1/governance/privileged-accounts/reviews` | `governance.privileged.manage` | `app.governance.routes::list_privileged_reviews` |
| POST | `/api/v1/governance/privileged-accounts/reviews` | `governance.privileged.manage` | `app.governance.routes::request_privileged_review` |
| POST | `/api/v1/governance/privileged-accounts/reviews/{review_id}/decide` | `governance.privileged.manage` | `app.governance.routes::decide_privileged_review` |
| GET | `/api/v1/governance/remediation-actions` | `governance.remediation.manage` | `app.governance.routes::list_remediation_actions` |
| POST | `/api/v1/governance/remediation-actions` | `governance.remediation.manage` | `app.governance.routes::create_remediation_action` |
| POST | `/api/v1/governance/remediation-actions/{action_id}/execute` | `governance.remediation.manage` | `app.governance.routes::execute_remediation_action` |
| POST | `/api/v1/governance/reviews/{item_id}/approve` | `governance.certification.manage` | `app.governance.routes::approve_review` |
| POST | `/api/v1/governance/reviews/{item_id}/delegate` | `governance.certification.manage` | `app.governance.routes::delegate_review` |
| POST | `/api/v1/governance/reviews/{item_id}/modify` | `governance.certification.manage` | `app.governance.routes::modify_review` |
| POST | `/api/v1/governance/reviews/{item_id}/revoke` | `governance.certification.manage` | `app.governance.routes::revoke_review` |
| GET | `/api/v1/governance/risk-scores` | `governance.analytics.view` | `app.governance.routes::list_risk_scores` |
| POST | `/api/v1/governance/risk-scores/recalculate` | `governance.analytics.view` | `app.governance.routes::recalculate_risk_scores` |
| GET | `/api/v1/governance/sod-findings` | `governance.sod.view` | `app.governance.routes::list_sod_findings` |
| POST | `/api/v1/governance/sod-findings/scan` | `governance.sod.manage` | `app.governance.routes::scan_sod` |
| GET | `/api/v1/governance/sod-rules` | `governance.sod.view` | `app.governance.routes::list_sod_rules` |
| POST | `/api/v1/governance/sod-rules` | `governance.sod.manage` | `app.governance.routes::create_sod_rule` |
| PUT | `/api/v1/governance/sod-rules/{rule_id}` | `governance.sod.manage` | `app.governance.routes::update_sod_rule` |
| POST | `/api/v1/governance/sod-rules/{rule_id}/activate` | `governance.sod.manage` | `app.governance.routes::activate_sod_rule` |
| POST | `/api/v1/governance/sod-rules/{rule_id}/disable` | `governance.sod.manage` | `app.governance.routes::disable_sod_rule` |
| GET | `/api/v1/governance/toxic-findings` | `governance.sod.view` | `app.governance.routes::list_toxic_findings` |
| POST | `/api/v1/governance/toxic-findings/scan` | `governance.toxic.manage` | `app.governance.routes::scan_toxic` |
| GET | `/api/v1/governance/toxic-rules` | `governance.sod.view` | `app.governance.routes::list_toxic_rules` |
| POST | `/api/v1/governance/toxic-rules` | `governance.toxic.manage` | `app.governance.routes::create_toxic_rule` |
| POST | `/api/v1/governance/toxic-rules/{rule_id}/activate` | `governance.toxic.manage` | `app.governance.routes::activate_toxic_rule` |
| POST | `/api/v1/governance/toxic-rules/{rule_id}/disable` | `governance.toxic.manage` | `app.governance.routes::disable_toxic_rule` |

#### `/api/v1/hierarchy`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/hierarchy/tree` | `organization.view` | `app.authorization.hierarchy.routes::hierarchy_tree` |

#### `/api/v1/identity`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/identity/agent-identities` | `agent.view` | `app.identity.api.routes.agent_identities::list_agent_identities` |
| POST | `/api/v1/identity/agent-identities` | `agent.create` | `app.identity.api.routes.agent_identities::create_agent_identity` |
| GET | `/api/v1/identity/agent-identities/{identity_id}` | `agent.view` | `app.identity.api.routes.agent_identities::get_agent_identity` |
| POST | `/api/v1/identity/agent-identities/{identity_id}/status` | `agent.create` | `app.identity.api.routes.agent_identities::transition_agent_identity` |
| GET | `/api/v1/identity/departments` | `user.view` | `app.identity.api.routes.departments::list_departments` |
| POST | `/api/v1/identity/departments` | `user.create` | `app.identity.api.routes.departments::create_department` |
| GET | `/api/v1/identity/departments/{department_id}` | `user.view` | `app.identity.api.routes.departments::get_department` |
| GET | `/api/v1/identity/email-delivery` | `invitation.view` | `app.identity.api.routes.invitations::email_delivery_status` |
| GET | `/api/v1/identity/external-clients` | `user.view` | `app.identity.api.routes.external_clients::list_external_clients` |
| POST | `/api/v1/identity/external-clients` | `user.create` | `app.identity.api.routes.external_clients::create_external_client` |
| GET | `/api/v1/identity/external-clients/{client_id}` | `user.view` | `app.identity.api.routes.external_clients::get_external_client` |
| POST | `/api/v1/identity/external-clients/{client_id}/status` | `user.create` | `app.identity.api.routes.external_clients::transition_external_client` |
| GET | `/api/v1/identity/invitations` | `invitation.view` | `app.identity.api.routes.invitations::list_invitations` |
| POST | `/api/v1/identity/invitations` | `invitation.manage` | `app.identity.api.routes.invitations::create_invitation` |
| POST | `/api/v1/identity/invitations/cancel` | `invitation.manage` | `app.identity.api.routes.invitations::cancel_invitation` |
| POST | `/api/v1/identity/invitations/resend` | `invitation.manage` | `app.identity.api.routes.invitations::resend_invitation` |
| GET | `/api/v1/identity/invitations/{token}` | `—` | `app.identity.api.routes.invitations::preview_invitation` |
| GET | `/api/v1/identity/organizations` | `user.view` | `app.identity.api.routes.organizations::list_organizations` |
| GET | `/api/v1/identity/organizations/{organization_id}` | `user.view` | `app.identity.api.routes.organizations::get_organization` |
| POST | `/api/v1/identity/organizations/{organization_id}/status` | `user.create` | `app.identity.api.routes.organizations::transition_organization` |
| GET | `/api/v1/identity/roles` | `user.view` | `app.identity.api.routes.roles::list_roles` |
| GET | `/api/v1/identity/security-events` | `session.view` | `app.identity.api.routes.sessions::list_security_events` |
| GET | `/api/v1/identity/security-events/types` | `session.view` | `app.identity.api.routes.sessions::list_security_event_types` |
| GET | `/api/v1/identity/service-accounts` | `user.view` | `app.identity.api.routes.service_accounts::list_service_accounts` |
| POST | `/api/v1/identity/service-accounts` | `user.create` | `app.identity.api.routes.service_accounts::create_service_account` |
| GET | `/api/v1/identity/service-accounts/{account_id}` | `user.view` | `app.identity.api.routes.service_accounts::get_service_account` |
| POST | `/api/v1/identity/service-accounts/{account_id}/status` | `user.create` | `app.identity.api.routes.service_accounts::transition_service_account` |
| GET | `/api/v1/identity/sessions` | `session.view` | `app.identity.api.routes.sessions::list_sessions` |
| GET | `/api/v1/identity/sessions/{session_id}` | `session.view` | `app.identity.api.routes.sessions::get_session` |
| GET | `/api/v1/identity/sessions/{session_id}/events` | `session.view` | `app.identity.api.routes.sessions::list_session_events` |
| POST | `/api/v1/identity/sessions/{session_id}/revoke` | `session.revoke` | `app.identity.api.routes.sessions::admin_revoke_session` |
| GET | `/api/v1/identity/users` | `user.view` | `app.identity.api.routes.users::list_users` |
| POST | `/api/v1/identity/users` | `user.create` | `app.identity.api.routes.users::create_user` |
| GET | `/api/v1/identity/users/{user_id}` | `user.view` | `app.identity.api.routes.users::get_user` |
| POST | `/api/v1/identity/users/{user_id}/activate` | `user.create` | `app.identity.api.routes.users::activate_user` |
| POST | `/api/v1/identity/users/{user_id}/approve` | `user.create` | `app.identity.api.routes.invitations::approve_registration` |
| GET | `/api/v1/identity/users/{user_id}/devices` | `session.view` | `app.identity.api.routes.sessions::list_user_devices` |
| POST | `/api/v1/identity/users/{user_id}/sessions/revoke-all` | `session.revoke` | `app.identity.api.routes.sessions::admin_revoke_all_sessions` |
| POST | `/api/v1/identity/users/{user_id}/status` | `user.create` | `app.identity.api.routes.users::transition_user` |
| POST | `/api/v1/identity/users/{user_id}/suspend` | `user.create` | `app.identity.api.routes.users::suspend_user` |

#### `/api/v1/organizations`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/organizations` | `organization.view` | `app.authorization.hierarchy.routes::list_organizations` |
| POST | `/api/v1/organizations` | `organization.manage` | `app.authorization.hierarchy.routes::create_organization` |
| DELETE | `/api/v1/organizations/{org_id}` | `organization.manage` | `app.authorization.hierarchy.routes::delete_organization` |
| GET | `/api/v1/organizations/{org_id}` | `organization.view` | `app.authorization.hierarchy.routes::get_organization` |
| PUT | `/api/v1/organizations/{org_id}` | `organization.manage` | `app.authorization.hierarchy.routes::update_organization` |

#### `/api/v1/permission-groups`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/permission-groups` | `role.view` | `app.authorization.routes::list_permission_groups` |

#### `/api/v1/permissions`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/permissions` | `role.view` | `app.authorization.routes::list_permissions` |
| POST | `/api/v1/permissions` | `role.manage` | `app.authorization.routes::create_permission` |
| DELETE | `/api/v1/permissions/{permission_id}` | `role.manage` | `app.authorization.routes::delete_permission` |
| PUT | `/api/v1/permissions/{permission_id}` | `role.manage` | `app.authorization.routes::update_permission` |

#### `/api/v1/projects`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/projects` | `organization.view` | `app.authorization.hierarchy.routes::list_projects` |
| POST | `/api/v1/projects` | `organization.manage` | `app.authorization.hierarchy.routes::create_project` |
| DELETE | `/api/v1/projects/{project_id}` | `organization.manage` | `app.authorization.hierarchy.routes::delete_project` |
| GET | `/api/v1/projects/{project_id}` | `organization.view` | `app.authorization.hierarchy.routes::get_project` |
| PUT | `/api/v1/projects/{project_id}` | `organization.manage` | `app.authorization.hierarchy.routes::update_project` |

#### `/api/v1/resource-ownership`

| Method | Path | Permission | Handler |
|---|---|---|---|
| POST | `/api/v1/resource-ownership` | `organization.manage` | `app.authorization.hierarchy.routes::assign_ownership` |
| POST | `/api/v1/resource-ownership/transfer` | `organization.manage` | `app.authorization.hierarchy.routes::transfer_ownership` |
| GET | `/api/v1/resource-ownership/{resource_type}/{resource_id}` | `organization.view` | `app.authorization.hierarchy.routes::get_ownership` |

#### `/api/v1/resources`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/resources` | `—` | `app.authorization.resources.routes::list_resources` |
| POST | `/api/v1/resources` | `—` | `app.authorization.resources.routes::register_resource` |
| GET | `/api/v1/resources/types` | `—` | `app.authorization.resources.routes::list_resource_types` |
| GET | `/api/v1/resources/{resource_pk}` | `—` | `app.authorization.resources.routes::get_resource` |
| PUT | `/api/v1/resources/{resource_pk}` | `—` | `app.authorization.resources.routes::update_resource` |
| GET | `/api/v1/resources/{resource_pk}/acl` | `—` | `app.authorization.resources.routes::list_acl` |
| POST | `/api/v1/resources/{resource_pk}/acl` | `—` | `app.authorization.resources.routes::add_acl_entry` |
| DELETE | `/api/v1/resources/{resource_pk}/acl/{acl_id}` | `—` | `app.authorization.resources.routes::delete_acl_entry` |
| PUT | `/api/v1/resources/{resource_pk}/acl/{acl_id}` | `—` | `app.authorization.resources.routes::update_acl_entry` |
| POST | `/api/v1/resources/{resource_pk}/authorize` | `—` | `app.authorization.resources.routes::authorize` |
| POST | `/api/v1/resources/{resource_pk}/delegate` | `—` | `app.authorization.resources.routes::delegate_resource` |
| DELETE | `/api/v1/resources/{resource_pk}/delegate/{delegation_id}` | `—` | `app.authorization.resources.routes::revoke_delegation` |
| GET | `/api/v1/resources/{resource_pk}/delegations` | `—` | `app.authorization.resources.routes::list_delegations` |
| GET | `/api/v1/resources/{resource_pk}/owner` | `—` | `app.authorization.resources.routes::get_owner` |
| GET | `/api/v1/resources/{resource_pk}/ownership-history` | `—` | `app.authorization.resources.routes::ownership_history` |
| PUT | `/api/v1/resources/{resource_pk}/policy` | `—` | `app.authorization.resources.routes::set_policy` |
| POST | `/api/v1/resources/{resource_pk}/share` | `—` | `app.authorization.resources.routes::share_resource` |
| DELETE | `/api/v1/resources/{resource_pk}/share/{share_id}` | `—` | `app.authorization.resources.routes::revoke_share` |
| PUT | `/api/v1/resources/{resource_pk}/share/{share_id}` | `—` | `app.authorization.resources.routes::update_share` |
| GET | `/api/v1/resources/{resource_pk}/shares` | `—` | `app.authorization.resources.routes::list_shares` |
| POST | `/api/v1/resources/{resource_pk}/transfer-ownership` | `—` | `app.authorization.resources.routes::transfer_ownership` |

#### `/api/v1/role-assignments`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/role-assignments` | `role.view` | `app.authorization.routes::list_role_assignments` |
| POST | `/api/v1/role-assignments` | `role.assign` | `app.authorization.routes::create_role_assignment` |
| DELETE | `/api/v1/role-assignments/{assignment_id}` | `role.assign` | `app.authorization.routes::delete_role_assignment` |

#### `/api/v1/role-hierarchy`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/role-hierarchy` | `role.view` | `app.authorization.routes::list_role_hierarchy` |
| POST | `/api/v1/role-hierarchy` | `role.manage` | `app.authorization.routes::create_role_hierarchy` |
| DELETE | `/api/v1/role-hierarchy/{edge_id}` | `role.manage` | `app.authorization.routes::delete_role_hierarchy` |

#### `/api/v1/roles`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/roles` | `role.view` | `app.authorization.routes::list_roles` |
| POST | `/api/v1/roles` | `role.manage` | `app.authorization.routes::create_role` |
| DELETE | `/api/v1/roles/{role_id}` | `role.manage` | `app.authorization.routes::delete_role` |
| GET | `/api/v1/roles/{role_id}` | `role.view` | `app.authorization.routes::get_role` |
| PUT | `/api/v1/roles/{role_id}` | `role.manage` | `app.authorization.routes::update_role` |
| GET | `/api/v1/roles/{role_id}/effective-permissions` | `role.view` | `app.authorization.routes::role_effective_permissions` |

#### `/api/v1/runtime`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/runtime/agents` | `runtime.agent.view` | `app.runtime.routes::list_agents` |
| POST | `/api/v1/runtime/agents` | `runtime.agent.create` | `app.runtime.routes::register_agent` |
| POST | `/api/v1/runtime/agents/export` | `runtime.agent.export` | `app.runtime.routes::export_agents` |
| GET | `/api/v1/runtime/agents/export/{job_id}` | `runtime.agent.export` | `app.runtime.routes::get_export_job` |
| GET | `/api/v1/runtime/agents/export/{job_id}/download` | `runtime.agent.export` | `app.runtime.routes::download_export` |
| POST | `/api/v1/runtime/agents/import` | `runtime.agent.import` | `app.runtime.routes::import_agents` |
| GET | `/api/v1/runtime/agents/import/{job_id}` | `runtime.agent.import` | `app.runtime.routes::get_import_job` |
| GET | `/api/v1/runtime/agents/import/{job_id}/items` | `runtime.agent.import` | `app.runtime.routes::get_import_items` |
| POST | `/api/v1/runtime/agents/migration/classify` | `runtime.agent.import` | `app.runtime.routes::classify_legacy_agents` |
| GET | `/api/v1/runtime/agents/migration/records` | `runtime.agent.import` | `app.runtime.routes::list_migration_records` |
| DELETE | `/api/v1/runtime/agents/{agent_id}` | `runtime.agent.delete` | `app.runtime.routes::delete_agent` |
| GET | `/api/v1/runtime/agents/{agent_id}` | `runtime.agent.view` | `app.runtime.routes::get_agent` |
| PATCH | `/api/v1/runtime/agents/{agent_id}` | `runtime.agent.update` | `app.runtime.routes::update_agent` |
| PUT | `/api/v1/runtime/agents/{agent_id}` | `runtime.agent.update` | `app.runtime.routes::update_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/activate` | `runtime.agent.activate` | `app.runtime.routes::activate_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/approve` | `runtime.agent.approve` | `app.runtime.routes::approve_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/archive` | `runtime.agent.archive` | `app.runtime.routes::archive_agent` |
| GET | `/api/v1/runtime/agents/{agent_id}/capabilities` | `runtime.agent.view` | `app.runtime.routes::agent_capabilities` |
| POST | `/api/v1/runtime/agents/{agent_id}/capabilities` | `runtime.capability.manage` | `app.runtime.routes::assign_capability` |
| DELETE | `/api/v1/runtime/agents/{agent_id}/capabilities/{assignment_id}` | `runtime.capability.manage` | `app.runtime.routes::revoke_capability` |
| POST | `/api/v1/runtime/agents/{agent_id}/capabilities/{assignment_id}/decide` | `runtime.capability.manage` | `app.runtime.routes::decide_capability` |
| GET | `/api/v1/runtime/agents/{agent_id}/definition` | `runtime.agent.view` | `app.runtime.routes::list_definitions` |
| GET | `/api/v1/runtime/agents/{agent_id}/definitions` | `runtime.agent.view` | `app.runtime.routes::list_definitions` |
| POST | `/api/v1/runtime/agents/{agent_id}/deprecate` | `runtime.agent.deprecate` | `app.runtime.routes::deprecate_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/duplicate-check` | `runtime.agent.update` | `app.runtime.routes::duplicate_check` |
| GET | `/api/v1/runtime/agents/{agent_id}/duplicate-matches` | `runtime.agent.view` | `app.runtime.routes::duplicate_matches` |
| POST | `/api/v1/runtime/agents/{agent_id}/duplicate-matches/{match_id}/review` | `runtime.agent.duplicate.review` | `app.runtime.routes::review_duplicate` |
| GET | `/api/v1/runtime/agents/{agent_id}/events` | `runtime.agent.audit.view` | `app.runtime.routes::agent_runtime_events` |
| GET | `/api/v1/runtime/agents/{agent_id}/identity` | `runtime.agent.view` | `app.runtime.routes::get_identity` |
| POST | `/api/v1/runtime/agents/{agent_id}/identity/associate` | `runtime.agent.identity.associate` | `app.runtime.routes::associate_identity` |
| POST | `/api/v1/runtime/agents/{agent_id}/identity/create-and-associate` | `runtime.agent.identity.create` | `app.runtime.routes::create_and_associate_identity` |
| POST | `/api/v1/runtime/agents/{agent_id}/identity/replace` | `runtime.agent.identity.replace` | `app.runtime.routes::replace_identity` |
| GET | `/api/v1/runtime/agents/{agent_id}/lifecycle-events` | `runtime.agent.audit.view` | `app.runtime.routes::agent_lifecycle_events` |
| GET | `/api/v1/runtime/agents/{agent_id}/ownership` | `runtime.agent.ownership.view` | `app.runtime.routes::get_ownership` |
| GET | `/api/v1/runtime/agents/{agent_id}/ownership/history` | `runtime.agent.ownership.view` | `app.runtime.routes::ownership_history` |
| POST | `/api/v1/runtime/agents/{agent_id}/ownership/transfer` | `runtime.agent.ownership.transfer` | `app.runtime.routes::transfer_ownership` |
| POST | `/api/v1/runtime/agents/{agent_id}/register` | `runtime.agent.register` | `app.runtime.routes::register_lifecycle_action` |
| POST | `/api/v1/runtime/agents/{agent_id}/reject` | `runtime.agent.reject` | `app.runtime.routes::reject_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/restore` | `runtime.agent.restore` | `app.runtime.routes::restore_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/resume` | `runtime.agent.resume` | `app.runtime.routes::resume_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/retire` | `runtime.agent.retire` | `app.runtime.routes::retire_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/schemas/test` | `runtime.agent.view` | `app.runtime.routes::test_schema` |
| POST | `/api/v1/runtime/agents/{agent_id}/submit-for-approval` | `runtime.agent.submit` | `app.runtime.routes::submit_for_approval` |
| POST | `/api/v1/runtime/agents/{agent_id}/suspend` | `runtime.agent.suspend` | `app.runtime.routes::suspend_agent` |
| GET | `/api/v1/runtime/agents/{agent_id}/tools` | `runtime.agent.view` | `app.runtime.routes::agent_tools` |
| POST | `/api/v1/runtime/agents/{agent_id}/tools` | `runtime.tool.assign` | `app.runtime.routes::assign_tool` |
| DELETE | `/api/v1/runtime/agents/{agent_id}/tools/{assignment_id}` | `runtime.tool.assign` | `app.runtime.routes::revoke_tool` |
| POST | `/api/v1/runtime/agents/{agent_id}/tools/{assignment_id}/decide` | `runtime.tool.assign` | `app.runtime.routes::decide_tool` |
| POST | `/api/v1/runtime/agents/{agent_id}/validate` | `runtime.agent.validate` | `app.runtime.routes::validate_agent` |
| GET | `/api/v1/runtime/agents/{agent_id}/validations` | `runtime.agent.validation.view` | `app.runtime.routes::list_validations` |
| POST | `/api/v1/runtime/agents/{agent_id}/validations/run` | `runtime.agent.validate` | `app.runtime.routes::run_validation` |
| GET | `/api/v1/runtime/agents/{agent_id}/validations/{validation_id}` | `runtime.agent.validation.view` | `app.runtime.routes::get_validation` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions` | `runtime.version.view` | `app.runtime.routes::list_versions` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions` | `runtime.version.create` | `app.runtime.routes::create_version` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}` | `runtime.version.view` | `app.runtime.routes::get_version` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/approve` | `runtime.agent.approve` | `app.runtime.routes::approve_version` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/artifacts` | `runtime.version.view` | `app.runtime.routes::list_release_artifacts` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/artifacts` | `runtime.version.create` | `app.runtime.routes::add_release_artifact` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/compare/{other_version_id}` | `runtime.version.view` | `app.runtime.routes::compare_versions` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/deprecate` | `runtime.version.deprecate` | `app.runtime.routes::deprecate_version` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/notes` | `runtime.version.view` | `app.runtime.routes::list_release_notes` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/notes` | `runtime.version.create` | `app.runtime.routes::add_release_note` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/publish` | `runtime.version.publish` | `app.runtime.routes::publish_version` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/readiness` | `runtime.version.view` | `app.runtime.routes::version_readiness` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/release-metadata` | `runtime.version.view` | `app.runtime.routes::get_release_metadata` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/release-metadata` | `runtime.version.create` | `app.runtime.routes::upsert_release_metadata` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/retire` | `runtime.version.retire` | `app.runtime.routes::retire_version` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/revoke` | `runtime.version.revoke` | `app.runtime.routes::revoke_version` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/rollback-target` | `runtime.version.create` | `app.runtime.routes::set_version_rollback_target` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/snapshot` | `runtime.version.view` | `app.runtime.routes::get_version_snapshot` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/status-history` | `runtime.version.view` | `app.runtime.routes::get_version_status_history` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/validate` | `runtime.version.create` | `app.runtime.routes::validate_version` |
| GET | `/api/v1/runtime/approvals` | `runtime.approval.review` | `app.runtime.routes::list_approvals` |
| POST | `/api/v1/runtime/approvals/{approval_id}/decide` | `runtime.approval.review` | `app.runtime.routes::decide_approval` |
| GET | `/api/v1/runtime/capabilities` | `runtime.agent.view` | `app.runtime.routes::list_capabilities` |
| POST | `/api/v1/runtime/capabilities` | `runtime.capability.manage` | `app.runtime.routes::create_capability` |
| GET | `/api/v1/runtime/dashboard` | `runtime.agent.view` | `app.runtime.routes::dashboard` |
| GET | `/api/v1/runtime/deployments` | `runtime.deployment.view` | `app.runtime.routes::list_deployments` |
| POST | `/api/v1/runtime/deployments` | `runtime.deployment.create` | `app.runtime.routes::create_deployment` |
| GET | `/api/v1/runtime/deployments/{deployment_id}` | `runtime.deployment.view` | `app.runtime.routes::get_deployment` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/deploy` | `runtime.deployment.deploy` | `app.runtime.routes::deploy` |
| GET | `/api/v1/runtime/deployments/{deployment_id}/health` | `runtime.health.view` | `app.runtime.routes::deployment_health` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/heartbeat` | `runtime.deployment.deploy` | `app.runtime.routes::submit_heartbeat` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/resume` | `runtime.deployment.deploy` | `app.runtime.routes::resume_deployment` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/retire` | `runtime.deployment.deploy` | `app.runtime.routes::retire_deployment` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/rollback` | `runtime.deployment.rollback` | `app.runtime.routes::rollback_deployment` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/suspend` | `runtime.deployment.deploy` | `app.runtime.routes::suspend_deployment` |
| GET | `/api/v1/runtime/executions` | `runtime.execution.view` | `app.runtime.routes::list_executions` |
| POST | `/api/v1/runtime/executions` | `runtime.execution.create` | `app.runtime.routes::request_execution` |
| POST | `/api/v1/runtime/executions/self` | `—` | `app.runtime.routes::request_self_execution` |
| GET | `/api/v1/runtime/executions/{execution_id}` | `runtime.execution.view` | `app.runtime.routes::get_execution` |
| GET | `/api/v1/runtime/executions/{execution_id}/attempts` | `runtime.execution.view` | `app.runtime.routes::execution_attempts` |
| POST | `/api/v1/runtime/executions/{execution_id}/cancel` | `runtime.execution.cancel` | `app.runtime.routes::cancel_execution` |
| GET | `/api/v1/runtime/executions/{execution_id}/events` | `runtime.execution.view` | `app.runtime.routes::execution_events` |
| POST | `/api/v1/runtime/executions/{execution_id}/replay` | `runtime.execution.retry` | `app.runtime.routes::replay_execution` |
| POST | `/api/v1/runtime/executions/{execution_id}/retry` | `runtime.execution.retry` | `app.runtime.routes::retry_execution` |
| GET | `/api/v1/runtime/executions/{execution_id}/tool-calls` | `runtime.execution.view` | `app.runtime.routes::execution_tool_calls` |
| GET | `/api/v1/runtime/health` | `runtime.health.view` | `app.runtime.routes::platform_health` |
| POST | `/api/v1/runtime/kill-switch/agents/{agent_id}` | `runtime.kill_switch.execute` | `app.runtime.routes::kill_agent` |
| POST | `/api/v1/runtime/kill-switch/executions/{execution_id}` | `runtime.kill_switch.execute` | `app.runtime.routes::kill_execution` |
| POST | `/api/v1/runtime/kill-switch/organizations/{organization_id}` | `runtime.kill_switch.execute` | `app.runtime.routes::kill_organization` |
| POST | `/api/v1/runtime/kill-switch/platform` | `runtime.kill_switch.execute` | `app.runtime.routes::kill_platform` |
| POST | `/api/v1/runtime/kill-switch/projects/{project_id}` | `runtime.kill_switch.execute` | `app.runtime.routes::kill_project` |
| GET | `/api/v1/runtime/release-channels` | `runtime.version.view` | `app.runtime.routes::list_release_channels` |
| GET | `/api/v1/runtime/tools` | `runtime.agent.view` | `app.runtime.routes::list_tools` |
| POST | `/api/v1/runtime/tools` | `runtime.tool.manage` | `app.runtime.routes::create_tool` |
| GET | `/api/v1/runtime/workers` | `runtime.health.view` | `app.runtime.routes::list_workers` |
| POST | `/api/v1/runtime/workers/reap` | `runtime.execution.retry` | `app.runtime.routes::reap_stale_locks` |

#### `/api/v1/security`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/security/account-locks` | `security.protection` | `app.identity.protection.routes::account_locks` |
| POST | `/api/v1/security/account-locks/{lock_id}/unlock` | `security.protection` | `app.identity.protection.routes::unlock_lock` |
| GET | `/api/v1/security/account-protection/summary` | `security.protection` | `app.identity.protection.routes::summary` |
| GET | `/api/v1/security/blocked-ips` | `security.protection` | `app.identity.protection.routes::list_blocked_ips` |
| POST | `/api/v1/security/blocked-ips` | `security.protection` | `app.identity.protection.routes::block_ip` |
| DELETE | `/api/v1/security/blocked-ips/{blocked_ip_id}` | `security.protection` | `app.identity.protection.routes::unblock_ip` |
| GET | `/api/v1/security/identity-protection-rules` | `security.protection` | `app.identity.protection.routes::list_rules` |
| POST | `/api/v1/security/identity-protection-rules` | `security.protection` | `app.identity.protection.routes::create_rule` |
| DELETE | `/api/v1/security/identity-protection-rules/{rule_id}` | `security.protection` | `app.identity.protection.routes::delete_rule` |
| PUT | `/api/v1/security/identity-protection-rules/{rule_id}` | `security.protection` | `app.identity.protection.routes::update_rule` |
| GET | `/api/v1/security/login-attempts` | `security.protection` | `app.identity.protection.routes::login_attempts` |
| GET | `/api/v1/security/password-dashboard` | `credential.dashboard` | `app.identity.credentials.routes::password_dashboard` |
| GET | `/api/v1/security/recovery-events` | `recovery.view` | `app.identity.recovery.routes::recovery_events` |
| GET | `/api/v1/security/risk-events` | `security.protection` | `app.identity.protection.routes::risk_events` |
| POST | `/api/v1/security/users/{user_id}/lock` | `security.protection` | `app.identity.protection.routes::lock_user` |
| POST | `/api/v1/security/users/{user_id}/unlock` | `security.protection` | `app.identity.protection.routes::unlock_user` |

#### `/api/v1/teams`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/teams` | `organization.view` | `app.authorization.hierarchy.routes::list_teams` |
| POST | `/api/v1/teams` | `organization.manage` | `app.authorization.hierarchy.routes::create_team` |
| DELETE | `/api/v1/teams/{team_id}` | `organization.manage` | `app.authorization.hierarchy.routes::delete_team` |
| GET | `/api/v1/teams/{team_id}` | `organization.view` | `app.authorization.hierarchy.routes::get_team` |
| PUT | `/api/v1/teams/{team_id}` | `organization.manage` | `app.authorization.hierarchy.routes::update_team` |

#### `/approvals`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/approvals` | `approval.view` | `app.api.routes.approvals::list_approvals` |
| GET | `/approvals/escalations` | `approval.view` | `app.api.routes.approvals::approval_escalations` |
| GET | `/approvals/history` | `approval.view` | `app.api.routes.approvals::approval_history` |
| GET | `/approvals/pending` | `approval.view` | `app.api.routes.approvals::list_pending_approvals` |
| GET | `/approvals/statistics` | `approval.view` | `app.api.routes.approvals::approval_statistics` |
| GET | `/approvals/{approval_id}` | `approval.view` | `app.api.routes.approvals::get_approval` |
| POST | `/approvals/{approval_id}/approve` | `approval.review` | `app.api.routes.approvals::approve` |
| POST | `/approvals/{approval_id}/assign` | `approval.assign` | `app.api.routes.approvals::assign` |
| GET | `/approvals/{approval_id}/comments` | `approval.view` | `app.api.routes.approvals::list_comments` |
| POST | `/approvals/{approval_id}/comments` | `approval.review` | `app.api.routes.approvals::add_comment` |
| POST | `/approvals/{approval_id}/escalate` | `approval.escalate` | `app.api.routes.approvals::escalate` |
| POST | `/approvals/{approval_id}/reject` | `approval.review` | `app.api.routes.approvals::reject` |
| GET | `/approvals/{approval_id}/timeline` | `approval.view` | `app.api.routes.approvals::approval_timeline` |

#### `/audit`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/audit` | `audit.view` | `app.api.routes.audit::list_audit` |
| GET | `/audit/compliance` | `audit.export` | `app.api.routes.audit::audit_compliance` |
| GET | `/audit/events` | `audit.view` | `app.api.routes.audit::audit_event_catalog` |
| GET | `/audit/export` | `audit.export` | `app.api.routes.audit::audit_export` |
| GET | `/audit/security` | `audit.export` | `app.api.routes.audit::audit_security` |
| GET | `/audit/statistics` | `audit.view` | `app.api.routes.audit::audit_statistics` |
| GET | `/audit/timeline` | `audit.view` | `app.api.routes.audit::audit_timeline` |
| GET | `/audit/{event_id}` | `audit.view` | `app.api.routes.audit::get_audit_event` |

#### `/audit-logs`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/audit-logs` | `—` | `app.api.routes.audit_logs::list_audit_logs` |
| GET | `/audit-logs/entity/{entity_type}/{entity_id}` | `—` | `app.api.routes.audit_logs::list_entity_audit_logs` |

#### `/auth`

| Method | Path | Permission | Handler |
|---|---|---|---|
| POST | `/auth/login` | `—` | `app.api.routes.auth::login` |
| GET | `/auth/me` | `—` | `app.api.routes.auth::me` |
| POST | `/auth/register` | `—` | `app.api.routes.auth::register` |

#### `/dashboard`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/dashboard/activity` | `dashboard.view` | `app.api.routes.dashboard::agent_activity` |
| GET | `/dashboard/high-risk-actions` | `dashboard.view` | `app.api.routes.dashboard::high_risk_actions` |
| GET | `/dashboard/pending-approvals` | `dashboard.view` | `app.api.routes.dashboard::pending_approvals` |
| GET | `/dashboard/recent-actions` | `dashboard.view` | `app.api.routes.dashboard::recent_actions` |
| GET | `/dashboard/risk-trend` | `dashboard.view` | `app.api.routes.dashboard::risk_trend` |
| GET | `/dashboard/summary` | `dashboard.view` | `app.api.routes.dashboard::dashboard_summary` |

#### `/health`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/health` | `—` | `app.main::health_check` |

#### `/organizations`

| Method | Path | Permission | Handler |
|---|---|---|---|
| POST | `/organizations` | `—` | `app.api.routes.organizations::create_organization` |
| GET | `/organizations/{organization_id}` | `—` | `app.api.routes.organizations::get_organization` |

#### `/permissions`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/permissions` | `—` | `app.api.routes.permissions::list_permissions` |
| POST | `/permissions` | `—` | `app.api.routes.permissions::create_permission` |
| GET | `/permissions/agent/{agent_id}` | `—` | `app.api.routes.permissions::list_agent_permissions` |

#### `/policies`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/policies` | `policy.view` | `app.api.routes.policies::list_policies` |
| POST | `/policies` | `policy.create` | `app.api.routes.policies::create_policy` |
| GET | `/policies/templates` | `—` | `app.api.routes.policies::list_policy_templates` |
| DELETE | `/policies/{policy_id}` | `policy.delete` | `app.api.routes.policies::delete_policy` |
| GET | `/policies/{policy_id}` | `policy.view` | `app.api.routes.policies::get_policy` |
| PATCH,PUT | `/policies/{policy_id}` | `policy.edit` | `app.api.routes.policies::update_policy` |
| GET | `/policies/{policy_id}/audit` | `policy.view` | `app.api.routes.policies::policy_audit` |
| PATCH | `/policies/{policy_id}/disable` | `policy.edit` | `app.api.routes.policies::disable_policy` |
| PATCH | `/policies/{policy_id}/enable` | `policy.edit` | `app.api.routes.policies::enable_policy` |
| POST | `/policies/{policy_id}/test` | `policy.view` | `app.api.routes.policies::test_policy` |

#### `/rbac`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/rbac/me` | `—` | `app.api.routes.rbac::my_permissions` |
| GET | `/rbac/permissions` | `—` | `app.api.routes.rbac::list_permissions` |
| GET | `/rbac/roles` | `—` | `app.api.routes.rbac::list_roles` |
| POST | `/rbac/users/{user_id}/roles` | `rbac.manage` | `app.api.routes.rbac::assign_role` |

#### `/system`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/system/health` | `—` | `app.api.routes.system::system_health` |

#### `/users`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/users` | `—` | `app.api.routes.users::list_users` |
| POST | `/users` | `—` | `app.api.routes.users::create_user` |
| GET | `/users/{user_id}` | `—` | `app.api.routes.users::get_user` |

## 6. Phase 5.2 Status

Verified against the current codebase (models, live schema, service files, route table) at generation time — not carried forward from any earlier summary.

| Sub-phase | Status | Evidence |
|---|---|---|
| **5.2.1 Version Core & Immutability** | **IMPLEMENTED** | `agent_versions` table (92-table live schema, §2); `AgentVersion` model class in `backend/app/models/runtime.py`; `AgentVersionService` (create/validate/approve/publish/deprecate/revoke/retire) in `backend/app/runtime/services.py`; `VERSION_LIFECYCLE = ("DRAFT","VALIDATING","READY_FOR_REVIEW","APPROVED","PUBLISHED","DEPRECATED","REVOKED","RETIRED")` (same file); `agent_version_status_history` table + `backend/app/runtime/versioning/status_history.py` records every transition. |
| **5.2.2 Configuration Snapshots** | **IMPLEMENTED** | Per-field snapshots on `agent_versions` (`configuration_snapshot`, `prompt_snapshot`, `model_configuration`, `capabilities_snapshot`, `tools_snapshot`, `policy_snapshot` — Phase 5.0) plus the complete frozen document in `agent_version_snapshots.snapshot` (JSONB), built by `SnapshotBuilderService.build_and_store` / `build_snapshot()` in `backend/app/runtime/versioning/snapshot.py`, called once at `publish()`. |
| **5.2.3 Content Addressing & Checksums** | **IMPLEMENTED** | `agent_versions.checksum` (sha256, `_checksum()` in `backend/app/runtime/services.py`, verified against tamper at `publish()`); `agent_version_snapshots.checksum` (`checksum_of()` in `backend/app/runtime/versioning/snapshot.py`). Not "content-addressed storage" in the sense of a CAS/object store — checksums are integrity hashes stored as a column, not used as lookup keys. |
| **5.2.4 Signing & Provenance** | **NOT STARTED** (column reserved only) | `agent_versions.signature_id` column exists (`backend/app/models/runtime.py:125`, nullable, no default logic). Verified via `grep -rn "signature_id" backend/app`: the **only** two occurrences in the entire codebase are the model column definition and its mirrored Pydantic schema field (`backend/app/runtime/schemas.py:90`) — no service ever reads, writes, generates, or verifies it. No signing key management, no verification logic, no provenance chain anywhere. |
| **5.2.5 Version Comparison & Diff** | **IMPLEMENTED** | `VersionComparisonService.compare()` in `backend/app/runtime/versioning/compare.py`; route `GET /agents/{agent_id}/versions/{version_id}/compare/{other_version_id}` in `backend/app/runtime/routes.py` (`compare_versions`). Scalar-field diff, key-level JSONB config diff, artifact/note set diff. |
| **5.2.6 Compatibility Detection** | **NOT STARTED** (column reserved only) | `agent_versions.compatibility_level` column exists (`backend/app/models/runtime.py:124`, default `"UNKNOWN"`). Verified via `grep -rn "compatibility_level" backend/app`: the only two occurrences are the model column and its mirrored schema field (`backend/app/runtime/schemas.py:89`) — nothing computes, infers, or changes it from `"UNKNOWN"`. `VersionReadinessService` (`backend/app/runtime/versioning/readiness.py`) explicitly reports this as a `skipped: true` check with the message *"Deferred to Part 3 — not evaluated in this part."* |
| **5.2.7 Release Channels & Promotion** | **IMPLEMENTED** | `agent_release_channels` table (seeded with STABLE/BETA/CANARY/INTERNAL by migration `0025`); `ReleaseChannelService` in `backend/app/runtime/versioning/channels.py`; route `GET /release-channels`. Promotion **readiness** (not promotion *execution*) via `VersionReadinessService` in `backend/app/runtime/versioning/readiness.py` and route `GET /agents/{agent_id}/versions/{version_id}/readiness` — a read-only diagnostic checklist (snapshot buildability, validation, metadata, ownership, registry status, blocking governance findings, artifacts, approval), never a gate on the lifecycle actions themselves. Actual environment promotion / rollout execution is out of scope (see §9). |

---

## 7. Conventions

| Convention | Detail | Reference |
|---|---|---|
| ORM declarative base | `class Base(DeclarativeBase)` | `backend/app/core/database.py:24` |
| PK mixin | `UUIDPrimaryKeyMixin` — app-generated `uuid.uuid4()` UUID primary key | `backend/app/models/mixins.py` |
| Timestamp mixin | `TimestampMixin` — `created_at`/`updated_at`, server-side `func.now()`, `onupdate` on the latter | `backend/app/models/mixins.py` |
| Error envelope | `ErrorCode` (string-constant class) + `IdentityError(code, message)` exception, handled by a registered FastAPI exception handler producing `{"success": false, "error": {"code", "message"}, "request_id"}` | `backend/app/identity/errors.py` — used well beyond the identity module itself (e.g. every `app/runtime/*` file imports `ErrorCode`/`IdentityError` from here) |
| Service pattern (dominant) | One `XService` class per aggregate, `__init__(self, db: Session)`, a `get_or_404` method, direct SQLAlchemy queries — no repository indirection | e.g. `AgentVersionService` in `backend/app/runtime/services.py`, `AgentLifecycleService` in `backend/app/runtime/registry/services.py` |
| Repository pattern (minority) | Explicit `XRepository` classes wrapping queries, used underneath services | Only in `backend/app/identity/repositories/*.py` (`BaseRepository` generic base in `base.py`) and `backend/app/authorization/repositories.py` (Phase 4.3.1 core only) — **not** used in the later authorization submodules (`abac/`, `admin/`, `hierarchy/`, `resources/`), governance, or runtime/registry/versioning, which query directly from services. This is an inconsistency across phases, not a documented rule (see §10). |
| Permission naming | Dot-notation `domain.resource.action` strings (e.g. `runtime.version.retire`, `agent.view`, `policy.edit`), centrally cataloged | `PERMISSION_CATALOG: dict[str, str]` in `backend/app/services/rbac_service.py`; `require_permission(code)` dependency in `backend/app/api/deps.py:129` |
| Backend test framework | pytest, real Postgres (not sqlite/mocks) via `SessionLocal()`; `client`/`db_session`/`admin` fixtures | `backend/tests/authorization/conftest.py`; hermetic defaults (notifications/rate-limit/envelope off) via autouse fixtures in `backend/tests/conftest.py` |
| Backend test layout | `backend/tests/{authorization,identity}/` plus flat `test_*.py` files at `backend/tests/` root for the original Phase 1-3 surface | verified via `find backend/tests -maxdepth 2 -type d` |
| Frontend test framework | Vitest, `jsdom` environment, `@testing-library/react` + `user-event`, cleanup via `afterEach` | `frontend/vitest.config.ts`, `frontend/src/test/setup.ts` |
| Frontend test layout | `frontend/src/modules/<domain>/tests/*.test.tsx` co-located per module (not a top-level `tests/` dir) | verified via `find frontend/src/modules -iname "*.test.*"` (this session) |
| Frontend structure | One module dir per backend domain (`frontend/src/modules/<domain>/`), one service file per domain (`frontend/src/services/<domain>Service.ts`), shared Radix-based primitives in `frontend/src/components/ui/` | `frontend/src/modules/*`, `frontend/src/services/*.ts` |
| Frontend stack | React 19, TypeScript, Vite, TanStack Query (server state), react-hook-form + zod (forms), Radix UI primitives, Tailwind, react-router-dom v7 | `frontend/package.json` |
| Backend stack | FastAPI 0.115, SQLAlchemy 2.0, Alembic 1.14, Pydantic 2.10, pytest 8.3 | `backend/requirements.txt` |

---

## 8. Branch History

Output of `git branch -a --sort=-committerdate`, with committer dates added via `--format` (the bare command has no date column; dates were requested). Names and dates only — 25 local branches, each mirrored by an `origin/*` remote-tracking branch at the same commit/date (shown once below; the `origin/<name>` counterpart is identical).

| Branch | Committer date |
|---|---|
| `main` | 2026-07-22 22:20:54 +0500 |
| `feature/phase-5.1-agent-registry-hardening` | 2026-07-22 22:19:01 +0500 |
| `feat/phase-5.0-hardening` | 2026-07-20 18:35:58 +0500 |
| `feat/phase-5.0-agent-runtime` | 2026-07-20 16:16:04 +0500 |
| `feat/phase-4.3.8-governance-and-redesign` | 2026-07-18 05:09:40 +0500 |
| `feat/4.3.7-admin-portal` | 2026-07-16 17:41:10 +0500 |
| `feat/4.3.6-authorization-middleware` | 2026-07-16 16:26:34 +0500 |
| `feat/4.3.5-abac-engine` | 2026-07-15 23:45:25 +0500 |
| `feat/4.3.4-resource-authorization` | 2026-07-15 02:32:06 +0500 |
| `feat/4.3.3-org-hierarchy` | 2026-07-10 22:46:03 +0500 |
| `feat/4.3.2-engine-events-and-perf` | 2026-07-10 19:35:57 +0500 |
| `feat/4.3.2-permission-engine` | 2026-07-10 19:18:52 +0500 |
| `feat/4.3.1-enterprise-rbac` | 2026-07-10 16:41:03 +0500 |
| `feat/4.2.2.3.5-envelope-and-deploy` | 2026-07-10 04:54:20 +0500 |
| `feat/4.2.2.3.5-integration-release` | 2026-07-10 04:27:05 +0500 |
| `feat/account-protection-4.2.2.3.4` | 2026-07-10 04:00:11 +0500 |
| `feat/account-recovery-4.2.2.3.3` | 2026-07-09 18:06:46 +0500 |
| `feat/credential-management-4.2.2.3.2` | 2026-07-09 16:35:03 +0500 |
| `feat/registration-invitations-4.2.2.3.1` | 2026-07-09 03:15:21 +0500 |
| `feat/phase-4.2.2.2-session-lifecycle` | 2026-07-08 23:17:27 +0500 |
| `feat/phase-4.2.2.1-human-auth-and-architecture-docs` | 2026-07-08 17:52:30 +0500 |
| `phase-4-authentication-architecture` | 2026-07-07 18:19:05 +0500 |
| `phase-4-1a-identity-lifecycle` | 2026-07-02 16:18:20 +0500 |
| `phase-4-identity-foundation` | 2026-07-02 00:34:10 +0500 |
| `feat/analytics-operations-part-3.6` | 2026-07-01 05:19:14 +0500 |
| `feat/audit-compliance-center-part-3.5` | 2026-07-01 04:18:00 +0500 |
| `feat/approval-workbench-part-3.4` | 2026-06-30 02:53:28 +0500 |

Current branch: `main`. Working tree is **not clean** — Phase 5.2 Part 1 changes (versioning models/services/routes/tests/docs) are present but uncommitted on top of `8092be1` (verified via `git status --porcelain`).

---

## 9. Known Gaps

Every item below was mechanically verified at generation time (grep with an explicit exit-code check, or an actual test run), not inferred.

1. **Zero `TODO`/`FIXME`/`XXX`/`HACK:` markers** anywhere in `backend/app` or `frontend/src` (`grep -rn` both returned no matches).
2. **Zero `NotImplementedError`** anywhere in `backend/app`.
3. **Zero pytest `skip`/`xfail` markers** in `backend/tests`.
4. **Duplicate OpenAPI `operationId` warning**: `update_policy` in `backend/app/api/routes/policies.py:137` is registered via `@router.api_route("/{policy_id}", methods=["PUT", "PATCH"])` — both methods share one function, so FastAPI's OpenAPI generator emits a `UserWarning: Duplicate Operation ID` every time the schema is built (reproduced during this session's test run). Cosmetic — both HTTP methods work correctly (`test_response_envelope.py::test_openapi_schema_is_not_enveloped` passes) — but would break strict OpenAPI-codegen tooling pointed at this schema.
5. **Only the `MOCK` model provider actually executes.** `ModelGatewayService` (`backend/app/runtime/services.py:898`) models and authorizes every other provider but fails closed with `MODEL_PROVIDER_UNAVAILABLE`.
6. **Only the `FUNCTION`/`echo` tool action actually executes.** Everything else fails closed with `TOOL_ACTION_NOT_ALLOWED` (`docs/runtime/overview.md`).
7. **CAPTCHA is a placeholder.** `CaptchaService.verify()` (`backend/app/identity/protection/policy.py:89`) has no real Turnstile/reCAPTCHA/hCaptcha integration.
8. **Analytics cost figures are deterministic estimates**, not real provider billing data (`backend/app/services/analytics_service.py:64`, "Estimated unit costs (USD)... deterministic placeholders").
9. **Phase 5.2 compatibility analysis and cryptographic signing are unimplemented** — see §6, rows 5.2.4 and 5.2.6.
10. **No "release package" entity.** The SRS for Phase 5.2 Part 1 lists "release packages" as in-scope; this codebase treats the frozen `agent_version_snapshots.snapshot` document as that bundle rather than introducing a separately-named table — documented as a deliberate equivalence in `docs/runtime/versioning.md`, not a gap in functionality, but worth flagging since no artifact literally named "release package" exists.
11. **Multi-agent orchestration and several other large feature areas do not exist in any form**: a visual workflow builder, distributed event streaming at hyperscale, automated model optimization, reinforcement learning, autonomous agent creation, a marketplace, multi-cloud federation, a Kubernetes operator, GPU scheduling. Explicitly out of scope per `docs/runtime/overview.md`'s "What's deliberately not here."
12. **Actual rollback/canary/traffic-shift execution does not exist.** `AgentVersion.rollback_target_id` (Phase 5.2 Part 1) is a settable pointer only; nothing reads it to perform a rollback. `DeploymentService.rollback` (Phase 5.0, `backend/app/runtime/services.py`) is the only thing that changes what's actually deployed, and is a full redeploy to a target version, not a traffic-shifting rollback.
13. **Frontend production bundle is a single ~1.65 MB chunk** (431 KB gzip) — Vite's build output flags this as exceeding its 500 KB warning threshold; no route-level code-splitting has been applied (reproduced this session via `npm run build`).
14. **`backend/.venv` had to be rebuilt mid-session** (Phase 5.1 work) because the one present in the working tree pointed at a Python interpreter path (`C:\Users\Dell\...`) from a different machine. It is gitignored, so this is a local-environment fact, not a repository defect — flagged here since a fresh clone on another machine will need the same rebuild. **UNVERIFIED** whether this affects any environment other than the one this document was generated in.
15. **Test suite status at generation time**: backend `661 passed, 0 failed` (`pytest -q`, 176.05s); frontend `297 passed, 0 failed` across 48 files (`vitest run`). Both re-run fresh for this document, not carried forward.

---

## 10. Architecture Decisions Made In Code

Decisions the SRS/roadmap documents don't specify, that the implementation settled — each verified against the actual code, with rationale where the code itself states one.

1. **The `agents` table (Phase 1) is the one agent registry across every later phase** (5.0/5.1/5.2) — never forked into a parallel table. Stated in the module docstring of `backend/app/models/runtime.py`.
2. **The execution queue *is* the `agent_executions` table** (`SELECT ... FOR UPDATE SKIP LOCKED`), not Redis/Celery. The worker runs inline/synchronously right after enqueue (an "eager queue", the same trick `CELERY_TASK_ALWAYS_EAGER` plays for local dev) rather than as a standalone process. Module docstring of `backend/app/runtime/services.py`.
3. **Every runtime authorization decision funnels through the single, pre-existing `AuthorizationGateway`** (Phase 4.3.6) rather than the runtime having its own RBAC/ABAC engine. `backend/app/authorization/middleware/gateway.py`, called from `backend/app/runtime/services.py`.
4. **Agents may only request execution of themselves — no agent-to-agent chaining.** `request_execution_as_agent` in `backend/app/runtime/services.py:1217-1224` explicitly rejects any `agent_id` in the payload that doesn't match the calling agent's own id, citing multi-agent orchestration as "explicitly deferred."
5. **Phase 5.2 Part 1 does not enforce "cannot publish two active releases."** This platform's existing Phase 5.0 rollback/canary deployment strategies require multiple simultaneously-`PUBLISHED` versions of one agent (a `Deployment` row, not a `Version`'s status, tracks what's live per environment). Enforcing the SRS rule literally would have broken the already-shipped, already-tested `test_deployment_rollback` scenario. Decided and documented in `docs/runtime/versioning.md` and in the comment block inside `AgentVersionService.publish` (`backend/app/runtime/services.py`).
6. **Phase 5.2 Part 1 kept the single `READY_FOR_REVIEW` version-lifecycle state** rather than splitting it into the SRS's separate "Ready"/"Approval Required" states — no new validation behavior would attach to either half, and the rename would touch roughly ten already-tested files for no functional gain. Documented in `docs/runtime/versioning.md`.
7. **Version snapshots freeze at `publish()`, not at version creation.** Publish is the actual immutability boundary (§21 of the SRS: "Published Version: Immutable"), and freezing there lets release metadata/artifacts/notes be attached any time beforehand without needing to rebuild an earlier snapshot. `backend/app/runtime/versioning/snapshot.py` module docstring.
8. **Version comparison and promotion readiness are both read-only/advisory — neither gates a lifecycle action.** A deliberate separation between diagnostic information and enforcement. `backend/app/runtime/versioning/compare.py`, `backend/app/runtime/versioning/readiness.py`.
9. **Release channels are a single global catalog, not per-organization.** No SRS bullet asked for org-scoped channels, and a shared STABLE/BETA/CANARY/INTERNAL vocabulary keeps release-channel badges comparable across tenants. `backend/app/runtime/versioning/channels.py` module docstring.
10. **Repository-layer usage is inconsistent across domains** (see §7): `identity` (extensively) and the core `authorization` module (Phase 4.3.1) both interpose an explicit `XRepository` layer between services and SQLAlchemy; every later domain (`abac`, `admin`, `hierarchy`, `resources`, `governance`, `runtime`/`registry`/`versioning`) queries the ORM directly from `XService` classes with no repository indirection. **UNVERIFIED** why later modules didn't adopt the same layering — no comment in the code states a reason; plausibly the repository layer was judged unnecessary indirection once the pattern was in production, but this is inference, not a verified fact.
11. **Password hashing migrated bcrypt → argon2id** (Phase 4.2.2.1); bcrypt is retained solely to verify and auto-upgrade pre-existing hashes on next login. `backend/requirements.txt` comment; `backend/app/core/security.py`.
12. **The response envelope and rate limiting are off by default in the entire test suite**, turned on only by the specific tests that assert their behavior (`_no_response_envelope`, `_no_rate_limit` autouse fixtures in `backend/tests/conftest.py`) — a hermetic-testing decision, not an SRS requirement.
13. **Semantic versions with no explicit value auto-derive** (patch-bump from the agent's current highest version, or `0.1.0` for the first) rather than defaulting to a fixed string — closes a gap where Phase 5.0 defaulted every version to `"0.1.0"` unconditionally, which would have made the new duplicate-rejection rule reject the second version of every agent. `backend/app/runtime/versioning/semantic_version.py`.

---

## 11. Update Protocol

This file must be regenerated at the end of every Phase 5.2 sub-phase (5.2.2 through 5.2.7, and any further sub-phases added later). On each regeneration:

- **§2 (Database Schema), §3 (Migration Chain), §5 (API Surface), and §6 (Phase 5.2 Status) must be re-derived from the live system** — re-run `alembic upgrade head` then live `sqlalchemy.inspect()` for §2; `alembic history`/`current` for §3; a fresh import-and-introspect of `app.main:app` for §5; and re-check every piece of evidence cited in §6 (file existence, grep results) — never edited by hand or carried forward from the previous version of this document.
- §1, §4, §7, §9, and §10 should also be re-verified (directory tree, AST module scan, conventions, gap greps, and any new deliberate decisions), since new sub-phases are expected to add files, close gaps, and make new decisions.
- §8 (Branch History) and the "Generated" line at the top should reflect the actual `git branch -a --sort=-committerdate` output and current commit at regeneration time.
- If a claim cannot be mechanically re-verified in the time available, mark it **UNVERIFIED** rather than repeating the old value as fact.
