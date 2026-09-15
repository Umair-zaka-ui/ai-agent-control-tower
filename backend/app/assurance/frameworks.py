"""Phase 5.9 (M5.9) - framework mappings: which ACT controls produce evidence
*relevant to* a published framework control.

**Read this before adding a mapping.** A mapping here is a claim about ACT, not
about the law. It says:

    "The evidence ACT's control X produces is relevant to NIST AI RMF GOVERN-1.1."

It does **not** say, and must never be read as saying:

    "Satisfying ACT's control X means you comply with NIST AI RMF GOVERN-1.1."

The difference is not pedantry. Whether an organization complies with a
framework depends on scope, interpretation, compensating controls, an auditor's
judgement and often a regulator's - none of which ACT can observe. ACT can say
what evidence it holds and where that evidence is relevant. An auditor decides
what it amounts to.

That is why there is no coverage percentage, no per-framework score, and no
status in this module or anywhere downstream of it. A "78% SOC 2 compliant"
badge would be the single most misleading thing this platform could render: it
would invent a denominator ACT does not know (the full control set in the
customer's chosen scope) and a verdict ACT is not entitled to give. What ACT
reports is the mapped controls and their evaluations - PASS, FAIL, or
INSUFFICIENT_EVIDENCE - and nothing aggregated into a judgement.

**Mappings are partial on purpose, and say so.** ACT maps the controls it
genuinely has evidence for. Every framework below covers far more ground than
ACT observes - personnel security, physical controls, vendor management,
training - and those are deliberately absent rather than stubbed. An absent
mapping means "ACT holds no evidence here", which is honest; a stubbed one
evaluating to PASS would be a fabrication.

**Versioned.** ``MAPPING_VERSION`` changes whenever a mapping changes, so a
stored evaluation can be traced to the mapping that produced it. Framework
revisions are tracked in ``FRAMEWORKS`` (``NIST AI RMF 1.0``, not "NIST"), since
control identifiers move between revisions.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Bump when any mapping below changes.
MAPPING_VERSION = "1"


@dataclass(frozen=True)
class Framework:
    id: str
    name: str
    revision: str
    #: Stated on every rendering of this framework. Not a disclaimer bolted on
    #: at the UI layer - it travels with the data.
    scope_note: str


FRAMEWORKS: tuple[Framework, ...] = (
    Framework(
        "NIST_AI_RMF", "NIST AI Risk Management Framework", "1.0",
        "ACT maps evidence to a subset of RMF subcategories it can observe. The RMF "
        "is a voluntary framework with no certification; ACT makes no conformance claim."),
    Framework(
        "ISO_42001", "ISO/IEC 42001 (AI management systems)", "2023",
        "ACT maps evidence to a subset of Annex A controls it can observe. Certification "
        "is issued by an accredited body assessing a management system, not by a tool; "
        "ACT makes no certification claim."),
    Framework(
        "SOC2", "SOC 2 Trust Services Criteria", "2017 (rev. 2022)",
        "ACT maps evidence to a subset of common criteria it can observe. A SOC 2 report "
        "is issued by a licensed CPA firm following an examination; ACT is not an auditor "
        "and makes no opinion."),
)

FRAMEWORKS_BY_ID = {f.id: f for f in FRAMEWORKS}


@dataclass(frozen=True)
class FrameworkMapping:
    """One published control, and the ACT controls that evidence it."""

    framework_id: str
    #: The identifier exactly as the framework publishes it, so a reader can
    #: look it up in the source document rather than trusting a paraphrase.
    control_ref: str
    title: str
    #: Why this ACT evidence is relevant to that control. The sentence an
    #: auditor reads when asking "why did you map these together?"
    rationale: str
    act_control_ids: tuple[str, ...]


MAPPINGS: tuple[FrameworkMapping, ...] = (
    # ---- NIST AI RMF 1.0 -------------------------------------------------- #
    FrameworkMapping(
        "NIST_AI_RMF", "GOVERN-1.1",
        "Legal and regulatory requirements are understood, managed and documented",
        "ACT evidences that each AI system has an accountable owner and an active "
        "governance policy — the organizational accountability this subcategory expects.",
        ("ACT.OWNERSHIP.ACCOUNTABLE_OWNER", "ACT.GOVERNANCE.POLICY_COVERAGE")),
    FrameworkMapping(
        "NIST_AI_RMF", "MAP-1.1",
        "Context is established and understood",
        "ACT evidences the provenance of each AI system and whether its authority "
        "can be reconstructed — establishing what the system is and where it came from.",
        ("ACT.PROVENANCE.KNOWN_ORIGIN", "ACT.AUTHORITY.CHAIN_PROVABLE")),
    FrameworkMapping(
        "NIST_AI_RMF", "MAP-4.1",
        "Approaches for mapping AI technology and legal risk of its components are in place",
        "ACT evidences the approval state of models and of MCP/tool dependencies — the "
        "third-party components whose risk this subcategory concerns.",
        ("ACT.MODEL.APPROVED", "ACT.SUPPLY_CHAIN.MCP_TRUST")),
    FrameworkMapping(
        "NIST_AI_RMF", "MEASURE-2.7",
        "AI system security and resilience are evaluated and documented",
        "ACT evidences credential lifecycle, least-privilege tool grants and whether "
        "incidents involving the system can be reconstructed.",
        ("ACT.CREDENTIAL.LIFECYCLE", "ACT.TOOL.LEAST_PRIVILEGE",
         "ACT.INCIDENT.RECONSTRUCTABLE")),
    FrameworkMapping(
        "NIST_AI_RMF", "MANAGE-4.1",
        "Post-deployment monitoring plans are implemented",
        "ACT evidences that runtime activity is traceable and that a service level "
        "objective is defined — the monitoring this subcategory expects after deployment.",
        ("ACT.RUNTIME.TRACEABLE", "ACT.RELIABILITY.SLO_COVERAGE")),

    # ---- ISO/IEC 42001:2023 ----------------------------------------------- #
    FrameworkMapping(
        "ISO_42001", "A.6.2.2",
        "AI system requirements and specification",
        "ACT evidences that each AI system's origin is established and an accountable "
        "owner is recorded.",
        ("ACT.PROVENANCE.KNOWN_ORIGIN", "ACT.OWNERSHIP.ACCOUNTABLE_OWNER")),
    FrameworkMapping(
        "ISO_42001", "A.6.2.6",
        "AI system operation and monitoring",
        "ACT evidences runtime traceability, defined service level objectives and "
        "governed spend for each operating AI system.",
        ("ACT.RUNTIME.TRACEABLE", "ACT.RELIABILITY.SLO_COVERAGE", "ACT.COST.GOVERNED")),
    FrameworkMapping(
        "ISO_42001", "A.10.2",
        "Allocating responsibilities for third-party and customer relationships",
        "ACT evidences the approval state of third-party MCP servers and tools an AI "
        "system depends on.",
        ("ACT.SUPPLY_CHAIN.MCP_TRUST", "ACT.TOOL.LEAST_PRIVILEGE")),

    # ---- SOC 2 Trust Services Criteria ------------------------------------ #
    FrameworkMapping(
        "SOC2", "CC1.3",
        "Management establishes structures, reporting lines, authorities and responsibilities",
        "ACT evidences that each AI system has an accountable owner and a reconstructable "
        "authority chain.",
        ("ACT.OWNERSHIP.ACCOUNTABLE_OWNER", "ACT.AUTHORITY.CHAIN_PROVABLE")),
    FrameworkMapping(
        "SOC2", "CC6.1",
        "Logical access security software and infrastructure are implemented",
        "ACT evidences credential lifecycle state and least-privilege tool grants.",
        ("ACT.CREDENTIAL.LIFECYCLE", "ACT.TOOL.LEAST_PRIVILEGE")),
    FrameworkMapping(
        "SOC2", "CC7.2",
        "The entity monitors system components for anomalies indicative of malicious acts",
        "ACT evidences that threat detection has evaluated the system and that incidents "
        "are reconstructable from findings, containment records and the audit trail.",
        ("ACT.INCIDENT.RECONSTRUCTABLE", "ACT.RUNTIME.TRACEABLE")),
    FrameworkMapping(
        "SOC2", "CC7.3",
        "The entity evaluates security events to determine whether they could prevent objectives",
        "ACT evidences that an active governance policy is in force for the system.",
        ("ACT.GOVERNANCE.POLICY_COVERAGE",)),
)


def mappings_for(framework_id: str) -> tuple[FrameworkMapping, ...]:
    return tuple(m for m in MAPPINGS if m.framework_id == framework_id)


def act_controls_for(framework_id: str) -> tuple[str, ...]:
    seen: list[str] = []
    for m in mappings_for(framework_id):
        for cid in m.act_control_ids:
            if cid not in seen:
                seen.append(cid)
    return tuple(seen)


__all__ = [
    "MAPPING_VERSION",
    "Framework",
    "FRAMEWORKS",
    "FRAMEWORKS_BY_ID",
    "FrameworkMapping",
    "MAPPINGS",
    "mappings_for",
    "act_controls_for",
]
