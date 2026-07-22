"""Phase 5.1 SRS §39-§45 — JSON/YAML/CSV agent import & export.

Runs synchronously inline within the request, same "eager" philosophy as the
Phase 5.0 execution queue (see ``app.runtime.services`` module docstring) —
this environment has no background worker to hand the job off to, so
``AgentImportJob``/``AgentExportJob`` go straight from ``PENDING`` to a
terminal status before the API call returns. The job/item tables still exist
and are populated correctly; a real deployment with a task queue could later
point a worker at the same ``AgentImportService.run_job`` without changing
its contract.
"""

from __future__ import annotations

import csv
import io
import json
import uuid

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.agent_registry import AgentExportJob, AgentImportItem, AgentImportJob
from app.models.runtime import AgentDefinition
from app.models.user import User
from app.runtime.registry.duplicates import AgentDuplicateDetectionService
from app.runtime.registry.validation import AgentValidationService
from app.runtime.services import _now, _record_event, _unique_slug

_MAX_IMPORT_BYTES = 5_000_000
_MAX_IMPORT_RECORDS = 5_000


def _parse_records(content: str, fmt: str) -> list[dict]:
    if len(content.encode("utf-8")) > _MAX_IMPORT_BYTES:
        raise IdentityError(ErrorCode.AGENT_IMPORT_INVALID,
                           f"Import file exceeds the {_MAX_IMPORT_BYTES} byte limit.")
    if fmt == "JSON":
        data = json.loads(content)
        records = data if isinstance(data, list) else [data]
    elif fmt == "YAML":
        # SRS §69 — never yaml.load(); safe_load refuses arbitrary object
        # construction (the classic YAML deserialization RCE vector).
        data = yaml.safe_load(content)
        records = data if isinstance(data, list) else [data]
    elif fmt == "CSV":
        reader = csv.DictReader(io.StringIO(content))
        records = list(reader)
    else:
        raise IdentityError(ErrorCode.AGENT_IMPORT_INVALID, f"Unsupported format '{fmt}'.")
    if len(records) > _MAX_IMPORT_RECORDS:
        raise IdentityError(ErrorCode.AGENT_IMPORT_INVALID,
                           f"Import exceeds the {_MAX_IMPORT_RECORDS}-record limit.")
    return records


