"""DT1 Stage 1 - the deterministic canonical estate generator (estate_truth).

``build_estate(seed, grounding)`` returns OBJECTIVE SYNTHETIC ENTERPRISE REALITY
ONLY: what exists in the fictional Northwind Payroll & Finance Group (primary
tenant) and Contoso Logistics (isolation-control tenant). It never states what
ACT is expected to observe, miss, find or refuse - that is the observability
contract's job, and Stage 2's to evaluate.

Every id is derived from the seed (``canonical.stable_id``); every list is sorted
by id before serialization; no wall-clock time, randomness, uuid4 or
environment-dependent value enters the artifact. Vocabularies (control states,
origin categories, enforcement modes, edge types, trust statuses, criticality,
classification, autonomy, lifecycle) are the real ACT names recorded by
``grounding.py``; the generator asserts against the grounding JSON so a schema
drift fails loudly instead of sealing a stale name.

Canonical agents carry OVERLAPPING properties (one agent can be external AND
shadow AND unowned AND over-privileged AND MCP-dependent AND gateway-enforced AND
of unknown provenance). Condition tags are DERIVED from facts by ``derive_conditions``
so they stay objective classifications of what exists, never expectations.
"""
from __future__ import annotations

from typing import Any

from canonical import sort_entities, stable_id, stable_uuid  # noqa: E402 - lab package, imported by path

# --------------------------------------------------------------------------- #
# vocabularies that must exist in the grounding (real ACT names)
# --------------------------------------------------------------------------- #
REQUIRED_VOCAB = {
    ("app/runtime/registry/control.py", "CONTROL_STATES"): ["DISCOVERED", "CLAIMED", "REGISTERED", "GOVERNED"],
    ("app/runtime/registry/control.py", "ORIGIN_CATEGORIES"): ["NATIVE", "EXTERNAL", "UNKNOWN"],
    ("app/models/bridge.py", "STORABLE_ENFORCEMENT_MODES"): ["OBSERVED", "ADVISORY", "GATEWAY_ENFORCED"],
    ("app/models/graph.py", "MCP_TRUST_STATUSES"): ["APPROVED", "PENDING", "REJECTED", "UNKNOWN"],
}
EDGE_TYPES_USED = ("DEPENDS_ON_TOOL", "DEPENDS_ON_MCP_SERVER", "DEPENDS_ON_CREDENTIAL", "DEPENDS_ON_RESOURCE",
                   "MCP_EXPOSES_TOOL", "TOOL_USES_CREDENTIAL", "TOOL_ACCESSES_RESOURCE", "CREDENTIAL_ACCESSES_RESOURCE",
                   "DELEGATES_TO", "AGENT_DELEGATES_TO", "TRUSTS")
LIFECYCLE_ACTIVE = "ACTIVE"
SENSITIVE = ("CONFIDENTIAL", "RESTRICTED", "REGULATED")

SERIOUS_CONDITIONS = frozenset({
    "OVER_PRIVILEGED_CREDENTIAL", "SHARED_CREDENTIAL", "STALE_CREDENTIAL", "EXPIRED_CREDENTIAL_STILL_ACTIVE",
    "UNOWNED", "SHADOW_DISCOVERABLE", "SHADOW_DARK", "UNKNOWN_PROVENANCE", "UNAPPROVED_MCP", "UNAPPROVED_TOOL",
    "DANGEROUS_DEPENDENCY_SENSITIVE_REACH", "DORMANT_WITH_ACTIVE_CREDENTIAL", "PRODUCTION_ACCESS_UNOWNED",
    "NATIVE_REFERENCE_COLLISION", "OUT_OF_SCOPE_GATEWAY_ATTEMPTS", "SHARED_GATEWAY_GRANT", "LIFECYCLE_NOT_ACTIVE_BUT_RUNNING",
})
STRUCTURAL_CONDITIONS = frozenset({
    "GATEWAY_ENFORCED_EXTERNAL", "TRUTHFUL_REFUSAL_SUBJECT", "I2_RELEVANT", "I1_RELEVANT", "F6_1_RELEVANT",
    "CLOUD_DISCOVERABLE", "REGISTRY_DISCOVERABLE",
})


def _check_vocab(grounding: dict) -> None:
    consts = grounding["constants"]
    for (path, name), expected in REQUIRED_VOCAB.items():
        got = consts.get(path, {}).get(name, {}).get("value")
        if got is None:
            raise SystemExit(f"GROUNDING CONFLICT: {path}::{name} not found - STOP, do not seal a guessed schema")
        if sorted(got) != sorted(expected):
            raise SystemExit(f"GROUNDING CONFLICT: {path}::{name} = {got} != expected {expected}")
    edge_types = consts["app/models/graph.py"]["EDGE_TYPES"]["value"]
    missing = [e for e in EDGE_TYPES_USED if e not in edge_types]
    if missing:
        raise SystemExit(f"GROUNDING CONFLICT: edge types {missing} absent from EDGE_TYPES")
    legal = consts["app/runtime/registry/control.py"]["LEGAL_CONTROL_STATES_BY_ORIGIN"]["value"]
    if sorted(legal["NATIVE"]) != ["GOVERNED"] or "GOVERNED" in legal["EXTERNAL"]:
        raise SystemExit("GROUNDING CONFLICT: LEGAL_CONTROL_STATES_BY_ORIGIN changed - the estate's control states must be re-derived")
    lifecycle = consts["app/runtime/services.py"]["AGENT_LIFECYCLE"]["value"]
    for st in ("ACTIVE", "SUSPENDED", "RETIRED", "DRAFT", "REGISTERED", "APPROVED"):
        if st not in lifecycle:
            raise SystemExit(f"GROUNDING CONFLICT: lifecycle state {st} absent")


# --------------------------------------------------------------------------- #
# the fictional enterprise - short keys here, stable ids in the artifact
# --------------------------------------------------------------------------- #
PEOPLE = [  # key, name, title, roles
    ("cfo", "Dana Whitfield", "Chief Financial Officer", ["BUSINESS_OWNER"]),
    ("payroll_lead", "Ines Marchetti", "Head of Payroll Operations", ["BUSINESS_OWNER"]),
    ("hr_dir", "Tomas Lindqvist", "HR Director", ["BUSINESS_OWNER"]),
    ("comp_mgr", "Priya Raman", "Compensation Manager", ["BUSINESS_OWNER"]),
    ("treasury", "Kwame Boateng", "Treasury Manager", ["BUSINESS_OWNER"]),
    ("it_eng", "Lena Hoffmann", "Senior Platform Engineer", ["TECHNICAL_OWNER"]),
    ("platform_eng", "Yusuf Demir", "Staff Engineer, AI Platform", ["TECHNICAL_OWNER"]),
    ("data_eng", "Mei Tanaka", "Data Engineering Lead", ["TECHNICAL_OWNER"]),
    ("sec_lead", "Rafael Ortiz", "Security Lead", ["SECURITY_OWNER", "COMPLIANCE_OWNER"]),
    ("compliance", "Aisha Khan", "Compliance Officer", ["COMPLIANCE_OWNER"]),
    ("ops_mgr", "Bram de Vries", "IT Operations Manager", ["BUSINESS_OWNER", "TECHNICAL_OWNER"]),
    ("marketing", "Chloe Bennett", "Marketing Director", ["BUSINESS_OWNER"]),
    ("vendor_mgr", "Olu Adeyemi", "Vendor Management Lead", ["BUSINESS_OWNER"]),
    ("analyst", "Sofia Petrova", "Financial Analyst", []),
    ("intern", "Jakub Nowak", "Finance Intern", []),
    ("contractor", "Ravi Iyer", "External Contractor (Data)", []),
    ("recruiting", "Hannah Okafor", "Talent Acquisition Lead", ["BUSINESS_OWNER"]),
]

RESOURCES = [  # key, name, resource_type, sensitivity, environment
    ("payroll_db", "Employee Payroll Database", "database", "RESTRICTED", "PRODUCTION"),
    ("comp_records", "Employee Compensation Records", "records_store", "RESTRICTED", "PRODUCTION"),
    ("financial_records", "Financial Records", "records_store", "CONFIDENTIAL", "PRODUCTION"),
    ("ledger_export", "General Ledger Export", "object_storage", "CONFIDENTIAL", "PRODUCTION"),
    ("hr_directory", "HR Directory", "directory", "INTERNAL", "PRODUCTION"),
    ("benefits_store", "Benefits Enrollment Store", "database", "CONFIDENTIAL", "PRODUCTION"),
    ("expense_bucket", "Expense Reports Bucket", "object_storage", "INTERNAL", "PRODUCTION"),
    ("vendor_master", "Vendor Master", "database", "INTERNAL", "PRODUCTION"),
    ("ticketing", "IT Ticketing System", "saas_app", "INTERNAL", "PRODUCTION"),
    ("wiki", "Knowledge Wiki", "wiki", "INTERNAL", "PRODUCTION"),
    ("catalog", "Public Product Catalog", "saas_app", "PUBLIC", "PRODUCTION"),
    ("marketing_bucket", "Marketing Assets Bucket", "object_storage", "PUBLIC", "PRODUCTION"),
    ("treasury_queue", "Treasury Payments Queue", "queue", "RESTRICTED", "PRODUCTION"),
    ("audit_archive", "Audit Log Archive", "object_storage", "CONFIDENTIAL", "PRODUCTION"),
    ("convo_store", "Copilot Conversation Store", "database", "CONFIDENTIAL", "PRODUCTION"),
    ("recruiting_ats", "Applicant Tracking System", "saas_app", "CONFIDENTIAL", "PRODUCTION"),
    ("dev_sandbox_db", "Development Sandbox Database", "database", "INTERNAL", "DEVELOPMENT"),
]

