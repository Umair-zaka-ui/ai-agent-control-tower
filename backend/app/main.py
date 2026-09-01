"""FastAPI application entry point.

Run locally with:
    uvicorn app.main:app --reload
Swagger UI is then served at http://localhost:8000/docs
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.middleware import install_http_middleware
from app.identity.api import identity_router
from app.identity.api.routes.registration import router as registration_router
from app.identity.auth.routes import router as auth_v1_router
from app.identity.federation.routes import router as federation_router
from app.identity.credentials.routes import router as credentials_router
from app.identity.credentials.routes import security_router as credentials_security_router
from app.identity.recovery.routes import router as recovery_router
from app.identity.recovery.routes import security_router as recovery_security_router
from app.identity.protection.routes import router as protection_router
from app.authorization.routes import router as authorization_router
from app.authorization.hierarchy.routes import router as hierarchy_router
from app.authorization.resources.routes import router as resources_router
from app.authorization.abac.routes import router as abac_router
from app.authorization.admin.routes import router as admin_router
from app.governance.routes import router as governance_router
from app.behavior.routes import router as behavior_router
from app.telemetry_export.routes import router as telemetry_export_router
from app.slo.routes import router as slo_router
from app.telemetry_export.routes import metrics_router as telemetry_metrics_router
from app.telemetry_privacy.routes import content_router as trace_content_router
from app.telemetry_privacy.routes import router as telemetry_privacy_router
from app.finops.routes import router as finops_router
from app.runtime.governance.routes import router as runtime_governance_router
from app.runtime.routes import router as runtime_router
from app.integration.routes import router as integration_router
from app.scheduler.routes import router as scheduler_router
from app.workers.routes import router as workers_router
from app.observability.routes import router as observability_router
from app.identity.errors import register_identity_exception_handlers

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Phase 3.8 retired the interim in-process connector-health scheduler that
    # used to start here. Its own module docstring specified this retirement in
    # advance -- "delete this module, delete its one call site in app/main.py's
    # lifespan, register the same iteration as a real job" -- and that is what
    # happened: the sweep now lives in app/integration/sweep.py and runs as the
    # `integration.connector_health_sweep` handler on the real distributed
    # scheduler (`python -m app.scheduler.runner`).
    #
    # The API process deliberately does *not* start a scheduler. A scheduler
    # that ran inside the web process would scale with HTTP traffic rather than
    # with scheduling need, and every API replica would become a competing
    # instance whether the operator wanted a fleet or not.
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    description=(
        "Phase 1 MVP backend that tracks, controls, approves, blocks and "
        "audits actions performed by AI agents."
    ),
    lifespan=lifespan,
)

if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Phase 4.2.2.3.5 (§15, §16, §23): request correlation ids + security response
# headers on every response. Registered after CORS so they sit outermost and
# still wrap error responses.
install_http_middleware(app)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Lightweight liveness probe."""
    return {"status": "ok"}


app.include_router(api_router, prefix=settings.API_PREFIX)

# Phase 4: Enterprise Identity Platform — versioned, isolated under /api/v1/identity.
register_identity_exception_handlers(app)
app.include_router(identity_router)

# Phase 4 Part 4.2.2.1: human authentication endpoints under /api/v1/auth.
app.include_router(auth_v1_router)

# Phase 2.3.1: external identity federation (OIDC/SAML SSO) login endpoints
# under /api/v1/auth/federation; admin config CRUD is mounted via
# identity_router above (/api/v1/identity/federation/configs).
app.include_router(federation_router)

# Phase 4 Part 4.2.2.3.1: public registration & email verification under /api/v1/auth.
app.include_router(registration_router)

# Phase 4 Part 4.2.2.3.2: credential management (change/reset/validate/policy/expiry)
# and the org-wide password dashboard under /api/v1/security.
app.include_router(credentials_router)
app.include_router(credentials_security_router)

# Phase 4 Part 4.2.2.3.3: password reset, account recovery & email change under
# /api/v1/auth, and the recovery-events dashboard under /api/v1/security.
app.include_router(recovery_router)
app.include_router(recovery_security_router)

# Phase 4 Part 4.2.2.3.4: account protection & risk-based auth admin console under
# /api/v1/security (locks, blocked IPs, protection rules, login attempts, risk events).
app.include_router(protection_router)

# Phase 4.3.1: Enterprise RBAC foundation — roles, permissions, permission groups,
# scoped role assignments, role hierarchy and the authorization audit under /api/v1.
app.include_router(authorization_router)

# Phase 4.3.3: Enterprise organization hierarchy — organizations, business units,
# departments, teams, projects, resource ownership and delegation under /api/v1.
app.include_router(hierarchy_router)

# Phase 4.3.4: Resource-based authorization — the protected-resource registry,
# per-resource ownership/ACL/sharing/delegation/policy and the authorization
# inspector under /api/v1.
app.include_router(resources_router)