class AgentImportService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def run_job(self, actor: User, *, file_name: str, fmt: str, mode: str, content: str) -> AgentImportJob:
        job = AgentImportJob(organization_id=actor.organization_id, file_name=file_name, format=fmt,
                             mode=mode, status="RUNNING", created_by=actor.id, started_at=_now())
        self.db.add(job)
        self.db.flush()
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_AGENT_IMPORT_STARTED, actor,
                     organization_id=actor.organization_id, meta={"job_id": str(job.id), "format": fmt})

        try:
            records = _parse_records(content, fmt)
        except (json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
            job.status = "FAILED"
            job.completed_at = _now()
            self.db.commit()
            self.db.refresh(job)
            raise IdentityError(ErrorCode.AGENT_IMPORT_INVALID, f"Could not parse {fmt} content: {exc}") from exc

        job.total_records = len(records)
        for index, record in enumerate(records):
            identifier = str(record.get("external_reference") or record.get("name") or f"row-{index + 1}")
            item = self._import_one(actor, job, identifier, record, mode)
            self.db.add(item)
            if item.status in ("CREATED", "UPDATED"):
                job.successful_records += 1
            elif item.status == "SKIPPED":
                job.warning_records += 1
            else:
                job.failed_records += 1

        job.status = "COMPLETED"
        job.completed_at = _now()
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_AGENT_IMPORT_COMPLETED, actor,
                     organization_id=actor.organization_id,
                     meta={"job_id": str(job.id), "successful": job.successful_records,
                          "failed": job.failed_records})
        self.db.commit()
        self.db.refresh(job)
        return job

    def _import_one(self, actor: User, job: AgentImportJob, identifier: str, record: dict,
                    mode: str) -> AgentImportItem:
        errors: list[dict] = []
        warnings: list[dict] = []
        name = record.get("name")
        if not name:
            return AgentImportItem(import_job_id=job.id, record_identifier=identifier, status="FAILED",
                                   errors=[{"code": "AGENT_IMPORT_INVALID", "message": "name is required"}])

        existing = self.db.execute(
            select(Agent).where(Agent.organization_id == actor.organization_id, Agent.name == name)
        ).scalar_one_or_none()

        if mode == "VALIDATE_ONLY":
            return AgentImportItem(import_job_id=job.id, record_identifier=identifier,
                                   status="SKIPPED", agent_id=existing.id if existing else None,
                                   warnings=[{"code": "VALIDATE_ONLY", "message": "No changes persisted."}])

        if existing is not None:
            if mode == "CREATE_ONLY":
                return AgentImportItem(import_job_id=job.id, record_identifier=identifier, status="SKIPPED",
                                       agent_id=existing.id,
                                       errors=[{"code": "AGENT_ALREADY_EXISTS",
                                               "message": "An agent with this name already exists."}])
            if mode == "UPDATE_DRAFTS" and existing.lifecycle_status != "DRAFT":
                return AgentImportItem(import_job_id=job.id, record_identifier=identifier, status="SKIPPED",
                                       agent_id=existing.id,
                                       errors=[{"code": "AGENT_NOT_EDITABLE",
                                               "message": f"Existing agent is {existing.lifecycle_status}, "
                                                          "not DRAFT."}])
            if mode == "UPSERT_NON_ACTIVE" and existing.lifecycle_status in ("ACTIVE", "APPROVED"):
                return AgentImportItem(import_job_id=job.id, record_identifier=identifier, status="SKIPPED",
                                       agent_id=existing.id,
                                       errors=[{"code": "AGENT_NOT_EDITABLE",
                                               "message": f"Existing agent is {existing.lifecycle_status}, "
                                                          "which is protected from bulk import."}])
            for field in ("description", "business_purpose", "criticality", "risk_level",
                         "data_classification", "autonomy_level"):
                if field in record and record[field]:
                    setattr(existing, field, record[field])
            existing.updated_by = actor.id
            self.db.flush()
            return AgentImportItem(import_job_id=job.id, record_identifier=identifier, status="UPDATED",
                                   agent_id=existing.id, warnings=warnings)

        # New agent — always lands in DRAFT, never directly ACTIVE (§45).
        slug = _unique_slug(self.db, actor.organization_id, name.lower().replace(" ", "-"))
        agent = Agent(
            organization_id=actor.organization_id, name=name, slug=slug,
            description=record.get("description"), business_purpose=record.get("business_purpose"),
            agent_type=record.get("agent_type", "ASSISTANT"),
            criticality=record.get("criticality", "MEDIUM"), risk_level=record.get("risk_level", "LOW"),
            data_classification=record.get("data_classification", "INTERNAL"),
            autonomy_level=record.get("autonomy_level", "ASSISTIVE"),
            external_reference=record.get("external_reference"),
            api_key_hash="", lifecycle_status="DRAFT", registration_source="IMPORT",
            created_by=actor.id, updated_by=actor.id,
        )
        self.db.add(agent)
        self.db.flush()
        definition_payload = record.get("definition") or {}
        definition = AgentDefinition(
            agent_id=agent.id, name=definition_payload.get("name", f"{name} definition"),
            entrypoint=definition_payload.get("entrypoint", "unknown"),
            entrypoint_type=definition_payload.get("entrypoint_type", "FUNCTION"),
            framework=definition_payload.get("framework", "CUSTOM"),
            created_by=actor.id, updated_by=actor.id,
        )
        self.db.add(definition)
        self.db.flush()

        duplicates = AgentDuplicateDetectionService(self.db).check(actor, agent)
        if any(d.status == "CONFIRMED_DUPLICATE" for d in duplicates):
            warnings.append({"code": "AGENT_DUPLICATE_REVIEW_REQUIRED",
                             "message": "A likely duplicate was detected; review before activating."})

        return AgentImportItem(import_job_id=job.id, record_identifier=identifier, status="CREATED",
                               agent_id=agent.id, warnings=warnings)

    def list_items(self, job_id: uuid.UUID) -> list[AgentImportItem]:
        stmt = select(AgentImportItem).where(AgentImportItem.import_job_id == job_id)
        return list(self.db.execute(stmt.order_by(AgentImportItem.created_at)).scalars())