# key, label, kind, posture tags, access (resource keys), held_in_act, last_used_days_ago, expired_days_ago|None, owner
CREDENTIALS = [
    ("payroll_ro", "svc-payroll-readonly", "SERVICE_ACCOUNT", ["LEAST_PRIVILEGE"], ["payroll_db"], True, 1, None, "payroll_lead"),
    ("finance_shared_sa", "svc-finance-shared", "SERVICE_ACCOUNT", ["SHARED", "OVER_PRIVILEGED"],
     ["payroll_db", "comp_records", "financial_records", "ledger_export", "treasury_queue"], False, 0, None, "analyst"),
    ("hr_dir_ro", "svc-hr-directory-readonly", "SERVICE_ACCOUNT", ["LEAST_PRIVILEGE"], ["hr_directory"], True, 2, None, "hr_dir"),
    ("benefits_rw", "svc-benefits-enrollment", "SERVICE_ACCOUNT", ["LEAST_PRIVILEGE"], ["benefits_store"], True, 1, None, "hr_dir"),
    ("ops_ticketing", "oauth-ops-ticketing", "OAUTH_CLIENT", ["LEAST_PRIVILEGE"], ["ticketing"], True, 0, None, "ops_mgr"),
    ("wiki_ro", "apikey-wiki-readonly", "API_KEY", ["LEAST_PRIVILEGE"], ["wiki"], True, 3, None, "ops_mgr"),
    ("catalog_public", "apikey-catalog-public", "API_KEY", ["LEAST_PRIVILEGE"], ["catalog"], True, 0, None, "marketing"),
    ("treasury_initiator", "svc-treasury-initiator", "SERVICE_ACCOUNT", ["OVER_PRIVILEGED"],
     ["treasury_queue", "financial_records", "ledger_export"], False, 4, None, "treasury"),
    ("legacy_etl_2023", "svc-legacy-etl-2023", "SERVICE_ACCOUNT", ["STALE", "OVER_PRIVILEGED"],
     ["payroll_db", "comp_records", "hr_directory"], False, 412, None, "data_eng"),
    ("expired_vendor_key", "apikey-vendor-portal-2024", "API_KEY", ["EXPIRED_STILL_ACTIVE"], ["vendor_master"], True, 9, 61, "vendor_mgr"),
    ("marketing_rw", "oauth-marketing-assets", "OAUTH_CLIENT", ["LEAST_PRIVILEGE"], ["marketing_bucket"], True, 1, None, "marketing"),
    ("dev_sandbox", "svc-dev-sandbox", "SERVICE_ACCOUNT", ["LEAST_PRIVILEGE"], ["dev_sandbox_db"], True, 0, None, "platform_eng"),
    ("audit_ro", "svc-audit-archive-readonly", "SERVICE_ACCOUNT", ["LEAST_PRIVILEGE"], ["audit_archive"], True, 5, None, "compliance"),
    ("exec_runner", "svc-exec-runner", "SERVICE_ACCOUNT", ["OVER_PRIVILEGED"],
     ["dev_sandbox_db", "expense_bucket", "wiki", "financial_records"], False, 2, None, "contractor"),
    ("comp_ro", "svc-compensation-readonly", "SERVICE_ACCOUNT", ["LEAST_PRIVILEGE"], ["comp_records"], True, 1, None, "comp_mgr"),
    ("expense_ro", "svc-expense-readonly", "SERVICE_ACCOUNT", ["LEAST_PRIVILEGE"], ["expense_bucket"], True, 2, None, "cfo"),
    ("finrec_ro", "svc-financial-records-readonly", "SERVICE_ACCOUNT", ["LEAST_PRIVILEGE"], ["financial_records", "ledger_export"], True, 1, None, "cfo"),
    ("convo_store_rw", "svc-copilot-conversations", "SERVICE_ACCOUNT", ["LEAST_PRIVILEGE"], ["convo_store"], True, 0, None, "platform_eng"),
    ("ats_rw", "oauth-ats-recruiting", "OAUTH_CLIENT", ["LEAST_PRIVILEGE"], ["recruiting_ats"], True, 0, None, "recruiting"),
    ("personal_token_analyst", "personal-token-analyst-desktop", "PERSONAL_TOKEN", ["SHARED", "OVER_PRIVILEGED"],
     ["financial_records", "comp_records"], False, 1, None, "analyst"),
    ("vendor_ro", "svc-vendor-master-readonly", "SERVICE_ACCOUNT", ["LEAST_PRIVILEGE"], ["vendor_master"], True, 1, None, "vendor_mgr"),
]

MCP_SERVERS = [  # key, name, trust_status, provenance, registered_in_act, exposes tool keys
    ("finance_mcp", "finance-mcp", "APPROVED", "EXPLICIT", True, ["ledger_export_tool", "finrec_query"]),
    ("finance_mcp_legacy", "finance-mcp-legacy", "UNKNOWN", "DISCOVERED", True, ["payroll_query", "comp_lookup", "ledger_export_tool"]),
    ("hr_mcp", "hr-mcp", "APPROVED", "EXPLICIT", True, ["hr_directory_search", "benefits_update"]),
    ("ops_mcp", "ops-mcp", "APPROVED", "EXPLICIT", True, ["ticket_create", "wiki_search", "calendar_read"]),
    ("community_mcp", "community-tools-mcp", "REJECTED", "DISCOVERED", True, ["code_exec", "file_fetch"]),
    ("treasury_mcp", "treasury-mcp", "PENDING", "EXPLICIT", True, ["treasury_initiate_payment"]),
    ("recruiting_mcp", "recruiting-mcp", "APPROVED", "EXPLICIT", True, ["ats_search", "ats_update"]),
]

# key, name, tool_type, approval, risk_level, side_effect_level, data_classification, requires_approval,
# uses credential key|None, accesses resource keys, registered_in_act
TOOLS = [
    ("payroll_query", "payroll-query", "HTTP", "APPROVED", "HIGH", "NONE", "RESTRICTED", False, "payroll_ro", ["payroll_db"], True),
    ("comp_lookup", "compensation-lookup", "HTTP", "APPROVED", "HIGH", "NONE", "RESTRICTED", False, "comp_ro", ["comp_records"], True),
    ("ledger_export_tool", "ledger-export", "HTTP", "APPROVED", "MEDIUM", "NONE", "CONFIDENTIAL", False, "finrec_ro", ["ledger_export"], True),
    ("finrec_query", "financial-records-query", "HTTP", "APPROVED", "MEDIUM", "NONE", "CONFIDENTIAL", False, "finrec_ro", ["financial_records"], True),
    ("hr_directory_search", "hr-directory-search", "HTTP", "APPROVED", "LOW", "NONE", "INTERNAL", False, "hr_dir_ro", ["hr_directory"], True),
    ("benefits_update", "benefits-enrollment-update", "HTTP", "APPROVED", "HIGH", "WRITE", "CONFIDENTIAL", True, "benefits_rw", ["benefits_store"], True),
    ("expense_submit", "expense-report-submit", "HTTP", "APPROVED", "MEDIUM", "WRITE", "INTERNAL", True, "expense_ro", ["expense_bucket"], True),
    ("vendor_lookup", "vendor-lookup", "HTTP", "APPROVED", "LOW", "NONE", "INTERNAL", False, "vendor_ro", ["vendor_master"], True),
    ("ticket_create", "ticket-create", "HTTP", "APPROVED", "LOW", "WRITE", "INTERNAL", False, "ops_ticketing", ["ticketing"], True),
    ("wiki_search", "wiki-search", "HTTP", "APPROVED", "LOW", "NONE", "INTERNAL", False, "wiki_ro", ["wiki"], True),
    ("catalog_search", "catalog-search", "HTTP", "APPROVED", "LOW", "NONE", "PUBLIC", False, "catalog_public", ["catalog"], True),
    ("email_send", "email-send", "HTTP", "APPROVED", "MEDIUM", "EXTERNAL", "INTERNAL", True, None, [], True),
    ("treasury_initiate_payment", "treasury-initiate-payment", "HTTP", "UNAPPROVED", "CRITICAL", "IRREVERSIBLE", "RESTRICTED", True, "treasury_initiator", ["treasury_queue"], True),
    ("file_fetch", "file-fetch", "HTTP", "UNAPPROVED", "HIGH", "NONE", "INTERNAL", False, "exec_runner", ["expense_bucket", "wiki"], True),
    ("code_exec", "code-exec", "FUNCTION", "UNAPPROVED", "CRITICAL", "IRREVERSIBLE", "INTERNAL", False, "exec_runner", ["dev_sandbox_db"], True),
    ("calendar_read", "calendar-read", "HTTP", "APPROVED", "LOW", "NONE", "INTERNAL", False, None, [], True),
    ("audit_query", "audit-archive-query", "HTTP", "APPROVED", "MEDIUM", "NONE", "CONFIDENTIAL", False, "audit_ro", ["audit_archive"], True),
    ("ats_search", "ats-candidate-search", "HTTP", "APPROVED", "MEDIUM", "NONE", "CONFIDENTIAL", False, "ats_rw", ["recruiting_ats"], True),
    ("ats_update", "ats-candidate-update", "HTTP", "APPROVED", "MEDIUM", "WRITE", "CONFIDENTIAL", True, "ats_rw", ["recruiting_ats"], True),
    ("marketing_publish", "marketing-asset-publish", "HTTP", "APPROVED", "LOW", "WRITE", "PUBLIC", False, "marketing_rw", ["marketing_bucket"], True),
    ("convo_persist", "conversation-persist", "HTTP", "APPROVED", "MEDIUM", "WRITE", "CONFIDENTIAL", False, "convo_store_rw", ["convo_store"], True),
]

