"""Phase 5.1 SRS §25-§31 — the agent-registry validation-report engine.

Ports jsonschema's bare ``validate()`` call (the Phase 5.0 execution-time
``_validate_schema`` in ``app.runtime.services``) into one with real DoS
guards, and adds the metadata/organization/ownership/identity/definition/risk
rule set §28 describes. Every rule appends a ``ValidationFinding`` (code,
field, message, severity) rather than raising immediately, so one run reports
everything wrong at once instead of failing at the first problem.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

import jsonschema
from sqlalchemy.orm import Session

from app.identity.models.agent_identity import AgentIdentity
from app.identity.models.department import Department, Team
from app.models.agent import Agent
from app.models.agent_registry import AgentValidationRun
from app.models.organization_hierarchy import BusinessUnit, Project
from app.models.user import User

VALIDATOR_VERSION = "5.1.0"

# --------------------------------------------------------------------------- #
# JSON Schema DoS guards (SRS §29) — jsonschema itself enforces none of this.
# --------------------------------------------------------------------------- #
_MAX_SCHEMA_BYTES = 65_536
_MAX_SCHEMA_DEPTH = 20

_AGENT_TYPES = {"ASSISTANT", "ANALYST", "REVIEWER", "AUTOMATION", "WORKFLOW", "DATA_PROCESSOR",
                "COMMUNICATION", "SECURITY", "DECISION_SUPPORT", "COMPLIANCE", "CUSTOM"}
_FRAMEWORKS = {"NATIVE_PYTHON", "LANGCHAIN", "LANGGRAPH", "SEMANTIC_KERNEL", "CREWAI", "AUTOGEN",
              "HTTP_SERVICE", "SERVERLESS_FUNCTION", "CONTAINER", "CUSTOM",
              "FUNCTION", "PYTHON"}  # + Phase 5.0 legacy values, accepted leniently
_ENTRYPOINT_TYPES = {"PYTHON_MODULE", "HTTP_ENDPOINT", "CONTAINER_IMAGE", "SERVERLESS_FUNCTION",
                     "QUEUE_CONSUMER", "WORKFLOW_REFERENCE", "EXTERNAL_SERVICE", "CUSTOM",
                     "FUNCTION"}  # "FUNCTION" is the Phase 5.0 default, kept for compatibility

_PYTHON_MODULE_RE = re.compile(r"^[a-zA-Z_][\w.]*:[a-zA-Z_]\w*$")
_CONTAINER_IMAGE_RE = re.compile(r"^[\w.\-/]+(:[\w.\-]+|@sha256:[0-9a-f]{64})$")
_URL_CREDENTIAL_RE = re.compile(r"^[a-zA-Z][\w+.-]*://[^/@\s]+:[^/@\s]+@")


class ValidationFinding:
    def __init__(self, code: str, message: str, severity: str, field: str | None = None) -> None:
        self.code = code
        self.message = message
        self.severity = severity  # INFO / WARNING / ERROR / BLOCKING
        self.field = field

    def as_dict(self) -> dict:
        return {"code": self.code, "field": self.field, "message": self.message,
               "severity": self.severity}


def check_schema_dos_guards(schema: dict, *, what: str) -> list[ValidationFinding]:
    """§29 — size, nesting-depth and draft checks jsonschema doesn't do on its
    own. Called for every contract schema before it's ever handed to
    ``jsonschema.validate`` (registration-time here; execution-time reuse is
    ``app.runtime.services._validate_schema``)."""
    findings: list[ValidationFinding] = []
    if not schema:
        return findings
    serialized = json.dumps(schema)
    if len(serialized.encode("utf-8")) > _MAX_SCHEMA_BYTES:
        findings.append(ValidationFinding(
            "AGENT_SCHEMA_TOO_LARGE", f"{what} schema exceeds {_MAX_SCHEMA_BYTES} bytes.",
            "BLOCKING", what))
        return findings  # too large to safely walk further
    depth = _json_depth(schema)
    if depth > _MAX_SCHEMA_DEPTH:
        findings.append(ValidationFinding(
            "AGENT_SCHEMA_TOO_DEEP",
            f"{what} schema nests {depth} levels deep (max {_MAX_SCHEMA_DEPTH}).",
            "BLOCKING", what))
        return findings
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        findings.append(ValidationFinding(
            f"AGENT_{what.upper()}_SCHEMA_INVALID", f"{what} schema is invalid: {exc.message}",
            "BLOCKING", what))
    return findings


def _json_depth(obj, current: int = 0) -> int:
    if current > _MAX_SCHEMA_DEPTH + 5:  # short-circuit pathological input
        return current
    if isinstance(obj, dict) and obj:
        return max((_json_depth(v, current + 1) for v in obj.values()), default=current)
    if isinstance(obj, list) and obj:
        return max((_json_depth(v, current + 1) for v in obj), default=current)
    return current


def validate_sample_payload(schema: dict, payload: dict) -> list[str]:
    """SRS §30 — sample-payload testing used by both the wizard's Contracts
    step and ``POST /agents/{id}/schemas/test``."""
    try:
        jsonschema.validate(instance=payload, schema=schema)
        return []
    except jsonschema.ValidationError as exc:
        return [exc.message]
    except jsonschema.SchemaError as exc:
        return [f"Schema itself is invalid: {exc.message}"]


# --------------------------------------------------------------------------- #
# Entrypoint validation (SRS §31)
# --------------------------------------------------------------------------- #
def validate_entrypoint(entrypoint_type: str, entrypoint: str) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    if entrypoint_type not in _ENTRYPOINT_TYPES:
        findings.append(ValidationFinding(
            "AGENT_ENTRYPOINT_TYPE_UNKNOWN", f"'{entrypoint_type}' is not a recognized entrypoint type.",
            "WARNING", "entrypoint_type"))
        return findings

    if entrypoint_type == "PYTHON_MODULE":
        if not _PYTHON_MODULE_RE.match(entrypoint):
            findings.append(ValidationFinding(
                "AGENT_ENTRYPOINT_INVALID",
                "PYTHON_MODULE entrypoint must look like 'module.path:function_name'.",
                "BLOCKING", "entrypoint"))
    elif entrypoint_type == "HTTP_ENDPOINT" or entrypoint_type == "EXTERNAL_SERVICE":
        if not entrypoint.startswith("https://"):
            findings.append(ValidationFinding(
                "AGENT_ENTRYPOINT_INVALID", "HTTP endpoint entrypoints must use https://.",
                "BLOCKING", "entrypoint"))
        elif _URL_CREDENTIAL_RE.match(entrypoint):
            findings.append(ValidationFinding(
                "AGENT_ENTRYPOINT_INVALID", "Entrypoint URL must not embed credentials.",
                "BLOCKING", "entrypoint"))
    elif entrypoint_type == "CONTAINER_IMAGE":
        if not _CONTAINER_IMAGE_RE.match(entrypoint):
            findings.append(ValidationFinding(
                "AGENT_ENTRYPOINT_INVALID",
                "Container image entrypoint must include a tag or a sha256 digest.",
                "BLOCKING", "entrypoint"))
    elif entrypoint_type == "SERVERLESS_FUNCTION":
        if entrypoint.count(":") < 2:
            findings.append(ValidationFinding(
                "AGENT_ENTRYPOINT_INVALID",
                "Serverless entrypoint must look like 'provider:region:function-id'.",
                "BLOCKING", "entrypoint"))
    return findings


def check_url_for_embedded_credentials(url: str | None, field: str) -> list[ValidationFinding]:
    """SRS §69 — 'URL fields must reject embedded credentials'."""
    if not url:
        return []
    if _URL_CREDENTIAL_RE.match(url):
        return [ValidationFinding("AGENT_URL_CREDENTIAL_EMBEDDED",
                                  f"{field} must not embed credentials in the URL.", "BLOCKING", field)]
    return []


# --------------------------------------------------------------------------- #
# Full validation run (SRS §25-§28)
# --------------------------------------------------------------------------- #
class AgentValidationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def run(self, actor: User, agent: Agent) -> AgentValidationRun:
        findings: list[ValidationFinding] = []
        checks: list[dict] = []

        def record(name: str, ok: bool) -> None:
            checks.append({"name": name, "passed": ok})

        # --- §28.1 metadata ---
        ok = bool(agent.name and agent.name.strip())
        record("name_required", ok)
        if not ok:
            findings.append(ValidationFinding("AGENT_NAME_REQUIRED", "Name is required.", "BLOCKING", "name"))

        ok = bool(agent.description and agent.description.strip())
        record("description_required", ok)
        if not ok:
            findings.append(ValidationFinding("AGENT_DESCRIPTION_REQUIRED", "Description is required.",
                                              "ERROR", "description"))

        ok = bool(agent.business_purpose and agent.business_purpose.strip())
        record("business_purpose_required", ok)
        if not ok:
            findings.append(ValidationFinding("AGENT_BUSINESS_PURPOSE_REQUIRED",
                                              "Business purpose is required.", "ERROR", "business_purpose"))

        ok = agent.agent_type in _AGENT_TYPES
        record("agent_type_valid", ok)
        if not ok:
            findings.append(ValidationFinding("AGENT_TYPE_INVALID", f"'{agent.agent_type}' is not a recognized "
                                              "agent type.", "WARNING", "agent_type"))

        # --- §28.2 organization / hierarchy ---
        # Project has no organization_id column of its own — org membership
        # is transitive through team -> department -> organization_id.
        ok = True
        if agent.project_id:
            project = self.db.get(Project, agent.project_id)
            project_team = self.db.get(Team, project.team_id) if project else None
            project_dept = self.db.get(Department, project_team.department_id) if project_team else None
            ok = project is not None and project_dept is not None and \
                project_dept.organization_id == agent.organization_id
            if ok and agent.team_id and project.team_id != agent.team_id:
                findings.append(ValidationFinding("AGENT_ORG_HIERARCHY_MISMATCH",
                                                  "team_id does not match the selected project's team.",
                                                  "ERROR", "team_id"))
        record("project_valid", ok)
        if not ok:
            findings.append(ValidationFinding("AGENT_ORG_HIERARCHY_INVALID",
                                              "project_id does not exist or is cross-tenant.",
                                              "BLOCKING", "project_id"))

        if agent.department_id and agent.business_unit_id:
            department = self.db.get(Department, agent.department_id)
            if department and department.business_unit_id and \
                    department.business_unit_id != agent.business_unit_id:
                findings.append(ValidationFinding("AGENT_ORG_HIERARCHY_MISMATCH",
                                                  "business_unit_id does not match the department's business unit.",
                                                  "ERROR", "business_unit_id"))

        # BusinessUnit/Department carry organization_id directly; Team only
        # has department_id (org membership is transitive through it), so
        # each gets its own cross-tenant check rather than a generic loop.
        if agent.business_unit_id is not None:
            bu = self.db.get(BusinessUnit, agent.business_unit_id)
            if bu is None or bu.organization_id != agent.organization_id:
                findings.append(ValidationFinding("AGENT_ORG_HIERARCHY_INVALID",
                                                  "business_unit_id does not exist or is cross-tenant.",
                                                  "BLOCKING", "business_unit_id"))
        if agent.department_id is not None:
            dept = self.db.get(Department, agent.department_id)
            if dept is None or dept.organization_id != agent.organization_id:
                findings.append(ValidationFinding("AGENT_ORG_HIERARCHY_INVALID",
                                                  "department_id does not exist or is cross-tenant.",
                                                  "BLOCKING", "department_id"))
        if agent.team_id is not None:
            team = self.db.get(Team, agent.team_id)
            team_dept = self.db.get(Department, team.department_id) if team else None
            if team is None or team_dept is None or team_dept.organization_id != agent.organization_id:
                findings.append(ValidationFinding("AGENT_ORG_HIERARCHY_INVALID",
                                                  "team_id does not exist or is cross-tenant.",
                                                  "BLOCKING", "team_id"))

        # --- §28.3 ownership ---
        ok = agent.owner_id is not None
        record("business_owner_required", ok)
        if not ok:
            findings.append(ValidationFinding("AGENT_OWNER_REQUIRED", "A business owner is required.",
                                              "BLOCKING", "owner_id"))

        needs_technical_owner = agent.criticality in ("HIGH", "MISSION_CRITICAL")
        ok = (not needs_technical_owner) or agent.technical_owner_id is not None
        record("technical_owner_required_if_high_criticality", ok)
        if not ok:
            findings.append(ValidationFinding("AGENT_OWNER_REQUIRED",
                                              "A technical owner is required for high-criticality agents.",
                                              "ERROR", "technical_owner_id"))

        needs_compliance_owner = agent.criticality == "MISSION_CRITICAL" or agent.risk_level in \
            ("HIGH", "CRITICAL")
        ok = (not needs_compliance_owner) or agent.compliance_owner_id is not None
        record("compliance_owner_required_if_high_risk", ok)
        if not ok:
            findings.append(ValidationFinding("AGENT_OWNER_REQUIRED",
                                              "A compliance owner is required for mission-critical or "
                                              "high/critical-risk agents.", "WARNING", "compliance_owner_id"))

        for field_name, owner_id in (
            ("owner_id", agent.owner_id), ("technical_owner_id", agent.technical_owner_id),
            ("compliance_owner_id", agent.compliance_owner_id),
        ):
            if owner_id is not None:
                owner = self.db.get(User, owner_id)
                ok = owner is not None and owner.organization_id == agent.organization_id
                if not ok:
                    findings.append(ValidationFinding("AGENT_OWNER_SCOPE_MISMATCH",
                                                      f"{field_name} does not belong to this organization.",
                                                      "BLOCKING", field_name))

        # --- §28.4 identity ---
        ok = agent.identity_id is not None
        record("identity_required", ok)
        if not ok:
            # WARNING, not ERROR/BLOCKING: the hard gate is enforced at
            # ``AgentLifecycleService.activate`` (§84 DoD — every *active*
            # agent needs one), not here — a registration wizard's step
            # ordering (identity is step 4, validation happens later) means
            # an otherwise-complete agent shouldn't fail validation just
            # because identity association hasn't happened yet.
            findings.append(ValidationFinding("AGENT_IDENTITY_REQUIRED",
                                              "A machine identity is required before activation.",
                                              "WARNING", "identity_id"))
        else:
            identity = self.db.get(AgentIdentity, agent.identity_id)
            if identity is None or identity.agent_id != agent.id:
                findings.append(ValidationFinding("AGENT_IDENTITY_INVALID",
                                                  "identity_id does not reference an eligible identity for "
                                                  "this agent.", "BLOCKING", "identity_id"))
            elif identity.status != "ACTIVE":
                findings.append(ValidationFinding("AGENT_IDENTITY_INVALID",
                                                  f"Identity is {identity.status}, not ACTIVE.",
                                                  "BLOCKING", "identity_id"))
            elif identity.expires_at and identity.expires_at <= datetime.now(timezone.utc):
                findings.append(ValidationFinding("AGENT_IDENTITY_INVALID", "Identity has expired.",
                                                  "BLOCKING", "identity_id"))

        # --- §28.5 definition ---
        definition = self._latest_definition(agent.id)
        ok = definition is not None
        record("definition_required", ok)
        if not ok:
            findings.append(ValidationFinding("AGENT_DEFINITION_REQUIRED", "Agent has no definition.",
                                              "BLOCKING", "definition"))
        else:
            findings.extend(validate_entrypoint(definition.entrypoint_type, definition.entrypoint))
            if definition.framework not in _FRAMEWORKS:
                findings.append(ValidationFinding("AGENT_FRAMEWORK_UNKNOWN",
                                                  f"'{definition.framework}' is not a recognized framework.",
                                                  "WARNING", "framework"))
            for what, schema in (("input", definition.input_schema), ("output", definition.output_schema),
                                 ("configuration", definition.configuration_schema)):
                findings.extend(check_schema_dos_guards(schema or {}, what=what))

        findings.extend(check_url_for_embedded_credentials(agent.documentation_url, "documentation_url"))
        findings.extend(check_url_for_embedded_credentials(agent.repository_url, "repository_url"))

        # --- §28.6 risk ---
        ok = agent.data_classification in ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED", "REGULATED")
        record("data_classification_valid", ok)
        if not ok:
            findings.append(ValidationFinding("AGENT_RISK_CLASSIFICATION_INVALID",
                                              "data_classification is not a recognized value.",
                                              "ERROR", "data_classification"))

        errors = [f.as_dict() for f in findings if f.severity in ("ERROR", "BLOCKING")]
        warnings = [f.as_dict() for f in findings if f.severity in ("INFO", "WARNING")]
        status = "FAILED" if errors else "PASSED"
        run = AgentValidationRun(
            agent_id=agent.id, status=status, validator_version=VALIDATOR_VERSION,
            summary={"passed": sum(1 for c in checks if c["passed"]),
                    "warnings": len(warnings), "failed": len(errors)},
            errors=errors, warnings=warnings, checks=checks,
            completed_at=datetime.now(timezone.utc), created_by=actor.id,
        )
        self.db.add(run)
        self.db.flush()
        return run

    def _latest_definition(self, agent_id: uuid.UUID):
        from sqlalchemy import select

        from app.models.runtime import AgentDefinition
        return self.db.execute(
            select(AgentDefinition).where(AgentDefinition.agent_id == agent_id)
            .order_by(AgentDefinition.created_at.desc()).limit(1)
        ).scalar_one_or_none()


def has_blocking_findings(run: AgentValidationRun) -> bool:
    return any(e.get("severity") == "BLOCKING" for e in run.errors)