class AgentExportService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def run_job(self, actor: User, *, export_type: str, fmt: str, filters: dict) -> AgentExportJob:
        job = AgentExportJob(organization_id=actor.organization_id, export_type=export_type, format=fmt,
                             filters=filters, status="RUNNING", created_by=actor.id)
        self.db.add(job)
        self.db.flush()
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_AGENT_EXPORT_STARTED, actor,
                     organization_id=actor.organization_id, meta={"job_id": str(job.id), "type": export_type})

        stmt = select(Agent).where(Agent.organization_id == actor.organization_id)
        if filters.get("status"):
            stmt = stmt.where(Agent.lifecycle_status == filters["status"])
        if filters.get("criticality"):
            stmt = stmt.where(Agent.criticality == filters["criticality"])
        agents = list(self.db.execute(stmt).scalars())

        records = [self._serialize(a, export_type) for a in agents]
        payload = self._render(records, fmt)

        job.record_count = len(records)
        job.payload = payload
        job.status = "COMPLETED"
        job.completed_at = _now()
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_AGENT_EXPORT_COMPLETED, actor,
                     organization_id=actor.organization_id,
                     meta={"job_id": str(job.id), "record_count": job.record_count})
        self.db.commit()
        self.db.refresh(job)
        return job

    def _serialize(self, agent: Agent, export_type: str) -> dict:
        base = {
            "id": str(agent.id), "name": agent.name, "slug": agent.slug,
            "lifecycle_status": agent.lifecycle_status, "criticality": agent.criticality,
            "risk_level": agent.risk_level, "data_classification": agent.data_classification,
            "tags": agent.tags,
        }
        if export_type == "INVENTORY_SUMMARY":
            return base
        if export_type == "COMPLIANCE_REPORT":
            return {**base, "owner_id": str(agent.owner_id) if agent.owner_id else None,
                   "technical_owner_id": str(agent.technical_owner_id) if agent.technical_owner_id else None,
                   "compliance_owner_id": str(agent.compliance_owner_id) if agent.compliance_owner_id else None,
                   "validated_at": agent.validated_at.isoformat() if agent.validated_at else None,
                   "approved_at": agent.approved_at.isoformat() if agent.approved_at else None}
        # FULL_CONFIGURATION / MIGRATION_PACKAGE
        definition = self.db.execute(
            select(AgentDefinition).where(AgentDefinition.agent_id == agent.id)
            .order_by(AgentDefinition.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        full = {**base, "description": agent.description, "business_purpose": agent.business_purpose,
               "agent_type": agent.agent_type, "autonomy_level": agent.autonomy_level,
               "definition": self._redact_definition(definition) if definition else None}
        return full

    def _redact_definition(self, definition: AgentDefinition) -> dict:
        """§43 — secrets and secret values must never be exported."""
        return {
            "name": definition.name, "framework": definition.framework,
            "entrypoint_type": definition.entrypoint_type, "entrypoint": definition.entrypoint,
            "input_schema": definition.input_schema, "output_schema": definition.output_schema,
            # secret_requirements deliberately omitted — an allowlist of safe
            # fields, not a denylist, so a new sensitive field added later
            # can't leak by omission.
        }

    def _render(self, records: list[dict], fmt: str) -> str:
        if fmt == "JSON":
            return json.dumps(records, indent=2, default=str)
        if fmt == "YAML":
            return yaml.safe_dump(records, sort_keys=False)
        if fmt == "CSV":
            return self._render_csv(records)
        raise IdentityError(ErrorCode.AGENT_IMPORT_INVALID, f"Unsupported export format '{fmt}'.")

    def _render_csv(self, records: list[dict]) -> str:
        if not records:
            return ""
        fieldnames = sorted({key for record in records for key in record.keys() if key != "definition"})
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({k: _csv_safe(v) for k, v in record.items() if k in fieldnames})
        return buf.getvalue()


def _csv_safe(value) -> str:
    """SRS §69 — neutralize CSV formula injection: a leading =, +, -, or @
    would be interpreted as a formula by Excel/Sheets when the file is
    reopened, so it's prefixed with a literal-text guard apostrophe."""
    text = json.dumps(value) if isinstance(value, (list, dict)) else str(value) if value is not None else ""
    if text and text[0] in ("=", "+", "-", "@"):
        return "'" + text
    return text