# Phase 4.3.5: ABAC engine — context-aware policies, the attribute catalog,
# simulation, evaluations and policy exceptions under /api/v1/authorization.
app.include_router(abac_router)

# Phase 4.3.7: Administration portal — dashboard, delegated role/policy/resource
# management, decision explorer, access reviews and analytics under /api/v1/admin.
app.include_router(admin_router)

# Phase 4.3.8: Identity Governance & Administration — certification campaigns,
# SoD/toxic-permission detection, privileged access review, orphaned-identity
# detection, risk scoring, remediation and compliance reporting under
# /api/v1/governance.
app.include_router(governance_router)

# Phase 5.0: Agent Runtime & Lifecycle Management — agent registry, immutable
# versions, deployments, the Runtime Gateway, executions, capabilities, tools,
# runtime approvals, health/workers and the kill switch under /api/v1/runtime.
app.include_router(runtime_router)

# Milestone 2: Enterprise Integration Framework under /api/v1/integration --
# connector types/instances/lifecycle (2.1.1), authentication schemes and
# encrypted credentials (2.1.2), and the registry/health-check surface
# (2.1.3: /auth-schemes, /credentials, /health*) all share this one router.
# No SDK or real connector yet (2.1.4/2.2.x).
app.include_router(integration_router)

# Phase 3.8: the distributed scheduler's management surface under
# /api/v1/runtime/scheduler -- job definitions and run history only. The
# claim/dispatch loop is a separate process (python -m app.scheduler.runner);
# no HTTP route can dispatch a job, which is what keeps the lease the single
# path to execution.
app.include_router(scheduler_router)
app.include_router(workers_router)
# Phase 4.2 -- the governed-observability trace surface
# (/api/v1/observability). Distinct from the legacy `analytics` dashboards,
# which aggregate the Phase 3 agent_actions table and know nothing of
# AgentExecution; no path collision between the two.
app.include_router(observability_router)
# Phase 4.3 -- the runtime governance management and decision-lineage surface,
# on the existing /api/v1/runtime prefix. Configuration and reads only: the
# enforcement engine itself runs inside the tool loop, and no route can invoke
# a checkpoint. That is what keeps "one enforcement path" true of the HTTP
# surface as well as of the loop.
app.include_router(runtime_governance_router)
# Phase 4.4 -- cost governance and FinOps under /api/v1/cost and
# /api/v1/budgets. The canonical financial view over *real* per-execution cost,
# distinct from the legacy /analytics/cost, which aggregates the Phase-3
# agent_actions table with flat placeholder constants and is now deprecated in
# place rather than rewired. No route here enforces a budget: enforcement runs
# in the tool loop through the 4.3 governance engine, which stays the one place
# that decides whether an execution may continue.
app.include_router(finops_router)
# Phase 4.5 -- behavioral signals under /api/v1/runtime/behavior. Deterministic,
# explainable detection of how an agent's runtime behavior changes, reusing
# Phase 3.5's veto -> sufficiency -> threshold -> baseline engine shape. A
# finding is a *signal*: nothing here can stop an execution, and no route can
# invoke enforcement -- 4.3's engine stays the only thing that decides whether
# a loop may continue.
app.include_router(behavior_router)
# Phase 4.6 -- OpenTelemetry & metrics interoperability. Export management under
# /api/v1/observability/export and a Prometheus exposition at GET /metrics. The
# OTel SDK lives behind app/telemetry_export's adapter and nowhere else in the
# codebase; export is fail-open telemetry (an exporter outage never touches an
# execution), buffering is bounded, and export runs off the hot path in a
# background dispatcher, not in the model->tool loop.
app.include_router(telemetry_export_router)
app.include_router(telemetry_metrics_router)
# Phase 4.7 -- SLOs, alert rules & incident signals under /api/v1/runtime/slos
# and /api/v1/runtime/alerts. An SLO breach or a significant behavioral finding
# (4.5) becomes a first-class, durable, auditable alert with a real lifecycle
# (OPEN -> ACKNOWLEDGED -> RESOLVED -> SUPPRESSED), deduplicated at the database.
# It stays a signal: nothing here stops an execution (4.3 does) and nothing
# here delivers a notification (a future integration consumes these records).
app.include_router(slo_router)
# Phase 4.8 -- telemetry privacy, retention & access governance. Capture policy
# (METADATA_ONLY / REDACTED_CONTENT / FULL_CONTENT / DISABLED) per tenant /
# environment / agent / classification, defaulting conservatively; per-class
# retention with a safe, idempotent, 3.8-schedulable expiration sweep; and the
# trace-content read as a distinct, stronger, audited permission
# (runtime.trace.content.view). Non-gating: no capture or retention operation
# ever stops or alters an execution.
app.include_router(telemetry_privacy_router)
app.include_router(trace_content_router)