DISCOVERY_SOURCES = [  # key, name, adapter_key, reality_class
    ("registry", "Enterprise Agent Registry (HTTP)", "HTTP_AGENT_REGISTRY", "REAL_EXTERNAL_SERVICE_REQUIRED_STAGE2"),
    ("cloud", "Cloud Agent Inventory (AWS Bedrock Agents, us-east-1)", "AWS_BEDROCK_AGENTS", "REAL_EXTERNAL_SERVICE_REQUIRED_STAGE2"),
]


def A(key, name, *, origin, provider, control, lifecycle="ACTIVE", env="PRODUCTION", criticality="MEDIUM",
      classification="INTERNAL", autonomy="ASSISTIVE", owners=(None, None, None), identity=None, creds=(), tools=(),
      mcps=(), resources=(), memory=("NONE", None, 0), gateway=None, process_owner="ENTERPRISE_TEAM",
      known_to_act=True, discoverable_via=(), provenance_quality="DOCUMENTED", last_activity_days=1, control_group=False,
      external_reference=None, purpose="", reality=None, agent_type="ASSISTANT", registration_source="MANUAL"):
    """One canonical agent spec. ``gateway`` = (mode, [grant tool keys], [in-scope attempts], [out-of-scope attempts],
    shared_grant_of_agent_key|None). ``memory`` = (kind, store resource key|None, retention_days)."""
    return dict(key=key, name=name, origin=origin, provider=provider, control=control, lifecycle=lifecycle, env=env,
                criticality=criticality, classification=classification, autonomy=autonomy, owners=owners, identity=identity,
                creds=list(creds), tools=list(tools), mcps=list(mcps), resources=list(resources), memory=memory,
                gateway=gateway, process_owner=process_owner, known_to_act=known_to_act, discoverable_via=list(discoverable_via),
                provenance_quality=provenance_quality, last_activity_days=last_activity_days, control_group=control_group,
                external_reference=external_reference, purpose=purpose, reality=reality, agent_type=agent_type,
                registration_source=registration_source)


O = lambda b, t, c: (b, t, c)  # noqa: E731 - owners (business, technical, compliance)

