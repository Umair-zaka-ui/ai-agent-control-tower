"""Agent Runtime & Lifecycle Management API (Phase 5.0 §66) — /api/v1/runtime."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_agent, require_permission
from app.authorization.enums import AuthorizationAuditEvent
from app.models.agent import Agent
from app.core.database import get_db
from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import (
    AgentDefinition,
    AgentVersionSnapshot,
    ExecutionAttempt,
    ExecutionMessage,
    RuntimeEvent,
    ToolCall,
)
from app.models.user import User
from app.runtime.deployment.canary import CanaryRolloutService
from app.runtime.deployment.health import HealthEvaluationService
from app.runtime.deployment.service import DeploymentLifecycleService
from app.runtime.deployment.strategies import DeploymentStrategyService
from app.runtime.deployment.traffic import TrafficAllocationService
from app.runtime.environment.service import EnvironmentService, PromotionPathService, PromotionService
from app.runtime.release_gate.service import ReleaseGateService
from app.runtime.registry.duplicates import AgentDuplicateDetectionService
from app.runtime.registry.identity import AgentIdentityAssociationService
from app.runtime.registry.imports_exports import AgentExportService, AgentImportService
from app.runtime.registry.migration import AgentMigrationService
from app.runtime.registry.ownership import AgentOwnershipService
from app.runtime.registry.schemas import (
    AgentIdentityRead,
    AgentLifecycleActionRequest,
    AgentOwnershipRead,
    AgentRegistrationCreate,
    AgentRegistryRead,
    AgentRegistryUpdate,
    DuplicateMatchRead,
    DuplicateReviewRequest,
    ExportJobRead,
    ExportRequest,
    IdentityAssociateRequest,
    IdentityCreateAndAssociateRequest,
    AgentLifecycleEventRead,
    IdentityReplaceRequest,
    ImportItemRead,
    ImportJobRead,
    ImportRequest,
    MigrationRecordRead,
    OwnershipHistoryRead,
    OwnershipTransferRequest,
    SchemaTestRequest,
    SchemaTestResponse,
    ValidationRunRead,
)
from app.runtime.registry.services import AgentLifecycleService, AgentSearchService
from app.runtime.registry.validation import validate_sample_payload
from app.runtime.schemas import (
    AgentCapabilityAssign,
    AgentCapabilityRead,
    AgentDefinitionRead,
    AgentSelfExecutionCreate,
    AgentToolAssign,
    AgentToolRead,
    AgentVersionCreate,
    AgentVersionRead,
    CapabilityCreate,
    CapabilityRead,
    DeploymentCreate,
    DeploymentEventRead,
    DeploymentHealthRead,
    DeploymentLifecycleActionRequest,
    DeploymentPreflightRead,
    DeploymentPromoteRequest,
    DeploymentRead,
    DeploymentRollbackRequest,
    DeploymentTransitionRequest,
    EnvironmentCreate,
    EnvironmentPolicyUpdate,
    EnvironmentRead,
    EnvironmentUpdate,
    ExecutionAttemptRead,
    ExecutionCreate,
    ExecutionMessageRead,
    ExecutionRead,
    HeartbeatSubmit,
    KillSwitchRequest,
    PromotionPathCreate,
    PromotionPathRead,
    ProviderCredentialRead,
    ProviderCredentialTestResult,
    ProviderCredentialUpsert,
    RuntimeApprovalDecision,
    RuntimeApprovalRead,
    RolloutActionRequest,
    RolloutCreate,
    RolloutHealthRead,
    RolloutPlanRead,
    RuntimeDashboardRead,
    RuntimeEventRead,
    StrategyOutcomeRead,
    ToolCallRead,
    ToolCreate,
    ToolRead,
    TrafficAllocationRead,
    TrafficAllocationWrite,
)
from app.runtime.services import (
    AgentRegistryService,
    AgentVersionService,
    CapabilityService,
    DeploymentService,
    ExecutionRequestService,
    ExecutionWorkerService,
    HealthMonitoringService,
    KillSwitchService,
    ProviderCredentialService,
    RuntimeApprovalService,
    RuntimeDashboardService,
    ToolRegistryService,
    _record_event,
)
from app.runtime.versioning.artifacts import ReleaseArtifactService
from app.runtime.versioning.attestation import AttestationService
from app.runtime.versioning.channels import ReleaseChannelService
from app.runtime.versioning.compare import VersionComparisonService
from app.runtime.versioning.compatibility import CompatibilityAnalysisService
from app.runtime.versioning.keys import SigningKeyService
from app.runtime.versioning.lineage import VersionLineageService
from app.runtime.versioning.notes import ReleaseNoteService
from app.runtime.versioning.readiness import VersionReadinessService
from app.runtime.versioning.release_metadata import ReleaseMetadataService
from app.runtime.versioning.schemas import (
    AttestationRead,
    CompatibilityFindingRead,
    CompatibilityReportRead,
    ProvenanceRead,
    ReleaseArtifactCreate,
    ReleaseArtifactRead,
    ReleaseChannelRead,
    ReleaseMetadataRead,
    ReleaseMetadataUpsert,
    ReleaseNoteCreate,
    ReleaseNoteRead,
    RevokeSigningKeyRequest,
    RevokeVersionRequest,
    RollbackTargetRequest,
    SignatureRead,
    SigningKeyRead,
    VerificationResultRead,
    VersionComparisonRead,
    VersionReadinessRead,
    VersionSnapshotRead,
    VersionStatusHistoryRead,
)
from app.runtime.versioning.status_history import list_status_history

router = APIRouter(prefix="/api/v1/runtime", tags=["runtime"])

_VIEW = "runtime.agent.view"
_CREATE = "runtime.agent.create"
_UPDATE = "runtime.agent.update"
_DELETE = "runtime.agent.delete"
_VALIDATE = "runtime.agent.validate"
_APPROVE = "runtime.agent.approve"
_ACTIVATE = "runtime.agent.activate"
_SUSPEND = "runtime.agent.suspend"
_RETIRE = "runtime.agent.retire"
_VERSION_VIEW = "runtime.version.view"
_VERSION_CREATE = "runtime.version.create"
_VERSION_PUBLISH = "runtime.version.publish"
_VERSION_DEPRECATE = "runtime.version.deprecate"
_VERSION_REVOKE = "runtime.version.revoke"
_VERSION_RETIRE = "runtime.version.retire"
_SIGNING_VIEW = "runtime.signing.view"
_SIGNING_MANAGE = "runtime.signing.manage"
_DEPLOY_VIEW = "runtime.deployment.view"
_DEPLOY_CREATE = "runtime.deployment.create"
_DEPLOY_ACTION = "runtime.deployment.deploy"
_DEPLOY_ROLLBACK = "runtime.deployment.rollback"
_ENV_VIEW = "runtime.environment.view"
_ENV_MANAGE = "runtime.environment.manage"
_EXEC_VIEW = "runtime.execution.view"
_EXEC_CREATE = "runtime.execution.create"
_EXEC_CANCEL = "runtime.execution.cancel"
_EXEC_RETRY = "runtime.execution.retry"
_CAPABILITY = "runtime.capability.manage"
_TOOL_MANAGE = "runtime.tool.manage"
_TOOL_ASSIGN = "runtime.tool.assign"
_HEALTH = "runtime.health.view"
_TELEMETRY = "runtime.telemetry.view"
_COST = "runtime.cost.view"
_PROVIDER_VIEW = "runtime.provider.view"
_PROVIDER_MANAGE = "runtime.provider.manage"
_APPROVAL = "runtime.approval.review"
_KILL_SWITCH = "runtime.kill_switch.execute"
# Enterprise Agent Registry (Phase 5.1 §57).
_REGISTER = "runtime.agent.register"
_SUBMIT = "runtime.agent.submit"
_REJECT = "runtime.agent.reject"
_RESUME = "runtime.agent.resume"
_DEPRECATE = "runtime.agent.deprecate"
_ARCHIVE = "runtime.agent.archive"
_RESTORE = "runtime.agent.restore"
_IDENTITY_ASSOCIATE = "runtime.agent.identity.associate"
_IDENTITY_CREATE = "runtime.agent.identity.create"
_IDENTITY_REPLACE = "runtime.agent.identity.replace"
_OWNERSHIP_VIEW = "runtime.agent.ownership.view"
_OWNERSHIP_TRANSFER = "runtime.agent.ownership.transfer"
_VALIDATION_VIEW = "runtime.agent.validation.view"
_DUPLICATE_REVIEW = "runtime.agent.duplicate.review"
_IMPORT = "runtime.agent.import"
_EXPORT = "runtime.agent.export"
_AUDIT_VIEW = "runtime.agent.audit.view"


# --------------------------------------------------------------------------- #
# Dashboard (§70)
# --------------------------------------------------------------------------- #
@router.get("/dashboard", response_model=RuntimeDashboardRead)
def dashboard(actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return RuntimeDashboardService(db).snapshot(actor)


# --------------------------------------------------------------------------- #
# Agent registry (Phase 5.1 §16, §22, §36-§38, §54, §66)
# --------------------------------------------------------------------------- #
def _lifecycle_ctx(actor: User, request: Request, reason: str | None) -> dict:
    return {"reason": reason, "request_id": getattr(request.state, "request_id", None),
           "correlation_id": getattr(request.state, "request_id", None)}


@router.get("/agents", response_model=list[AgentRegistryRead])
def list_agents(query: str | None = Query(default=None), project_id: uuid.UUID | None = Query(default=None),
                owner_id: uuid.UUID | None = Query(default=None), status_filter: str | None = Query(
                    default=None, alias="status"), agent_type: str | None = Query(default=None),
                framework: str | None = Query(default=None), criticality: str | None = Query(default=None),
                risk_level: str | None = Query(default=None),
                data_classification: str | None = Query(default=None),
                autonomy_level: str | None = Query(default=None), tag: list[str] | None = Query(default=None),
                view: str | None = Query(default=None), page: int = Query(default=1, ge=1),
                page_size: int = Query(default=50, ge=1, le=500),
                sort: str = Query(default="-created_at"),
                actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    """§36-§38, §56 — search/filter/inventory-views. ``view`` selects one of
    the named SRS §37 views (e.g. ``ACTIVE``, ``HIGH_RISK``, ``MY_AGENTS``,
    ``ORPHANED``, ``RECENTLY_UPDATED``); explicit filters are ignored when a
    view is given."""
    search = AgentSearchService(db)
    if view:
        rows, _total = search.view(actor, view, page=page, page_size=page_size)
        return rows
    rows, _total = search.search(
        actor, query=query, project_id=project_id, owner_id=owner_id, status=status_filter,
        agent_type=agent_type, framework=framework, criticality=criticality, risk_level=risk_level,
        data_classification=data_classification, autonomy_level=autonomy_level, tags=tag,
        page=page, page_size=page_size, sort=sort,
    )
    return rows


@router.post("/agents", response_model=AgentRegistryRead, status_code=status.HTTP_201_CREATED)
def register_agent(payload: AgentRegistrationCreate, actor: User = Depends(require_permission(_CREATE)),
                   db: Session = Depends(get_db)):
    return AgentRegistryService(db).register(actor, payload.model_dump())


@router.get("/agents/{agent_id}", response_model=AgentRegistryRead)
def get_agent(agent_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return AgentRegistryService(db).get_or_404(actor, agent_id)


@router.put("/agents/{agent_id}", response_model=AgentRegistryRead)
@router.patch("/agents/{agent_id}", response_model=AgentRegistryRead)
def update_agent(agent_id: uuid.UUID, payload: AgentRegistryUpdate,
                 actor: User = Depends(require_permission(_UPDATE)), db: Session = Depends(get_db)):
    return AgentRegistryService(db).update(actor, agent_id, payload.model_dump(exclude_unset=True))


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(agent_id: uuid.UUID, actor: User = Depends(require_permission(_DELETE)),
                 db: Session = Depends(get_db)):
    svc = AgentRegistryService(db)
    agent = svc.get_or_404(actor, agent_id)
    if agent.lifecycle_status not in ("DRAFT",):
        raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                            "Only DRAFT agents can be deleted; retire active agents instead.")
    db.delete(agent)
    db.commit()


@router.get("/agents/{agent_id}/definitions", response_model=list[AgentDefinitionRead])
@router.get("/agents/{agent_id}/definition", response_model=list[AgentDefinitionRead])
def list_definitions(agent_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
                     db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    stmt = select(AgentDefinition).where(AgentDefinition.agent_id == agent_id).order_by(
        AgentDefinition.created_at.desc())
    return list(db.execute(stmt).scalars())


# --- Lifecycle actions (§19, §20, §54) --- #
@router.post("/agents/{agent_id}/register", response_model=AgentRegistryRead)
def register_lifecycle_action(agent_id: uuid.UUID, request: Request,
                              payload: AgentLifecycleActionRequest = AgentLifecycleActionRequest(),
                              actor: User = Depends(require_permission(_REGISTER)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentLifecycleService(db).register(actor, agent, **_lifecycle_ctx(actor, request, payload.reason))


@router.post("/agents/{agent_id}/validate", response_model=AgentRegistryRead)
def validate_agent(agent_id: uuid.UUID, request: Request,
                   payload: AgentLifecycleActionRequest = AgentLifecycleActionRequest(),
                   actor: User = Depends(require_permission(_VALIDATE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    agent, _run = AgentLifecycleService(db).start_validation(
        actor, agent, **_lifecycle_ctx(actor, request, payload.reason))
    return agent


@router.post("/agents/{agent_id}/submit-for-approval", response_model=AgentRegistryRead)
def submit_for_approval(agent_id: uuid.UUID, request: Request,
                        payload: AgentLifecycleActionRequest = AgentLifecycleActionRequest(),
                        actor: User = Depends(require_permission(_SUBMIT)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentLifecycleService(db).submit_for_approval(
        actor, agent, **_lifecycle_ctx(actor, request, payload.reason))


@router.post("/agents/{agent_id}/approve", response_model=AgentRegistryRead)
def approve_agent(agent_id: uuid.UUID, request: Request,
                  payload: AgentLifecycleActionRequest = AgentLifecycleActionRequest(),
                  actor: User = Depends(require_permission(_APPROVE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentLifecycleService(db).approve(actor, agent, **_lifecycle_ctx(actor, request, payload.reason))


@router.post("/agents/{agent_id}/reject", response_model=AgentRegistryRead)
def reject_agent(agent_id: uuid.UUID, request: Request, payload: AgentLifecycleActionRequest,
                 actor: User = Depends(require_permission(_REJECT)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    ctx = _lifecycle_ctx(actor, request, payload.reason)
    ctx.pop("reason")
    return AgentLifecycleService(db).reject(actor, agent, reason=payload.reason or "", **ctx)


@router.post("/agents/{agent_id}/activate", response_model=AgentRegistryRead)
def activate_agent(agent_id: uuid.UUID, request: Request,
                   payload: AgentLifecycleActionRequest = AgentLifecycleActionRequest(),
                   actor: User = Depends(require_permission(_ACTIVATE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentLifecycleService(db).activate(actor, agent, **_lifecycle_ctx(actor, request, payload.reason))


@router.post("/agents/{agent_id}/suspend", response_model=AgentRegistryRead)
def suspend_agent(agent_id: uuid.UUID, request: Request,
                  payload: AgentLifecycleActionRequest = AgentLifecycleActionRequest(),
                  actor: User = Depends(require_permission(_SUSPEND)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentLifecycleService(db).suspend(actor, agent, **_lifecycle_ctx(actor, request, payload.reason))


@router.post("/agents/{agent_id}/resume", response_model=AgentRegistryRead)
def resume_agent(agent_id: uuid.UUID, request: Request,
                 payload: AgentLifecycleActionRequest = AgentLifecycleActionRequest(),
                 actor: User = Depends(require_permission(_RESUME)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentLifecycleService(db).resume(actor, agent, **_lifecycle_ctx(actor, request, payload.reason))


@router.post("/agents/{agent_id}/deprecate", response_model=AgentRegistryRead)
def deprecate_agent(agent_id: uuid.UUID, request: Request,
                    payload: AgentLifecycleActionRequest = AgentLifecycleActionRequest(),
                    actor: User = Depends(require_permission(_DEPRECATE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentLifecycleService(db).deprecate(actor, agent, **_lifecycle_ctx(actor, request, payload.reason))


@router.post("/agents/{agent_id}/archive", response_model=AgentRegistryRead)
def archive_agent(agent_id: uuid.UUID, request: Request,
                  payload: AgentLifecycleActionRequest = AgentLifecycleActionRequest(),
                  actor: User = Depends(require_permission(_ARCHIVE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentLifecycleService(db).archive(actor, agent, **_lifecycle_ctx(actor, request, payload.reason))


@router.post("/agents/{agent_id}/restore", response_model=AgentRegistryRead)
def restore_agent(agent_id: uuid.UUID, request: Request,
                  payload: AgentLifecycleActionRequest = AgentLifecycleActionRequest(),
                  actor: User = Depends(require_permission(_RESTORE)), db: Session = Depends(get_db)):
    """§20 — ARCHIVED -> DRAFT, 'only when restoration is authorized':
    gated behind its own ``runtime.agent.restore`` permission, deliberately
    separate from every other lifecycle action's permission."""
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentLifecycleService(db).restore(actor, agent, **_lifecycle_ctx(actor, request, payload.reason))


