"""Phase 5.2.6 SRS ACT-VER-FR-100..108 — compatibility & breaking-change detection.

Classifies a candidate version against a resolved baseline into
``COMPATIBLE`` / ``BACKWARD_COMPATIBLE`` / ``BREAKING`` / ``UNKNOWN``, and
persists the verdict onto ``agent_versions.compatibility_level`` plus one
``AgentVersionCompatibilityFinding`` row per detected change.

Three data-source decisions worth recording, since a wrong guess here would
propagate into every future compatibility judgment the platform makes:

- **Input/output contract** is read from ``AgentDefinition.input_schema`` /
  ``output_schema`` — real JSON Schema (``properties``/``required``),
  already carried into a version's frozen snapshot (``snapshot.py``) and the
  same fields ``app.runtime.services._validate_schema`` uses to actually
  validate execution payloads elsewhere in this codebase. Not
  ``AgentVersion.configuration_snapshot``: today that field is simply a copy
  of ``model_configuration`` (see ``AgentVersionService.create``) with no
  "inputs" substructure of its own to diff.
- **Resource limits** have no dedicated field on a version or its snapshot
  (``AgentDeployment.runtime_limits`` is the closest match, but it lives on
  a per-environment deployment, not a version, and isn't part of what a
  version snapshots). This module instead scans ``model_configuration`` for
  numeric values whose key name looks like a limit/quota
  (``max_*``/``*_limit``/``*_timeout``/``*_quota``/``*_cap``) — a heuristic,
  not something specified anywhere, deliberately excluding the sampling
  parameters called out below.
- **Model configuration nuance**: a change to ``temperature``, ``top_p``,
  ``top_k``, or the frequency/presence penalties is behavioral drift, not a
  contract change — classified ``COMPATIBLE``. A change to ``provider`` or
  ``model`` is a different underlying model/provider and is classified
  ``BREAKING``.
- **Policy tightening** is scored only for the three ``policy_snapshot``
  keys ``RuntimePolicyService.evaluate`` (``app/runtime/services.py``)
  actually gives meaning to — ``approved_models``, ``prohibited_
  environments``, ``requires_approval_environments`` — rather than guessing
  at semantics for arbitrary future policy keys.

Like ``VersionComparisonService`` (``compare.py``) and
``VersionReadinessService`` (``readiness.py``), this module reads directly
from ``AgentVersion``/``AgentDefinition`` ORM columns rather than the frozen
``agent_version_snapshots.snapshot`` document — those columns are exactly
what the frozen document is built from (``snapshot.py``), and reading them
directly lets a still-DRAFT version's readiness check reason about
compatibility before anything has ever been published.

Semver-consistency is advisory only, matching Part 1's advisory-only
boundary for comparison and readiness (see docs/runtime/versioning.md):
reported as a finding and surfaced in readiness, never raised from
``publish()``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import AgentDefinition, AgentVersion, AgentVersionCompatibilityFinding
from app.runtime.versioning.semantic_version import parse_semver

logger = logging.getLogger(__name__)

CATEGORIES = ("INPUT_CONTRACT", "OUTPUT_CONTRACT", "TOOL_BINDING", "CAPABILITY", "MODEL_CONFIG",
             "RESOURCE_LIMIT", "POLICY", "PROMPT", "METADATA")
CHANGE_TYPES = ("ADDED", "REMOVED", "MODIFIED")
MATERIALITY_LEVELS = ("BREAKING", "BACKWARD_COMPATIBLE", "COMPATIBLE")
COMPATIBILITY_LEVELS = ("COMPATIBLE", "BACKWARD_COMPATIBLE", "BREAKING", "UNKNOWN")

_SAMPLING_PARAMETERS = {"temperature", "top_p", "top_k", "frequency_penalty", "presence_penalty", "seed"}
_LIMIT_KEYWORDS = ("max", "limit", "quota", "timeout", "cap", "threshold")
_POLICY_RESTRICTION_LISTS = ("prohibited_environments", "requires_approval_environments")
_KIND_SPACE = {
    "integer": frozenset({"integer"}),
    "number": frozenset({"integer", "float"}),
    "string": frozenset({"string"}),
    "boolean": frozenset({"boolean"}),
    "object": frozenset({"object"}),
    "array": frozenset({"array"}),
    "null": frozenset({"null"}),
}
_INCREMENT_RANK = {"major": 3, "minor": 2, "patch": 1, "none": 0}


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Finding:
    category: str
    path: str
    change_type: str
    materiality: str
    description: str
    baseline_value: str | None = None
    candidate_value: str | None = None


def _finding_dict(finding) -> dict:
    """Normalizes a ``Finding`` dataclass instance or an
    ``AgentVersionCompatibilityFinding`` ORM row to the same plain dict —
    both expose identical attribute names by design."""
    return {
        "category": finding.category, "path": finding.path, "change_type": finding.change_type,
        "materiality": finding.materiality, "baseline_value": finding.baseline_value,
        "candidate_value": finding.candidate_value, "description": finding.description,
    }


# --------------------------------------------------------------------------- #
# Semver consistency helpers (§4.3) — pure, database-free.
# --------------------------------------------------------------------------- #
def declared_increment(baseline_semver: str, candidate_semver: str) -> str:
    """Which of major/minor/patch actually changed between two semvers."""
    baseline, candidate = parse_semver(baseline_semver), parse_semver(candidate_semver)
    if candidate[0] != baseline[0]:
        return "major"
    if candidate[1] != baseline[1]:
        return "minor"
    if candidate[2] != baseline[2]:
        return "patch"
    return "none"


def expected_increment_for(level: str) -> str | None:
    return {"BREAKING": "major", "BACKWARD_COMPATIBLE": "minor", "COMPATIBLE": "patch"}.get(level)


def is_semver_consistent(declared: str | None, expected: str | None) -> bool:
    """§4.3 — the expected increment is a *minimum*: a major bump satisfies
    an expectation of minor or patch."""
    if expected is None:
        return True
    return _INCREMENT_RANK.get(declared or "none", 0) >= _INCREMENT_RANK.get(expected, 0)


# --------------------------------------------------------------------------- #
# Input/output contract (§4.2) — JSON Schema properties/required diffing.
# --------------------------------------------------------------------------- #
def _kind_space(prop_schema: dict | None) -> frozenset[str] | None:
    """The set of JSON value-kinds a property accepts. ``None`` means "any"
    (no ``type`` constraint) — the universal superset of every other space."""
    type_field = (prop_schema or {}).get("type")
    if not type_field:
        return None
    names = [type_field] if isinstance(type_field, str) else list(type_field)
    space: set[str] = set()
    for name in names:
        space |= _KIND_SPACE.get(name, {name})
    return frozenset(space)


def _type_change(baseline_prop: dict | None, candidate_prop: dict | None) -> str | None:
    """Returns ``"NARROWED"``, ``"WIDENED"``, or ``None`` (no meaningful
    change). An unrelated/incomparable type change (e.g. ``string`` ->
    ``boolean``) is treated conservatively as narrowed."""
    baseline_space, candidate_space = _kind_space(baseline_prop), _kind_space(candidate_prop)
    if baseline_space == candidate_space:
        return None
    if baseline_space is None:
        return "NARROWED"
    if candidate_space is None:
        return "WIDENED"
    if baseline_space < candidate_space:
        return "WIDENED"
    if candidate_space < baseline_space:
        return "NARROWED"
    return "NARROWED"


def _raw_type_label(prop_schema: dict | None) -> str:
    type_field = (prop_schema or {}).get("type")
    if not type_field:
        return "any"
    if isinstance(type_field, str):
        return type_field
    return "|".join(sorted(type_field))


def _describe_prop(prop_schema: dict | None, required: bool) -> str:
    return f"{_raw_type_label(prop_schema)} ({'required' if required else 'optional'})"


def _compare_json_schema(baseline_schema: dict | None, candidate_schema: dict | None, *,
                         category: str, path_prefix: str, is_output: bool) -> list[Finding]:
    baseline_schema, candidate_schema = baseline_schema or {}, candidate_schema or {}
    baseline_props: dict = baseline_schema.get("properties") or {}
    candidate_props: dict = candidate_schema.get("properties") or {}
    baseline_required = set(baseline_schema.get("required") or [])
    candidate_required = set(candidate_schema.get("required") or [])
    findings: list[Finding] = []
    noun = "Output" if is_output else "Input"

    for key, baseline_prop in baseline_props.items():
        path = f"{path_prefix}.{key}"
        if key not in candidate_props:
            findings.append(Finding(
                category=category, path=path, change_type="REMOVED", materiality="BREAKING",
                baseline_value=_describe_prop(baseline_prop, key in baseline_required), candidate_value=None,
                description=(
                    f"{noun} field '{key}' was removed; "
                    + ("callers expecting it in the response will need to handle its absence."
                       if is_output else "existing callers supplying it will now fail validation.")
                ),
            ))
            continue

        candidate_prop = candidate_props[key]
        if not is_output:
            was_required, is_required = key in baseline_required, key in candidate_required
            if not was_required and is_required:
                findings.append(Finding(
                    category=category, path=path, change_type="MODIFIED", materiality="BREAKING",
                    baseline_value=_describe_prop(baseline_prop, was_required),
                    candidate_value=_describe_prop(candidate_prop, is_required),
                    description=f"Input field '{key}' became required; existing callers that previously "
                               "omitted it will now fail validation.",
                ))
            elif was_required and not is_required:
                findings.append(Finding(
                    category=category, path=path, change_type="MODIFIED", materiality="BACKWARD_COMPATIBLE",
                    baseline_value=_describe_prop(baseline_prop, was_required),
                    candidate_value=_describe_prop(candidate_prop, is_required),
                    description=f"Input field '{key}' became optional; every existing caller that already "
                               "supplied it continues to work unchanged.",
                ))

        type_change = _type_change(baseline_prop, candidate_prop)
        if type_change == "NARROWED":
            findings.append(Finding(
                category=category, path=f"{path}.type", change_type="MODIFIED", materiality="BREAKING",
                baseline_value=_raw_type_label(baseline_prop), candidate_value=_raw_type_label(candidate_prop),
                description=f"The type of {noun.lower()} field '{key}' narrowed from "
                           f"{_raw_type_label(baseline_prop)} to {_raw_type_label(candidate_prop)}; values "
                           f"existing callers previously {'received' if is_output else 'sent'} may now be "
                           f"{'no longer produced' if is_output else 'rejected'}.",
            ))
        elif type_change == "WIDENED":
            findings.append(Finding(
                category=category, path=f"{path}.type", change_type="MODIFIED", materiality="BACKWARD_COMPATIBLE",
                baseline_value=_raw_type_label(baseline_prop), candidate_value=_raw_type_label(candidate_prop),
                description=f"The type of {noun.lower()} field '{key}' widened from "
                           f"{_raw_type_label(baseline_prop)} to {_raw_type_label(candidate_prop)}; every value "
                           "existing callers used before remains valid.",
            ))

    for key, candidate_prop in candidate_props.items():
        if key in baseline_props:
            continue
        path = f"{path_prefix}.{key}"
        if is_output:
            findings.append(Finding(
                category=category, path=path, change_type="ADDED", materiality="BACKWARD_COMPATIBLE",
                baseline_value=None, candidate_value=_describe_prop(candidate_prop, key in candidate_required),
                description=f"Output field '{key}' was added; existing callers that ignore unrecognized fields "
                           "are unaffected.",
            ))
        elif key in candidate_required and "default" not in (candidate_prop or {}):
            findings.append(Finding(
                category=category, path=path, change_type="ADDED", materiality="BREAKING",
                baseline_value=None, candidate_value=_describe_prop(candidate_prop, True),
                description=f"A new required input field '{key}' was added with no default value; existing "
                           "callers that don't already supply it will now fail validation.",
            ))
        else:
            # Genuinely optional (not in `required`), or required but with a
            # declared default — either way, an existing caller that omits
            # it is unaffected.
            findings.append(Finding(
                category=category, path=path, change_type="ADDED", materiality="BACKWARD_COMPATIBLE",
                baseline_value=None, candidate_value=_describe_prop(candidate_prop, key in candidate_required),
                description=f"Optional input field '{key}' was added; existing callers that omit it are "
                           "unaffected.",
            ))
    return findings


def compare_input_contract(baseline_schema: dict | None, candidate_schema: dict | None) -> list[Finding]:
    return _compare_json_schema(baseline_schema, candidate_schema, category="INPUT_CONTRACT",
                                path_prefix="inputs", is_output=False)


def compare_output_contract(baseline_schema: dict | None, candidate_schema: dict | None) -> list[Finding]:
    return _compare_json_schema(baseline_schema, candidate_schema, category="OUTPUT_CONTRACT",
                                path_prefix="outputs", is_output=True)


# --------------------------------------------------------------------------- #
# Tool bindings & capabilities (§4.2) — set diffs, mirroring compare.py's
# own list-field handling.
# --------------------------------------------------------------------------- #
def _compare_list_bindings(baseline_list: list | None, candidate_list: list | None, *,
                           category: str, noun: str) -> list[Finding]:
    baseline_set, candidate_set = set(baseline_list or []), set(candidate_list or [])
    singular = noun[:-1] if noun.endswith("s") else noun
    findings: list[Finding] = []
    for item in sorted(baseline_set - candidate_set):
        findings.append(Finding(
            category=category, path=f"{noun}.{item}", change_type="REMOVED", materiality="BREAKING",
            baseline_value=item, candidate_value=None,
            description=f"The {singular} '{item}' was removed; existing callers that depend on it being "
                       "available to this agent will now be denied or fail.",
        ))
    for item in sorted(candidate_set - baseline_set):
        findings.append(Finding(
            category=category, path=f"{noun}.{item}", change_type="ADDED", materiality="BACKWARD_COMPATIBLE",
            baseline_value=None, candidate_value=item,
            description=f"A new {singular} '{item}' was added; existing callers are unaffected since nothing "
                       "that previously worked was removed.",
        ))
    return findings


def compare_tool_bindings(baseline_tools: list | None, candidate_tools: list | None) -> list[Finding]:
    return _compare_list_bindings(baseline_tools, candidate_tools, category="TOOL_BINDING", noun="tools")


def compare_capabilities(baseline_capabilities: list | None, candidate_capabilities: list | None) -> list[Finding]:
    return _compare_list_bindings(baseline_capabilities, candidate_capabilities, category="CAPABILITY",
                                  noun="capabilities")


# --------------------------------------------------------------------------- #
# Model configuration & resource limits (§4.2) — provider/model, sampling
# parameters, and the numeric-limit heuristic described in the module
# docstring.
# --------------------------------------------------------------------------- #
def _looks_like_limit(key: str) -> bool:
    lower = key.lower()
    return any(word in lower for word in _LIMIT_KEYWORDS)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compare_model_configuration(baseline_config: dict | None, candidate_config: dict | None) -> list[Finding]:
    baseline, candidate = baseline_config or {}, candidate_config or {}
    findings: list[Finding] = []
    for key in sorted(set(baseline) | set(candidate)):
        if key not in baseline or key not in candidate or baseline[key] == candidate[key]:
            continue
        path = f"model_configuration.{key}"
        if key in ("provider", "model"):
            findings.append(Finding(
                category="MODEL_CONFIG", path=path, change_type="MODIFIED", materiality="BREAKING",
                baseline_value=str(baseline[key]), candidate_value=str(candidate[key]),
                description=f"The model configuration's '{key}' changed from '{baseline[key]}' to "
                           f"'{candidate[key]}'; this is a different underlying model/provider with potentially "
                           "different behavior, latency, and output format — existing integrations should be "
                           "re-validated.",
            ))
        elif key in _SAMPLING_PARAMETERS:
            findings.append(Finding(
                category="MODEL_CONFIG", path=path, change_type="MODIFIED", materiality="COMPATIBLE",
                baseline_value=str(baseline[key]), candidate_value=str(candidate[key]),
                description=f"Sampling parameter '{key}' changed from {baseline[key]} to {candidate[key]}; this "
                           "is behavioral drift, not a contract change — existing callers are unaffected "
                           "structurally.",
            ))
        elif _looks_like_limit(key) and _is_number(baseline[key]) and _is_number(candidate[key]):
            if candidate[key] < baseline[key]:
                findings.append(Finding(
                    category="RESOURCE_LIMIT", path=path, change_type="MODIFIED", materiality="BREAKING",
                    baseline_value=str(baseline[key]), candidate_value=str(candidate[key]),
                    description=f"Resource limit '{key}' was reduced from {baseline[key]} to {candidate[key]}; "
                               "existing callers operating within the old limit may now be rejected or "
                               "truncated.",
                ))
            else:
                findings.append(Finding(
                    category="RESOURCE_LIMIT", path=path, change_type="MODIFIED", materiality="BACKWARD_COMPATIBLE",
                    baseline_value=str(baseline[key]), candidate_value=str(candidate[key]),
                    description=f"Resource limit '{key}' was increased from {baseline[key]} to {candidate[key]}; "
                               "every case that worked under the old limit continues to work.",
                ))
        else:
            findings.append(Finding(
                category="MODEL_CONFIG", path=path, change_type="MODIFIED", materiality="COMPATIBLE",
                baseline_value=str(baseline[key]), candidate_value=str(candidate[key]),
                description=f"Model configuration field '{key}' changed from {baseline[key]!r} to "
                           f"{candidate[key]!r}; no known contract impact.",
            ))
    return findings


# --------------------------------------------------------------------------- #
# Policy tightening (§4.2) — scoped to the three keys RuntimePolicyService
# actually reads (app/runtime/services.py::RuntimePolicyService.evaluate).
# --------------------------------------------------------------------------- #
def compare_policy(baseline_policy: dict | None, candidate_policy: dict | None) -> list[Finding]:
    baseline, candidate = baseline_policy or {}, candidate_policy or {}
    findings: list[Finding] = []

    baseline_models, candidate_models = baseline.get("approved_models"), candidate.get("approved_models")
    if baseline_models != candidate_models:
        baseline_set = set(baseline_models) if baseline_models is not None else None
        candidate_set = set(candidate_models) if candidate_models is not None else None
        path = "policy.approved_models"
        if baseline_set is None and candidate_set is not None:
            findings.append(Finding(
                category="POLICY", path=path, change_type="MODIFIED", materiality="BREAKING",
                baseline_value="unrestricted", candidate_value=", ".join(sorted(candidate_set)),
                description="An approved-models allow-list was introduced where none existed before; any "
                           "caller using a model outside this new list will now be denied.",
            ))
        elif baseline_set is not None and candidate_set is None:
            findings.append(Finding(
                category="POLICY", path=path, change_type="MODIFIED", materiality="BACKWARD_COMPATIBLE",
                baseline_value=", ".join(sorted(baseline_set)), candidate_value="unrestricted",
                description="The approved-models allow-list was removed; every model that was previously "
                           "allowed is still allowed, plus more.",
            ))
        else:
            removed = baseline_set - candidate_set
            if removed:
                findings.append(Finding(
                    category="POLICY", path=path, change_type="MODIFIED", materiality="BREAKING",
                    baseline_value=", ".join(sorted(baseline_set)), candidate_value=", ".join(sorted(candidate_set)),
                    description=f"Model(s) {', '.join(sorted(removed))} were removed from the approved-models "
                               "list; callers configured to use them will now be denied.",
                ))
            else:
                findings.append(Finding(
                    category="POLICY", path=path, change_type="MODIFIED", materiality="BACKWARD_COMPATIBLE",
                    baseline_value=", ".join(sorted(baseline_set)), candidate_value=", ".join(sorted(candidate_set)),
                    description="The approved-models list grew; every previously-approved model is still "
                               "approved.",
                ))

    for list_key in _POLICY_RESTRICTION_LISTS:
        baseline_list = set(baseline.get(list_key) or [])
        candidate_list = set(candidate.get(list_key) or [])
        added, removed = candidate_list - baseline_list, baseline_list - candidate_list
        path = f"policy.{list_key}"
        blocks_outright = list_key == "prohibited_environments"
        for env in sorted(added):
            findings.append(Finding(
                category="POLICY", path=f"{path}.{env}", change_type="ADDED", materiality="BREAKING",
                baseline_value=None, candidate_value=env,
                description=f"Environment '{env}' was added to {list_key}; executions there that previously "
                           "proceeded without this restriction will now be "
                           + ("blocked outright." if blocks_outright else "held for approval."),
            ))
        for env in sorted(removed):
            findings.append(Finding(
                category="POLICY", path=f"{path}.{env}", change_type="REMOVED", materiality="BACKWARD_COMPATIBLE",
                baseline_value=env, candidate_value=None,
                description=f"Environment '{env}' was removed from {list_key}; executions there are no longer "
                           + ("blocked." if blocks_outright else "held for approval."),
            ))
    return findings


# --------------------------------------------------------------------------- #
# Prompt & metadata (§4.2) — always COMPATIBLE; no contract impact.
# --------------------------------------------------------------------------- #
def compare_prompt_and_metadata(baseline_prompt, candidate_prompt, baseline_release_notes,
                                candidate_release_notes) -> list[Finding]:
    findings: list[Finding] = []
    if (baseline_prompt or None) != (candidate_prompt or None):
        findings.append(Finding(
            category="PROMPT", path="prompt_snapshot", change_type="MODIFIED", materiality="COMPATIBLE",
            baseline_value=None, candidate_value=None,
            description="The version's prompt content changed; this has no structural contract impact on "
                       "callers, though it may change model behavior.",
        ))
    if (baseline_release_notes or None) != (candidate_release_notes or None):
        findings.append(Finding(
            category="METADATA", path="release_notes", change_type="MODIFIED", materiality="COMPATIBLE",
            baseline_value=baseline_release_notes, candidate_value=candidate_release_notes,
            description="Release notes text changed; documentation only, no contract impact.",
        ))
    return findings


# --------------------------------------------------------------------------- #
# Orchestration (§4.1) — pure, database-free.
# --------------------------------------------------------------------------- #
def detect_breaking(findings: list[Finding]) -> bool:
    return any(finding.materiality == "BREAKING" for finding in findings)


def overall_level(findings: list[Finding]) -> str:
    """§4.2 precedence — one breaking finding makes the whole version
    BREAKING regardless of how many compatible/backward-compatible findings
    accompany it. Only called when a baseline was actually resolved; the
    no-baseline case is UNKNOWN regardless of findings (§4.1, §4.4)."""
    if detect_breaking(findings):
        return "BREAKING"
    if any(finding.materiality == "BACKWARD_COMPATIBLE" for finding in findings):
        return "BACKWARD_COMPATIBLE"
    return "COMPATIBLE"


def classify_change(*, baseline_input_schema: dict | None = None, candidate_input_schema: dict | None = None,
                    baseline_output_schema: dict | None = None, candidate_output_schema: dict | None = None,
                    baseline_tools: list | None = None, candidate_tools: list | None = None,
                    baseline_capabilities: list | None = None, candidate_capabilities: list | None = None,
                    baseline_model_configuration: dict | None = None,
                    candidate_model_configuration: dict | None = None,
                    baseline_policy: dict | None = None, candidate_policy: dict | None = None,
                    baseline_prompt=None, candidate_prompt=None,
                    baseline_release_notes: str | None = None,
                    candidate_release_notes: str | None = None) -> tuple[str, list[Finding]]:
    """Runs every classification rule and returns ``(level, findings)`` for
    one candidate-vs-baseline comparison. Entirely database-free — every
    argument is a plain dict/list/scalar, so this is unit-testable with no
    database connection at all."""
    findings: list[Finding] = []
    findings += compare_input_contract(baseline_input_schema, candidate_input_schema)
    findings += compare_output_contract(baseline_output_schema, candidate_output_schema)
    findings += compare_tool_bindings(baseline_tools, candidate_tools)
    findings += compare_capabilities(baseline_capabilities, candidate_capabilities)
    findings += compare_model_configuration(baseline_model_configuration, candidate_model_configuration)
    findings += compare_policy(baseline_policy, candidate_policy)
    findings += compare_prompt_and_metadata(baseline_prompt, candidate_prompt, baseline_release_notes,
                                            candidate_release_notes)
    return overall_level(findings), findings


def _summarize(findings: list) -> dict:
    return {
        "breaking": sum(1 for f in findings if f.materiality == "BREAKING"),
        "backward_compatible": sum(1 for f in findings if f.materiality == "BACKWARD_COMPATIBLE"),
        "compatible": sum(1 for f in findings if f.materiality == "COMPATIBLE"),
    }


# --------------------------------------------------------------------------- #
# CompatibilityAnalysisService — the database-touching layer. Direct
# SQLAlchemy queries, no repository layer, matching the rest of the runtime
# domain (see REPO_STATE.md §7).
# --------------------------------------------------------------------------- #
class CompatibilityAnalysisService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_404(self, agent_id: uuid.UUID, version_id: uuid.UUID) -> AgentVersion:
        version = self.db.get(AgentVersion, version_id)
        if version is None or version.agent_id != agent_id:
            raise IdentityError(ErrorCode.AGENT_VERSION_NOT_FOUND, "Agent version not found.")
        return version

    def resolve_baseline(self, version: AgentVersion, *, baseline_id: uuid.UUID | None = None) -> AgentVersion | None:
        """§4.4 — an explicit ``baseline_id`` always wins; otherwise
        ``parent_version_id``; otherwise the highest ``PUBLISHED`` version
        older than the candidate for the same agent; otherwise ``None``
        (the caller reports ``UNKNOWN``)."""
        if baseline_id is not None:
            baseline = self.db.get(AgentVersion, baseline_id)
            if baseline is None or baseline.agent_id != version.agent_id:
                raise IdentityError(ErrorCode.COMPATIBILITY_BASELINE_NOT_FOUND,
                                    "The requested baseline version does not exist for this agent.")
            return baseline
        if version.parent_version_id is not None:
            parent = self.db.get(AgentVersion, version.parent_version_id)
            if parent is not None:
                return parent
        return self.db.execute(
            select(AgentVersion).where(
                AgentVersion.agent_id == version.agent_id,
                AgentVersion.status == "PUBLISHED",
                AgentVersion.version < version.version,
            ).order_by(AgentVersion.version.desc()).limit(1)
        ).scalar_one_or_none()

    def analyze(self, version_id: uuid.UUID, *, agent_id: uuid.UUID | None = None,
               baseline_id: uuid.UUID | None = None, persist: bool = True) -> dict:
        """Computes a compatibility report for ``version_id``. Persists the
        verdict onto the version row and replaces its findings when
        ``persist`` is True (the default, and always true for the automatic
        post-publish trigger and the explicit ``/analyze`` endpoint); an
        explicit-baseline ``GET`` evaluates ephemerally (``persist=False``)
        so a read-only lookup against a hypothetical baseline never has a
        side effect."""
        version = self.db.get(AgentVersion, version_id)
        if version is None or (agent_id is not None and version.agent_id != agent_id):
            raise IdentityError(ErrorCode.AGENT_VERSION_NOT_FOUND, "Agent version not found.")

        baseline = self.resolve_baseline(version, baseline_id=baseline_id)

        if baseline is None:
            level = "UNKNOWN"
            findings: list[Finding] = [Finding(
                category="METADATA", path="baseline", change_type="ADDED", materiality="COMPATIBLE",
                baseline_value=None, candidate_value=None,
                description="No baseline version could be resolved (no parent version and no earlier "
                           "published version exists for this agent) — compatibility cannot be determined "
                           "for this version.",
            )]
        else:
            baseline_definition = self.db.get(AgentDefinition, baseline.definition_id)
            candidate_definition = self.db.get(AgentDefinition, version.definition_id)
            level, findings = classify_change(
                baseline_input_schema=baseline_definition.input_schema if baseline_definition else None,
                candidate_input_schema=candidate_definition.input_schema if candidate_definition else None,
                baseline_output_schema=baseline_definition.output_schema if baseline_definition else None,
                candidate_output_schema=candidate_definition.output_schema if candidate_definition else None,
                baseline_tools=baseline.tools_snapshot, candidate_tools=version.tools_snapshot,
                baseline_capabilities=baseline.capabilities_snapshot,
                candidate_capabilities=version.capabilities_snapshot,
                baseline_model_configuration=baseline.model_configuration,
                candidate_model_configuration=version.model_configuration,
                baseline_policy=baseline.policy_snapshot, candidate_policy=version.policy_snapshot,
                baseline_prompt=baseline.prompt_snapshot, candidate_prompt=version.prompt_snapshot,
                baseline_release_notes=baseline.release_notes, candidate_release_notes=version.release_notes,
            )

        analyzed_at = _now()
        expected_incr = expected_increment_for(level) if level != "UNKNOWN" else None
        declared_incr = declared_increment(baseline.semantic_version, version.semantic_version) if baseline else None
        semver_ok = is_semver_consistent(declared_incr, expected_incr) if baseline else True

        if persist:
            version.compatibility_level = level
            version.compatibility_baseline_id = baseline.id if baseline else None
            version.compatibility_analyzed_at = analyzed_at
            self._persist_findings(version.id, baseline.id if baseline else None, findings)
            self.db.commit()
            self.db.refresh(version)

        return {
            "candidate_version_id": version.id,
            "baseline_version_id": baseline.id if baseline else None,
            "compatibility_level": level,
            "declared_semver": version.semantic_version,
            "declared_increment": declared_incr,
            "expected_increment": expected_incr,
            "semver_consistent": semver_ok,
            "analyzed_at": analyzed_at,
            "summary": _summarize(findings),
            "findings": [_finding_dict(f) for f in findings],
        }

    def _persist_findings(self, version_id: uuid.UUID, baseline_id: uuid.UUID | None,
                          findings: list[Finding]) -> None:
        """Re-running analysis replaces prior findings for that version
        rather than accumulating duplicates."""
        self.db.execute(delete(AgentVersionCompatibilityFinding).where(
            AgentVersionCompatibilityFinding.agent_version_id == version_id))
        for finding in findings:
            self.db.add(AgentVersionCompatibilityFinding(
                agent_version_id=version_id, baseline_version_id=baseline_id, category=finding.category,
                path=finding.path, change_type=finding.change_type, materiality=finding.materiality,
                baseline_value=finding.baseline_value, candidate_value=finding.candidate_value,
                description=finding.description,
            ))
        self.db.flush()

    def get_report(self, version_id: uuid.UUID) -> dict:
        """Returns the last-persisted compatibility report for a version
        without recomputing anything — the cheap, side-effect-free read
        path for ``GET .../compatibility`` (no baseline override)."""
        version = self.db.get(AgentVersion, version_id)
        if version is None:
            raise IdentityError(ErrorCode.AGENT_VERSION_NOT_FOUND, "Agent version not found.")
        findings = self.list_findings(version_id)
        baseline = (self.db.get(AgentVersion, version.compatibility_baseline_id)
                   if version.compatibility_baseline_id else None)
        level = version.compatibility_level
        expected_incr = expected_increment_for(level) if level != "UNKNOWN" else None
        declared_incr = declared_increment(baseline.semantic_version, version.semantic_version) if baseline else None
        semver_ok = is_semver_consistent(declared_incr, expected_incr) if baseline else True
        return {
            "candidate_version_id": version.id,
            "baseline_version_id": baseline.id if baseline else None,
            "compatibility_level": level,
            "declared_semver": version.semantic_version,
            "declared_increment": declared_incr,
            "expected_increment": expected_incr,
            "semver_consistent": semver_ok,
            "analyzed_at": version.compatibility_analyzed_at,
            "summary": _summarize(findings),
            "findings": [_finding_dict(f) for f in findings],
        }

    def list_findings(self, version_id: uuid.UUID) -> list[AgentVersionCompatibilityFinding]:
        stmt = select(AgentVersionCompatibilityFinding).where(
            AgentVersionCompatibilityFinding.agent_version_id == version_id
        ).order_by(AgentVersionCompatibilityFinding.created_at)
        return list(self.db.execute(stmt).scalars())