AGENTS_PRIMARY = [
    # ---------------- healthy control group (12): well-governed, no planted serious condition ----------------
    A("payroll_recon", "Payroll Reconciliation Assistant", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED",
      criticality="HIGH", classification="RESTRICTED", owners=O("payroll_lead", "it_eng", "compliance"), identity="AGENT_IDENTITY",
      creds=["payroll_ro"], tools=["payroll_query"], mcps=["finance_mcp"], purpose="Reconciles payroll runs against the ledger.",
      control_group=True, process_owner="ACT"),
    A("hr_helpdesk", "HR Helpdesk Agent", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED",
      owners=O("hr_dir", "it_eng", "compliance"), identity="AGENT_IDENTITY", creds=["hr_dir_ro"], tools=["hr_directory_search"],
      mcps=["hr_mcp"], memory=("SESSION", None, 0), purpose="Answers employee HR policy questions.", control_group=True, process_owner="ACT"),
    A("benefits_assist", "Benefits Enrollment Assistant", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED",
      criticality="HIGH", classification="CONFIDENTIAL", autonomy="SUPERVISED", owners=O("hr_dir", "platform_eng", "compliance"),
      identity="AGENT_IDENTITY", creds=["benefits_rw"], tools=["benefits_update", "hr_directory_search"], mcps=["hr_mcp"],
      purpose="Guides employees through benefits enrollment.", control_group=True, process_owner="ACT"),
    A("ticket_triage", "IT Ticket Triage Bot", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED",
      owners=O("ops_mgr", "ops_mgr", "sec_lead"), identity="AGENT_IDENTITY", creds=["ops_ticketing"], tools=["ticket_create", "wiki_search"],
      mcps=["ops_mcp"], purpose="Classifies and routes IT tickets.", control_group=True, process_owner="ACT"),
    A("knowledge_search", "Knowledge Search Assistant", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED",
      criticality="LOW", owners=O("ops_mgr", "platform_eng", "compliance"), identity="AGENT_IDENTITY", creds=["wiki_ro"],
      tools=["wiki_search"], mcps=["ops_mcp"], purpose="Searches the internal wiki.", control_group=True, process_owner="ACT"),
    A("catalog_qa", "Catalog Q&A Bot", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED", criticality="LOW",
      classification="PUBLIC", owners=O("marketing", "platform_eng", "compliance"), identity="AGENT_IDENTITY", creds=["catalog_public"],
      tools=["catalog_search"], purpose="Answers product questions from the public catalog.", control_group=True, process_owner="ACT"),
    A("expense_advisor", "Expense Policy Advisor", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED",
      owners=O("cfo", "it_eng", "compliance"), identity="AGENT_IDENTITY", creds=["expense_ro"], tools=["expense_submit"],
      purpose="Checks expense reports against policy before submission.", control_group=True, process_owner="ACT"),
    A("ledger_close", "Ledger Close Copilot", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED", criticality="HIGH",
      classification="CONFIDENTIAL", owners=O("cfo", "data_eng", "compliance"), identity="AGENT_IDENTITY", creds=["finrec_ro"],
      tools=["ledger_export_tool", "finrec_query"], mcps=["finance_mcp"], purpose="Assists the monthly ledger close.",
      control_group=True, process_owner="ACT"),
    A("vendor_onboarding", "Vendor Onboarding Assistant", origin="EXTERNAL", provider="LANGGRAPH", control="REGISTERED",
      owners=O("vendor_mgr", "platform_eng", "compliance"), identity="EXTERNAL_CLIENT", creds=["vendor_ro"], tools=["vendor_lookup"],
      gateway=("GATEWAY_ENFORCED", ["vendor_lookup"], ["vendor_lookup"], [], None), external_reference="vendor-onboarding-assistant",
      discoverable_via=["registry"], purpose="Collects and validates new-vendor documentation.", control_group=True),
    A("compliance_collector", "Compliance Evidence Collector", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED",
      classification="CONFIDENTIAL", owners=O("compliance", "it_eng", "sec_lead"), identity="AGENT_IDENTITY", creds=["audit_ro"],
      tools=["audit_query"], purpose="Collects audit evidence on schedule.", control_group=True, process_owner="ACT"),
    A("meeting_scheduler", "Meeting Scheduler", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED", criticality="LOW",
      owners=O("ops_mgr", "it_eng", "compliance"), identity="AGENT_IDENTITY", tools=["calendar_read"], mcps=["ops_mcp"],
      purpose="Proposes meeting slots.", control_group=True, process_owner="ACT"),
    A("treasury_reporting", "Treasury Reporting Assistant", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED",
      criticality="HIGH", classification="CONFIDENTIAL", owners=O("treasury", "data_eng", "compliance"), identity="AGENT_IDENTITY",
      creds=["finrec_ro"], tools=["finrec_query"], mcps=["finance_mcp"], purpose="Produces daily treasury position reports.",
      control_group=True, process_owner="ACT"),
    # ---------------- the canonical multi-property agent from the brief ----------------
    A("finance_research", "Finance Research Assistant", origin="EXTERNAL", provider="CUSTOM", control="DISCOVERED",
      criticality="HIGH", classification="RESTRICTED", owners=O(None, None, None), creds=["finance_shared_sa"],
      tools=["payroll_query", "comp_lookup", "ledger_export_tool"], mcps=["finance_mcp_legacy"],
      gateway=(None, [], ["ledger_export_tool"], ["payroll_query", "treasury_initiate_payment"], "finance_connector"),
      known_to_act=False, discoverable_via=["registry"], provenance_quality="UNKNOWN", external_reference="finance-research-assistant",
      process_owner="UNKNOWN", memory=("PERSISTENT", "convo_store", 365),
      purpose="Ad-hoc finance research over payroll and compensation data (grown out of an analyst script)."),
    A("finance_connector", "Finance Data Connector", origin="EXTERNAL", provider="CUSTOM", control="REGISTERED",
      classification="CONFIDENTIAL", owners=O("cfo", None, None), identity="EXTERNAL_CLIENT", creds=["finrec_ro"],
      tools=["ledger_export_tool"], gateway=("GATEWAY_ENFORCED", ["ledger_export_tool"], ["ledger_export_tool"], [], None),
      external_reference="finance-data-connector", discoverable_via=["registry"], purpose="Exports ledger data for downstream analytics."),
    # ---------------- F6-1-relevant gateway agents (registered, enforced, attempting out-of-scope targets) ----------------
    A("close_orchestrator", "Finance Close Orchestrator", origin="EXTERNAL", provider="LANGGRAPH", control="REGISTERED",
      criticality="HIGH", classification="CONFIDENTIAL", autonomy="SEMI_AUTONOMOUS", owners=O("cfo", "platform_eng", None),
      identity="EXTERNAL_CLIENT", creds=["finrec_ro"], tools=["ledger_export_tool", "finrec_query"],
      gateway=("GATEWAY_ENFORCED", ["ledger_export_tool", "finrec_query"], ["ledger_export_tool"], ["treasury_initiate_payment", "payroll_query"], None),
      external_reference="finance-close-orchestrator", discoverable_via=["registry"], purpose="Orchestrates the close across worker agents."),
    A("ledger_reconciler", "Ledger Reconciler Worker", origin="EXTERNAL", provider="LANGGRAPH", control="REGISTERED",
      classification="CONFIDENTIAL", owners=O("cfo", "platform_eng", None), identity="EXTERNAL_CLIENT", creds=["finrec_ro"],
      tools=["finrec_query"], gateway=("GATEWAY_ENFORCED", ["finrec_query"], ["finrec_query"], [], None),
      external_reference="ledger-reconciler-worker", discoverable_via=["registry"], purpose="Reconciles sub-ledgers on request."),
    A("variance_explainer", "Variance Explainer Worker", origin="EXTERNAL", provider="LANGGRAPH", control="REGISTERED",
      classification="CONFIDENTIAL", owners=O("cfo", None, None), identity="EXTERNAL_CLIENT", creds=["finance_shared_sa"],
      tools=["finrec_query", "comp_lookup"], gateway=("GATEWAY_ENFORCED", ["finrec_query"], ["finrec_query"], ["comp_lookup"], None),
      external_reference="variance-explainer-worker", discoverable_via=["registry"], purpose="Explains period-over-period variances."),
    A("recruiting_manager", "Recruiting Crew Manager", origin="EXTERNAL", provider="CREWAI", control="REGISTERED",
      classification="CONFIDENTIAL", owners=O("recruiting", "platform_eng", "compliance"), identity="EXTERNAL_CLIENT", creds=["ats_rw"],
      tools=["ats_search"], mcps=["recruiting_mcp"], gateway=("GATEWAY_ENFORCED", ["ats_search"], ["ats_search"], [], None),
      external_reference="recruiting-crew-manager", discoverable_via=["registry"], purpose="Coordinates sourcing and scheduling crew agents."),
    A("candidate_sourcer", "Candidate Sourcer", origin="EXTERNAL", provider="CREWAI", control="REGISTERED", classification="CONFIDENTIAL",
      owners=O("recruiting", None, None), identity="EXTERNAL_CLIENT", creds=["ats_rw"], tools=["ats_search", "ats_update"],
      mcps=["recruiting_mcp"], gateway=("GATEWAY_ENFORCED", ["ats_search"], ["ats_search"], ["ats_update", "hr_directory_search"], None),
      external_reference="candidate-sourcer", discoverable_via=["registry"], purpose="Finds candidates in the ATS."),
    A("interview_scheduler", "Interview Scheduler", origin="EXTERNAL", provider="CREWAI", control="REGISTERED",
      owners=O("recruiting", None, None), identity="EXTERNAL_CLIENT", tools=["calendar_read"],
      gateway=("GATEWAY_ENFORCED", ["calendar_read"], ["calendar_read"], [], None), external_reference="interview-scheduler",
      discoverable_via=["registry"], memory=("PERSISTENT", "convo_store", 90), purpose="Schedules interviews."),
    A("treasury_scheduler", "Treasury Payment Scheduler", origin="EXTERNAL", provider="CUSTOM", control="REGISTERED",
      criticality="MISSION_CRITICAL", classification="RESTRICTED", autonomy="AUTONOMOUS", owners=O("treasury", None, None),
      identity="EXTERNAL_CLIENT", creds=["treasury_initiator"], tools=["treasury_initiate_payment", "finrec_query"], mcps=["treasury_mcp"],
      gateway=("GATEWAY_ENFORCED", ["finrec_query"], ["finrec_query"], ["treasury_initiate_payment"], None),
      external_reference="treasury-payment-scheduler", discoverable_via=["registry"], provenance_quality="PARTIAL",
      purpose="Schedules outbound treasury payments (vendor-built)."),
    A("vendor_portal_bot", "Vendor Portal Sync Bot", origin="EXTERNAL", provider="CUSTOM", control="REGISTERED",
      owners=O("vendor_mgr", None, None), identity="EXTERNAL_CLIENT", creds=["expired_vendor_key"], tools=["vendor_lookup"],
      gateway=("GATEWAY_ENFORCED", ["vendor_lookup"], ["vendor_lookup"], [], None), external_reference="vendor-portal-sync",
      discoverable_via=["registry"], process_owner="VENDOR", purpose="Syncs vendor portal records into the vendor master."),
    A("employee_copilot", "Employee Q&A Copilot", origin="EXTERNAL", provider="OPENAI", control="REGISTERED", classification="CONFIDENTIAL",
      owners=O("hr_dir", "platform_eng", None), identity="EXTERNAL_CLIENT", creds=["hr_dir_ro", "convo_store_rw"],
      tools=["hr_directory_search", "convo_persist"], memory=("PERSISTENT", "convo_store", 180),
      gateway=("GATEWAY_ENFORCED", ["hr_directory_search", "convo_persist"], ["hr_directory_search", "convo_persist"], ["benefits_update"], None),
      external_reference="employee-qa-copilot", discoverable_via=["registry"], purpose="Answers employee questions; remembers past conversations."),
    # ---------------- advisory / observed externals (registered or claimed, not enforced) ----------------
    A("expense_auditor", "Expense Auditor", origin="EXTERNAL", provider="ANTHROPIC", control="REGISTERED",
      owners=O("cfo", "data_eng", None), identity="SERVICE_ACCOUNT", creds=["expense_ro"], tools=["expense_submit"],
      gateway=("ADVISORY", [], [], [], None), external_reference="expense-auditor", discoverable_via=["registry"],
      purpose="Flags anomalous expense reports."),
    A("dq_monitor", "Data Quality Monitor", origin="EXTERNAL", provider="CUSTOM", control="CLAIMED", owners=O("data_eng", "data_eng", None),
      identity="SERVICE_ACCOUNT", creds=["finrec_ro", "vendor_ro"], tools=["finrec_query", "vendor_lookup"],
      gateway=("OBSERVED", [], [], [], None), external_reference="data-quality-monitor", discoverable_via=["registry"],
      purpose="Monitors data quality across finance sources."),
    A("marketing_gen", "Marketing Content Generator", origin="EXTERNAL", provider="OPENAI", control="REGISTERED", criticality="LOW",
      classification="PUBLIC", owners=O("marketing", None, None), identity="SERVICE_ACCOUNT", creds=["marketing_rw"],
      tools=["marketing_publish"], gateway=("ADVISORY", [], [], [], None), external_reference="marketing-content-generator",
      discoverable_via=["registry"], purpose="Drafts marketing copy and publishes approved assets."),
    A("code_review", "Code Review Assistant", origin="EXTERNAL", provider="ANTHROPIC", control="REGISTERED", env="DEVELOPMENT",
      owners=O("platform_eng", "platform_eng", None), identity="SERVICE_ACCOUNT", creds=["dev_sandbox"], tools=["code_exec"],
      mcps=["community_mcp"], gateway=("OBSERVED", [], [], [], None), external_reference="code-review-assistant",
      discoverable_via=["registry"], purpose="Reviews pull requests in the development environment."),
    A("wiki_gardener", "Wiki Gardener", origin="EXTERNAL", provider="LANGGRAPH", control="CLAIMED", criticality="LOW",
      owners=O("ops_mgr", None, None), creds=["wiki_ro"], tools=["wiki_search"], mcps=["ops_mcp"], gateway=("OBSERVED", [], [], [], None),
      external_reference="wiki-gardener", discoverable_via=["registry"], purpose="Suggests wiki page merges and cleanups."),
    A("comp_analyst_assist", "Compensation Analyst Assistant", origin="EXTERNAL", provider="CUSTOM", control="CLAIMED",
      criticality="HIGH", classification="RESTRICTED", owners=O("comp_mgr", None, None), creds=["personal_token_analyst"],
      tools=["comp_lookup"], mcps=["finance_mcp_legacy"], gateway=("OBSERVED", [], [], [], None), external_reference="comp-analyst-assistant",
      discoverable_via=["registry"], provenance_quality="PARTIAL", purpose="Prepares compensation benchmarking packs."),
    # ---------------- shadow: discoverable via the registry but unclaimed and unowned ----------------
    A("payroll_faq_bot", "Payroll FAQ Bot", origin="EXTERNAL", provider="OPENAI", control="DISCOVERED", creds=["hr_dir_ro"],
      tools=["hr_directory_search"], known_to_act=False, discoverable_via=["registry"], provenance_quality="PARTIAL",
      external_reference="payroll-faq-bot", process_owner="UNKNOWN", purpose="Answers payroll FAQs in the employee portal."),
    A("slack_summarizer", "Slack Channel Summarizer", origin="EXTERNAL", provider="CUSTOM", control="DISCOVERED", criticality="LOW",
      creds=["wiki_ro"], tools=["wiki_search"], known_to_act=False, discoverable_via=["registry"], provenance_quality="UNKNOWN",
      external_reference="slack-channel-summarizer", process_owner="UNKNOWN", memory=("PERSISTENT", "convo_store", 30),
      purpose="Summarizes finance team channels nightly."),
    A("vendor_master_sync_ext", "Vendor Master Sync (external)", origin="EXTERNAL", provider="CUSTOM", control="DISCOVERED",
      creds=["vendor_ro"], tools=["vendor_lookup"], known_to_act=False, discoverable_via=["registry"], provenance_quality="PARTIAL",
      external_reference="vendor-master-sync", process_owner="UNKNOWN", purpose="A second, external process that also syncs the vendor master."),
    A("expense_ocr", "Expense Receipt OCR Agent", origin="EXTERNAL", provider="GOOGLE", control="DISCOVERED", creds=["exec_runner"],
      tools=["file_fetch"], mcps=["community_mcp"], known_to_act=False, discoverable_via=["registry"], provenance_quality="UNKNOWN",
      external_reference="expense-receipt-ocr", process_owner="UNKNOWN", purpose="Extracts receipt data from the expense bucket."),
    A("onboarding_buddy", "New-Hire Onboarding Buddy", origin="EXTERNAL", provider="OPENAI", control="DISCOVERED", creds=["hr_dir_ro"],
      tools=["hr_directory_search", "calendar_read"], known_to_act=False, discoverable_via=["registry"], provenance_quality="PARTIAL",
      external_reference="onboarding-buddy", process_owner="UNKNOWN", memory=("PERSISTENT", "convo_store", 60),
      purpose="Guides new hires through their first weeks."),
    A("budget_forecaster", "Budget Forecaster", origin="EXTERNAL", provider="CUSTOM", control="DISCOVERED", criticality="HIGH",
      classification="CONFIDENTIAL", creds=["finance_shared_sa"], tools=["finrec_query", "ledger_export_tool"], mcps=["finance_mcp_legacy"],
      known_to_act=False, discoverable_via=["registry"], provenance_quality="UNKNOWN", external_reference="budget-forecaster",
      process_owner="UNKNOWN", purpose="Forecasts departmental budgets from ledger history."),
    # ---------------- cloud-discoverable (Bedrock inventory) ----------------
    A("cloud_invoice_extractor", "Invoice Extraction Agent (cloud)", origin="EXTERNAL", provider="AWS", control="DISCOVERED",
      classification="CONFIDENTIAL", creds=["exec_runner"], known_to_act=False, discoverable_via=["cloud"], provenance_quality="PARTIAL",
      external_reference="bedrock-agent:us-east-1:INV0EXTR01", process_owner="ENTERPRISE_TEAM", purpose="Extracts invoice fields for AP."),
    A("cloud_policy_qa", "Policy Q&A Agent (cloud)", origin="EXTERNAL", provider="AWS", control="DISCOVERED", criticality="LOW",
      known_to_act=False, discoverable_via=["cloud"], provenance_quality="PARTIAL", external_reference="bedrock-agent:us-east-1:POLQA00001",
      process_owner="ENTERPRISE_TEAM", purpose="Answers finance policy questions from a knowledge base."),
    A("cloud_collections", "Collections Outreach Agent (cloud)", origin="EXTERNAL", provider="AWS", control="CLAIMED",
      classification="CONFIDENTIAL", owners=O("cfo", None, None), creds=["finrec_ro"], discoverable_via=["cloud"],
      external_reference="bedrock-agent:us-east-1:COLLECT001", purpose="Drafts collections outreach for overdue invoices."),
    A("cloud_travel", "Travel Booking Agent (cloud)", origin="EXTERNAL", provider="AWS", control="DISCOVERED", criticality="LOW",
      creds=["expense_ro"], known_to_act=False, discoverable_via=["cloud"], provenance_quality="PARTIAL",
      external_reference="bedrock-agent:us-east-1:TRAVEL0001", process_owner="ENTERPRISE_TEAM", purpose="Books employee travel."),
    A("cloud_experiments", "Experimentation Sandbox Agent (cloud)", origin="EXTERNAL", provider="AWS", control="DISCOVERED",
      env="DEVELOPMENT", criticality="LOW", creds=["dev_sandbox"], known_to_act=False, discoverable_via=["cloud"],
      provenance_quality="UNKNOWN", external_reference="bedrock-agent:us-east-1:EXPRMNT001", process_owner="UNKNOWN",
      purpose="A prototype agent left running in the development account."),
    A("cloud_payroll_export", "Payroll Export Agent (cloud)", origin="EXTERNAL", provider="AWS", control="DISCOVERED",
      criticality="HIGH", classification="RESTRICTED", creds=["legacy_etl_2023"], known_to_act=False, discoverable_via=["cloud"],
      provenance_quality="UNKNOWN", external_reference="bedrock-agent:us-east-1:PAYEXPORT1", process_owner="UNKNOWN",
      last_activity_days=200, purpose="Exports payroll data to an analytics bucket (built by a former contractor)."),
    # ---------------- dark shadow: exists, runs, discoverable by nothing ACT has ----------------
    A("analyst_gpt_script", "Analyst Desktop GPT Script", origin="UNKNOWN", provider="UNKNOWN", control="DISCOVERED",
      classification="RESTRICTED", creds=["personal_token_analyst"], known_to_act=False, provenance_quality="UNKNOWN",
      process_owner="UNKNOWN", memory=("PERSISTENT", None, 0), purpose="A personal script that queries compensation exports."),
    A("contractor_notebook", "Contractor Automation Notebook", origin="UNKNOWN", provider="UNKNOWN", control="DISCOVERED",
      creds=["exec_runner"], known_to_act=False, provenance_quality="UNKNOWN", process_owner="UNKNOWN",
      purpose="A notebook automating file fetches and code execution."),
    A("spreadsheet_macro", "Spreadsheet Macro Agent", origin="UNKNOWN", provider="UNKNOWN", control="DISCOVERED", criticality="LOW",
      creds=["expense_ro"], known_to_act=False, provenance_quality="UNKNOWN", process_owner="UNKNOWN",
      purpose="A macro that pulls expense totals into a spreadsheet."),
    A("treasury_sidecar", "Treasury Sidecar Bot", origin="UNKNOWN", provider="UNKNOWN", control="DISCOVERED", criticality="HIGH",
      classification="RESTRICTED", creds=["treasury_initiator"], known_to_act=False, provenance_quality="UNKNOWN",
      process_owner="UNKNOWN", purpose="An undocumented helper beside the treasury scheduler."),
    # ---------------- dormant / lifecycle edge cases ----------------
    A("legacy_etl", "Legacy ETL Agent 2023", origin="EXTERNAL", provider="CUSTOM", control="CLAIMED", owners=O("data_eng", None, None),
      creds=["legacy_etl_2023"], known_to_act=True, discoverable_via=["registry"], external_reference="legacy-etl-2023",
      provenance_quality="PARTIAL", last_activity_days=412, purpose="A 2023 ETL agent nobody has switched off.", reality="DORMANT_ASSET"),
    A("retired_migration", "Retired Migration Bot", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED", lifecycle="RETIRED",
      owners=O("data_eng", "data_eng", "compliance"), identity="AGENT_IDENTITY", creds=["dev_sandbox"], last_activity_days=300,
      process_owner="ACT", purpose="Migrated the vendor master in 2025; retired.", reality="DORMANT_ASSET"),
    A("suspended_forecaster", "Suspended Cash Forecaster", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED", lifecycle="SUSPENDED",
      criticality="HIGH", classification="CONFIDENTIAL", owners=O("treasury", "data_eng", "compliance"), identity="AGENT_IDENTITY",
      creds=["finrec_ro"], tools=["finrec_query"], mcps=["finance_mcp"], last_activity_days=45, process_owner="ACT",
      purpose="Suspended after a forecasting defect; awaiting fix."),
    A("draft_ap_agent", "Accounts Payable Agent (draft)", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED", lifecycle="DRAFT",
      owners=O("cfo", "platform_eng", None), identity=None, tools=["vendor_lookup"], last_activity_days=0, process_owner="ACT",
      purpose="Being built; not yet registered for execution."),
    A("pending_travel_native", "Travel Policy Agent (pending approval)", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED",
      lifecycle="PENDING_APPROVAL", criticality="LOW", owners=O("cfo", "it_eng", "compliance"), identity="AGENT_IDENTITY",
      tools=["expense_submit"], creds=["expense_ro"], process_owner="ACT", purpose="Awaiting approval."),
    # ---------------- NATIVE with conditions (collision, unapproved MCP, missing owners, dangerous reach) ----------------
    A("vendor_master_sync_native", "Vendor Master Sync", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED",
      owners=O("vendor_mgr", "data_eng", "compliance"), identity="AGENT_IDENTITY", creds=["vendor_ro"], tools=["vendor_lookup"],
      external_reference="vendor-master-sync", process_owner="ACT",
      purpose="Nightly vendor master synchronisation (its external_reference collides with the external process of the same name)."),
    A("payments_assistant", "Payments Assistant", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED", criticality="MISSION_CRITICAL",
      classification="RESTRICTED", autonomy="AUTONOMOUS", owners=O("treasury", None, None), identity="AGENT_IDENTITY",
      creds=["treasury_initiator"], tools=["treasury_initiate_payment", "finrec_query"], mcps=["treasury_mcp"], process_owner="ACT",
      purpose="Prepares and initiates payments from the treasury queue."),
    A("dev_helper", "Developer Helper", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED", env="DEVELOPMENT",
      owners=O(None, "platform_eng", None), identity="AGENT_IDENTITY", creds=["exec_runner"], tools=["code_exec", "file_fetch"],
      mcps=["community_mcp"], process_owner="ACT", purpose="Runs code snippets for developers."),
    A("hr_analytics", "HR Analytics Agent", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED", criticality="HIGH",
      classification="RESTRICTED", owners=O("hr_dir", None, None), identity="AGENT_IDENTITY", creds=["finance_shared_sa"],
      tools=["comp_lookup", "hr_directory_search"], mcps=["finance_mcp_legacy", "hr_mcp"], process_owner="ACT",
      purpose="Builds workforce analytics over compensation and directory data."),
    A("ops_runbook", "Ops Runbook Executor", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED", autonomy="SEMI_AUTONOMOUS",
      owners=O("ops_mgr", "it_eng", None), identity="AGENT_IDENTITY", creds=["ops_ticketing"], tools=["ticket_create", "file_fetch"],
      mcps=["ops_mcp", "community_mcp"], process_owner="ACT", purpose="Executes operational runbooks."),
    A("intern_reporter", "Intern Reporting Helper", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED", criticality="LOW",
      owners=O("analyst", None, None), identity="AGENT_IDENTITY", creds=["personal_token_analyst"], tools=["finrec_query"],
      process_owner="ACT", purpose="Prepares weekly reporting tables for the finance team."),
]

