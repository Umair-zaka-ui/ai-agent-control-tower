"""DT1 Stage 1 - MANIFEST SELF-VALIDATOR: validates the GENERATED ARTIFACTS,
never ACT behaviour. Every check is named; the validator exits non-zero on the
first violation class and reports every violation (§9). It must be capable of
failing - the negative tests in ``tests/test_negative.py`` prove it is.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from canonical import canonical_bytes, is_stable_id

REALITY_CLASSES = ("ACTIVE_REAL_PROCESS_REQUIRED_STAGE2", "REAL_EXTERNAL_SERVICE_REQUIRED_STAGE2", "SIMULATED_ASSET", "DORMANT_ASSET")
OBS_CLASSES = ("OBSERVE", "PARTIALLY_OBSERVE", "NOT_OBSERVE", "ENFORCE", "REFUSE")
REQUIRED_CONDITIONS = ("OVER_PRIVILEGED_CREDENTIAL", "SHARED_CREDENTIAL", "STALE_CREDENTIAL", "EXPIRED_CREDENTIAL_STILL_ACTIVE",
                       "UNOWNED", "SHADOW_DISCOVERABLE", "SHADOW_DARK", "UNKNOWN_PROVENANCE", "UNAPPROVED_MCP", "UNAPPROVED_TOOL",
                       "DANGEROUS_DEPENDENCY_SENSITIVE_REACH", "DORMANT_WITH_ACTIVE_CREDENTIAL", "NATIVE_REFERENCE_COLLISION",
                       "PRODUCTION_ACCESS_UNOWNED")
EXPECTATION_KEY = re.compile(r"(?i)^(expected[_-]?|act_should|finding|verdict|expect_)")
# secret shapes (copied from the product scrubber's published patterns; the DT1 package imports nothing from app)
SECRET_SHAPES = [re.compile(p) for p in (
    r"\b(sk|pk|rk|ak)-[A-Za-z0-9_-]{16,}", r"\b(ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{16,}", r"\bxox[baprs]-[A-Za-z0-9-]{10,}",
    r"\bAKIA[0-9A-Z]{16}\b", r"\bAIza[0-9A-Za-z_-]{35}", r"-----BEGIN[A-Z ]*PRIVATE KEY-----",
    r"^ey[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+$", r"\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{16,}",
    r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@")]
PHI_MARKERS = re.compile(r"(?i)\b(patient|diagnosis|medical record|PHI|prescription|clinical)\b")
ALLOWED_ARTIFACTS = {"estate_truth.json", "observability_contract.json", "agent_property_matrix.json", "anchor.json", "schema_grounding.json"}
PRODUCTION_PATHS = ["backend/app", "backend/migrations", "backend/requirements.txt", "backend/tests", "frontend", ".github"]


class Report:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append({"check": name, "ok": bool(ok), "detail": detail[:400]})

    @property
    def ok(self) -> bool:
        return all(r["ok"] for r in self.results)

    def failures(self) -> list[dict]:
        return [r for r in self.results if not r["ok"]]


def _walk_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}" if path else k, k
            yield from _walk_keys(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_keys(v, f"{path}[{i}]")


def validate(art_dir: Path, *, grounding: dict | None = None, base_commit: str | None = None, repo_root: Path | None = None,
             check_regeneration: bool = True) -> Report:
    R = Report()
    art_dir = Path(art_dir)
    try:
        truth = json.loads((art_dir / "estate_truth.json").read_text(encoding="utf-8"))
        contract = json.loads((art_dir / "observability_contract.json").read_text(encoding="utf-8"))
        matrix = json.loads((art_dir / "agent_property_matrix.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        R.check("artifacts.loadable", False, f"{type(exc).__name__}: {exc}")
        return R
    R.check("artifacts.loadable", True)
    grounding = grounding or json.loads((art_dir / "schema_grounding.json").read_text(encoding="utf-8"))

    # ---- canonical schema validity (structural) ----
    req_top = ["schema_version", "generator", "tenants", "people", "resources", "credentials", "tools", "mcp_servers", "identities", "agents",
               "dependencies", "delegations", "agent_authority", "a2a_handoffs", "discovery_sources", "sensitive_reachability",
               "identifier_collisions", "truthful_refusal_subject_agent_ids", "control_group_agent_ids", "summary"]
    missing = [k for k in req_top if k not in truth]
    R.check("schema.estate_truth.top_level", not missing, f"missing: {missing}")
    req_agent = ["id", "tenant_id", "name", "origin_category", "origin_provider", "control_state", "lifecycle_status", "external_reference",
                 "external_enforcement_mode", "inventory_status", "known_to_act_inventory", "discoverable_via_source_ids", "owners", "identity_id",
                 "credential_ids", "tool_ids", "mcp_server_ids", "memory", "gateway", "process_owner", "provenance_quality", "reality_class",
                 "control_group", "estate_conditions", "serious_condition_count"]
    bad = [a.get("id") for a in truth["agents"] if any(k not in a for k in req_agent)]
    R.check("schema.estate_truth.agents", not bad, f"agents missing keys: {bad[:5]}")
    R.check("schema.observability_contract", all(k in contract for k in ("contract_version", "classes", "entries", "derivation_rule", "summary"))
            and all(k in e for k in ("id", "fact_class", "classification", "code_refs", "justification") for e in contract["entries"]))
    R.check("schema.agent_property_matrix", all(k in matrix for k in ("matrix_version", "columns", "rows", "summary")))

    # ---- vocabularies match the grounding ----
    consts = grounding["constants"]
    control_states = consts["app/runtime/registry/control.py"]["CONTROL_STATES"]["value"]
    origins = consts["app/runtime/registry/control.py"]["ORIGIN_CATEGORIES"]["value"]
    modes = consts["app/models/bridge.py"]["STORABLE_ENFORCEMENT_MODES"]["value"]
    legal = consts["app/runtime/registry/control.py"]["LEGAL_CONTROL_STATES_BY_ORIGIN"]["value"]
    lifecycle = consts["app/runtime/services.py"]["AGENT_LIFECYCLE"]["value"]
    edge_types = consts["app/models/graph.py"]["EDGE_TYPES"]["value"]
    trust = consts["app/models/graph.py"]["MCP_TRUST_STATUSES"]["value"]
    R.check("vocab.control_state", all(a["control_state"] in control_states for a in truth["agents"]))
    R.check("vocab.origin_category", all(a["origin_category"] in origins for a in truth["agents"]))
    R.check("vocab.lifecycle", all(a["lifecycle_status"] in lifecycle for a in truth["agents"]))
    R.check("vocab.enforcement_mode", all(a["external_enforcement_mode"] in (None, *modes) for a in truth["agents"]))
    R.check("vocab.edge_types", all(e["edge_type"] in edge_types for e in truth["dependencies"]))
    R.check("vocab.mcp_trust", all(m["trust_status"] in trust for m in truth["mcp_servers"]))
    illegal = [a["id"] for a in truth["agents"] if a["control_state"] not in legal[a["origin_category"]]]
    R.check("legality.control_state_by_origin", not illegal, f"illegal origin x control_state: {illegal[:5]}")
    R.check("legality.native_provider", all(a["origin_provider"] == "ACT_NATIVE" for a in truth["agents"] if a["origin_category"] == "NATIVE"))
    R.check("legality.mode_only_for_external", all(a["external_enforcement_mode"] is None for a in truth["agents"] if a["origin_category"] == "NATIVE"))
    R.check("legality.gateway_enforced_is_registered_and_known",
            all(a["control_state"] == "REGISTERED" and a["known_to_act_inventory"] for a in truth["agents"] if a["external_enforcement_mode"] == "GATEWAY_ENFORCED"))
    R.check("vocab.reality_class", all(a["reality_class"] in REALITY_CLASSES for a in truth["agents"]))

    # ---- identifiers ----
    ids = [a["id"] for a in truth["agents"]]
    R.check("agents.unique_ids", len(ids) == len(set(ids)), f"{len(ids) - len(set(ids))} duplicate ids")
    names = [(a["tenant_id"], a["name"]) for a in truth["agents"]]
    R.check("agents.unique_names_per_tenant", len(names) == len(set(names)))
    all_ids = []
    for coll in ("tenants", "people", "resources", "credentials", "tools", "mcp_servers", "identities", "agents", "dependencies", "delegations",
                 "agent_authority", "a2a_handoffs", "discovery_sources", "sensitive_reachability", "identifier_collisions"):
        all_ids += [x["id"] for x in truth[coll]]
    R.check("ids.stable_shape", all(is_stable_id(i) for i in all_ids), "an id does not match <kind>-<20 hex>")
    R.check("ids.globally_unique", len(all_ids) == len(set(all_ids)))

    # ---- referential integrity + tenant isolation ----
    tenant_of: dict[str, str] = {}
    for coll in ("people", "resources", "credentials", "tools", "mcp_servers", "identities", "agents", "discovery_sources"):
        for x in truth[coll]:
            tenant_of[x["id"]] = x["tenant_id"]
    tenant_ids = {t["id"] for t in truth["tenants"]}
    R.check("tenants.two_roles", {t["role"] for t in truth["tenants"]} == {"PRIMARY", "ISOLATION_CONTROL"})
    problems: list[str] = []
    xt: list[str] = []

    def ref(owner_id, owner_tenant, target, what):
        if target is None:
            return
        if target not in tenant_of:
            problems.append(f"{what}: {owner_id} -> {target} (missing)")
        elif tenant_of[target] != owner_tenant:
            xt.append(f"{what}: {owner_id} -> {target}")
    for a in truth["agents"]:
        if a["tenant_id"] not in tenant_ids:
            problems.append(f"agent tenant missing: {a['id']}")
        for k in ("business_person_id", "technical_person_id", "compliance_person_id"):
            ref(a["id"], a["tenant_id"], a["owners"][k], "owner")
        ref(a["id"], a["tenant_id"], a["identity_id"], "identity")
        for c in a["credential_ids"]:
            ref(a["id"], a["tenant_id"], c, "credential")
        for t in a["tool_ids"]:
            ref(a["id"], a["tenant_id"], t, "tool")
        for m in a["mcp_server_ids"]:
            ref(a["id"], a["tenant_id"], m, "mcp")
        for r in a["direct_resource_ids"]:
            ref(a["id"], a["tenant_id"], r, "resource")
        for s in a["discoverable_via_source_ids"]:
            ref(a["id"], a["tenant_id"], s, "source")
        ref(a["id"], a["tenant_id"], a["memory"]["store_resource_id"], "memory_store")
        for g in a["gateway"]["grants"]:
            ref(a["id"], a["tenant_id"], g["target_tool_id"], "grant_target")
        ref(a["id"], a["tenant_id"], a["gateway"]["uses_grant_issued_to_agent_id"], "shared_grant_agent")
    for c in truth["credentials"]:
        ref(c["id"], c["tenant_id"], c["owner_person_id"], "credential_owner")
        for r in c["grants_access_to_resource_ids"]:
            ref(c["id"], c["tenant_id"], r, "credential_resource")
    for t in truth["tools"]:
        ref(t["id"], t["tenant_id"], t["uses_credential_id"], "tool_credential")
        ref(t["id"], t["tenant_id"], t["exposed_by_mcp_server_id"], "tool_mcp")
        for r in t["accesses_resource_ids"]:
            ref(t["id"], t["tenant_id"], r, "tool_resource")
    for m in truth["mcp_servers"]:
        for t in m["exposes_tool_ids"]:
            ref(m["id"], m["tenant_id"], t, "mcp_tool")
    for e in truth["dependencies"]:
        ref(e["id"], e["tenant_id"], e["source_id"], "edge_source")
        ref(e["id"], e["tenant_id"], e["target_id"], "edge_target")
    for d in truth["delegations"]:
        ref(d["id"], d["tenant_id"], d["delegator_person_id"], "delegator")
        ref(d["id"], d["tenant_id"], d["delegatee_person_id"], "delegatee")
    for x in truth["agent_authority"] + truth["a2a_handoffs"]:
        ref(x["id"], x["tenant_id"], x["from_agent_id"], "a2a_from")
        ref(x["id"], x["tenant_id"], x["to_agent_id"], "a2a_to")
    for s in truth["discovery_sources"]:
        for aid in s["lists_agent_ids"]:
            ref(s["id"], s["tenant_id"], aid, "source_lists")
    for r in truth["sensitive_reachability"]:
        ref(r["id"], r["tenant_id"], r["agent_id"], "reach_agent")
        ref(r["id"], r["tenant_id"], r["resource_id"], "reach_resource")
    R.check("references.integrity", not problems, "; ".join(problems[:6]))
    R.check("tenant.isolation", not xt, "cross-tenant references: " + "; ".join(xt[:6]))

    # ---- ownership / control group ----
    cg = [a for a in truth["agents"] if a["control_group"]]
    R.check("control_group.count_10_to_15", 10 <= len(cg) <= 15, f"control group = {len(cg)}")
    R.check("control_group.ids_consistent", sorted(a["id"] for a in cg) == truth["control_group_agent_ids"])
    R.check("control_group.fully_owned", all(all(a["owners"][k] for k in ("business_person_id", "technical_person_id", "compliance_person_id")) for a in cg))
    R.check("control_group.no_serious_condition", all(a["serious_condition_count"] == 0 for a in cg),
            f"control agents with serious conditions: {[a['id'] for a in cg if a['serious_condition_count']][:5]}")
    R.check("control_group.active_lifecycle", all(a["lifecycle_status"] == "ACTIVE" for a in cg))
    R.check("estate.not_all_risky", 0 < len(cg) < len(truth["agents"]) and any(a["serious_condition_count"] >= 3 for a in truth["agents"]))
    R.check("estate.size_50_to_60", 50 <= len(truth["agents"]) <= 60, f"{len(truth['agents'])} canonical agents")

    # ---- adversarial conditions present (objective) ----
    present = {c for a in truth["agents"] for c in a["estate_conditions"]}
    missing_c = [c for c in REQUIRED_CONDITIONS if c not in present]
    R.check("adversarial.required_conditions_present", not missing_c, f"missing: {missing_c}")
    gs = grounding["gap_status"]
    if gs.get("F6-1") == "PRESENT":
        R.check("adversarial.f6_1_represented", any("F6_1_RELEVANT" in a["estate_conditions"] and a["gateway"]["attempted_targets_out_of_scope_tool_ids"] for a in truth["agents"]))
    if gs.get("I-1") == "PRESENT":
        R.check("adversarial.i1_represented", any(a["memory"]["kind"] == "PERSISTENT" for a in truth["agents"]))
    if gs.get("I-2") == "PRESENT":
        R.check("adversarial.i2_represented", bool(truth["a2a_handoffs"]) and bool(truth["agent_authority"]))
    subj = [a for a in truth["agents"] if a["id"] in truth["truthful_refusal_subject_agent_ids"]]
    R.check("truthful_refusal.represented", bool(subj) and all(
        a["process_owner"] != "ACT" and (a["gateway"]["grants"] or a["gateway"]["uses_grant_issued_to_agent_id"])
        and a["reality_class"] == "ACTIVE_REAL_PROCESS_REQUIRED_STAGE2" for a in subj), f"{len(subj)} subjects")
    R.check("collision.represented_objectively", bool(truth["identifier_collisions"]) and all(
        c["native_agent_id"] != c["external_agent_id"] for c in truth["identifier_collisions"]))

    # ---- Stage-2 reality markings ----
    a2a_cross = {x for h in truth["a2a_handoffs"] if h["crosses_process_boundary"] for x in (h["from_agent_id"], h["to_agent_id"])}
    bad_real = [a["id"] for a in truth["agents"] if (a["external_enforcement_mode"] == "GATEWAY_ENFORCED" or a["id"] in a2a_cross
                or a["gateway"]["uses_grant_issued_to_agent_id"]) and a["reality_class"] != "ACTIVE_REAL_PROCESS_REQUIRED_STAGE2"]
    R.check("stage2.real_process_markings", not bad_real, f"should be ACTIVE_REAL_PROCESS_REQUIRED_STAGE2: {bad_real[:5]}")
    R.check("stage2.discovery_crosses_boundary", any(s["crosses_process_boundary"] and s["lists_agent_ids"] for s in truth["discovery_sources"]))
    R.check("stage2.sources_list_only_discoverable_agents", all(
        s["id"] in next(a for a in truth["agents"] if a["id"] == aid)["discoverable_via_source_ids"]
        for s in truth["discovery_sources"] for aid in s["lists_agent_ids"]))

    # ---- no expectations, no secrets, no forbidden real data ----
    exp_keys = sorted({k for _, k in _walk_keys(truth) if EXPECTATION_KEY.match(k)})
    R.check("truth.no_expectation_keys", not exp_keys, f"{exp_keys[:5]}")
    text = json.dumps(truth, ensure_ascii=False) + json.dumps(contract, ensure_ascii=False) + json.dumps(matrix, ensure_ascii=False)
    hits = [p.pattern for p in SECRET_SHAPES if p.search(text)]
    R.check("security.no_secret_shapes", not hits, f"secret-shaped content: {hits}")
    R.check("security.credentials_carry_no_value", all(c.get("secret_value") is None for c in truth["credentials"]))
    R.check("privacy.no_phi_default", not PHI_MARKERS.search(json.dumps([a["name"] + a["description"] for a in truth["agents"]] + [r["name"] for r in truth["resources"]])))
    R.check("privacy.fictional_emails", all(p["email"].endswith(".example") for p in truth["people"]))

    # ---- contract ----
    R.check("contract.classes", all(e["classification"] in OBS_CLASSES for e in contract["entries"]))
    R.check("contract.non_observe_justified", all((e["code_refs"] and e["justification"] and (e["missing_evidence"] or e["control_boundary"] or e["precondition"]))
                                                  for e in contract["entries"] if e["classification"] != "OBSERVE"))
    R.check("contract.no_weakness_only_justification", not any(re.search(r"(?i)known (weakness|gap|to miss)", e["justification"]) and not e["code_refs"] for e in contract["entries"]))
    R.check("contract.gap_ids_grounded", all(e["gap_id"] in gs for e in contract["entries"] if e["gap_id"]))
    R.check("contract.examples_exist", all(x in set(ids) for e in contract["entries"] for x in e["example_agent_ids"]))
    R.check("contract.covers_all_five_classes", set(e["classification"] for e in contract["entries"]) == set(OBS_CLASSES))
    R.check("contract.generator_matches_truth", contract["generator"] == truth["generator"])

    # ---- matrix ----
    R.check("matrix.one_row_per_agent", [r["id"] for r in matrix["rows"]] == sorted(ids))
    by = {a["id"]: a for a in truth["agents"]}
    R.check("matrix.conditions_match_truth", all(r["estate_conditions"] == by[r["id"]]["estate_conditions"] and r["control_group"] == by[r["id"]]["control_group"] for r in matrix["rows"]))

    # ---- canonical serialization + determinism ----
    for name, obj in (("estate_truth.json", truth), ("observability_contract.json", contract), ("agent_property_matrix.json", matrix)):
        R.check(f"canonical.{name}", canonical_bytes(obj) == (art_dir / name).read_bytes(), "re-serialization differs from bytes on disk")
    if check_regeneration:
        try:
            import estate as estate_mod, contract as contract_mod, matrix as matrix_mod  # noqa: E401
            regen = estate_mod.build_estate(truth["generator"]["seed"], grounding, generator_version=truth["generator"]["generator_version"],
                                            schema_version=truth["schema_version"])
            R.check("determinism.regenerate_estate_identical", canonical_bytes(regen) == (art_dir / "estate_truth.json").read_bytes())
            R.check("determinism.regenerate_contract_identical",
                    canonical_bytes(contract_mod.build_contract(regen, grounding, contract_version=contract["contract_version"])) == (art_dir / "observability_contract.json").read_bytes())
            R.check("determinism.regenerate_matrix_identical",
                    canonical_bytes(matrix_mod.build_matrix(regen, matrix_version=matrix["matrix_version"])) == (art_dir / "agent_property_matrix.json").read_bytes())
        except Exception as exc:  # noqa: BLE001
            R.check("determinism.regenerate", False, f"{type(exc).__name__}: {exc}")

    # ---- seal ----
    anchor_path = art_dir / "anchor.json"
    if anchor_path.exists():
        import seal as seal_mod
        v = seal_mod.verify(art_dir)
        R.check("seal.hashes_match_anchor", v["ok"], json.dumps(v["differences"])[:300])
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        R.check("seal.anchor_not_in_content", "created_at" not in text and anchor["combined_root_sha256"] not in text)
        R.check("seal.versions_match", anchor["seed"] == truth["generator"]["seed"] and anchor["schema_grounding_version"] == truth["generator"]["schema_grounding_version"])
        base_commit = base_commit or anchor.get("base_commit")

    # ---- no ACT execution artifacts; product boundary ----
    extra = sorted(p.name for p in art_dir.glob("*") if p.is_file() and p.name not in ALLOWED_ARTIFACTS)
    R.check("boundary.no_unexpected_artifacts", not extra, f"unexpected files: {extra}")
    act_exec_keys = sorted({k for _, k in _walk_keys(truth) if k in ("discovery_runs", "threat_findings", "posture_findings", "containment_actions", "external_gateway_calls")})
    R.check("boundary.no_act_execution_artifacts", not act_exec_keys, f"{act_exec_keys}")
    if base_commit and repo_root:
        p = subprocess.run(["git", "diff", "--quiet", base_commit, "--", *PRODUCTION_PATHS], cwd=str(repo_root))
        R.check("boundary.empty_production_diff", p.returncode == 0, f"git diff {base_commit} -- {' '.join(PRODUCTION_PATHS)} is not empty (rc={p.returncode})")
    return R