@router.post("/agents/{agent_id}/retire", response_model=AgentRegistryRead)
def retire_agent(agent_id: uuid.UUID, request: Request,
                 payload: AgentLifecycleActionRequest = AgentLifecycleActionRequest(),
                 actor: User = Depends(require_permission(_RETIRE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentLifecycleService(db).retire(actor, agent, **_lifecycle_ctx(actor, request, payload.reason))


# --------------------------------------------------------------------------- #
# Ownership (§12, §13, §54)
# --------------------------------------------------------------------------- #
@router.get("/agents/{agent_id}/ownership", response_model=AgentOwnershipRead)
def get_ownership(agent_id: uuid.UUID, actor: User = Depends(require_permission(_OWNERSHIP_VIEW)),
                  db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentOwnershipRead(owner_type=agent.owner_type, owner_id=agent.owner_id,
                              technical_owner_id=agent.technical_owner_id,
                              compliance_owner_id=agent.compliance_owner_id)


@router.post("/agents/{agent_id}/ownership/transfer", response_model=AgentRegistryRead)
def transfer_ownership(agent_id: uuid.UUID, payload: OwnershipTransferRequest,
                       actor: User = Depends(require_permission(_OWNERSHIP_TRANSFER)),
                       db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentOwnershipService(db).transfer(
        actor, agent, owner_role=payload.owner_role, new_owner_type=payload.new_owner_type,
        new_owner_id=payload.new_owner_id, reason=payload.reason)


@router.get("/agents/{agent_id}/ownership/history", response_model=list[OwnershipHistoryRead])
def ownership_history(agent_id: uuid.UUID, actor: User = Depends(require_permission(_OWNERSHIP_VIEW)),
                      db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentOwnershipService(db).history(agent_id)


# --------------------------------------------------------------------------- #
# Machine identity (§11, §54)
# --------------------------------------------------------------------------- #
@router.get("/agents/{agent_id}/identity", response_model=AgentIdentityRead | None)
def get_identity(agent_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
                 db: Session = Depends(get_db)):
    from app.identity.models.agent_identity import AgentIdentity

    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    if agent.identity_id is None:
        return None
    return db.get(AgentIdentity, agent.identity_id)


@router.post("/agents/{agent_id}/identity/associate", response_model=AgentRegistryRead)
def associate_identity(agent_id: uuid.UUID, payload: IdentityAssociateRequest,
                       actor: User = Depends(require_permission(_IDENTITY_ASSOCIATE)),
                       db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentIdentityAssociationService(db).associate(actor, agent, payload.identity_id)


@router.post("/agents/{agent_id}/identity/create-and-associate", response_model=AgentRegistryRead)
def create_and_associate_identity(agent_id: uuid.UUID, payload: IdentityCreateAndAssociateRequest,
                                  actor: User = Depends(require_permission(_IDENTITY_CREATE)),
                                  db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentIdentityAssociationService(db).create_and_associate(
        actor, agent, client_id=payload.client_id, credential_type=payload.credential_type,
        expires_at=payload.expires_at)


@router.post("/agents/{agent_id}/identity/replace", response_model=AgentRegistryRead)
def replace_identity(agent_id: uuid.UUID, payload: IdentityReplaceRequest,
                     actor: User = Depends(require_permission(_IDENTITY_REPLACE)),
                     db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentIdentityAssociationService(db).replace(
        actor, agent, client_id=payload.client_id, credential_type=payload.credential_type,
        expires_at=payload.expires_at, reason=payload.reason)


# --------------------------------------------------------------------------- #
# Validation (§25-§30, §54)
# --------------------------------------------------------------------------- #
@router.get("/agents/{agent_id}/validations", response_model=list[ValidationRunRead])
def list_validations(agent_id: uuid.UUID, actor: User = Depends(require_permission(_VALIDATION_VIEW)),
                     db: Session = Depends(get_db)):
    from app.models.agent_registry import AgentValidationRun

    AgentRegistryService(db).get_or_404(actor, agent_id)
    stmt = select(AgentValidationRun).where(AgentValidationRun.agent_id == agent_id).order_by(
        AgentValidationRun.created_at.desc())
    return list(db.execute(stmt).scalars())


@router.get("/agents/{agent_id}/validations/{validation_id}", response_model=ValidationRunRead)
def get_validation(agent_id: uuid.UUID, validation_id: uuid.UUID,
                   actor: User = Depends(require_permission(_VALIDATION_VIEW)), db: Session = Depends(get_db)):
    from app.models.agent_registry import AgentValidationRun

    AgentRegistryService(db).get_or_404(actor, agent_id)
    run = db.get(AgentValidationRun, validation_id)
    if run is None or run.agent_id != agent_id:
        raise IdentityError(ErrorCode.VALIDATION_ERROR, "Validation run not found.")
    return run


@router.post("/agents/{agent_id}/validations/run", response_model=ValidationRunRead)
def run_validation(agent_id: uuid.UUID, request: Request,
                   actor: User = Depends(require_permission(_VALIDATE)), db: Session = Depends(get_db)):
    """Alias for the ``/validate`` lifecycle action that returns the
    validation report itself rather than the agent (SRS §54's
    ``POST .../validations/run``)."""
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    _agent, run = AgentLifecycleService(db).start_validation(actor, agent, **_lifecycle_ctx(actor, request, None))
    return run


@router.post("/agents/{agent_id}/schemas/test", response_model=SchemaTestResponse)
def test_schema(agent_id: uuid.UUID, payload: SchemaTestRequest,
                actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    """SRS §30 — sample-payload testing against the agent's current
    definition contracts."""
    AgentRegistryService(db).get_or_404(actor, agent_id)
    stmt = select(AgentDefinition).where(AgentDefinition.agent_id == agent_id).order_by(
        AgentDefinition.created_at.desc()).limit(1)
    definition = db.execute(stmt).scalar_one_or_none()
    if definition is None:
        raise IdentityError(ErrorCode.AGENT_DEFINITION_REQUIRED, "Agent has no definition.")
    schema = {"INPUT": definition.input_schema, "OUTPUT": definition.output_schema,
             "CONFIGURATION": definition.configuration_schema}.get(payload.schema_type) or {}
    errors = validate_sample_payload(schema, payload.payload)
    return SchemaTestResponse(valid=not errors, errors=errors)


# --------------------------------------------------------------------------- #
# Duplicate detection (§32, §33, §54, §64)
# --------------------------------------------------------------------------- #
@router.post("/agents/{agent_id}/duplicate-check", response_model=list[DuplicateMatchRead])
def duplicate_check(agent_id: uuid.UUID, actor: User = Depends(require_permission(_UPDATE)),
                    db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentDuplicateDetectionService(db).check(actor, agent)


@router.get("/agents/{agent_id}/duplicate-matches", response_model=list[DuplicateMatchRead])
def duplicate_matches(agent_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
                      db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentDuplicateDetectionService(db).list_matches(agent_id)


@router.post("/agents/{agent_id}/duplicate-matches/{match_id}/review", response_model=DuplicateMatchRead)
def review_duplicate(agent_id: uuid.UUID, match_id: uuid.UUID, payload: DuplicateReviewRequest,
                     actor: User = Depends(require_permission(_DUPLICATE_REVIEW)), db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentDuplicateDetectionService(db).review(
        actor, match_id, decision=payload.review_decision, reason=payload.review_reason)


# --------------------------------------------------------------------------- #
# Lifecycle & audit history (§21, §38 Lifecycle/Audit tabs)
# --------------------------------------------------------------------------- #
@router.get("/agents/{agent_id}/lifecycle-events", response_model=list[AgentLifecycleEventRead])
def agent_lifecycle_events(agent_id: uuid.UUID, actor: User = Depends(require_permission(_AUDIT_VIEW)),
                          db: Session = Depends(get_db)):
    from app.models.agent_registry import AgentLifecycleEvent

    AgentRegistryService(db).get_or_404(actor, agent_id)
    stmt = select(AgentLifecycleEvent).where(AgentLifecycleEvent.agent_id == agent_id).order_by(
        AgentLifecycleEvent.created_at.desc())
    return list(db.execute(stmt).scalars())


@router.get("/agents/{agent_id}/events", response_model=list[RuntimeEventRead])
def agent_runtime_events(agent_id: uuid.UUID, actor: User = Depends(require_permission(_AUDIT_VIEW)),
                        db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    stmt = select(RuntimeEvent).where(RuntimeEvent.agent_id == agent_id).order_by(RuntimeEvent.created_at.desc())
    return list(db.execute(stmt).scalars())


# --------------------------------------------------------------------------- #
# Import / export (§39-§45, §54)
# --------------------------------------------------------------------------- #
@router.post("/agents/import", response_model=ImportJobRead)
def import_agents(payload: ImportRequest, actor: User = Depends(require_permission(_IMPORT)),
                  db: Session = Depends(get_db)):
    return AgentImportService(db).run_job(actor, file_name=payload.file_name, fmt=payload.format,
                                          mode=payload.mode, content=payload.content)


@router.get("/agents/import/{job_id}", response_model=ImportJobRead)
def get_import_job(job_id: uuid.UUID, actor: User = Depends(require_permission(_IMPORT)),
                   db: Session = Depends(get_db)):
    from app.models.agent_registry import AgentImportJob

    job = db.get(AgentImportJob, job_id)
    if job is None or job.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.AGENT_IMPORT_INVALID, "Import job not found.")
    return job


@router.get("/agents/import/{job_id}/items", response_model=list[ImportItemRead])
def get_import_items(job_id: uuid.UUID, actor: User = Depends(require_permission(_IMPORT)),
                     db: Session = Depends(get_db)):
    from app.models.agent_registry import AgentImportJob

    job = db.get(AgentImportJob, job_id)
    if job is None or job.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.AGENT_IMPORT_INVALID, "Import job not found.")
    return AgentImportService(db).list_items(job_id)


@router.post("/agents/export", response_model=ExportJobRead)
def export_agents(payload: ExportRequest, actor: User = Depends(require_permission(_EXPORT)),
                  db: Session = Depends(get_db)):
    return AgentExportService(db).run_job(actor, export_type=payload.export_type, fmt=payload.format,
                                          filters=payload.filters)


@router.get("/agents/export/{job_id}", response_model=ExportJobRead)
def get_export_job(job_id: uuid.UUID, actor: User = Depends(require_permission(_EXPORT)),
                   db: Session = Depends(get_db)):
    from app.models.agent_registry import AgentExportJob

    job = db.get(AgentExportJob, job_id)
    if job is None or job.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.AGENT_EXPORT_DENIED, "Export job not found.")
    return job


@router.get("/agents/export/{job_id}/download")
def download_export(job_id: uuid.UUID, actor: User = Depends(require_permission(_EXPORT)),
                    db: Session = Depends(get_db)):
    from fastapi.responses import PlainTextResponse

    from app.models.agent_registry import AgentExportJob

    job = db.get(AgentExportJob, job_id)
    if job is None or job.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.AGENT_EXPORT_DENIED, "Export job not found.")
    media_type = {"JSON": "application/json", "YAML": "application/yaml", "CSV": "text/csv"}.get(
        job.format, "text/plain")
    return PlainTextResponse(content=job.payload or "", media_type=media_type)


# --------------------------------------------------------------------------- #
# Legacy migration classification (§70-§73)
# --------------------------------------------------------------------------- #
@router.post("/agents/migration/classify", response_model=list[MigrationRecordRead])
def classify_legacy_agents(actor: User = Depends(require_permission(_IMPORT)), db: Session = Depends(get_db)):
    """§70-§71 — classifies every not-yet-classified agent in the caller's
    organization (idempotent; re-running only classifies new/unclassified
    rows) and opportunistically backfills derivable org-hierarchy columns."""
    return AgentMigrationService(db).classify_all(actor)


@router.get("/agents/migration/records", response_model=list[MigrationRecordRead])
def list_migration_records(batch_id: str | None = Query(default=None),
                           actor: User = Depends(require_permission(_IMPORT)), db: Session = Depends(get_db)):
    return AgentMigrationService(db).list_records(actor, batch_id=batch_id)


# --------------------------------------------------------------------------- #
# Agent versions (§11, §12, §66)
# --------------------------------------------------------------------------- #
@router.get("/agents/{agent_id}/versions", response_model=list[AgentVersionRead])
def list_versions(agent_id: uuid.UUID, actor: User = Depends(require_permission(_VERSION_VIEW)),
                  db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentVersionService(db).list(agent_id)


@router.post("/agents/{agent_id}/versions", response_model=AgentVersionRead, status_code=status.HTTP_201_CREATED)
def create_version(agent_id: uuid.UUID, payload: AgentVersionCreate,
                   actor: User = Depends(require_permission(_VERSION_CREATE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentVersionService(db).create(actor, agent, payload.model_dump())


@router.get("/agents/{agent_id}/versions/{version_id}", response_model=AgentVersionRead)
def get_version(agent_id: uuid.UUID, version_id: uuid.UUID,
                actor: User = Depends(require_permission(_VERSION_VIEW)), db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentVersionService(db).get_or_404(actor, agent_id, version_id)


@router.post("/agents/{agent_id}/versions/{version_id}/validate", response_model=AgentVersionRead)
def validate_version(agent_id: uuid.UUID, version_id: uuid.UUID,
                     actor: User = Depends(require_permission(_VERSION_CREATE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentVersionService(db).validate(actor, agent, version_id)


@router.post("/agents/{agent_id}/versions/{version_id}/approve", response_model=AgentVersionRead)
def approve_version(agent_id: uuid.UUID, version_id: uuid.UUID,
                    actor: User = Depends(require_permission(_APPROVE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentVersionService(db).approve(actor, agent, version_id)


@router.post("/agents/{agent_id}/versions/{version_id}/publish", response_model=AgentVersionRead)
def publish_version(agent_id: uuid.UUID, version_id: uuid.UUID, request: Request,
                    actor: User = Depends(require_permission(_VERSION_PUBLISH)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentVersionService(db).publish(actor, agent, version_id,
                                           correlation_id=request.headers.get("x-correlation-id"),
                                           source_ip=request.client.host if request.client else None)


@router.post("/agents/{agent_id}/versions/{version_id}/deprecate", response_model=AgentVersionRead)
def deprecate_version(agent_id: uuid.UUID, version_id: uuid.UUID,
                      actor: User = Depends(require_permission(_VERSION_DEPRECATE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentVersionService(db).deprecate(actor, agent, version_id)


@router.post("/agents/{agent_id}/versions/{version_id}/revoke", response_model=AgentVersionRead)
def revoke_version(agent_id: uuid.UUID, version_id: uuid.UUID,
                   payload: RevokeVersionRequest = RevokeVersionRequest(),
                   actor: User = Depends(require_permission(_VERSION_REVOKE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentVersionService(db).revoke(actor, agent, version_id, reason=payload.reason)


@router.post("/agents/{agent_id}/versions/{version_id}/retire", response_model=AgentVersionRead)
def retire_version(agent_id: uuid.UUID, version_id: uuid.UUID,
                   actor: User = Depends(require_permission(_VERSION_RETIRE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentVersionService(db).retire(actor, agent, version_id)


# --------------------------------------------------------------------------- #
# Version release management (Phase 5.2 Part 1 — snapshot, lineage, release
# metadata, artifacts, notes, status history, release channels)
# --------------------------------------------------------------------------- #
@router.get("/agents/{agent_id}/versions/{version_id}/snapshot", response_model=VersionSnapshotRead | None)
def get_version_snapshot(agent_id: uuid.UUID, version_id: uuid.UUID,
                         actor: User = Depends(require_permission(_VERSION_VIEW)), db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return db.execute(
        select(AgentVersionSnapshot).where(AgentVersionSnapshot.agent_version_id == version_id)
    ).scalar_one_or_none()


@router.get("/agents/{agent_id}/versions/{version_id}/status-history", response_model=list[VersionStatusHistoryRead])
def get_version_status_history(agent_id: uuid.UUID, version_id: uuid.UUID,
                               actor: User = Depends(require_permission(_VERSION_VIEW)),
                               db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return list_status_history(db, version_id)


@router.post("/agents/{agent_id}/versions/{version_id}/rollback-target", response_model=AgentVersionRead)
def set_version_rollback_target(agent_id: uuid.UUID, version_id: uuid.UUID, payload: RollbackTargetRequest,
                                actor: User = Depends(require_permission(_VERSION_CREATE)),
                                db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    version = AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    version = VersionLineageService(db).set_rollback_target(version, payload.target_version_id)
    _record_event(db, AuthorizationAuditEvent.RUNTIME_VERSION_ROLLBACK_TARGET_SET, actor,
                 organization_id=actor.organization_id, agent_id=agent.id,
                 meta={"version_id": str(version_id), "target_version_id": str(payload.target_version_id)})
    db.commit()
    db.refresh(version)
    return version


@router.get("/agents/{agent_id}/versions/{version_id}/release-metadata", response_model=ReleaseMetadataRead | None)
def get_release_metadata(agent_id: uuid.UUID, version_id: uuid.UUID,
                         actor: User = Depends(require_permission(_VERSION_VIEW)), db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return ReleaseMetadataService(db).get(version_id)


@router.post("/agents/{agent_id}/versions/{version_id}/release-metadata", response_model=ReleaseMetadataRead)
def upsert_release_metadata(agent_id: uuid.UUID, version_id: uuid.UUID, payload: ReleaseMetadataUpsert,
                            actor: User = Depends(require_permission(_VERSION_CREATE)),
                            db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    version = AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return ReleaseMetadataService(db).upsert(actor, agent.id, version, payload.model_dump(exclude_unset=True))


@router.get("/agents/{agent_id}/versions/{version_id}/artifacts", response_model=list[ReleaseArtifactRead])
def list_release_artifacts(agent_id: uuid.UUID, version_id: uuid.UUID,
                           actor: User = Depends(require_permission(_VERSION_VIEW)), db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return ReleaseArtifactService(db).list(version_id)


@router.post("/agents/{agent_id}/versions/{version_id}/artifacts", response_model=ReleaseArtifactRead,
            status_code=status.HTTP_201_CREATED)
def add_release_artifact(agent_id: uuid.UUID, version_id: uuid.UUID, payload: ReleaseArtifactCreate,
                         actor: User = Depends(require_permission(_VERSION_CREATE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    version = AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return ReleaseArtifactService(db).add(actor, agent.id, version, artifact_type=payload.artifact_type,
                                          reference=payload.reference)


@router.get("/agents/{agent_id}/versions/{version_id}/notes", response_model=list[ReleaseNoteRead])
def list_release_notes(agent_id: uuid.UUID, version_id: uuid.UUID,
                       actor: User = Depends(require_permission(_VERSION_VIEW)), db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return ReleaseNoteService(db).list(version_id)


@router.post("/agents/{agent_id}/versions/{version_id}/notes", response_model=ReleaseNoteRead,
            status_code=status.HTTP_201_CREATED)
def add_release_note(agent_id: uuid.UUID, version_id: uuid.UUID, payload: ReleaseNoteCreate,
                     actor: User = Depends(require_permission(_VERSION_CREATE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    version = AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return ReleaseNoteService(db).add(actor, agent.id, version, category=payload.category, note=payload.note)


@router.get("/release-channels", response_model=list[ReleaseChannelRead])
def list_release_channels(actor: User = Depends(require_permission(_VERSION_VIEW)), db: Session = Depends(get_db)):
    service = ReleaseChannelService(db)
    service.ensure_seeded()
    db.commit()
    return service.list()


@router.get("/agents/{agent_id}/versions/{version_id}/compare/{other_version_id}",
           response_model=VersionComparisonRead)
def compare_versions(agent_id: uuid.UUID, version_id: uuid.UUID, other_version_id: uuid.UUID,
                     actor: User = Depends(require_permission(_VERSION_VIEW)), db: Session = Depends(get_db)):
    """SRS §3 — version comparison; works regardless of either version's
    lifecycle status."""
    AgentRegistryService(db).get_or_404(actor, agent_id)
    version_a = AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    version_b = AgentVersionService(db).get_or_404(actor, agent_id, other_version_id)
    return VersionComparisonService(db).compare(version_a, version_b)


@router.get("/agents/{agent_id}/versions/{version_id}/readiness", response_model=VersionReadinessRead)
def version_readiness(agent_id: uuid.UUID, version_id: uuid.UUID,
                      actor: User = Depends(require_permission(_VERSION_VIEW)), db: Session = Depends(get_db)):
    """SRS §3, §30 — promotion readiness: a read-only diagnostic checklist,
    never a gate enforced by the lifecycle actions themselves."""
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    version = AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return VersionReadinessService(db).check(agent, version)


@router.get("/agents/{agent_id}/versions/{version_id}/compatibility", response_model=CompatibilityReportRead)
def get_version_compatibility(agent_id: uuid.UUID, version_id: uuid.UUID,
                              baseline_version_id: uuid.UUID | None = Query(default=None),
                              actor: User = Depends(require_permission(_VERSION_VIEW)),
                              db: Session = Depends(get_db)):
    """Phase 5.2.6 — with no override, returns the last-persisted report
    (read-only, no recomputation). An explicit ``baseline_version_id``
    evaluates ephemerally against that baseline instead, without persisting
    anything — e.g. to preview compatibility against the current occupant of
    a release channel."""
    AgentRegistryService(db).get_or_404(actor, agent_id)
    AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    service = CompatibilityAnalysisService(db)
    if baseline_version_id is not None:
        return service.analyze(version_id, agent_id=agent_id, baseline_id=baseline_version_id, persist=False)
    return service.get_report(version_id)


@router.post("/agents/{agent_id}/versions/{version_id}/compatibility/analyze",
             response_model=CompatibilityReportRead)
def analyze_version_compatibility(agent_id: uuid.UUID, version_id: uuid.UUID,
                                  baseline_version_id: uuid.UUID | None = Query(default=None),
                                  actor: User = Depends(require_permission(_VERSION_VIEW)),
                                  db: Session = Depends(get_db)):
    """Recomputes and persists — useful after the analyzer improves, and for
    versions published before this phase existed."""
    AgentRegistryService(db).get_or_404(actor, agent_id)
    AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return CompatibilityAnalysisService(db).analyze(version_id, agent_id=agent_id, baseline_id=baseline_version_id)


@router.get("/agents/{agent_id}/versions/{version_id}/compatibility/findings",
           response_model=list[CompatibilityFindingRead])
def list_version_compatibility_findings(agent_id: uuid.UUID, version_id: uuid.UUID,
                                        actor: User = Depends(require_permission(_VERSION_VIEW)),
                                        db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return CompatibilityAnalysisService(db).list_findings(version_id)


# --------------------------------------------------------------------------- #
# Cryptographic signing, provenance & attestation (Phase 5.2.4) — no public or
# unauthenticated route here (ACT-VER-FR-070 deferred; see
# docs/runtime/versioning.md's Known Deviations) — every endpoint below
# requires authentication and is scoped to the caller's organization via
# AgentRegistryService.get_or_404.
# --------------------------------------------------------------------------- #
@router.get("/agents/{agent_id}/versions/{version_id}/signatures", response_model=list[SignatureRead])
def list_version_signatures(agent_id: uuid.UUID, version_id: uuid.UUID,
                            actor: User = Depends(require_permission(_VERSION_VIEW)),
                            db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return AttestationService(db).list_signatures(version_id)


@router.get("/agents/{agent_id}/versions/{version_id}/provenance", response_model=ProvenanceRead | None)
def get_version_provenance(agent_id: uuid.UUID, version_id: uuid.UUID,
                           actor: User = Depends(require_permission(_VERSION_VIEW)),
                           db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return AttestationService(db).get_provenance(version_id)


@router.get("/agents/{agent_id}/versions/{version_id}/attestation", response_model=AttestationRead)
def get_version_attestation(agent_id: uuid.UUID, version_id: uuid.UUID,
                            actor: User = Depends(require_permission(_VERSION_VIEW)),
                            db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    version = AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return AttestationService(db).get_attestation(version)


@router.post("/agents/{agent_id}/versions/{version_id}/verify", response_model=VerificationResultRead)
def verify_version(agent_id: uuid.UUID, version_id: uuid.UUID,
                   actor: User = Depends(require_permission(_VERSION_VIEW)), db: Session = Depends(get_db)):
    """Independently re-verifies every signature over this version plus
    whether the frozen snapshot still matches what was signed — never
    trusts the persisted ``verification_status`` alone."""
    AgentRegistryService(db).get_or_404(actor, agent_id)
    version = AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return AttestationService(db).verify(version)


@router.post("/agents/{agent_id}/versions/{version_id}/countersign", response_model=SignatureRead,
            status_code=status.HTTP_201_CREATED)
def countersign_version(agent_id: uuid.UUID, version_id: uuid.UUID,
                        actor: User = Depends(require_permission(_APPROVE)), db: Session = Depends(get_db)):
    """Adds an additional, independent signature over the same payload the
    ``PUBLISHER`` signature covers (``ACT-VER-FR-069``). Gated by
    ``runtime.agent.approve`` — the permission that already governs
    approving a version (``_APPROVE`` — see ``approve_version`` above); no
    separate ``runtime.version.approve`` code exists in this codebase, and
    inventing a synonym for one that already gates the same action would
    only add catalog bloat."""
    AgentRegistryService(db).get_or_404(actor, agent_id)
    version = AgentVersionService(db).get_or_404(actor, agent_id, version_id)
    return AttestationService(db).countersign(version, actor_id=actor.id)


@router.get("/signing-keys", response_model=list[SigningKeyRead])
def list_signing_keys(actor: User = Depends(require_permission(_SIGNING_VIEW)), db: Session = Depends(get_db)):
    return SigningKeyService(db).list()


@router.post("/signing-keys/{key_id}/rotate", response_model=SigningKeyRead)
def rotate_signing_key(key_id: str, actor: User = Depends(require_permission(_SIGNING_MANAGE)),
                       db: Session = Depends(get_db)):
    return SigningKeyService(db).rotate(key_id)


@router.post("/signing-keys/{key_id}/revoke", response_model=SigningKeyRead)
def revoke_signing_key(key_id: str, payload: RevokeSigningKeyRequest = RevokeSigningKeyRequest(),
                       actor: User = Depends(require_permission(_SIGNING_MANAGE)), db: Session = Depends(get_db)):
    return SigningKeyService(db).revoke(key_id, reason=payload.reason)


# --------------------------------------------------------------------------- #
# Provider credentials (Phase 5.7a.5 SRS ACT-MDL-FR-080..083)
#
# Per-organization: every method below scopes by ``actor.organization_id``,
# never by a caller-supplied id, so org A structurally cannot reach org B's
# row (ACT-PLT-NFR-001) -- the same discipline every other org-scoped
# resource in this router already follows (see get_or_404 elsewhere).
# --------------------------------------------------------------------------- #
@router.get("/providers/credentials", response_model=list[ProviderCredentialRead])
def list_provider_credentials(actor: User = Depends(require_permission(_PROVIDER_VIEW)),
                              db: Session = Depends(get_db)):
    return ProviderCredentialService(db).list_for_org(actor.organization_id)


@router.put("/providers/{provider}/credentials", response_model=ProviderCredentialRead)
def upsert_provider_credential(provider: str, payload: ProviderCredentialUpsert,
                               actor: User = Depends(require_permission(_PROVIDER_MANAGE)),
                               db: Session = Depends(get_db)):
    """Create or replace-and-re-encrypt (AC-16) — the request body is never
    logged or echoed back; the response carries metadata and a masked hint
    only (ACT-MDL-FR-081)."""
    return ProviderCredentialService(db).store(
        actor, actor.organization_id, provider.upper(), payload.secret, base_url=payload.base_url,
    )


@router.delete("/providers/{provider}/credentials", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider_credential(provider: str, actor: User = Depends(require_permission(_PROVIDER_MANAGE)),
                               db: Session = Depends(get_db)):
    ProviderCredentialService(db).delete(actor, actor.organization_id, provider.upper())


@router.post("/providers/{provider}/credentials/test", response_model=ProviderCredentialTestResult)
def test_provider_credential(provider: str, actor: User = Depends(require_permission(_PROVIDER_MANAGE)),
                             db: Session = Depends(get_db)):
    """A minimal real call through whatever credential currently resolves
    for this org/provider (stored, or the fallback), classified via the
    Phase 5.7a.4 taxonomy. Never returns the credential itself."""
    return ProviderCredentialService(db).test(actor.organization_id, provider.upper())


# --------------------------------------------------------------------------- #
# Deployments (§14, §15, §57, §66)
# --------------------------------------------------------------------------- #
@router.get("/deployments", response_model=list[DeploymentRead])
def list_deployments(agent_id: uuid.UUID | None = Query(default=None), status_filter: str | None = Query(
                     default=None, alias="status"), actor: User = Depends(require_permission(_DEPLOY_VIEW)),
                     db: Session = Depends(get_db)):
    return DeploymentService(db).list(actor, agent_id=agent_id, status=status_filter)


@router.post("/deployments", response_model=DeploymentRead, status_code=status.HTTP_201_CREATED)
def create_deployment(payload: DeploymentCreate, agent_id: uuid.UUID = Query(...),
                      idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                      actor: User = Depends(require_permission(_DEPLOY_CREATE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    version = AgentVersionService(db).get_or_404(actor, agent_id, payload.agent_version_id)
    result, _replayed = DeploymentLifecycleService(db).create(
        actor, agent, version, payload.model_dump(exclude={"agent_version_id"}),
        idempotency_key=idempotency_key,
    )
    return result


@router.get("/deployments/{deployment_id}", response_model=DeploymentRead)
def get_deployment(deployment_id: uuid.UUID, actor: User = Depends(require_permission(_DEPLOY_VIEW)),
                   db: Session = Depends(get_db)):
    return DeploymentService(db).get_or_404(actor, deployment_id)


@router.post("/deployments/{deployment_id}/deploy", response_model=DeploymentRead)
def deploy(deployment_id: uuid.UUID, actor: User = Depends(require_permission(_DEPLOY_ACTION)),
          db: Session = Depends(get_db)):
    return DeploymentService(db).deploy(actor, deployment_id)


@router.post("/deployments/{deployment_id}/suspend", response_model=DeploymentRead)
def suspend_deployment(deployment_id: uuid.UUID, actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                       db: Session = Depends(get_db)):
    return DeploymentService(db).suspend(actor, deployment_id)


@router.post("/deployments/{deployment_id}/resume", response_model=DeploymentRead)
def resume_deployment(deployment_id: uuid.UUID, actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                      db: Session = Depends(get_db)):
    return DeploymentService(db).resume(actor, deployment_id)


@router.post("/deployments/{deployment_id}/rollback", response_model=DeploymentRead)
def rollback_deployment(deployment_id: uuid.UUID, payload: DeploymentRollbackRequest,
                        actor: User = Depends(require_permission(_DEPLOY_ROLLBACK)), db: Session = Depends(get_db)):
    return DeploymentService(db).rollback(actor, deployment_id, payload.target_version_id)


@router.post("/deployments/{deployment_id}/retire", response_model=DeploymentRead)
def retire_deployment(deployment_id: uuid.UUID, actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                      db: Session = Depends(get_db)):
    return DeploymentService(db).retire(actor, deployment_id)


# --------------------------------------------------------------------------- #
# Phase 3.1 (ACT-SRS-M3 §3.1) -- the new governed deployment lifecycle.
# Nested under "/lifecycle" rather than reusing the legacy "/resume" and
# "/retire" paths directly above: FastAPI cannot register two handlers on
# one (path, method) pair, and those two legacy paths already exist,
# operating on the pre-existing `status` field. This phase deliberately
# leaves that legacy `DeploymentService`/`.status` machinery untouched
# (see app.runtime.deployment.service's own module docstring) rather than
# merge the two concepts, so a real conflict between this build prompt's
# literal `/pause`/`/resume`/`/retire` paths and the already-shipped routes
# above is resolved this way -- reported in docs/deployment/lifecycle.md
# rather than silently reusing the same path for two different machines.
# --------------------------------------------------------------------------- #
def _run_idempotent_lifecycle_command(db: Session, actor: User, *, operation: str,
                                      idempotency_key: str | None, payload: dict, fn) -> dict:
    from app.runtime.deployment.idempotency import IdempotencyService
    result, _replayed = IdempotencyService(db).execute(
        organization_id=actor.organization_id, operation=operation,
        key=idempotency_key, payload=payload, fn=fn,
    )
    return result


@router.post("/deployments/{deployment_id}/lifecycle/transition", response_model=DeploymentRead)
def transition_deployment(deployment_id: uuid.UUID, payload: DeploymentTransitionRequest,
                          idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                          actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                          db: Session = Depends(get_db)):
    service = DeploymentLifecycleService(db)

    def _do() -> dict:
        deployment = service.get_or_404(actor, deployment_id)
        # "DEPLOYING" from READY/APPROVED is the one transition with real
        # side effects beyond a bare state change (the READY-stage
        # approval-reroute, and the synchronous DEPLOYING->ACTIVE completion
        # -- there is no distributed worker in this phase to do it
        # out-of-band) -- see DeploymentLifecycleService.start_deploying's
        # own docstring for why this is not just another graph edge.
        if payload.to_state == "DEPLOYING" and deployment.lifecycle_state in ("READY", "APPROVED"):
            deployment = service.start_deploying(actor, deployment, reason=payload.reason,
                                                 expected_revision=payload.expected_revision)
        else:
            deployment = service.transition(actor, deployment, payload.to_state, reason=payload.reason,
                                            expected_revision=payload.expected_revision)
        return DeploymentRead.model_validate(deployment).model_dump(mode="json")

    return _run_idempotent_lifecycle_command(
        db, actor, operation="deployment.transition", idempotency_key=idempotency_key,
        payload={"deployment_id": str(deployment_id), **payload.model_dump()}, fn=_do,
    )


@router.post("/deployments/{deployment_id}/lifecycle/pause", response_model=DeploymentRead)
def pause_deployment_lifecycle(deployment_id: uuid.UUID, payload: DeploymentLifecycleActionRequest,
                               idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                               actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                               db: Session = Depends(get_db)):
    service = DeploymentLifecycleService(db)

    def _do() -> dict:
        deployment = service.get_or_404(actor, deployment_id)
        deployment = service.pause(actor, deployment, reason=payload.reason,
                                   expected_revision=payload.expected_revision)
        return DeploymentRead.model_validate(deployment).model_dump(mode="json")

    return _run_idempotent_lifecycle_command(
        db, actor, operation="deployment.pause", idempotency_key=idempotency_key,
        payload={"deployment_id": str(deployment_id), **payload.model_dump()}, fn=_do,
    )


@router.post("/deployments/{deployment_id}/lifecycle/resume", response_model=DeploymentRead)
def resume_deployment_lifecycle(deployment_id: uuid.UUID, payload: DeploymentLifecycleActionRequest,
                                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                                actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                                db: Session = Depends(get_db)):
    service = DeploymentLifecycleService(db)

    def _do() -> dict:
        deployment = service.get_or_404(actor, deployment_id)
        deployment = service.resume(actor, deployment, reason=payload.reason,
                                    expected_revision=payload.expected_revision)
        return DeploymentRead.model_validate(deployment).model_dump(mode="json")

    return _run_idempotent_lifecycle_command(
        db, actor, operation="deployment.resume", idempotency_key=idempotency_key,
        payload={"deployment_id": str(deployment_id), **payload.model_dump()}, fn=_do,
    )


@router.post("/deployments/{deployment_id}/lifecycle/retire", response_model=DeploymentRead)
def retire_deployment_lifecycle(deployment_id: uuid.UUID, payload: DeploymentLifecycleActionRequest,
                                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                                actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                                db: Session = Depends(get_db)):
    service = DeploymentLifecycleService(db)

    def _do() -> dict:
        deployment = service.get_or_404(actor, deployment_id)
        deployment = service.retire(actor, deployment, reason=payload.reason,
                                    expected_revision=payload.expected_revision)
        return DeploymentRead.model_validate(deployment).model_dump(mode="json")

    return _run_idempotent_lifecycle_command(
        db, actor, operation="deployment.retire", idempotency_key=idempotency_key,
        payload={"deployment_id": str(deployment_id), **payload.model_dump()}, fn=_do,
    )


@router.get("/deployments/{deployment_id}/lifecycle/events", response_model=list[DeploymentEventRead])
def list_deployment_lifecycle_events(deployment_id: uuid.UUID,
                                     actor: User = Depends(require_permission(_DEPLOY_VIEW)),
                                     db: Session = Depends(get_db)):
    return DeploymentLifecycleService(db).list_events(actor, deployment_id)


# --------------------------------------------------------------------------- #
# Phase 3.2 (ACT-SRS-M3 §3.2) -- promotion. "/deployments/{id}/promote" does
# not collide with any pre-existing path (unlike 3.1's own
# pause/resume/retire conflict), so it is used directly, exactly as the
# build prompt's own §6 suggests, rather than needing "/lifecycle/..."
# nesting. Reuses "_DEPLOY_ACTION" (runtime.deployment.deploy) rather than a
# third permission code -- a promotion *is* a deployment operation.
# --------------------------------------------------------------------------- #
@router.post("/deployments/{deployment_id}/promote", response_model=DeploymentRead)
def promote_deployment(deployment_id: uuid.UUID, payload: DeploymentPromoteRequest,
                       idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                       actor: User = Depends(require_permission(_DEPLOY_ACTION)), db: Session = Depends(get_db)):
    deployment = DeploymentLifecycleService(db).get_or_404(actor, deployment_id)
    result, _replayed = PromotionService(db).promote(
        actor, deployment, payload.to_environment_id, reason=payload.reason, idempotency_key=idempotency_key,
    )
    return result


# --------------------------------------------------------------------------- #
# Phase 3.3 (ACT-SRS-M3 §Phase-3.3) -- deployment preflight / release gate.
# Reuses "_DEPLOY_ACTION"/"_DEPLOY_VIEW" verbatim (build prompt §6): running
# an evaluation is a deployment operation, viewing one is a deployment read
# -- no third permission code. The API is the explicit/preview path;
# enforcement happens in-lifecycle (DeploymentLifecycleService.start_deploying).
# --------------------------------------------------------------------------- #
@router.post("/deployments/{deployment_id}/preflight", response_model=DeploymentPreflightRead)
def run_deployment_preflight(deployment_id: uuid.UUID, actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                             db: Session = Depends(get_db)):
    deployment = DeploymentLifecycleService(db).get_or_404(actor, deployment_id)
    return ReleaseGateService(db).evaluate(actor, deployment)


@router.get("/deployments/{deployment_id}/preflight", response_model=DeploymentPreflightRead | None)
def get_deployment_preflight(deployment_id: uuid.UUID, actor: User = Depends(require_permission(_DEPLOY_VIEW)),
                             db: Session = Depends(get_db)):
    return ReleaseGateService(db).get_latest(actor, deployment_id)


@router.get("/deployments/{deployment_id}/preflight/history", response_model=list[DeploymentPreflightRead])
def get_deployment_preflight_history(deployment_id: uuid.UUID, limit: int = Query(default=50, ge=1, le=200),
                                     offset: int = Query(default=0, ge=0),
                                     actor: User = Depends(require_permission(_DEPLOY_VIEW)),
                                     db: Session = Depends(get_db)):
    return ReleaseGateService(db).get_history(actor, deployment_id, limit=limit, offset=offset)


# --------------------------------------------------------------------------- #
# Phase 3.4 (ACT-SRS-M3 §Phase-3.4 §6) -- weighted traffic allocation.
#
# Mounted under ``/agents/{agent_id}/environments/{environment_id}/traffic``,
# not under ``/deployments/{id}/traffic``: an allocation spans *several*
# deployments of one agent in one environment, so hanging it off a single
# deployment id would make one of those deployments arbitrarily own the
# others' weights, and would leave the resolver's own lookup key (agent +
# environment) unexpressible in the URL. The build prompt offers both shapes
# and asks which was chosen and why -- this is the choice and the reason.
#
# Reuses "_DEPLOY_VIEW"/"_DEPLOY_ACTION" verbatim, as 3.2 and 3.3 already do:
# changing what serves production traffic is a deployment operation, reading
# it is a deployment read -- no fourth permission code.
# --------------------------------------------------------------------------- #
@router.get("/agents/{agent_id}/environments/{environment_id}/traffic",
            response_model=TrafficAllocationRead | None)
def get_traffic_allocation(agent_id: uuid.UUID, environment_id: uuid.UUID,
                           actor: User = Depends(require_permission(_DEPLOY_VIEW)),
                           db: Session = Depends(get_db)):
    service = TrafficAllocationService(db)
    agent, environment = service.resolve_scope(actor, agent_id, environment_id)
    allocation = service.current(actor.organization_id, agent.id, environment.id)
    if allocation is None:
        return None
    return service.read_model(allocation)


@router.put("/agents/{agent_id}/environments/{environment_id}/traffic",
            response_model=TrafficAllocationRead)
def set_traffic_allocation(agent_id: uuid.UUID, environment_id: uuid.UUID,
                           payload: TrafficAllocationWrite,
                           idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                           actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                           db: Session = Depends(get_db)):
    service = TrafficAllocationService(db)
    agent, environment = service.resolve_scope(actor, agent_id, environment_id)
    if payload.expected_revision is not None:
        current = service.current(actor.organization_id, agent.id, environment.id)
        observed = current.revision if current is not None else 0
        if observed != payload.expected_revision:
            raise IdentityError(
                ErrorCode.TRAFFIC_ALLOCATION_CONFLICT,
                "This agent's traffic allocation was changed by another request; reload and retry.",
            )
    result, _replayed = service.set_weights(
        actor, agent, environment,
        [entry.model_dump() for entry in payload.weights],
        reason=payload.reason, idempotency_key=idempotency_key,
    )
    return result


@router.get("/agents/{agent_id}/environments/{environment_id}/traffic/history",
            response_model=list[TrafficAllocationRead])
def get_traffic_allocation_history(agent_id: uuid.UUID, environment_id: uuid.UUID,
                                   limit: int = Query(default=50, ge=1, le=200),
                                   offset: int = Query(default=0, ge=0),
                                   actor: User = Depends(require_permission(_DEPLOY_VIEW)),
                                   db: Session = Depends(get_db)):
    service = TrafficAllocationService(db)
    agent, environment = service.resolve_scope(actor, agent_id, environment_id)
    return [service.read_model(allocation) for allocation in
            service.history(actor, agent.id, environment.id, limit=limit, offset=offset)]


# --------------------------------------------------------------------------- #
# Phase 3.5 (ACT-SRS-M3 §Phase-3.5 §6) -- the canary rollout engine.
#
# Mounted under the same agent+environment prefix Phase 3.4's traffic routes
# use, for the same reason: a rollout drives one (agent, environment)'s traffic
# allocation, which is exactly that tuple. The build prompt writes the paths as
# "/api/v1/agents/..."; they are mounted on this module's existing
# "/api/v1/runtime" router instead, so every runtime surface stays under one
# prefix -- the identical adjustment 3.4's traffic routes already made.
#
# Reuses "_DEPLOY_VIEW"/"_DEPLOY_ACTION" verbatim, as 3.2/3.3/3.4 do: driving a
# rollout is a deployment operation, reading one is a deployment read. No
# production-specific permission is introduced -- the pre-existing environment
# policy (Phase 3.2's ``requires_approval``, evaluated at deploy time) is where
# this codebase already expresses "production needs more authority", and adding
# a second, parallel mechanism here would fragment it.
# --------------------------------------------------------------------------- #
@router.post("/agents/{agent_id}/environments/{environment_id}/rollouts",
             response_model=RolloutPlanRead, status_code=status.HTTP_201_CREATED)
def create_rollout(agent_id: uuid.UUID, environment_id: uuid.UUID, payload: RolloutCreate,
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                   actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                   db: Session = Depends(get_db)):
    result, _replayed = CanaryRolloutService(db).create(
        actor, agent_id, environment_id,
        payload.model_dump(mode="json"), idempotency_key=idempotency_key,
    )
    return result


@router.get("/rollouts/{rollout_id}", response_model=RolloutPlanRead)
def get_rollout(rollout_id: uuid.UUID, actor: User = Depends(require_permission(_DEPLOY_VIEW)),
                db: Session = Depends(get_db)):
    service = CanaryRolloutService(db)
    return service.read_model(service.get_or_404(actor, rollout_id))


@router.get("/rollouts/{rollout_id}/health", response_model=RolloutHealthRead)
def get_rollout_health(rollout_id: uuid.UUID,
                       actor: User = Depends(require_permission(_DEPLOY_VIEW)),
                       db: Session = Depends(get_db)):
    service = CanaryRolloutService(db)
    plan = service.get_or_404(actor, rollout_id)
    # A read must not write: this evaluation is not persisted, unlike the one
    # an advance performs (which is retained as the evidence behind a gate
    # decision). Looking at a canary's health should not create an audit
    # record implying a gate was evaluated for a decision.
    gates, health = service.evaluate_gates(plan, actor=actor, persist=False)
    return {"current": health, "gates": gates.as_dict(),
            "history": HealthEvaluationService(db).latest_for_plan(plan.id)}


@router.post("/rollouts/{rollout_id}/advance", response_model=RolloutPlanRead)
def advance_rollout(rollout_id: uuid.UUID, payload: RolloutActionRequest | None = None,
                    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                    actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                    db: Session = Depends(get_db)):
    service = CanaryRolloutService(db)
    plan = service.get_or_404(actor, rollout_id)
    return service.advance(actor, plan, idempotency_key=idempotency_key)


@router.post("/rollouts/{rollout_id}/evaluate", response_model=RolloutPlanRead)
def evaluate_rollout(rollout_id: uuid.UUID,
                     idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                     actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                     db: Session = Depends(get_db)):
    """The interim auto-advance entry point (M3-3.5-FR-013): evaluate the
    current stage once and advance by at most one stage if it is AUTO and every
    gate is satisfied. Bounded and idempotent. **Interim until Phase 3.8**,
    whose real distributed scheduler will call this on a timer -- the same
    relationship ``app.integration.scheduler`` (Phase 2.1.3's interim
    in-process loop) already documents."""
    service = CanaryRolloutService(db)
    plan = service.get_or_404(actor, rollout_id)
    return service.evaluate_and_advance(actor, plan, idempotency_key=idempotency_key)


@router.post("/rollouts/{rollout_id}/pause", response_model=RolloutPlanRead)
def pause_rollout(rollout_id: uuid.UUID, payload: RolloutActionRequest | None = None,
                  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                  actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                  db: Session = Depends(get_db)):
    service = CanaryRolloutService(db)
    plan = service.get_or_404(actor, rollout_id)
    return service.pause(actor, plan, reason=payload.reason if payload else None,
                        idempotency_key=idempotency_key)


@router.post("/rollouts/{rollout_id}/resume", response_model=RolloutPlanRead)
def resume_rollout(rollout_id: uuid.UUID, payload: RolloutActionRequest | None = None,
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                   actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                   db: Session = Depends(get_db)):
    service = CanaryRolloutService(db)
    plan = service.get_or_404(actor, rollout_id)
    return service.resume(actor, plan, reason=payload.reason if payload else None,
                         idempotency_key=idempotency_key)


@router.post("/rollouts/{rollout_id}/abort", response_model=RolloutPlanRead)
def abort_rollout(rollout_id: uuid.UUID, payload: RolloutActionRequest | None = None,
                  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                  actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                  db: Session = Depends(get_db)):
    service = CanaryRolloutService(db)
    plan = service.get_or_404(actor, rollout_id)
    return service.abort(actor, plan, reason=payload.reason if payload else None,
                        idempotency_key=idempotency_key)


@router.post("/rollouts/{rollout_id}/promote", response_model=RolloutPlanRead)
def promote_rollout(rollout_id: uuid.UUID, payload: RolloutActionRequest | None = None,
                    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                    actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                    db: Session = Depends(get_db)):
    service = CanaryRolloutService(db)
    plan = service.get_or_404(actor, rollout_id)
    return service.promote(actor, plan, reason=payload.reason if payload else None,
                          idempotency_key=idempotency_key)


@router.post("/rollouts/{rollout_id}/request-rollback", response_model=RolloutPlanRead)
def request_rollout_rollback(rollout_id: uuid.UUID, payload: RolloutActionRequest | None = None,
                             idempotency_key: str | None = Header(default=None,
                                                                  alias="Idempotency-Key"),
                             actor: User = Depends(require_permission(_DEPLOY_ROLLBACK)),
                             db: Session = Depends(get_db)):
    """Uses ``runtime.deployment.rollback`` rather than ``.deploy``: this
    permission already exists for exactly this act, and rolling back is the one
    rollout operation an organization may well want to grant separately from
    the ability to push a canary forward."""
    service = CanaryRolloutService(db)
    plan = service.get_or_404(actor, rollout_id)
    return service.request_rollback(actor, plan, reason=payload.reason if payload else None,
                                    idempotency_key=idempotency_key)


# --------------------------------------------------------------------------- #
# Phase 3.6 (ACT-SRS-M3 §Phase-3.6 §6) -- deployment strategy execution.
#
# **A unified execute endpoint, dispatching on the column** -- the build prompt
# offers either a per-strategy path or a unified one, and this is the choice
# plus the reason: M3-3.6-FR-001 asks for one abstraction dispatched on
# ``agent_deployments.deployment_strategy``, and a ``/strategy/recreate`` path
# would let a caller run a recreate on a deployment declared BLUE_GREEN, making
# the column decorative again. The declaration on the row is the input; to
# deploy differently, change the declaration. The strategy is deliberately NOT
# taken from the request body for the same reason.
#
# Blue-green's switch and rollback are separate endpoints because they are
# separate operator decisions: warming a candidate is not agreeing to send it
# production traffic, and rolling back is not the inverse of preparing.
#
# Reuses "_DEPLOY_ACTION"/"_DEPLOY_ROLLBACK" verbatim, as 3.2-3.5 do. No path
# collision: 3.4's traffic routes live under /agents/..., 3.5's under
# /rollouts/..., and the pre-existing /deployments/{id}/... paths are
# deploy/suspend/resume/rollback/retire/promote/preflight/heartbeat/health --
# none of which is /strategy/*.
# --------------------------------------------------------------------------- #
@router.post("/deployments/{deployment_id}/strategy/execute", response_model=StrategyOutcomeRead)
def execute_deployment_strategy(deployment_id: uuid.UUID,
                                idempotency_key: str | None = Header(default=None,
                                                                     alias="Idempotency-Key"),
                                actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                                db: Session = Depends(get_db)):
    """Runs the strategy declared on the deployment: RECREATE cuts over,
    BLUE_GREEN prepares (warms GREEN at 0%), ROLLING raises
    ``STRATEGY_ROLLING_DEFERRED`` (Phase 3.9), CANARY points at the rollout
    API."""
    return DeploymentStrategyService(db).execute(actor, deployment_id,
                                                 idempotency_key=idempotency_key)


@router.post("/deployments/{deployment_id}/strategy/blue-green/switch",
             response_model=StrategyOutcomeRead)
def blue_green_switch(deployment_id: uuid.UUID,
                      idempotency_key: str | None = Header(default=None,
                                                           alias="Idempotency-Key"),
                      actor: User = Depends(require_permission(_DEPLOY_ACTION)),
                      db: Session = Depends(get_db)):
    return DeploymentStrategyService(db).blue_green_switch(actor, deployment_id,
                                                           idempotency_key=idempotency_key)


@router.post("/deployments/{deployment_id}/strategy/blue-green/rollback",
             response_model=StrategyOutcomeRead)
def blue_green_rollback(deployment_id: uuid.UUID,
                        idempotency_key: str | None = Header(default=None,
                                                             alias="Idempotency-Key"),
                        actor: User = Depends(require_permission(_DEPLOY_ROLLBACK)),
                        db: Session = Depends(get_db)):
    """Uses ``runtime.deployment.rollback`` rather than ``.deploy``, matching
    3.5's own rollout rollback: an organization may well grant "can return to
    the previous version" separately from "can push a new one forward"."""
    return DeploymentStrategyService(db).blue_green_rollback(actor, deployment_id,
                                                             idempotency_key=idempotency_key)


@router.post("/deployments/{deployment_id}/heartbeat", response_model=DeploymentHealthRead)
def submit_heartbeat(deployment_id: uuid.UUID, payload: HeartbeatSubmit,
                     actor: User = Depends(require_permission(_DEPLOY_ACTION)), db: Session = Depends(get_db)):
    return HealthMonitoringService(db).heartbeat(actor, deployment_id, payload.model_dump())


@router.get("/deployments/{deployment_id}/health", response_model=list[DeploymentHealthRead])
def deployment_health(deployment_id: uuid.UUID, actor: User = Depends(require_permission(_HEALTH)),
                      db: Session = Depends(get_db)):
    return HealthMonitoringService(db).deployment_health(actor, deployment_id)


# --------------------------------------------------------------------------- #
# Environments & Promotion Paths (ACT-SRS-M3 §3.2)
# --------------------------------------------------------------------------- #
@router.get("/environments", response_model=list[EnvironmentRead])
def list_environments(actor: User = Depends(require_permission(_ENV_VIEW)), db: Session = Depends(get_db)):
    service = EnvironmentService(db)
    service.ensure_seeded(actor.organization_id)
    db.commit()
    return service.list(actor)


@router.post("/environments", response_model=EnvironmentRead, status_code=status.HTTP_201_CREATED)
def create_environment(payload: EnvironmentCreate, actor: User = Depends(require_permission(_ENV_MANAGE)),
                       db: Session = Depends(get_db)):
    return EnvironmentService(db).create(actor, payload.model_dump())


@router.get("/environments/{environment_id}", response_model=EnvironmentRead)
def get_environment(environment_id: uuid.UUID, actor: User = Depends(require_permission(_ENV_VIEW)),
                    db: Session = Depends(get_db)):
    return EnvironmentService(db).get_or_404(actor, environment_id)


@router.patch("/environments/{environment_id}", response_model=EnvironmentRead)
def update_environment(environment_id: uuid.UUID, payload: EnvironmentUpdate,
                       actor: User = Depends(require_permission(_ENV_MANAGE)), db: Session = Depends(get_db)):
    return EnvironmentService(db).update(actor, environment_id, payload.model_dump(exclude_unset=True))


@router.get("/environments/{environment_id}/policy", response_model=EnvironmentRead)
def get_environment_policy(environment_id: uuid.UUID, actor: User = Depends(require_permission(_ENV_VIEW)),
                           db: Session = Depends(get_db)):
    return EnvironmentService(db).get_or_404(actor, environment_id)


@router.put("/environments/{environment_id}/policy", response_model=EnvironmentRead)
def set_environment_policy(environment_id: uuid.UUID, payload: EnvironmentPolicyUpdate,
                           actor: User = Depends(require_permission(_ENV_MANAGE)), db: Session = Depends(get_db)):
    return EnvironmentService(db).set_policy(actor, environment_id, payload.policy)


@router.get("/promotion-paths", response_model=list[PromotionPathRead])
def list_promotion_paths(actor: User = Depends(require_permission(_ENV_VIEW)), db: Session = Depends(get_db)):
    return PromotionPathService(db).list(actor)


@router.post("/promotion-paths", response_model=PromotionPathRead, status_code=status.HTTP_201_CREATED)
def create_promotion_path(payload: PromotionPathCreate, actor: User = Depends(require_permission(_ENV_MANAGE)),
                          db: Session = Depends(get_db)):
    return PromotionPathService(db).create(actor, payload.from_environment_id, payload.to_environment_id,
                                           requires_approval=payload.requires_approval)


@router.delete("/promotion-paths/{path_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_promotion_path(path_id: uuid.UUID, actor: User = Depends(require_permission(_ENV_MANAGE)),
                          db: Session = Depends(get_db)):
    PromotionPathService(db).delete(actor, path_id)
    return None


# --------------------------------------------------------------------------- #
# Executions (§24-§28, §66)
# --------------------------------------------------------------------------- #
@router.post("/executions", response_model=ExecutionRead, status_code=status.HTTP_201_CREATED)
def request_execution(payload: ExecutionCreate, actor: User = Depends(require_permission(_EXEC_CREATE)),
                      db: Session = Depends(get_db)):
    return ExecutionRequestService(db).request_execution(actor, payload.model_dump())


@router.post("/executions/self", response_model=ExecutionRead, status_code=status.HTTP_201_CREATED)
def request_self_execution(payload: AgentSelfExecutionCreate,
                           agent: Agent = Depends(get_current_agent), db: Session = Depends(get_db)):
    """§29, §31 — an agent (authenticated by its own API key, not a human
    session) requesting an execution of itself. There is no ``agent_id`` in
    the request body to spoof: the target is always the authenticated
    agent. Authorized through ``AuthorizationGateway.authorize_agent``
    (ABAC), not RBAC — an agent holds no roles of its own."""
    return ExecutionRequestService(db).request_execution_as_agent(agent, payload.model_dump())


@router.get("/executions", response_model=list[ExecutionRead])
def list_executions(agent_id: uuid.UUID | None = Query(default=None), status_filter: str | None = Query(
                    default=None, alias="status"), limit: int = Query(default=100, le=500),
                    actor: User = Depends(require_permission(_EXEC_VIEW)), db: Session = Depends(get_db)):
    return ExecutionRequestService(db).list(actor, agent_id=agent_id, status=status_filter, limit=limit)


@router.get("/executions/{execution_id}", response_model=ExecutionRead)
def get_execution(execution_id: uuid.UUID, actor: User = Depends(require_permission(_EXEC_VIEW)),
                  db: Session = Depends(get_db)):
    return ExecutionRequestService(db).get_or_404(actor, execution_id)


@router.post("/executions/{execution_id}/cancel", response_model=ExecutionRead)
def cancel_execution(execution_id: uuid.UUID, actor: User = Depends(require_permission(_EXEC_CANCEL)),
                     db: Session = Depends(get_db)):
    return ExecutionRequestService(db).cancel(actor, execution_id)


@router.post("/executions/{execution_id}/retry", response_model=ExecutionRead)
def retry_execution(execution_id: uuid.UUID, actor: User = Depends(require_permission(_EXEC_RETRY)),
                    db: Session = Depends(get_db)):
    return ExecutionRequestService(db).retry(actor, execution_id)


@router.post("/executions/{execution_id}/replay", response_model=ExecutionRead)
def replay_execution(execution_id: uuid.UUID, actor: User = Depends(require_permission(_EXEC_RETRY)),
                     db: Session = Depends(get_db)):
    return ExecutionRequestService(db).replay(actor, execution_id)


@router.get("/executions/{execution_id}/attempts", response_model=list[ExecutionAttemptRead])
def execution_attempts(execution_id: uuid.UUID, actor: User = Depends(require_permission(_EXEC_VIEW)),
                       db: Session = Depends(get_db)):
    ExecutionRequestService(db).get_or_404(actor, execution_id)
    stmt = select(ExecutionAttempt).where(ExecutionAttempt.execution_id == execution_id).order_by(
        ExecutionAttempt.attempt_number)
    return list(db.execute(stmt).scalars())


@router.get("/executions/{execution_id}/tool-calls", response_model=list[ToolCallRead])
def execution_tool_calls(execution_id: uuid.UUID, actor: User = Depends(require_permission(_EXEC_VIEW)),
                         db: Session = Depends(get_db)):
    ExecutionRequestService(db).get_or_404(actor, execution_id)
    stmt = select(ToolCall).where(ToolCall.execution_id == execution_id).order_by(ToolCall.created_at)
    return list(db.execute(stmt).scalars())


@router.get("/executions/{execution_id}/events", response_model=list[RuntimeEventRead])
def execution_events(execution_id: uuid.UUID, actor: User = Depends(require_permission(_EXEC_VIEW)),
                     db: Session = Depends(get_db)):
    ExecutionRequestService(db).get_or_404(actor, execution_id)
    stmt = select(RuntimeEvent).where(RuntimeEvent.execution_id == execution_id).order_by(RuntimeEvent.created_at)
    return list(db.execute(stmt).scalars())


@router.get("/executions/{execution_id}/messages", response_model=list[ExecutionMessageRead])
def execution_messages(execution_id: uuid.UUID, actor: User = Depends(require_permission(_EXEC_VIEW)),
                       db: Session = Depends(get_db)):
    """Phase 5.6a.3 (ACT-TLX-FR-049) — the full conversation transcript for
    this execution's model-driven tool loop, in strict sequence order."""
    ExecutionRequestService(db).get_or_404(actor, execution_id)
    stmt = select(ExecutionMessage).where(ExecutionMessage.execution_id == execution_id).order_by(
        ExecutionMessage.sequence)
    return list(db.execute(stmt).scalars())


# --------------------------------------------------------------------------- #
# Capabilities (§18, §19, §66)
# --------------------------------------------------------------------------- #
@router.get("/capabilities", response_model=list[CapabilityRead])
def list_capabilities(actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return CapabilityService(db).list_catalog()


@router.post("/capabilities", response_model=CapabilityRead, status_code=status.HTTP_201_CREATED)
def create_capability(payload: CapabilityCreate, actor: User = Depends(require_permission(_CAPABILITY)),
                      db: Session = Depends(get_db)):
    return CapabilityService(db).create(payload.model_dump())


@router.get("/agents/{agent_id}/capabilities", response_model=list[AgentCapabilityRead])
def agent_capabilities(agent_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
                       db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    return CapabilityService(db).list_for_agent(agent_id)


@router.post("/agents/{agent_id}/capabilities", response_model=AgentCapabilityRead,
            status_code=status.HTTP_201_CREATED)
def assign_capability(agent_id: uuid.UUID, payload: AgentCapabilityAssign,
                      actor: User = Depends(require_permission(_CAPABILITY)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return CapabilityService(db).assign(actor, agent, payload.model_dump())


@router.post("/agents/{agent_id}/capabilities/{assignment_id}/decide", response_model=AgentCapabilityRead)
def decide_capability(agent_id: uuid.UUID, assignment_id: uuid.UUID, approve: bool = Query(...),
                      actor: User = Depends(require_permission(_CAPABILITY)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return CapabilityService(db).decide(actor, agent, assignment_id, approve=approve)


@router.delete("/agents/{agent_id}/capabilities/{assignment_id}", response_model=AgentCapabilityRead)
def revoke_capability(agent_id: uuid.UUID, assignment_id: uuid.UUID,
                      actor: User = Depends(require_permission(_CAPABILITY)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return CapabilityService(db).revoke(actor, agent, assignment_id)


# --------------------------------------------------------------------------- #
# Tools (§20, §23, §66)
# --------------------------------------------------------------------------- #
@router.get("/tools", response_model=list[ToolRead])
def list_tools(actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return ToolRegistryService(db).list_catalog(actor)


@router.post("/tools", response_model=ToolRead, status_code=status.HTTP_201_CREATED)
def create_tool(payload: ToolCreate, actor: User = Depends(require_permission(_TOOL_MANAGE)),
                db: Session = Depends(get_db)):
    return ToolRegistryService(db).create(actor, payload.model_dump())


@router.get("/agents/{agent_id}/tools", response_model=list[AgentToolRead])
def agent_tools(agent_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    return ToolRegistryService(db).list_for_agent(agent_id)


@router.post("/agents/{agent_id}/tools", response_model=AgentToolRead, status_code=status.HTTP_201_CREATED)
def assign_tool(agent_id: uuid.UUID, payload: AgentToolAssign,
                actor: User = Depends(require_permission(_TOOL_ASSIGN)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return ToolRegistryService(db).assign(actor, agent, payload.model_dump())


@router.post("/agents/{agent_id}/tools/{assignment_id}/decide", response_model=AgentToolRead)
def decide_tool(agent_id: uuid.UUID, assignment_id: uuid.UUID, approve: bool = Query(...),
                actor: User = Depends(require_permission(_TOOL_ASSIGN)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return ToolRegistryService(db).decide(actor, agent, assignment_id, approve=approve)


@router.delete("/agents/{agent_id}/tools/{assignment_id}", response_model=AgentToolRead)
def revoke_tool(agent_id: uuid.UUID, assignment_id: uuid.UUID,
                actor: User = Depends(require_permission(_TOOL_ASSIGN)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return ToolRegistryService(db).revoke(actor, agent, assignment_id)


# --------------------------------------------------------------------------- #
# Runtime approvals (§39, §66)
# --------------------------------------------------------------------------- #
@router.get("/approvals", response_model=list[RuntimeApprovalRead])
def list_approvals(status_filter: str | None = Query(default=None, alias="status"),
                   actor: User = Depends(require_permission(_APPROVAL)), db: Session = Depends(get_db)):
    return RuntimeApprovalService(db).list(actor, status=status_filter)


@router.post("/approvals/{approval_id}/decide", response_model=RuntimeApprovalRead)
def decide_approval(approval_id: uuid.UUID, payload: RuntimeApprovalDecision,
                    actor: User = Depends(require_permission(_APPROVAL)), db: Session = Depends(get_db)):
    return RuntimeApprovalService(db).decide(actor, approval_id, decision=payload.decision,
                                             comment=payload.comment)


# --------------------------------------------------------------------------- #
# Health & workers (§49, §50, §66)
# --------------------------------------------------------------------------- #
@router.get("/health", response_model=dict)
def platform_health(actor: User = Depends(require_permission(_HEALTH)), db: Session = Depends(get_db)):
    return HealthMonitoringService(db).platform_health(actor)


@router.get("/workers", response_model=list[dict])
def list_workers(actor: User = Depends(require_permission(_HEALTH)), db: Session = Depends(get_db)):
    return HealthMonitoringService(db).workers(actor)


@router.post("/workers/reap", response_model=dict)
def reap_stale_locks(actor: User = Depends(require_permission(_EXEC_RETRY)), db: Session = Depends(get_db)):
    """§32 — recover executions left ``RUNNING`` by a worker that never
    renewed its lease. Self-healing paths call this automatically before
    every claim; this endpoint exists for operator-triggered recovery and
    observability (how many were actually stuck)."""
    reaped = ExecutionWorkerService(db).reap_expired_locks()
    return {"reaped": reaped}


# --------------------------------------------------------------------------- #
# Kill switch (§60, §66)
# --------------------------------------------------------------------------- #
@router.post("/kill-switch/executions/{execution_id}", response_model=dict)
def kill_execution(execution_id: uuid.UUID, payload: KillSwitchRequest,
                   actor: User = Depends(require_permission(_KILL_SWITCH)), db: Session = Depends(get_db)):
    return KillSwitchService(db).activate(actor, "EXECUTION", execution_id, payload.reason)


@router.post("/kill-switch/agents/{agent_id}", response_model=dict)
def kill_agent(agent_id: uuid.UUID, payload: KillSwitchRequest,
              actor: User = Depends(require_permission(_KILL_SWITCH)), db: Session = Depends(get_db)):
    return KillSwitchService(db).activate(actor, "AGENT", agent_id, payload.reason)


@router.post("/kill-switch/projects/{project_id}", response_model=dict)
def kill_project(project_id: uuid.UUID, payload: KillSwitchRequest,
                 actor: User = Depends(require_permission(_KILL_SWITCH)), db: Session = Depends(get_db)):
    return KillSwitchService(db).activate(actor, "PROJECT", project_id, payload.reason)


@router.post("/kill-switch/organizations/{organization_id}", response_model=dict)
def kill_organization(organization_id: uuid.UUID, payload: KillSwitchRequest,
                      actor: User = Depends(require_permission(_KILL_SWITCH)), db: Session = Depends(get_db)):
    if organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.PERMISSION_DENIED, "Cannot activate the kill switch for another organization.")
    return KillSwitchService(db).activate(actor, "ORGANIZATION", organization_id, payload.reason)


@router.post("/kill-switch/platform", response_model=dict)
def kill_platform(payload: KillSwitchRequest,
                  actor: User = Depends(require_permission(_KILL_SWITCH)), db: Session = Depends(get_db)):
    """§60 — cross-tenant; ``KillSwitchService.activate`` additionally
    requires the actor's legacy role to be SUPER_ADMIN, since the ordinary
    per-organization ``runtime.kill_switch.execute`` grant must never be
    sufficient on its own to halt every organization's executions."""
    return KillSwitchService(db).activate(actor, "PLATFORM", None, payload.reason)