AGENTS_SECONDARY = [  # Contoso Logistics - the isolation-control tenant; never referenced from the primary tenant
    A("c_dispatch", "Dispatch Planner", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED", owners=O("c_ops", "c_eng", "c_eng"),
      identity="AGENT_IDENTITY", creds=["c_fleet_ro"], tools=["c_fleet_query"], resources=[], process_owner="ACT",
      purpose="Plans daily dispatch.", control_group=False),
    A("c_customs", "Customs Paperwork Assistant", origin="NATIVE", provider="ACT_NATIVE", control="GOVERNED", owners=O("c_ops", "c_eng", "c_eng"),
      identity="AGENT_IDENTITY", creds=["c_docs_rw"], tools=["c_docs_update"], process_owner="ACT", purpose="Prepares customs forms."),
    A("c_routing_ext", "Route Optimizer (external)", origin="EXTERNAL", provider="LANGGRAPH", control="REGISTERED", owners=O("c_ops", "c_eng", None),
      identity="EXTERNAL_CLIENT", creds=["c_fleet_ro"], tools=["c_fleet_query"],
      gateway=("GATEWAY_ENFORCED", ["c_fleet_query"], ["c_fleet_query"], [], None), external_reference="route-optimizer",
      discoverable_via=["c_registry"], purpose="Optimizes routes."),
    A("c_shadow_tracker", "Shipment Tracker Script", origin="UNKNOWN", provider="UNKNOWN", control="DISCOVERED", creds=["c_fleet_ro"],
      known_to_act=False, provenance_quality="UNKNOWN", process_owner="UNKNOWN", purpose="A tracking script of unknown origin."),
]
SECONDARY_PEOPLE = [("c_ops", "Marta Silva", "Operations Director", ["BUSINESS_OWNER"]), ("c_eng", "Noah Fischer", "Platform Engineer", ["TECHNICAL_OWNER", "COMPLIANCE_OWNER"])]
SECONDARY_RESOURCES = [("c_fleet_db", "Fleet Telemetry Database", "database", "CONFIDENTIAL", "PRODUCTION"),
                       ("c_docs", "Customs Document Store", "object_storage", "CONFIDENTIAL", "PRODUCTION")]
