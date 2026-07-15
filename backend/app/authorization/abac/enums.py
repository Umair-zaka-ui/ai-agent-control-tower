"""ABAC engine enums (Phase 4.3.5 §5, §7–§13, §38)."""

from __future__ import annotations

import enum


class PolicyStatus(str, enum.Enum):
    """§7 — DRAFT → VALIDATED → ACTIVE (published) → DISABLED/DEPRECATED/ARCHIVED.
    Draft/validated policies never affect decisions; published versions are
    immutable; at most one ACTIVE version per family."""

    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


class PolicyEffect(str, enum.Enum):
    """§8."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    REQUIRE_MFA = "REQUIRE_MFA"
    REQUIRE_JUSTIFICATION = "REQUIRE_JUSTIFICATION"
    MASK_FIELDS = "MASK_FIELDS"
    LIMIT_ACTION = "LIMIT_ACTION"
    LOG_ONLY = "LOG_ONLY"


# Effects that block until a challenge is satisfied (§4 "challenge").
CHALLENGE_EFFECTS = {
    PolicyEffect.REQUIRE_APPROVAL.value,
    PolicyEffect.REQUIRE_MFA.value,
    PolicyEffect.REQUIRE_JUSTIFICATION.value,
}
# Effects that allow but constrain the action (obligations attach).
CONSTRAINT_EFFECTS = {
    PolicyEffect.MASK_FIELDS.value,
    PolicyEffect.LIMIT_ACTION.value,
}


class CombiningAlgorithm(str, enum.Enum):
    """§13 — default DENY_OVERRIDES."""

    DENY_OVERRIDES = "DENY_OVERRIDES"
    ALLOW_OVERRIDES = "ALLOW_OVERRIDES"
    FIRST_APPLICABLE = "FIRST_APPLICABLE"
    HIGHEST_PRIORITY = "HIGHEST_PRIORITY"
    ALL_MUST_ALLOW = "ALL_MUST_ALLOW"


class PolicyScopeType(str, enum.Enum):
    """§12 — platform applies globally; narrower scopes apply downward."""

    PLATFORM = "PLATFORM"
    ORGANIZATION = "ORGANIZATION"
    BUSINESS_UNIT = "BUSINESS_UNIT"
    DEPARTMENT = "DEPARTMENT"
    TEAM = "TEAM"
    PROJECT = "PROJECT"
    RESOURCE = "RESOURCE"


class AttributeCategory(str, enum.Enum):
    """§5 — the five attribute categories."""

    SUBJECT = "SUBJECT"
    RESOURCE = "RESOURCE"
    ACTION = "ACTION"
    ENVIRONMENT = "ENVIRONMENT"
    AI = "AI"


class AttributeDataType(str, enum.Enum):
    """§10."""

    STRING = "STRING"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    DATETIME = "DATETIME"
    DATE = "DATE"
    TIME = "TIME"
    ARRAY = "ARRAY"
    SET = "SET"
    OBJECT = "OBJECT"
    NULL = "NULL"


class AttributeSensitivity(str, enum.Enum):
    """§20 — RESTRICTED values are redacted from user-facing output (§16)."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    RESTRICTED = "RESTRICTED"


class Operator(str, enum.Enum):
    """§9 — comparison operators. Logical ALL/ANY/NOT are tree nodes, not operators."""

    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    IN = "IN"
    NOT_IN = "NOT_IN"
    CONTAINS = "CONTAINS"
    NOT_CONTAINS = "NOT_CONTAINS"
    GREATER_THAN = "GREATER_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN = "LESS_THAN"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    STARTS_WITH = "STARTS_WITH"
    ENDS_WITH = "ENDS_WITH"
    MATCHES_REGEX = "MATCHES_REGEX"
    EXISTS = "EXISTS"
    NOT_EXISTS = "NOT_EXISTS"
    BETWEEN = "BETWEEN"


class ABACDecision(str, enum.Enum):
    """§4 — the normalized final decision."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    REQUIRE_MFA = "REQUIRE_MFA"
    REQUIRE_JUSTIFICATION = "REQUIRE_JUSTIFICATION"
    MASK_FIELDS = "MASK_FIELDS"
    LIMIT_ACTION = "LIMIT_ACTION"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ABACAuditEvent(str, enum.Enum):
    """§38 — recorded on the shared authorization_audit table."""

    ABAC_POLICY_CREATED = "ABAC_POLICY_CREATED"
    ABAC_POLICY_UPDATED = "ABAC_POLICY_UPDATED"
    ABAC_POLICY_VALIDATED = "ABAC_POLICY_VALIDATED"
    ABAC_POLICY_PUBLISHED = "ABAC_POLICY_PUBLISHED"
    ABAC_POLICY_DISABLED = "ABAC_POLICY_DISABLED"
    ABAC_POLICY_ARCHIVED = "ABAC_POLICY_ARCHIVED"
    ABAC_POLICY_ROLLED_BACK = "ABAC_POLICY_ROLLED_BACK"
    ABAC_POLICY_SIMULATED = "ABAC_POLICY_SIMULATED"
    ABAC_POLICY_MATCHED = "ABAC_POLICY_MATCHED"
    ABAC_ACCESS_ALLOWED = "ABAC_ACCESS_ALLOWED"
    ABAC_ACCESS_DENIED = "ABAC_ACCESS_DENIED"
    ABAC_APPROVAL_REQUIRED = "ABAC_APPROVAL_REQUIRED"
    ABAC_OBLIGATION_APPLIED = "ABAC_OBLIGATION_APPLIED"
    ATTRIBUTE_DEFINITION_CREATED = "ATTRIBUTE_DEFINITION_CREATED"
    ATTRIBUTE_DEFINITION_UPDATED = "ATTRIBUTE_DEFINITION_UPDATED"
    POLICY_EXCEPTION_CREATED = "POLICY_EXCEPTION_CREATED"
    POLICY_EXCEPTION_EXPIRED = "POLICY_EXCEPTION_EXPIRED"
