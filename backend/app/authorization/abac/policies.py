"""ABAC policy services (Phase 4.3.5 §6–§8, §11–§13, §21, §23–§24, §27–§28).

- ``PolicyValidationService`` — schema, attributes, operators, types, effect,
  obligations, target and scope validation; runs at validate *and* publish
  (§28 compilation: a published policy is guaranteed well-formed, so runtime
  never re-parses unvalidated JSON).
- ``PolicyService`` — CRUD + lifecycle (draft → validated → active →
  disabled/deprecated/archived), immutable published versions, rollback, clone.
- ``PolicyResolver`` — applicable ACTIVE policies for a request, by tenant,
  validity window, scope and target — served from the per-org cache (§27).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.abac.attributes import AttributeRegistryService
from app.authorization.abac.conditions import ConditionEvaluator
from app.authorization.abac.enums import (
    ABACAuditEvent,
    CombiningAlgorithm,
    PolicyEffect,
    PolicyScopeType,
    PolicyStatus,
)
from app.authorization.abac.operators import validate_condition_value
from app.identity.errors import ErrorCode, IdentityError
from app.models.abac import ABACPolicy, ABACPolicyException, ABACPolicyVersion
from app.models.rbac import AuthorizationAudit
from app.models.user import User

MAX_CONDITION_DEPTH = 16
_TARGET_KEYS = {"resource_types", "actions", "identity_types", "roles", "classifications"}
_SUB_ORG_SCOPES = {
    PolicyScopeType.BUSINESS_UNIT.value, PolicyScopeType.DEPARTMENT.value,
    PolicyScopeType.TEAM.value, PolicyScopeType.PROJECT.value, PolicyScopeType.RESOURCE.value,
}


def record_abac_event(db: Session, event: ABACAuditEvent, *, organization_id, actor_id,
                      meta: dict | None = None) -> None:
    db.add(AuthorizationAudit(organization_id=organization_id, actor_id=actor_id,
                              event_type=event.value, meta=meta))
    db.flush()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Cache (§27) — active policy snapshots per tenant, version-invalidated.
# In-process by design (single-node deployment); every mutation bumps the key.
# --------------------------------------------------------------------------- #
class PolicyCache:
    _store: dict[str, tuple[int, list[dict]]] = {}
    _versions: dict[str, int] = {}
    hits: int = 0
    misses: int = 0

    @classmethod
    def _key(cls, organization_id: uuid.UUID | None) -> str:
        return str(organization_id) if organization_id else "platform"

    @classmethod
    def get(cls, organization_id: uuid.UUID | None) -> list[dict] | None:
        key = cls._key(organization_id)
        entry = cls._store.get(key)
        version = cls._versions.get(key, 0)
        if entry is not None and entry[0] == version:
            cls.hits += 1
            return entry[1]
        cls.misses += 1
        return None

    @classmethod
    def put(cls, organization_id: uuid.UUID | None, policies: list[dict]) -> None:
        key = cls._key(organization_id)
        cls._store[key] = (cls._versions.get(key, 0), policies)

    @classmethod
    def invalidate(cls, organization_id: uuid.UUID | None) -> None:
        key = cls._key(organization_id)
        cls._versions[key] = cls._versions.get(key, 0) + 1
        if organization_id is not None:
            # A platform policy change affects every tenant; an org change also
            # invalidates the merged view cached under the org key.
            return
        cls._store.clear()

    @classmethod
    def reset(cls) -> None:
        cls._store.clear()
        cls._versions.clear()
        cls.hits = 0
        cls.misses = 0


# --------------------------------------------------------------------------- #
# Validation (§10, §24, §28)
# --------------------------------------------------------------------------- #
class PolicyValidationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.registry = AttributeRegistryService(db)

    def validate(self, policy: ABACPolicy) -> list[dict]:
        """Full §24 validation. Returns [] when valid, else a list of
        ``{"code", "message"}`` errors."""
        errors: list[dict] = []

        def err(code: str, message: str) -> None:
            errors.append({"code": code, "message": message})

        # Effect + combining algorithm + status-independent basics.
        if policy.effect not in {e.value for e in PolicyEffect}:
            err(ErrorCode.ABAC_EFFECT_INVALID, f"Unknown effect {policy.effect!r}.")
        if policy.combining_algorithm not in {a.value for a in CombiningAlgorithm}:
            err(ErrorCode.ABAC_POLICY_INVALID,
                f"Unknown combining algorithm {policy.combining_algorithm!r}.")
        if not policy.name or not policy.name.strip():
            err(ErrorCode.ABAC_POLICY_INVALID, "A policy needs a name.")

        # Scope (§12).
        if policy.scope_type not in {s.value for s in PolicyScopeType}:
            err(ErrorCode.ABAC_SCOPE_INVALID, f"Unknown scope type {policy.scope_type!r}.")
        elif policy.scope_type in _SUB_ORG_SCOPES and policy.scope_id is None:
            err(ErrorCode.ABAC_SCOPE_INVALID,
                f"{policy.scope_type} scope requires a scope_id.")

        # Target (§11).
        target = policy.target or {}
        if not isinstance(target, dict):
            err(ErrorCode.ABAC_POLICY_INVALID, "Target must be an object.")
        else:
            for key, value in target.items():
                if key not in _TARGET_KEYS:
                    err(ErrorCode.ABAC_POLICY_INVALID, f"Unknown target key {key!r}.")
                elif not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    err(ErrorCode.ABAC_POLICY_INVALID,
                        f"Target {key} must be a list of strings.")

        # Validity window.
        vf, vu = _aware(policy.valid_from), _aware(policy.valid_until)
        if vf and vu and vf >= vu:
            err(ErrorCode.ABAC_POLICY_INVALID, "valid_from must precede valid_until.")

        # Conditions (§9, §10, §20).
        conditions = policy.conditions
        if conditions is not None and not isinstance(conditions, dict):
            err(ErrorCode.ABAC_CONDITION_INVALID, "Conditions must be an object.")
        elif conditions:
            if ConditionEvaluator.depth_of(conditions) > MAX_CONDITION_DEPTH:
                err(ErrorCode.ABAC_CONDITION_INVALID,
                    f"Condition tree deeper than {MAX_CONDITION_DEPTH} levels.")
            if not self._tree_shape_ok(conditions):
                err(ErrorCode.ABAC_CONDITION_INVALID,
                    "Each node must be an ALL/ANY list, a NOT node, or an "
                    "attribute/operator leaf.")
            else:
                catalog = self.registry.catalog()
                for leaf in ConditionEvaluator.leaves_of(conditions):
                    errors.extend(self._validate_leaf(leaf, catalog))

        # Obligations (§8).
        errors.extend(self._validate_obligations(policy.effect, policy.obligations))
        return errors

    def _tree_shape_ok(self, node: Any) -> bool:
        if not isinstance(node, dict) or not node:
            return False
        if "all" in node or "any" in node:
            children = node.get("all") or node.get("any")
            return isinstance(children, list) and len(children) > 0 and all(
                self._tree_shape_ok(child) for child in children
            )
        if "not" in node:
            return self._tree_shape_ok(node["not"])
        return "attribute" in node and "operator" in node

    def _validate_leaf(self, leaf: dict, catalog: dict) -> list[dict]:
        errors: list[dict] = []
        attribute, operator = leaf.get("attribute", ""), leaf.get("operator", "")
        definition = catalog.get(attribute)
        if definition is None or not definition.enabled:
            errors.append({"code": ErrorCode.ABAC_ATTRIBUTE_NOT_FOUND,
                           "message": f"Attribute {attribute!r} is not registered."})
            return errors
        supported = definition.supported_operators or []
        if operator not in supported:
            errors.append({"code": ErrorCode.ABAC_OPERATOR_NOT_SUPPORTED,
                           "message": f"Operator {operator!r} is not supported for "
                                      f"{attribute} ({definition.data_type})."})
            return errors
        type_error = validate_condition_value(operator, leaf.get("value"), definition.data_type)
        if type_error:
            errors.append({"code": ErrorCode.ABAC_ATTRIBUTE_TYPE_MISMATCH,
                           "message": f"{attribute}: {type_error}"})
        return errors

    def _validate_obligations(self, effect: str, obligations: dict | None) -> list[dict]:
        errors: list[dict] = []
        if obligations is None:
            if effect == PolicyEffect.MASK_FIELDS.value:
                errors.append({"code": ErrorCode.ABAC_OBLIGATION_INVALID,
                               "message": "MASK_FIELDS requires obligations.fields."})
            if effect == PolicyEffect.LIMIT_ACTION.value:
                errors.append({"code": ErrorCode.ABAC_OBLIGATION_INVALID,
                               "message": "LIMIT_ACTION requires obligation limits."})
            return errors
        if not isinstance(obligations, dict):
            return [{"code": ErrorCode.ABAC_OBLIGATION_INVALID,
                     "message": "Obligations must be an object."}]
        if effect == PolicyEffect.MASK_FIELDS.value:
            fields = obligations.get("fields")
            if not isinstance(fields, list) or not fields or not all(isinstance(f, str) for f in fields):
                errors.append({"code": ErrorCode.ABAC_OBLIGATION_INVALID,
                               "message": "MASK_FIELDS obligations need a non-empty 'fields' list."})
        if effect == PolicyEffect.LIMIT_ACTION.value:
            limits = {k: v for k, v in obligations.items() if k != "fields"}
            if not limits:
                errors.append({"code": ErrorCode.ABAC_OBLIGATION_INVALID,
                               "message": "LIMIT_ACTION obligations need at least one limit."})
        return errors


# --------------------------------------------------------------------------- #
# Lifecycle + versions (§7, §23)
# --------------------------------------------------------------------------- #
_MUTABLE = {PolicyStatus.DRAFT.value, PolicyStatus.VALIDATED.value}


class PolicyService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.validator = PolicyValidationService(db)

    # --- reads ----------------------------------------------------------- #
    def list(self, actor: User, *, status: str | None = None) -> list[ABACPolicy]:
        q = select(ABACPolicy).where(
            (ABACPolicy.organization_id == actor.organization_id)
            | (ABACPolicy.organization_id.is_(None))
        ).order_by(ABACPolicy.created_at.desc())
        if status:
            q = q.where(ABACPolicy.status == status.upper())
        return list(self.db.execute(q).scalars())

    def get(self, actor: User, policy_id: uuid.UUID) -> ABACPolicy:
        p = self.db.get(ABACPolicy, policy_id)
        if p is None or (p.organization_id is not None
                         and p.organization_id != actor.organization_id):
            raise IdentityError(ErrorCode.ABAC_POLICY_NOT_FOUND, "Policy not found.")
        return p

    def versions(self, actor: User, policy_id: uuid.UUID) -> list[ABACPolicyVersion]:
        p = self.get(actor, policy_id)
        return list(self.db.execute(
            select(ABACPolicyVersion)
            .where(ABACPolicyVersion.policy_family_id == p.policy_family_id)
            .order_by(ABACPolicyVersion.version.desc())
        ).scalars())

    # --- writes ------------------------------------------------------------ #
    def create(self, actor: User, payload: dict, *, is_platform_admin: bool) -> ABACPolicy:
        scope_type = (payload.get("scope_type") or PolicyScopeType.ORGANIZATION.value).upper()
        if scope_type == PolicyScopeType.PLATFORM.value and not is_platform_admin:
            raise IdentityError(ErrorCode.ABAC_POLICY_PUBLISH_DENIED,
                                "Platform-scoped policies require platform administration.")
        p = ABACPolicy(
            policy_family_id=uuid.uuid4(),
            organization_id=None if scope_type == PolicyScopeType.PLATFORM.value
            else actor.organization_id,
            name=payload.get("name", "").strip(),
            description=payload.get("description"),
            version=1, status=PolicyStatus.DRAFT.value,
            priority=payload.get("priority", 100),
            combining_algorithm=payload.get("combining_algorithm",
                                            CombiningAlgorithm.DENY_OVERRIDES.value),
            scope_type=scope_type, scope_id=payload.get("scope_id"),
            target=payload.get("target"), conditions=payload.get("conditions"),
            effect=(payload.get("effect") or PolicyEffect.DENY.value).upper(),
            obligations=payload.get("obligations"),
            valid_from=payload.get("valid_from"), valid_until=payload.get("valid_until"),
            created_by=actor.id, updated_by=actor.id,
        )
        if not p.name:
            raise IdentityError(ErrorCode.ABAC_POLICY_INVALID, "A policy needs a name.")
        self.db.add(p)
        self.db.flush()
        record_abac_event(self.db, ABACAuditEvent.ABAC_POLICY_CREATED,
                          organization_id=actor.organization_id, actor_id=actor.id,
                          meta={"policy_id": str(p.id), "name": p.name})
        return p

    def update(self, actor: User, policy_id: uuid.UUID, payload: dict) -> ABACPolicy:
        p = self.get(actor, policy_id)
        if p.status not in _MUTABLE:
            if p.status == PolicyStatus.ACTIVE.value:
                # §7 — published policies are immutable; editing creates a new draft version.
                p = self._new_version_from(actor, p, payload)
                record_abac_event(self.db, ABACAuditEvent.ABAC_POLICY_UPDATED,
                                  organization_id=actor.organization_id, actor_id=actor.id,
                                  meta={"policy_id": str(p.id), "new_version": p.version})
                return p
            raise IdentityError(ErrorCode.ABAC_POLICY_CONFLICT,
                                f"A {p.status} policy cannot be edited.")
        for field in ("name", "description", "priority", "combining_algorithm",
                      "scope_type", "scope_id", "target", "conditions", "effect",
                      "obligations", "valid_from", "valid_until"):
            if field in payload and payload[field] is not None:
                setattr(p, field, payload[field])
        p.status = PolicyStatus.DRAFT.value  # edits require re-validation
        p.updated_by = actor.id
        self.db.flush()
        record_abac_event(self.db, ABACAuditEvent.ABAC_POLICY_UPDATED,
                          organization_id=actor.organization_id, actor_id=actor.id,
                          meta={"policy_id": str(p.id)})
        return p

    def _new_version_from(self, actor: User, active: ABACPolicy, payload: dict) -> ABACPolicy:
        latest = self.db.execute(
            select(ABACPolicy.version).where(ABACPolicy.policy_family_id == active.policy_family_id)
            .order_by(ABACPolicy.version.desc()).limit(1)
        ).scalar_one()
        clone = ABACPolicy(
            policy_family_id=active.policy_family_id,
            organization_id=active.organization_id,
            name=payload.get("name") or active.name,
            description=payload.get("description") or active.description,
            version=latest + 1, status=PolicyStatus.DRAFT.value,
            priority=payload.get("priority") or active.priority,
            combining_algorithm=payload.get("combining_algorithm") or active.combining_algorithm,
            scope_type=payload.get("scope_type") or active.scope_type,
            scope_id=payload.get("scope_id") or active.scope_id,
            target=payload.get("target") if payload.get("target") is not None else active.target,
            conditions=payload.get("conditions") if payload.get("conditions") is not None
            else active.conditions,
            effect=(payload.get("effect") or active.effect),
            obligations=payload.get("obligations") if payload.get("obligations") is not None
            else active.obligations,
            valid_from=payload.get("valid_from") or active.valid_from,
            valid_until=payload.get("valid_until") or active.valid_until,
            created_by=actor.id, updated_by=actor.id,
        )
        self.db.add(clone)
        self.db.flush()
        return clone

    def delete(self, actor: User, policy_id: uuid.UUID) -> None:
        p = self.get(actor, policy_id)
        # §7 — deleting published history is prohibited; only never-published drafts go.
        if p.status not in _MUTABLE or p.published_at is not None:
            raise IdentityError(ErrorCode.ABAC_POLICY_CONFLICT,
                                "Published policies cannot be deleted — archive instead.")
        self.db.delete(p)
        self.db.flush()

    # --- lifecycle ---------------------------------------------------------- #
    def validate(self, actor: User, policy_id: uuid.UUID) -> tuple[ABACPolicy, list[dict]]:
        p = self.get(actor, policy_id)
        errors = self.validator.validate(p)
        if not errors and p.status == PolicyStatus.DRAFT.value:
            p.status = PolicyStatus.VALIDATED.value
            self.db.flush()
        record_abac_event(self.db, ABACAuditEvent.ABAC_POLICY_VALIDATED,
                          organization_id=actor.organization_id, actor_id=actor.id,
                          meta={"policy_id": str(p.id), "errors": len(errors)})
        return p, errors

    def publish(self, actor: User, policy_id: uuid.UUID, *, is_platform_admin: bool) -> ABACPolicy:
        p = self.get(actor, policy_id)
        if p.organization_id is None and not is_platform_admin:
            raise IdentityError(ErrorCode.ABAC_POLICY_PUBLISH_DENIED,
                                "Publishing platform policies requires platform administration.")
        if p.status not in _MUTABLE:
            raise IdentityError(ErrorCode.ABAC_POLICY_CONFLICT,
                                f"A {p.status} policy cannot be published.")
        errors = self.validator.validate(p)  # §28 — compile-on-publish
        if errors:
            raise IdentityError(ErrorCode.ABAC_POLICY_INVALID,
                                "; ".join(e["message"] for e in errors[:5]))
        # Only one ACTIVE version per family (§7): deprecate the current one.
        for other in self.db.execute(
            select(ABACPolicy).where(
                ABACPolicy.policy_family_id == p.policy_family_id,
                ABACPolicy.status == PolicyStatus.ACTIVE.value,
                ABACPolicy.id != p.id,
            )
        ).scalars():
            other.status = PolicyStatus.DEPRECATED.value
        p.status = PolicyStatus.ACTIVE.value
        p.published_at = _now()
        p.updated_by = actor.id
        self.db.add(ABACPolicyVersion(
            policy_family_id=p.policy_family_id, version=p.version,
            snapshot=self.snapshot(p), created_by=actor.id,
        ))
        self.db.flush()
        PolicyCache.invalidate(p.organization_id)
        record_abac_event(self.db, ABACAuditEvent.ABAC_POLICY_PUBLISHED,
                          organization_id=actor.organization_id, actor_id=actor.id,
                          meta={"policy_id": str(p.id), "version": p.version})
        return p

    def disable(self, actor: User, policy_id: uuid.UUID) -> ABACPolicy:
        p = self.get(actor, policy_id)
        p.status = PolicyStatus.DISABLED.value
        self.db.flush()
        PolicyCache.invalidate(p.organization_id)
        record_abac_event(self.db, ABACAuditEvent.ABAC_POLICY_DISABLED,
                          organization_id=actor.organization_id, actor_id=actor.id,
                          meta={"policy_id": str(p.id)})
        return p

    def archive(self, actor: User, policy_id: uuid.UUID) -> ABACPolicy:
        p = self.get(actor, policy_id)
        p.status = PolicyStatus.ARCHIVED.value
        self.db.flush()
        PolicyCache.invalidate(p.organization_id)
        record_abac_event(self.db, ABACAuditEvent.ABAC_POLICY_ARCHIVED,
                          organization_id=actor.organization_id, actor_id=actor.id,
                          meta={"policy_id": str(p.id)})
        return p

    def clone(self, actor: User, policy_id: uuid.UUID) -> ABACPolicy:
        p = self.get(actor, policy_id)
        clone = ABACPolicy(
            policy_family_id=uuid.uuid4(), organization_id=actor.organization_id,
            name=f"{p.name} (copy)", description=p.description, version=1,
            status=PolicyStatus.DRAFT.value, priority=p.priority,
            combining_algorithm=p.combining_algorithm, scope_type=p.scope_type,
            scope_id=p.scope_id, target=p.target, conditions=p.conditions,
            effect=p.effect, obligations=p.obligations,
            valid_from=p.valid_from, valid_until=p.valid_until,
            created_by=actor.id, updated_by=actor.id,
        )
        self.db.add(clone)
        self.db.flush()
        record_abac_event(self.db, ABACAuditEvent.ABAC_POLICY_CREATED,
                          organization_id=actor.organization_id, actor_id=actor.id,
                          meta={"policy_id": str(clone.id), "cloned_from": str(p.id)})
        return clone

    def rollback(self, actor: User, policy_id: uuid.UUID, version: int, *,
                 is_platform_admin: bool) -> ABACPolicy:
        p = self.get(actor, policy_id)
        snapshot_row = self.db.execute(
            select(ABACPolicyVersion).where(
                ABACPolicyVersion.policy_family_id == p.policy_family_id,
                ABACPolicyVersion.version == version,
            )
        ).scalar_one_or_none()
        if snapshot_row is None:
            raise IdentityError(ErrorCode.ABAC_POLICY_NOT_FOUND, "Version not found.")
        restored = self._new_version_from(actor, p, snapshot_row.snapshot)
        published = self.publish(actor, restored.id, is_platform_admin=is_platform_admin)
        record_abac_event(self.db, ABACAuditEvent.ABAC_POLICY_ROLLED_BACK,
                          organization_id=actor.organization_id, actor_id=actor.id,
                          meta={"policy_id": str(published.id), "restored_version": version,
                                "new_version": published.version})
        return published

    @staticmethod
    def snapshot(p: ABACPolicy) -> dict:
        return {
            "name": p.name, "description": p.description, "priority": p.priority,
            "combining_algorithm": p.combining_algorithm, "scope_type": p.scope_type,
            "scope_id": str(p.scope_id) if p.scope_id else None,
            "target": p.target, "conditions": p.conditions, "effect": p.effect,
            "obligations": p.obligations,
            "valid_from": p.valid_from.isoformat() if p.valid_from else None,
            "valid_until": p.valid_until.isoformat() if p.valid_until else None,
        }


# --------------------------------------------------------------------------- #
# Resolver (§11, §12, §24) + exceptions (§21)
# --------------------------------------------------------------------------- #
class PolicyResolver:
    def __init__(self, db: Session) -> None:
        self.db = db

    def active_policies(self, organization_id: uuid.UUID | None) -> list[dict]:
        cached = PolicyCache.get(organization_id)
        if cached is not None:
            return cached
        rows = self.db.execute(
            select(ABACPolicy).where(
                ABACPolicy.status == PolicyStatus.ACTIVE.value,
                (ABACPolicy.organization_id == organization_id)
                | (ABACPolicy.organization_id.is_(None)),
            )
        ).scalars()
        policies = [self._as_dict(p) for p in rows]
        PolicyCache.put(organization_id, policies)
        return policies

    def resolve(self, organization_id: uuid.UUID | None, context_flat: dict,
                subject_id: uuid.UUID | None = None) -> list[dict]:
        """Applicable policies: active, inside their validity window, scope and
        target matching, and not exempted for this subject."""
        now = _now()
        applicable = []
        for p in self.active_policies(organization_id):
            if p["valid_from"] and now < p["valid_from"]:
                continue
            if p["valid_until"] and now > p["valid_until"]:
                continue
            if not self._scope_matches(p, context_flat):
                continue
            if not self._target_matches(p, context_flat):
                continue
            if subject_id is not None and self._has_exception(p, subject_id, context_flat):
                continue
            applicable.append(p)
        # §13 precedence: broader scope first, then priority (higher number first).
        scope_rank = {s.value: i for i, s in enumerate(PolicyScopeType)}
        applicable.sort(key=lambda p: (scope_rank.get(p["scope_type"], 9), -p["priority"]))
        return applicable

    def _as_dict(self, p: ABACPolicy) -> dict:
        return {
            "id": str(p.id), "policy_family_id": str(p.policy_family_id),
            "organization_id": str(p.organization_id) if p.organization_id else None,
            "name": p.name, "version": p.version, "priority": p.priority,
            "combining_algorithm": p.combining_algorithm,
            "scope_type": p.scope_type,
            "scope_id": str(p.scope_id) if p.scope_id else None,
            "target": p.target or {}, "conditions": p.conditions,
            "effect": p.effect, "obligations": p.obligations or {},
            "valid_from": _aware(p.valid_from), "valid_until": _aware(p.valid_until),
        }

    def _scope_matches(self, p: dict, ctx: dict) -> bool:
        st, sid = p["scope_type"], p["scope_id"]
        if st in (PolicyScopeType.PLATFORM.value, PolicyScopeType.ORGANIZATION.value):
            return True  # tenancy already filtered in active_policies()
        if sid is None:
            return False
        if st == PolicyScopeType.RESOURCE.value:
            return ctx.get("resource.id") == sid
        attr = {
            PolicyScopeType.BUSINESS_UNIT.value: "business_unit_id",
            PolicyScopeType.DEPARTMENT.value: "department_id",
            PolicyScopeType.TEAM.value: "team_id",
            PolicyScopeType.PROJECT.value: "project_id",
        }[st]
        return ctx.get(f"resource.{attr}") == sid or ctx.get(f"identity.{attr}") == sid

    def _target_matches(self, p: dict, ctx: dict) -> bool:
        target = p["target"]
        checks = [
            ("resource_types", ctx.get("resource.type")),
            ("actions", ctx.get("action.name")),
            ("identity_types", ctx.get("identity.type")),
            ("classifications", ctx.get("resource.classification")),
        ]
        for key, actual in checks:
            wanted = target.get(key)
            if not wanted:
                continue
            if actual is None:
                return False
            if key == "actions":
                if not any(actual == w or (w.endswith(".*") and actual.startswith(w[:-1]))
                           for w in wanted):
                    return False
            elif actual not in wanted:
                return False
        wanted_roles = target.get("roles")
        if wanted_roles:
            roles = ctx.get("identity.roles") or []
            if not any(r in roles for r in wanted_roles):
                return False
        return True

    def _has_exception(self, p: dict, subject_id: uuid.UUID, ctx: dict) -> bool:
        now = _now()
        rows = self.db.execute(
            select(ABACPolicyException).where(
                ABACPolicyException.policy_id == uuid.UUID(p["id"]),
                ABACPolicyException.subject_id == subject_id,
                ABACPolicyException.status == "ACTIVE",
            )
        ).scalars()
        for exc in rows:
            if exc.valid_until is not None and _aware(exc.valid_until) < now:
                exc.status = "EXPIRED"  # §40.12 — exceptions expire automatically
                record_abac_event(self.db, ABACAuditEvent.POLICY_EXCEPTION_EXPIRED,
                                  organization_id=None, actor_id=None,
                                  meta={"exception_id": str(exc.id), "policy_id": p["id"]})
                continue
            if exc.valid_from is not None and _aware(exc.valid_from) > now:
                continue
            if exc.resource_id is not None and ctx.get("resource.id") != str(exc.resource_id):
                continue
            return True
        return False