SECONDARY_CREDENTIALS = [("c_fleet_ro", "svc-fleet-readonly", "SERVICE_ACCOUNT", ["LEAST_PRIVILEGE"], ["c_fleet_db"], True, 1, None, "c_ops"),
                         ("c_docs_rw", "svc-customs-docs", "SERVICE_ACCOUNT", ["LEAST_PRIVILEGE"], ["c_docs"], True, 1, None, "c_ops")]
SECONDARY_TOOLS = [("c_fleet_query", "fleet-query", "HTTP", "APPROVED", "MEDIUM", "NONE", "CONFIDENTIAL", False, "c_fleet_ro", ["c_fleet_db"], True),
                   ("c_docs_update", "customs-docs-update", "HTTP", "APPROVED", "MEDIUM", "WRITE", "CONFIDENTIAL", True, "c_docs_rw", ["c_docs"], True)]
SECONDARY_SOURCES = [("c_registry", "Contoso Agent Registry (HTTP)", "HTTP_AGENT_REGISTRY", "REAL_EXTERNAL_SERVICE_REQUIRED_STAGE2")]

# actual agent-to-agent relationships (objective runtime facts)
A2A_HANDOFFS = [  # from, to, mechanism, crosses_process_boundary
    ("close_orchestrator", "ledger_reconciler", "LANGGRAPH_STATE_EDGE", True),
    ("close_orchestrator", "variance_explainer", "LANGGRAPH_STATE_EDGE", True),
    ("recruiting_manager", "candidate_sourcer", "CREWAI_TASK_DELEGATION", True),
    ("recruiting_manager", "interview_scheduler", "CREWAI_TASK_DELEGATION", True),
    ("finance_research", "budget_forecaster", "HTTP_A2A_CALL", True),
    ("employee_copilot", "hr_helpdesk", "HTTP_A2A_CALL", True),
]
AGENT_AUTHORITY = [  # from, to, kind - actual authority one agent holds over another
    ("close_orchestrator", "ledger_reconciler", "AGENT_DELEGATES_TO"),
    ("close_orchestrator", "variance_explainer", "AGENT_DELEGATES_TO"),
    ("recruiting_manager", "candidate_sourcer", "AGENT_DELEGATES_TO"),
    ("recruiting_manager", "interview_scheduler", "AGENT_DELEGATES_TO"),
    ("payroll_recon", "ledger_close", "TRUSTS"),
]
HUMAN_DELEGATIONS = [("cfo", "treasury"), ("treasury", "analyst"), ("hr_dir", "recruiting"), ("ops_mgr", "it_eng")]


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def _tenant(seed, key, name, role):
    return {"id": stable_id(seed, "ten", key), "act_organization_uuid": stable_uuid(seed, "organization", key),
            "name": name, "slug": key, "role": role}


