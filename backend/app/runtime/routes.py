"""Agent Runtime & Lifecycle Management API (Phase 5.0 §66) — /api/v1/runtime."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.database import get_db
from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import AgentDefinition, ExecutionAttempt, RuntimeEvent, ToolCall
from app.models.user import User
from app.runtime.schemas import (
    AgentCapabilityAssign,
    AgentCapabilityRead,
    AgentDefinitionRead,
    AgentRegisterRequest,
    AgentRuntimeRead,
    AgentToolAssign,
    AgentToolRead,
    AgentUpdateRequest,
    AgentVersionCreate,
    AgentVersionRead,
    CapabilityCreate,
    CapabilityRead,
    DeploymentCreate,
    DeploymentHealthRead,
    DeploymentRead,
    DeploymentRollbackRequest,
    ExecutionAttemptRead,
    ExecutionCreate,
    ExecutionRead,
    HeartbeatSubmit,
    KillSwitchRequest,
    RuntimeApprovalDecision,
    RuntimeApprovalRead,
    RuntimeDashboardRead,
    RuntimeEventRead,
    ToolCallRead,
    ToolCreate,
    ToolRead,
)
from app.runtime.services import (
    AgentRegistryService,
    AgentVersionService,
    CapabilityService,
    DeploymentService,
    ExecutionRequestService,
    HealthMonitoringService,
    KillSwitchService,
    RuntimeApprovalService,
    RuntimeDashboardService,
    ToolRegistryService,
)

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
_DEPLOY_VIEW = "runtime.deployment.view"
_DEPLOY_CREATE = "runtime.deployment.create"
_DEPLOY_ACTION = "runtime.deployment.deploy"
_DEPLOY_ROLLBACK = "runtime.deployment.rollback"
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
_APPROVAL = "runtime.approval.review"
_KILL_SWITCH = "runtime.kill_switch.execute"


# --------------------------------------------------------------------------- #
# Dashboard (§70)
# --------------------------------------------------------------------------- #
@router.get("/dashboard", response_model=RuntimeDashboardRead)
def dashboard(actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return RuntimeDashboardService(db).snapshot(actor)


# --------------------------------------------------------------------------- #
# Agent registry (§16, §66)
# --------------------------------------------------------------------------- #
@router.get("/agents", response_model=list[AgentRuntimeRead])
def list_agents(lifecycle_status: str | None = Query(default=None), criticality: str | None = Query(default=None),
                actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return AgentRegistryService(db).list(actor, lifecycle_status=lifecycle_status, criticality=criticality)


@router.post("/agents", response_model=AgentRuntimeRead, status_code=status.HTTP_201_CREATED)
def register_agent(payload: AgentRegisterRequest, actor: User = Depends(require_permission(_CREATE)),
                   db: Session = Depends(get_db)):
    return AgentRegistryService(db).register(actor, payload.model_dump())


@router.get("/agents/{agent_id}", response_model=AgentRuntimeRead)
def get_agent(agent_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return AgentRegistryService(db).get_or_404(actor, agent_id)


@router.put("/agents/{agent_id}", response_model=AgentRuntimeRead)
def update_agent(agent_id: uuid.UUID, payload: AgentUpdateRequest,
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
def list_definitions(agent_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
                     db: Session = Depends(get_db)):
    AgentRegistryService(db).get_or_404(actor, agent_id)
    stmt = select(AgentDefinition).where(AgentDefinition.agent_id == agent_id).order_by(
        AgentDefinition.created_at.desc())
    return list(db.execute(stmt).scalars())


@router.post("/agents/{agent_id}/validate", response_model=AgentRuntimeRead)
def validate_agent(agent_id: uuid.UUID, actor: User = Depends(require_permission(_VALIDATE)),
                   db: Session = Depends(get_db)):
    return AgentRegistryService(db).validate(actor, agent_id)


@router.post("/agents/{agent_id}/approve", response_model=AgentRuntimeRead)
def approve_agent(agent_id: uuid.UUID, actor: User = Depends(require_permission(_APPROVE)),
                  db: Session = Depends(get_db)):
    return AgentRegistryService(db).approve(actor, agent_id)


@router.post("/agents/{agent_id}/activate", response_model=AgentRuntimeRead)
def activate_agent(agent_id: uuid.UUID, actor: User = Depends(require_permission(_ACTIVATE)),
                   db: Session = Depends(get_db)):
    return AgentRegistryService(db).activate(actor, agent_id)


@router.post("/agents/{agent_id}/suspend", response_model=AgentRuntimeRead)
def suspend_agent(agent_id: uuid.UUID, actor: User = Depends(require_permission(_SUSPEND)),
                  db: Session = Depends(get_db)):
    return AgentRegistryService(db).suspend(actor, agent_id)


@router.post("/agents/{agent_id}/deprecate", response_model=AgentRuntimeRead)
def deprecate_agent(agent_id: uuid.UUID, actor: User = Depends(require_permission(_SUSPEND)),
                    db: Session = Depends(get_db)):
    return AgentRegistryService(db).deprecate(actor, agent_id)


@router.post("/agents/{agent_id}/archive", response_model=AgentRuntimeRead)
def archive_agent(agent_id: uuid.UUID, actor: User = Depends(require_permission(_RETIRE)),
                  db: Session = Depends(get_db)):
    return AgentRegistryService(db).archive(actor, agent_id)


@router.post("/agents/{agent_id}/retire", response_model=AgentRuntimeRead)
def retire_agent(agent_id: uuid.UUID, actor: User = Depends(require_permission(_RETIRE)),
                 db: Session = Depends(get_db)):
    return AgentRegistryService(db).retire(actor, agent_id)


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
def publish_version(agent_id: uuid.UUID, version_id: uuid.UUID,
                    actor: User = Depends(require_permission(_VERSION_PUBLISH)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentVersionService(db).publish(actor, agent, version_id)


@router.post("/agents/{agent_id}/versions/{version_id}/deprecate", response_model=AgentVersionRead)
def deprecate_version(agent_id: uuid.UUID, version_id: uuid.UUID,
                      actor: User = Depends(require_permission(_VERSION_DEPRECATE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentVersionService(db).deprecate(actor, agent, version_id)


@router.post("/agents/{agent_id}/versions/{version_id}/revoke", response_model=AgentVersionRead)
def revoke_version(agent_id: uuid.UUID, version_id: uuid.UUID,
                   actor: User = Depends(require_permission(_VERSION_REVOKE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return AgentVersionService(db).revoke(actor, agent, version_id)


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
                      actor: User = Depends(require_permission(_DEPLOY_CREATE)), db: Session = Depends(get_db)):
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    version = AgentVersionService(db).get_or_404(actor, agent_id, payload.agent_version_id)
    return DeploymentService(db).create(actor, agent, version, payload.model_dump(exclude={"agent_version_id"}))


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


@router.post("/deployments/{deployment_id}/heartbeat", response_model=DeploymentHealthRead)
def submit_heartbeat(deployment_id: uuid.UUID, payload: HeartbeatSubmit,
                     actor: User = Depends(require_permission(_DEPLOY_ACTION)), db: Session = Depends(get_db)):
    return HealthMonitoringService(db).heartbeat(actor, deployment_id, payload.model_dump())


@router.get("/deployments/{deployment_id}/health", response_model=list[DeploymentHealthRead])
def deployment_health(deployment_id: uuid.UUID, actor: User = Depends(require_permission(_HEALTH)),
                      db: Session = Depends(get_db)):
    return HealthMonitoringService(db).deployment_health(actor, deployment_id)


# --------------------------------------------------------------------------- #
# Executions (§24-§28, §66)
# --------------------------------------------------------------------------- #
@router.post("/executions", response_model=ExecutionRead, status_code=status.HTTP_201_CREATED)
def request_execution(payload: ExecutionCreate, actor: User = Depends(require_permission(_EXEC_CREATE)),
                      db: Session = Depends(get_db)):
    return ExecutionRequestService(db).request_execution(actor, payload.model_dump())


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


@router.post("/kill-switch/organizations/{organization_id}", response_model=dict)
def kill_organization(organization_id: uuid.UUID, payload: KillSwitchRequest,
                      actor: User = Depends(require_permission(_KILL_SWITCH)), db: Session = Depends(get_db)):
    if organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.PERMISSION_DENIED, "Cannot activate the kill switch for another organization.")
    return KillSwitchService(db).activate(actor, "ORGANIZATION", organization_id, payload.reason)
