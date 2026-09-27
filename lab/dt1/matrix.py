"""DT1 Stage 1 - AGENT_PROPERTY_MATRIX: one row per canonical agent, every
overlapping property, reality class, estate conditions, control-group flag.
Derived from estate_truth, never hand-edited."""
from __future__ import annotations

COLUMNS = ["id", "tenant_role", "name", "origin_category", "origin_provider", "control_state", "lifecycle_status",
           "inventory_status", "external_enforcement_mode", "owned", "identity_kind", "credential_postures", "tool_approval",
           "mcp_trust", "sensitive_reach", "memory_kind", "a2a_participant", "gateway_grants", "out_of_scope_attempts",
           "provenance_quality", "reality_class", "control_group", "serious_condition_count", "estate_conditions"]


def build_matrix(estate: dict, *, matrix_version: str) -> dict:
    tenants = {t["id"]: t["role"] for t in estate["tenants"]}
    cred = {c["id"]: c for c in estate["credentials"]}
    tool = {t["id"]: t for t in estate["tools"]}
    mcp = {m["id"]: m for m in estate["mcp_servers"]}
    ident = {i["agent_id"]: i["kind"] for i in estate["identities"]}
    a2a = {h["from_agent_id"] for h in estate["a2a_handoffs"]} | {h["to_agent_id"] for h in estate["a2a_handoffs"]}
    reach: dict[str, list] = {}
    for r in estate["sensitive_reachability"]:
        reach.setdefault(r["agent_id"], []).append(r["sensitivity"])
    rows = []
    for a in estate["agents"]:
        rows.append({
            "id": a["id"], "tenant_role": tenants[a["tenant_id"]], "name": a["name"], "origin_category": a["origin_category"],
            "origin_provider": a["origin_provider"], "control_state": a["control_state"], "lifecycle_status": a["lifecycle_status"],
            "inventory_status": a["inventory_status"], "external_enforcement_mode": a["external_enforcement_mode"],
            "owned": bool(a["owners"]["business_person_id"]), "identity_kind": ident.get(a["id"]),
            "credential_postures": sorted({p for c in a["credential_ids"] for p in cred[c]["posture"]}),
            "tool_approval": sorted({tool[t]["approval_state"] for t in a["tool_ids"]}),
            "mcp_trust": sorted({mcp[m]["trust_status"] for m in a["mcp_server_ids"]}),
            "sensitive_reach": sorted(set(reach.get(a["id"], []))), "memory_kind": a["memory"]["kind"],
            "a2a_participant": a["id"] in a2a, "gateway_grants": len(a["gateway"]["grants"]),
            "out_of_scope_attempts": len(a["gateway"]["attempted_targets_out_of_scope_tool_ids"]),
            "provenance_quality": a["provenance_quality"], "reality_class": a["reality_class"], "control_group": a["control_group"],
            "serious_condition_count": a["serious_condition_count"], "estate_conditions": a["estate_conditions"],
        })
    rows.sort(key=lambda r: r["id"])
    def dist(key):
        out: dict[str, int] = {}
        for r in rows:
            v = r[key]
            for x in (v if isinstance(v, list) else [v]):
                out[str(x)] = out.get(str(x), 0) + 1
        return dict(sorted(out.items()))
    return {"matrix_version": matrix_version, "generator": estate["generator"], "columns": COLUMNS, "rows": rows,
            "summary": {"agents": len(rows), "control_group": sum(1 for r in rows if r["control_group"]),
                        "primary_tenant_agents": sum(1 for r in rows if r["tenant_role"] == "PRIMARY"),
                        "agents_with_2_plus_serious_conditions": sum(1 for r in rows if r["serious_condition_count"] >= 2),
                        "agents_with_4_plus_serious_conditions": sum(1 for r in rows if r["serious_condition_count"] >= 4),
                        "by_origin_category": dist("origin_category"), "by_control_state": dist("control_state"),
                        "by_inventory_status": dist("inventory_status"), "by_enforcement_mode": dist("external_enforcement_mode"),
                        "by_reality_class": dist("reality_class"), "by_memory_kind": dist("memory_kind"),
                        "by_estate_condition": dist("estate_conditions"), "by_credential_posture": dist("credential_postures")}}


def render_markdown(matrix: dict, estate: dict) -> str:
    L = ["# AGENT_PROPERTY_MATRIX — DT1 Stage 1", "",
         f"Generated from `estate_truth` (seed `{matrix['generator']['seed']}`, generator `{matrix['generator']['generator_version']}`). "
         "One row per canonical agent; properties overlap by construction. Serious conditions are objective estate facts, not ACT findings.", "",
         "## Summary", ""]
    for k, v in matrix["summary"].items():
        L.append(f"- **{k}**: `{v}`" if not isinstance(v, dict) else f"- **{k}**: " + ", ".join(f"{a} = {b}" for a, b in v.items()))
    L += ["", "## Rows", "", "| agent | tenant | origin / provider | control · lifecycle | inventory | mode | owned | creds | tools | mcp | sensitive reach | memory | A2A | grants / out-of-scope | reality | ctrl | conditions |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in matrix["rows"]:
        L.append(f"| **{r['name']}** `{r['id'][-8:]}` | {r['tenant_role'][:4]} | {r['origin_category']} / {r['origin_provider']} | {r['control_state']} · {r['lifecycle_status']} | "
                 f"{r['inventory_status']} | {r['external_enforcement_mode'] or '—'} | {'yes' if r['owned'] else '**no**'} | {','.join(r['credential_postures']) or '—'} | "
                 f"{','.join(r['tool_approval']) or '—'} | {','.join(r['mcp_trust']) or '—'} | {','.join(r['sensitive_reach']) or '—'} | {r['memory_kind']} | "
                 f"{'yes' if r['a2a_participant'] else '—'} | {r['gateway_grants']} / {r['out_of_scope_attempts']} | {r['reality_class'].replace('_REQUIRED_STAGE2', '')} | "
                 f"{'**✓**' if r['control_group'] else ''} | {', '.join(r['estate_conditions']) or '—'} |")
    return "\n".join(L) + "\n"