def build_estate(seed: str, grounding: dict, *, generator_version: str, schema_version: str) -> dict:
    _check_vocab(grounding)
    tenants = [_tenant(seed, "northwind-pfg", "Northwind Payroll & Finance Group", "PRIMARY"),
               _tenant(seed, "contoso-logistics", "Contoso Logistics", "ISOLATION_CONTROL")]
    T = {"northwind-pfg": tenants[0]["id"], "contoso-logistics": tenants[1]["id"]}
    ids: dict[str, str] = {}

    def reg(kind, key):
        ids[key] = stable_id(seed, kind, key)
        return ids[key]

    people, resources, credentials, tools, mcps, sources = [], [], [], [], [], []
    for tslug, plist, rlist, clist, tlist, mlist, slist in (
        ("northwind-pfg", PEOPLE, RESOURCES, CREDENTIALS, TOOLS, MCP_SERVERS, DISCOVERY_SOURCES),
        ("contoso-logistics", SECONDARY_PEOPLE, SECONDARY_RESOURCES, SECONDARY_CREDENTIALS, SECONDARY_TOOLS, [], SECONDARY_SOURCES),
    ):
        tid = T[tslug]
        for key, name, title, roles in plist:
            people.append({"id": reg("per", key), "tenant_id": tid, "name": name, "title": title, "roles": sorted(roles),
                           "email": f"{key.replace('_', '.')}@{tslug}.example", "act_user_uuid": stable_uuid(seed, "user", key)})
        for key, name, rtype, sens, env in rlist:
            resources.append({"id": reg("res", key), "tenant_id": tid, "name": name, "resource_type": rtype, "sensitivity": sens,
                              "environment": env, "act_resource_uuid": stable_uuid(seed, "resource", key)})
        for key, label, kind, posture, access, held, last_used, expired, owner in clist:
            credentials.append({"id": reg("cred", key), "tenant_id": tid, "label": label, "kind": kind, "posture": sorted(posture),
                                "grants_access_to_resource_ids": sorted(stable_id(seed, "res", a) for a in access),
                                "held_in_act": held, "last_used_days_ago": last_used, "expired_days_ago": expired,
                                "owner_person_id": stable_id(seed, "per", owner), "secret_value": None})
        for key, name, trust, prov, registered, exposes in mlist:
            mcps.append({"id": reg("mcp", key), "tenant_id": tid, "name": name, "trust_status": trust, "provenance": prov,
                         "registered_in_act": registered, "exposes_tool_ids": sorted(stable_id(seed, "tool", t) for t in exposes)})
        for key, name, ttype, approval, risk, side, cls, req, cred, access, registered in tlist:
            mcp_id = next((stable_id(seed, "mcp", m[0]) for m in mlist if key in m[5]), None)
            tools.append({"id": reg("tool", key), "tenant_id": tid, "name": name, "tool_type": ttype, "approval_state": approval,
                          "risk_level": risk, "side_effect_level": side, "data_classification": cls, "requires_approval": req,
                          "uses_credential_id": stable_id(seed, "cred", cred) if cred else None,
                          "accesses_resource_ids": sorted(stable_id(seed, "res", a) for a in access),
                          "exposed_by_mcp_server_id": mcp_id, "registered_in_act": registered})
        for key, name, adapter, reality in slist:
            sources.append({"id": reg("src", key), "tenant_id": tid, "name": name, "adapter_key": adapter, "reality_class": reality,
                            "crosses_process_boundary": True, "lists_agent_ids": []})

    agents, identities, dependencies, gateway_rel = [], [], [], []
    spec_by_key = {s["key"]: (s, "northwind-pfg") for s in AGENTS_PRIMARY}
    spec_by_key.update({s["key"]: (s, "contoso-logistics") for s in AGENTS_SECONDARY})
    for key, (s, tslug) in spec_by_key.items():
        reg("agt", key)
    for key, (s, tslug) in spec_by_key.items():
        tid, aid = T[tslug], ids[key]
        ident_id = None
        if s["identity"]:
            ident_id = stable_id(seed, "idn", key)
            identities.append({"id": ident_id, "tenant_id": tid, "agent_id": aid, "kind": s["identity"],
                               "client_id": f"{key.replace('_', '-')}-client", "status": "ACTIVE" if s["lifecycle"] not in ("RETIRED",) else "SUSPENDED",
                               "approval_state": "APPROVED"})
        b, t, c = s["owners"]
        owners = {"business_person_id": stable_id(seed, "per", b) if b else None,
                  "technical_person_id": stable_id(seed, "per", t) if t else None,
                  "compliance_person_id": stable_id(seed, "per", c) if c else None}
        mode, grant_tools, in_scope, out_scope, shared_of = (s["gateway"] or (None, [], [], [], None))
        # external_enforcement_mode is an ACT column: it exists only for agents ACT knows (never NATIVE). A shadow
        # process that calls the gateway with a grant issued to ANOTHER agent has no mode of its own - that fact
        # is carried by uses_grant_issued_to_agent_id and is what makes it a shared-grant condition.
        act_mode = mode if (s["origin"] != "NATIVE" and s["gateway"] and s["known_to_act"] and mode) else None
        gw = {"via_gateway": act_mode == "GATEWAY_ENFORCED" or bool(shared_of),
              "external_enforcement_mode": act_mode,
              "grants": [{"capability": "http_tool.invoke", "target_tool_id": stable_id(seed, "tool", g), "label": f"grant-{key}-{g}"} for g in sorted(grant_tools)],
              "attempted_targets_in_scope_tool_ids": sorted(stable_id(seed, "tool", g) for g in in_scope),
              "attempted_targets_out_of_scope_tool_ids": sorted(stable_id(seed, "tool", g) for g in out_scope),
              "uses_grant_issued_to_agent_id": ids.get(shared_of) if shared_of else None}
        mkind, mstore, mret = s["memory"]
        agent = {
            "id": aid, "tenant_id": tid, "act_agent_uuid": stable_uuid(seed, "agent", key), "name": s["name"], "agent_type": s["agent_type"],
            "description": s["purpose"], "business_purpose": s["purpose"] or s["name"],
            "origin_category": s["origin"], "origin_provider": s["provider"], "control_state": s["control"],
            "lifecycle_status": s["lifecycle"], "external_reference": s["external_reference"],
            "external_enforcement_mode": gw["external_enforcement_mode"], "default_environment": s["env"],
            "criticality": s["criticality"], "data_classification": s["classification"], "autonomy_level": s["autonomy"],
            "registration_source": s["registration_source"],
            "known_to_act_inventory": s["known_to_act"],
            "inventory_status": ("REGISTERED_IN_ACT" if s["known_to_act"] else ("SHADOW_DISCOVERABLE" if s["discoverable_via"] else "SHADOW_DARK")),
            "discoverable_via_source_ids": sorted(stable_id(seed, "src", d) for d in s["discoverable_via"]),
            "owners": owners, "owner_type": "USER" if b else None, "identity_id": ident_id,
            "credential_ids": sorted(stable_id(seed, "cred", cd) for cd in s["creds"]),
            "tool_ids": sorted(stable_id(seed, "tool", tl) for tl in s["tools"]),
            "mcp_server_ids": sorted(stable_id(seed, "mcp", m) for m in s["mcps"]),
            "direct_resource_ids": sorted(stable_id(seed, "res", r) for r in s["resources"]),
            "memory": {"kind": mkind, "store_resource_id": stable_id(seed, "res", mstore) if mstore else None, "retention_days": mret},
            "gateway": gw, "process_owner": s["process_owner"], "provenance_quality": s["provenance_quality"],
            "last_activity_days_ago": s["last_activity_days"], "control_group": s["control_group"],
        }
        agents.append(agent)
        for src_key in s["discoverable_via"]:
            for src in sources:
                if src["id"] == stable_id(seed, "src", src_key):
                    src["lists_agent_ids"].append(aid)

        def edge(et, st, sid, tt, tgt, prov="DECLARED"):
            dependencies.append({"id": stable_id(seed, "edge", f"{et}|{sid}|{tgt}"), "tenant_id": tid, "edge_type": et,
                                 "source_type": st, "source_id": sid, "target_type": tt, "target_id": tgt, "provenance_in_estate": prov})
        for tl in s["tools"]:
            edge("DEPENDS_ON_TOOL", "AGENT", aid, "TOOL", stable_id(seed, "tool", tl))
        for m in s["mcps"]:
            edge("DEPENDS_ON_MCP_SERVER", "AGENT", aid, "MCP_SERVER", stable_id(seed, "mcp", m))
        for cd in s["creds"]:
            edge("DEPENDS_ON_CREDENTIAL", "AGENT", aid, "CREDENTIAL", stable_id(seed, "cred", cd))
        for r in s["resources"]:
            edge("DEPENDS_ON_RESOURCE", "AGENT", aid, "RESOURCE", stable_id(seed, "res", r))
    for src in sources:
        src["lists_agent_ids"].sort()
    for m in mcps:
        for t in m["exposes_tool_ids"]:
            dependencies.append({"id": stable_id(seed, "edge", f"MCP_EXPOSES_TOOL|{m['id']}|{t}"), "tenant_id": m["tenant_id"],
                                 "edge_type": "MCP_EXPOSES_TOOL", "source_type": "MCP_SERVER", "source_id": m["id"], "target_type": "TOOL",
                                 "target_id": t, "provenance_in_estate": "DECLARED"})
    for t in tools:
        if t["uses_credential_id"]:
            dependencies.append({"id": stable_id(seed, "edge", f"TOOL_USES_CREDENTIAL|{t['id']}|{t['uses_credential_id']}"), "tenant_id": t["tenant_id"],
                                 "edge_type": "TOOL_USES_CREDENTIAL", "source_type": "TOOL", "source_id": t["id"], "target_type": "CREDENTIAL",
                                 "target_id": t["uses_credential_id"], "provenance_in_estate": "DECLARED"})
        for r in t["accesses_resource_ids"]:
            dependencies.append({"id": stable_id(seed, "edge", f"TOOL_ACCESSES_RESOURCE|{t['id']}|{r}"), "tenant_id": t["tenant_id"],
                                 "edge_type": "TOOL_ACCESSES_RESOURCE", "source_type": "TOOL", "source_id": t["id"], "target_type": "RESOURCE",
                                 "target_id": r, "provenance_in_estate": "DECLARED"})
    for cd in credentials:
        for r in cd["grants_access_to_resource_ids"]:
            dependencies.append({"id": stable_id(seed, "edge", f"CREDENTIAL_ACCESSES_RESOURCE|{cd['id']}|{r}"), "tenant_id": cd["tenant_id"],
                                 "edge_type": "CREDENTIAL_ACCESSES_RESOURCE", "source_type": "CREDENTIAL", "source_id": cd["id"],
                                 "target_type": "RESOURCE", "target_id": r, "provenance_in_estate": "DECLARED"})
    delegations = [{"id": stable_id(seed, "dlg", f"{a}|{b}"), "tenant_id": T["northwind-pfg"], "delegator_person_id": stable_id(seed, "per", a),
                    "delegatee_person_id": stable_id(seed, "per", b), "scope_type": "ORGANIZATION", "kind": "HUMAN_TO_HUMAN"}
                   for a, b in HUMAN_DELEGATIONS]
    for a, b in HUMAN_DELEGATIONS:
        dependencies.append({"id": stable_id(seed, "edge", f"DELEGATES_TO|{a}|{b}"), "tenant_id": T["northwind-pfg"], "edge_type": "DELEGATES_TO",
                             "source_type": "HUMAN", "source_id": stable_id(seed, "per", a), "target_type": "HUMAN",
                             "target_id": stable_id(seed, "per", b), "provenance_in_estate": "DECLARED"})
    authority = [{"id": stable_id(seed, "aut", f"{a}|{b}|{k}"), "tenant_id": T["northwind-pfg"], "from_agent_id": ids[a], "to_agent_id": ids[b],
                  "kind": k} for a, b, k in AGENT_AUTHORITY]
    handoffs = [{"id": stable_id(seed, "a2a", f"{a}|{b}|{m}"), "tenant_id": T["northwind-pfg"], "from_agent_id": ids[a], "to_agent_id": ids[b],
                 "mechanism": m, "crosses_process_boundary": x} for a, b, m, x in A2A_HANDOFFS]

    # objective sensitive-resource reachability over the estate's own edges (BFS, shortest path per (agent, resource))
    adj: dict[str, list[tuple[str, str]]] = {}
    for e in dependencies:
        if e["edge_type"] in ("DEPENDS_ON_TOOL", "DEPENDS_ON_MCP_SERVER", "DEPENDS_ON_CREDENTIAL", "DEPENDS_ON_RESOURCE",
                              "MCP_EXPOSES_TOOL", "TOOL_USES_CREDENTIAL", "TOOL_ACCESSES_RESOURCE", "CREDENTIAL_ACCESSES_RESOURCE"):
            adj.setdefault(e["source_id"], []).append((e["target_id"], e["edge_type"]))
    res_by_id = {r["id"]: r for r in resources}
    reach = []
    for ag in agents:
        seen = {ag["id"]: [ag["id"]]}
        frontier = [ag["id"]]
        while frontier:
            nxt = []
            for node in frontier:
                for tgt, et in sorted(adj.get(node, [])):
                    if tgt not in seen:
                        seen[tgt] = seen[node] + [tgt]
                        nxt.append(tgt)
            frontier = nxt
        for node, path in sorted(seen.items()):
            r = res_by_id.get(node)
            if r and r["sensitivity"] in SENSITIVE:
                reach.append({"id": stable_id(seed, "reach", f"{ag['id']}|{node}"), "tenant_id": ag["tenant_id"], "agent_id": ag["id"],
                              "resource_id": node, "sensitivity": r["sensitivity"], "path_node_ids": path, "hops": len(path) - 1})

    collisions = []
    by_ref: dict[tuple, list] = {}
    for ag in agents:
        if ag["external_reference"]:
            by_ref.setdefault((ag["tenant_id"], ag["external_reference"]), []).append(ag)
    for (tid, ref), group in sorted(by_ref.items()):
        natives = [g for g in group if g["origin_category"] == "NATIVE"]
        others = [g for g in group if g["origin_category"] != "NATIVE"]
        for n in natives:
            for o in others:
                collisions.append({"id": stable_id(seed, "coll", f"{n['id']}|{o['id']}"), "tenant_id": tid, "native_agent_id": n["id"],
                                   "external_agent_id": o["id"], "external_reference": ref})

    derive_conditions(agents, credentials, tools, mcps, res_by_id, reach, collisions, handoffs, authority)
    for ag in agents:
        spec = spec_by_key[next(k for k, v in ids.items() if v == ag["id"])][0]
        ag["reality_class"] = spec["reality"] or derive_reality(ag, handoffs)
    truthful = sorted(a["id"] for a in agents if "TRUTHFUL_REFUSAL_SUBJECT" in a["estate_conditions"])

    estate = {
        "schema_version": schema_version,
        "generator": {"seed": seed, "generator_version": generator_version, "schema_grounding_version": grounding["schema_grounding_version"]},
        "vocabulary_sources": {"control_states": "app/runtime/registry/control.py::CONTROL_STATES", "origin_categories": "app/runtime/registry/control.py::ORIGIN_CATEGORIES",
                               "enforcement_modes": "app/models/bridge.py::STORABLE_ENFORCEMENT_MODES", "edge_types": "app/models/graph.py::EDGE_TYPES",
                               "mcp_trust_statuses": "app/models/graph.py::MCP_TRUST_STATUSES", "lifecycle": "app/runtime/services.py::AGENT_LIFECYCLE",
                               "criticality|classification|autonomy": "app/runtime/registry/schemas.py (Field patterns)"},
        "tenants": sort_entities(tenants), "people": sort_entities(people), "environments": ["DEVELOPMENT", "PRODUCTION", "STAGING"],
        "resources": sort_entities(resources), "credentials": sort_entities(credentials), "tools": sort_entities(tools),
        "mcp_servers": sort_entities(mcps), "identities": sort_entities(identities), "agents": sort_entities(agents),
        "dependencies": sort_entities(dependencies), "delegations": sort_entities(delegations), "agent_authority": sort_entities(authority),
        "a2a_handoffs": sort_entities(handoffs), "discovery_sources": sort_entities(sources), "sensitive_reachability": sort_entities(reach),
        "identifier_collisions": sort_entities(collisions), "truthful_refusal_subject_agent_ids": truthful,
        "control_group_agent_ids": sorted(a["id"] for a in agents if a["control_group"]),
    }
    estate["summary"] = summarize(estate)
    return estate


def derive_conditions(agents, credentials, tools, mcps, res_by_id, reach, collisions, handoffs, authority) -> None:
    cred_by = {c["id"]: c for c in credentials}
    tool_by = {t["id"]: t for t in tools}
    mcp_by = {m["id"]: m for m in mcps}
    collided = {c["native_agent_id"] for c in collisions} | {c["external_agent_id"] for c in collisions}
    a2a = {h["from_agent_id"] for h in handoffs} | {h["to_agent_id"] for h in handoffs} | {x["from_agent_id"] for x in authority} | {x["to_agent_id"] for x in authority}
    reach_by_agent: dict[str, list] = {}
    for r in reach:
        reach_by_agent.setdefault(r["agent_id"], []).append(r)
    for ag in agents:
        c: set[str] = set()
        creds = [cred_by[i] for i in ag["credential_ids"]]
        if any("OVER_PRIVILEGED" in x["posture"] for x in creds):
            c.add("OVER_PRIVILEGED_CREDENTIAL")
        if any("SHARED" in x["posture"] for x in creds):
            c.add("SHARED_CREDENTIAL")
        if any("STALE" in x["posture"] for x in creds):
            c.add("STALE_CREDENTIAL")
        if any("EXPIRED_STILL_ACTIVE" in x["posture"] for x in creds):
            c.add("EXPIRED_CREDENTIAL_STILL_ACTIVE")
        if not ag["owners"]["business_person_id"]:
            c.add("UNOWNED")
            if ag["default_environment"] == "PRODUCTION" and (creds or ag["tool_ids"]):
                c.add("PRODUCTION_ACCESS_UNOWNED")
        if ag["inventory_status"] == "SHADOW_DISCOVERABLE":
            c.add("SHADOW_DISCOVERABLE")
        if ag["inventory_status"] == "SHADOW_DARK":
            c.add("SHADOW_DARK")
        if ag["origin_category"] == "UNKNOWN" or ag["provenance_quality"] == "UNKNOWN":
            c.add("UNKNOWN_PROVENANCE")
        if any(mcp_by[m]["trust_status"] != "APPROVED" for m in ag["mcp_server_ids"]):
            c.add("UNAPPROVED_MCP")
        if any(tool_by[t]["approval_state"] != "APPROVED" for t in ag["tool_ids"]):
            c.add("UNAPPROVED_TOOL")
        for r in reach_by_agent.get(ag["id"], []):
            # a sensitive reach is dangerous when the path runs through an unapproved tool/MCP or a non-least-privilege credential
            risky = False
            for node in r["path_node_ids"][1:-1]:
                if node in tool_by and tool_by[node]["approval_state"] != "APPROVED":
                    risky = True
                if node in mcp_by and mcp_by[node]["trust_status"] != "APPROVED":
                    risky = True
                if node in cred_by and "LEAST_PRIVILEGE" not in cred_by[node]["posture"]:
                    risky = True
            if risky and r["sensitivity"] in ("RESTRICTED", "REGULATED"):
                c.add("DANGEROUS_DEPENDENCY_SENSITIVE_REACH")
        if ag["last_activity_days_ago"] > 90 and any(x["expired_days_ago"] is None for x in creds):
            c.add("DORMANT_WITH_ACTIVE_CREDENTIAL")
        if ag["id"] in collided:
            c.add("NATIVE_REFERENCE_COLLISION")
        gw = ag["gateway"]
        if gw["external_enforcement_mode"] == "GATEWAY_ENFORCED":
            c.add("GATEWAY_ENFORCED_EXTERNAL")
        if gw["uses_grant_issued_to_agent_id"]:
            c.add("SHARED_GATEWAY_GRANT")
        if gw["via_gateway"]:
            if gw["attempted_targets_out_of_scope_tool_ids"]:
                c.update({"OUT_OF_SCOPE_GATEWAY_ATTEMPTS", "F6_1_RELEVANT"})
            if (gw["grants"] or gw["uses_grant_issued_to_agent_id"]) and ag["process_owner"] != "ACT":
                c.add("TRUTHFUL_REFUSAL_SUBJECT")
        if ag["memory"]["kind"] == "PERSISTENT":
            c.add("I1_RELEVANT")
        if ag["id"] in a2a:
            c.add("I2_RELEVANT")
        if ag["discoverable_via_source_ids"]:
            c.add("REGISTRY_DISCOVERABLE" if ag["origin_provider"] != "AWS" else "CLOUD_DISCOVERABLE")
        if ag["lifecycle_status"] not in ("ACTIVE",) and ag["last_activity_days_ago"] <= 30 and ag["lifecycle_status"] in ("SUSPENDED", "RETIRED", "DRAFT"):
            c.add("LIFECYCLE_NOT_ACTIVE_BUT_RUNNING")
        ag["estate_conditions"] = sorted(c)
        ag["serious_condition_count"] = len(c & SERIOUS_CONDITIONS)


def derive_reality(ag, handoffs) -> str:
    in_a2a = any(ag["id"] in (h["from_agent_id"], h["to_agent_id"]) and h["crosses_process_boundary"] for h in handoffs)
    if ag["gateway"]["via_gateway"] or in_a2a:
        return "ACTIVE_REAL_PROCESS_REQUIRED_STAGE2"
    if ag["last_activity_days_ago"] > 90:
        return "DORMANT_ASSET"
    if not ag["known_to_act_inventory"] and ag["discoverable_via_source_ids"]:
        return "REAL_EXTERNAL_SERVICE_REQUIRED_STAGE2"
    return "SIMULATED_ASSET"


def summarize(e: dict) -> dict:
    agents = e["agents"]
    primary_id = next(t["id"] for t in e["tenants"] if t["role"] == "PRIMARY")
    prim = [a for a in agents if a["tenant_id"] == primary_id]
    def count(key):
        out: dict[str, int] = {}
        for a in agents:
            v = a[key] if not isinstance(a[key], dict) else None
            out[str(v)] = out.get(str(v), 0) + 1
        return dict(sorted(out.items()))
    cond: dict[str, int] = {}
    for a in agents:
        for c in a["estate_conditions"]:
            cond[c] = cond.get(c, 0) + 1
    return {
        "canonical_agents_total": len(agents), "canonical_agents_primary_tenant": len(prim),
        "control_group": len(e["control_group_agent_ids"]), "people": len(e["people"]), "resources": len(e["resources"]),
        "credentials": len(e["credentials"]), "tools": len(e["tools"]), "mcp_servers": len(e["mcp_servers"]),
        "identities": len(e["identities"]), "dependencies": len(e["dependencies"]), "delegations": len(e["delegations"]),
        "agent_authority": len(e["agent_authority"]), "a2a_handoffs": len(e["a2a_handoffs"]), "discovery_sources": len(e["discovery_sources"]),
        "sensitive_reachability_paths": len(e["sensitive_reachability"]), "identifier_collisions": len(e["identifier_collisions"]),
        "truthful_refusal_subjects": len(e["truthful_refusal_subject_agent_ids"]),
        "by_origin_category": count("origin_category"), "by_control_state": count("control_state"), "by_lifecycle_status": count("lifecycle_status"),
        "by_inventory_status": count("inventory_status"), "by_reality_class": count("reality_class"),
        "by_enforcement_mode": count("external_enforcement_mode"), "by_estate_condition": dict(sorted(cond.items())),
        "agents_with_multiple_serious_conditions": sum(1 for a in agents if a["serious_condition_count"] >= 2),
    }
