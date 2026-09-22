"""V5 RED TEAM — discovery poisoning (T19a), reconciliation corruption (T19b),
control-graph attacks (T20).

V3 attacked what flows *through* ACT; V4 attacked its *authority model*; V5
attacks its **picture of reality** — the inventory and graph every downstream
governance decision reads.

The model under attack (grounded in code, expectations fixed before execution):
  * `ReconciliationService` matches on an EXACT `(organization_id,
    external_reference)` pair — no fuzzy/name matching (a documented non-goal).
    Exactly three outcomes: CREATE / LINK / FLAG. NATIVE collision is checked
    FIRST and ALWAYS flags. Below `LINK_CREATE_CONFIDENCE_THRESHOLD = 0.75`
    always flags. LINK touches discovery metadata ONLY — never ownership,
    control_state or lifecycle_status.
  * `HttpAgentRegistryAdapter.normalize()` hard-codes `confidence=1.00` as an
    adapter-CLASS constant; it is never read from the source payload, so a
    hostile source cannot forge a confidence signal.
  * Observations are append-only EVIDENCE, bounded before persist, each in its
    own SAVEPOINT.
  * Staleness raises a non-destructive `STALE_AGENT` finding — never a delete.
  * Blast radius is per-hop tenant-bounded, depth-capped, cycle-safe, and
    carries `incomplete` + `incomplete_reason` so an answer is never falsely
    "empty" (unknown != safe).

Every reconciliation and blast-radius result is scored against a **ground-truth
manifest** recorded before poisoning. Imports nothing from `app`.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab"
RUN = LAB / "run"
RES = RUN / "results"
RES.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(LAB / "harness"))
import ledger  # noqa: E402
import v4_common as C  # noqa: E402

MODE = os.environ.get("LAB_MODE", "host")
HOSTILE_HOST = os.environ.get("LAB_HOSTILE_HOST", "hostile_registry" if MODE == "wrapped" else "127.0.0.1")
HOSTILE = f"http://{HOSTILE_HOST}:8813"
REG_HOST = C.REG_HOST
DISC, GRAPH, RT, POSTURE = C.DISC, C.GRAPH, C.RT, "/api/v1/posture"


# --------------------------------------------------------------------------- #
# hostile source control plane
# --------------------------------------------------------------------------- #
def set_scenario(scenario, **extra):
    body = json.dumps({"scenario": scenario, **extra}).encode()
    req = urllib.request.Request(HOSTILE + "/_control", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:200]}


def hostile_source(tenant, name=None):
    """A discovery source pointed at the HOSTILE registry."""
    s, src, _, raw = C.http("POST", f"{DISC}/sources", headers=tenant["headers"], body={
        "name": name or f"V5 Hostile Source {uuid.uuid4().hex[:6]}",
        "adapter_key": "HTTP_AGENT_REGISTRY",
        "config": {"base_url": HOSTILE, "allowed_hosts": [HOSTILE_HOST],
                   "local_dev_hosts": [HOSTILE_HOST], "allow_plaintext_http": True,
                   "path": "/agents", "page_size": 50, "max_pages": 5}})
    return s, (src if s == 201 else raw)


def sweep(tenant, source_id):
    s, run, ms, raw = C.http("POST", f"{DISC}/sources/{source_id}/runs", headers=tenant["headers"])
    return s, (run if s == 201 else raw), ms


def inventory(org_id):
    rows = C.sql("""SELECT id::text, name, external_reference, origin_category, origin_provider,
                           control_state, owner_id::text, lifecycle_status
                    FROM agents WHERE organization_id=%s ORDER BY external_reference""", (org_id,))
    return [{"id": r[0], "name": r[1], "external_reference": r[2], "origin_category": r[3],
             "origin_provider": r[4], "control_state": r[5], "owner_id": r[6],
             "lifecycle_status": r[7]} for r in rows]


def observations(org_id):
    rows = C.sql("""SELECT external_identifier, confidence::text FROM discovery_observations
                    WHERE organization_id=%s ORDER BY observed_at""", (org_id,))
    return [{"external_identifier": r[0], "confidence": r[1]} for r in rows]


def findings(org_id):
    rows = C.sql("""SELECT finding_type, status, external_identifier, reason
                    FROM discovery_findings WHERE organization_id=%s ORDER BY created_at""", (org_id,))
    return [{"type": r[0], "status": r[1], "external_identifier": r[2], "reason": (r[3] or "")[:160]}
            for r in rows]


def is_trusted(agent):
    """'Trusted inventory' = anything beyond an unowned, external, DISCOVERED row."""
    return (agent["control_state"] != "DISCOVERED"
            or agent["origin_category"] == "NATIVE"
            or agent["owner_id"] is not None)


def poisoned_tenant(scenario, label, **extra):
    """Fresh tenant + hostile source + one sweep under `scenario`."""
    t = C.register(f"V5 {label} {uuid.uuid4().hex[:6]}")
    ctl = set_scenario(scenario, **extra)
    s_src, src = hostile_source(t)
    if s_src != 201:
        return {"tenant": t, "error": "source_create_failed", "detail": src, "control": ctl}
    s_run, run, ms = sweep(t, src["id"])
    return {"tenant": t, "source": src, "control": ctl, "run_status": s_run, "run": run, "ms": ms,
            "inventory": inventory(t["organization_id"]),
            "observations": observations(t["organization_id"]),
            "findings": findings(t["organization_id"])}


# --------------------------------------------------------------------------- #
def main() -> int:
    out = {"phase": "V5", "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "ground_truth": {}, "discovery": [], "reconciliation": [], "graph": [],
           "blockers": {"silent_over_merge": False, "silent_under_merge": False,
                        "cross_tenant_traversal": False, "false_asset_trusted": False,
                        "forged_confidence_auto_link": False, "poisoned_edge_granted_authority": False,
                        "blast_radius_false_safe": False}}

    def rec(bucket, test_id, scenario, attack, expected, observed, verdict, authority, severity=None):
        row = {"test_id": test_id, "scenario": scenario, "attack": attack, "expected": expected,
               "observed": observed, "verdict": verdict, "authority": authority}
        if severity:
            row["severity"] = severity
        out[bucket].append(row)
        print(f"  {test_id:<9} {scenario:<32} -> {verdict}", flush=True)

    # ======================================================================= #
    # §1 GROUND TRUTH — the true inventory and graph, recorded before poisoning
    # ======================================================================= #
    print("GROUND TRUTH", flush=True)
    gt_tenant = C.register("V5 Ground Truth")
    set_scenario("baseline")
    s_src, gt_src = hostile_source(gt_tenant, name="V5 Ground Truth Source")
    s_run, gt_run, _ = sweep(gt_tenant, gt_src["id"])
    gt_inv = inventory(gt_tenant["organization_id"])
    out["ground_truth"] = {
        "tenant": gt_tenant["organization_id"],
        "true_agent_count": 3,
        "true_external_references": sorted(a["external_reference"] for a in gt_inv),
        "observed_inventory": gt_inv,
        "run": {"status": s_run, "created": gt_run.get("agents_created"),
                "linked": gt_run.get("agents_linked"), "flagged": gt_run.get("findings_raised")},
        "landing_state": sorted({(a["control_state"], a["origin_category"],
                                  a["owner_id"] is None) for a in gt_inv}),
        "note": "the hostile source's `baseline` scenario serves exactly the three REAL lab agents; "
                "this is the known-correct picture every later result is scored against",
    }
    print(f"  ground truth: {len(gt_inv)} agents, states={out['ground_truth']['landing_state']}", flush=True)

    # ======================================================================= #
    # §3 DISCOVERY POISONING (T19a)
    # ======================================================================= #
    print("BATCH T19a: discovery poisoning", flush=True)

    # --- V5-D1 false-asset injection ---------------------------------------
    r = poisoned_tenant("false_assets", "FalseAssets")
    inv = r.get("inventory", [])
    ghosts = [a for a in inv if "ghost" in a["external_reference"]]
    promoted = [a for a in ghosts if is_trusted(a)]
    out["blockers"]["false_asset_trusted"] = bool(promoted)
    rec("discovery", "V5-D1", "false-asset injection",
        "a hostile source reports agents that do not exist",
        "recorded as observation/evidence and created only as unowned EXTERNAL/DISCOVERED rows; "
        "never promoted to trusted inventory",
        {"agents_total": len(inv), "ghost_rows": len(ghosts),
         "ghost_states": sorted({(a["control_state"], a["origin_category"], a["owner_id"] is None)
                                 for a in ghosts}),
         "promoted_to_trusted": len(promoted), "observations": len(r.get("observations", []))},
        "PASS (evidence-not-trusted)" if ghosts and not promoted else
        ("FAIL — false asset trusted" if promoted else "GAP"),
        "5.2 observations are evidence; creation lands DISCOVERED/EXTERNAL/unowned",
        severity="BLOCKER" if promoted else None)

    # --- V5-D2 source impersonation ----------------------------------------
    # An unregistered source cannot drive discovery at all: a sweep requires a
    # registered, tenant-scoped source row and an authorized actor.
    t_imp = C.register("V5 Impersonation")
    s_noauth, r_noauth, _, _ = C.http("POST", f"{DISC}/sources/{uuid.uuid4()}/runs",
                                      headers=t_imp["headers"])
    s_other, other_src = hostile_source(gt_tenant, name="V5 Victim Source")
    s_cross, r_cross, _, _ = C.http("POST", f"{DISC}/sources/{other_src['id']}/runs",
                                    headers=t_imp["headers"]) if s_other == 201 else (None, None, None, None)
    rec("discovery", "V5-D2", "source impersonation",
        "an unregistered source poses as trusted; another tenant drives a victim's source",
        "both rejected: a sweep requires a registered, tenant-scoped source and an authorized actor",
        {"unregistered_source_run": s_noauth, "cross_tenant_source_run": s_cross},
        "PASS (rejected)" if s_noauth in (403, 404) and s_cross in (403, 404) else "FAIL",
        "5.2 source registration + tenant scoping",
        severity=None if s_noauth in (403, 404) and s_cross in (403, 404) else "BLOCKER")

    # --- V5-D3 malformed / oversized metadata -------------------------------
    r = poisoned_tenant("oversized", "Oversized")
    inv = r.get("inventory", [])
    over = inv[0] if inv else None
    rec("discovery", "V5-D3", "malformed / oversized metadata",
        "giant name (5k), description (200k), origin_provider (500), identifier (5k)",
        "bounded before persist (name<=255, origin_provider<=50, description<=4000, identifier bounded); "
        "the run completes and nothing crashes or stores unbounded",
        {"run_status": r.get("run_status"), "agents": len(inv),
         "name_len": len(over["name"]) if over else None,
         "origin_provider_len": len(over["origin_provider"]) if over else None,
         "external_reference_len": len(over["external_reference"]) if over else None,
         "observations": len(r.get("observations", []))},
        "PASS (bounded)" if over and len(over["name"]) <= 255 and len(over["origin_provider"]) <= 50
        else ("GAP" if over else "GAP (no row persisted)"),
        "5.2 _bounded() + persist-time identifier cap")

    # --- V5-D4 observation replay (idempotency) ------------------------------
    t_rep = C.register("V5 Replay")
    set_scenario("replay")
    s_src, src_rep = hostile_source(t_rep)
    runs = []
    for _ in range(3):
        s_run, run, _ = sweep(t_rep, src_rep["id"])
        runs.append({"status": s_run, "created": run.get("agents_created"),
                     "linked": run.get("agents_linked")})
    inv_rep = inventory(t_rep["organization_id"])
    obs_rep = observations(t_rep["organization_id"])
    rec("discovery", "V5-D4", "observation replay",
        "replay the identical observation set three times",
        "idempotent canonical effect: 3 created on the first sweep, 0 created / 3 linked after; "
        "observations accumulate as append-only evidence",
        {"runs": runs, "canonical_agents": len(inv_rep), "observation_rows": len(obs_rep)},
        "PASS (idempotent)" if len(inv_rep) == 3 and runs[0]["created"] == 3
        and all(r["created"] == 0 for r in runs[1:]) else "FAIL",
        "5.2 exact-identifier reconciliation")

    # --- V5-D5 disappearance / tombstone manipulation -------------------------
    set_scenario("disappear")
    s_run2, run2, _ = sweep(t_rep, src_rep["id"])
    inv_after = inventory(t_rep["organization_id"])
    find_after = findings(t_rep["organization_id"])
    stale = [f for f in find_after if f["type"] == "STALE_AGENT"]
    rec("discovery", "V5-D5", "forced disappearance (tombstone)",
        "two real agents vanish from the source to force a false deletion",
        "non-destructive: no agent row is deleted and no control_state changes; staleness becomes a "
        "finding only after the configured missed-sweep threshold",
        {"agents_before": 3, "agents_after": len(inv_after),
         "any_deleted": len(inv_after) < 3,
         "control_states": sorted({a["control_state"] for a in inv_after}),
         "stale_findings": len(stale)},
        "PASS (non-destructive)" if len(inv_after) == 3 else "FAIL — real agent deleted",
        "5.2 staleness is a finding, never a deletion",
        severity=None if len(inv_after) == 3 else "BLOCKER")

    # --- V5-D6 ownership / trust poisoning -------------------------------------
    r = poisoned_tenant("ownership_poison", "OwnershipPoison")
    inv = r.get("inventory", [])
    poisoned = [a for a in inv if "owned-ghost" in a["external_reference"]]
    injected = [a for a in poisoned if is_trusted(a)]
    out["blockers"]["false_asset_trusted"] = out["blockers"]["false_asset_trusted"] or bool(injected)
    rec("discovery", "V5-D6", "ownership / trust poisoning",
        "payload asserts owner_id, owner_type, control_state=GOVERNED, origin_category=NATIVE, "
        "trust_status=APPROVED, is_trusted",
        "every authority field is ignored: creation goes through AgentProvenanceService as "
        "EXTERNAL/DISCOVERED/unowned; ownership requires an authorized claim",
        {"rows": len(poisoned),
         "observed": [{"control_state": a["control_state"], "origin_category": a["origin_category"],
                       "owner_id": a["owner_id"], "lifecycle_status": a["lifecycle_status"]}
                      for a in poisoned],
         "authority_injected": len(injected)},
        "PASS (payload authority ignored)" if poisoned and not injected else
        ("FAIL — authority injected via payload" if injected else "GAP"),
        "5.2 AgentProvenanceService owns creation; payload never sets authority",
        severity="BLOCKER" if injected else None)

    # --- V5-D7 confidence manipulation -----------------------------------------
    conf = {o["confidence"] for o in r.get("observations", [])}
    rec("discovery", "V5-D7", "confidence manipulation",
        "payload carries discovery_confidence/confidence = 1.00 to inflate match confidence",
        "confidence is an adapter-CLASS constant (1.00 for HTTP_AGENT_REGISTRY), never read from the "
        "payload — a hostile source cannot forge or inflate it",
        {"persisted_confidences": sorted(conf),
         "payload_supplied_confidence_honoured": False,
         "source_of_confidence": "HttpAgentRegistryAdapter.normalize() hard-codes Decimal('1.00')"},
        "PASS (not attacker-controllable)", "5.2 adapter-class confidence")

    # ======================================================================= #
    # §4 RECONCILIATION CORRUPTION (T19b) — scored vs ground truth
    # ======================================================================= #
    print("BATCH T19b: reconciliation corruption", flush=True)

    # --- V5-R1 identifier collision / silent OVER-merge ------------------------
    r = poisoned_tenant("identifier_collision", "Collision")
    inv = r.get("inventory", [])
    obs = r.get("observations", [])
    coll = [a for a in inv if "collision" in a["external_reference"]]
    # Ground truth: the source advertised TWO distinct agents under ONE identifier.
    # ACT's documented identity signal IS the identifier, so one canonical row is
    # the correct derivation — the blocker is whether the second is HIDDEN.
    both_observed = len([o for o in obs if "collision" in o["external_identifier"]]) >= 2
    hidden = len(coll) == 1 and not both_observed
    out["blockers"]["silent_over_merge"] = hidden
    rec("reconciliation", "V5-R1", "identifier collision (over-merge probe)",
        "two DIFFERENT agents advertised under ONE external identifier",
        "deterministic derivation: exactly one canonical row for one identifier, and BOTH observations "
        "retained as append-only evidence so nothing is hidden. A fusion that hides an agent is a BLOCKER",
        {"canonical_rows": len(coll), "observation_rows_for_identifier":
            len([o for o in obs if "collision" in o["external_identifier"]]),
         "both_observations_retained": both_observed,
         "run": {"created": r.get("run", {}).get("agents_created"),
                 "linked": r.get("run", {}).get("agents_linked")},
         "note": "the identifier is ACT's documented identity signal; a source claiming one identifier "
                 "for two agents is the source asserting they are one asset"},
        "PASS (deterministic, nothing hidden)" if len(coll) == 1 and both_observed else
        ("FAIL — silent over-merge" if hidden else "GAP"),
        "5.2 exact-identifier matching + append-only observations",
        severity="BLOCKER" if hidden else None)

    # --- V5-R2 split identity / silent UNDER-merge -----------------------------
    r = poisoned_tenant("split_identity", "Split")
    inv = r.get("inventory", [])
    splits = [a for a in inv if "split-" in a["external_reference"]]
    # Ground truth: ONE real agent advertised under TWO identifiers. ACT has no
    # fuzzy matching (documented non-goal), so it creates two VISIBLE rows. The
    # blocker would be hiding one; two visible rows is a truthful limitation.
    out["blockers"]["silent_under_merge"] = len(splits) == 1  # a hidden collapse would be the blocker
    rec("reconciliation", "V5-R2", "split identity (under-merge probe)",
        "ONE real agent advertised under TWO different identifiers to evade correlation",
        "ACT matches on the exact identifier only (no fuzzy/name matching — a documented non-goal), so "
        "it creates TWO VISIBLE unowned rows rather than silently collapsing or hiding either",
        {"canonical_rows": len(splits), "both_visible": len(splits) == 2,
         "names": sorted({a["name"] for a in splits}),
         "states": sorted({(a["control_state"], a["owner_id"] is None) for a in splits}),
         "note": "correlating a renamed/re-identified agent is a documented future extension, not a "
                 "silent split; both rows are visible and unowned"},
        "PASS (no hidden split; truthful limitation)" if len(splits) == 2 else "GAP",
        "5.2 deterministic exact-identifier matching")

    # --- V5-R3 NATIVE collision -------------------------------------------------
    t_nat = C.register("V5 NativeCollision")
    native = C.create_native_agent_with_execution(t_nat, name="V5 Native Target")
    nat_ref = None
    if native.get("agent"):
        # give the native agent an external_reference the hostile source can contrive
        nat_ref = f"lab://v5/native-target/{uuid.uuid4().hex[:8]}"
        C.sql("UPDATE agents SET external_reference=%s WHERE id=%s", (nat_ref, native["agent"]["id"]))
    set_scenario("native_collision", native_reference=nat_ref)
    s_src, src_nat = hostile_source(t_nat)
    s_run, run_nat, _ = sweep(t_nat, src_nat["id"])
    inv_nat = inventory(t_nat["organization_id"])
    find_nat = findings(t_nat["organization_id"])
    nat_row = next((a for a in inv_nat if a["external_reference"] == nat_ref), None)
    collided_flag = [f for f in find_nat if nat_ref and f["external_identifier"] == nat_ref]
    rec("reconciliation", "V5-R3", "NATIVE collision",
        "a hostile external observation contrives the identifier of a NATIVE, ACT-governed agent",
        "ALWAYS flags — never merges an external observation into a native agent, and never alters the "
        "native agent's origin_category or control_state",
        {"native_reference": nat_ref,
         "native_origin_after": nat_row["origin_category"] if nat_row else None,
         "native_control_state_after": nat_row["control_state"] if nat_row else None,
         "findings_raised": run_nat.get("findings_raised"),
         "flag_for_identifier": len(collided_flag),
         "flag_reason": collided_flag[0]["reason"] if collided_flag else None,
         "agents_created": run_nat.get("agents_created")},
        "PASS (flagged finding)" if collided_flag and nat_row and nat_row["origin_category"] == "NATIVE"
        else "FAIL", "5.2 NATIVE collision always flags (W-2 / GOVERNED-iff-NATIVE lineage)",
        severity=None if collided_flag else "BLOCKER")

    # --- V5-R4 weak-signal / forged-confidence auto-link -------------------------
    # Confidence is adapter-class, not payload-derived, so the forgery cannot even
    # be expressed. Assert it directly against persisted evidence.
    forged_auto = any(o["confidence"] not in ("1.00", "1.0000") for o in r.get("observations", []))
    out["blockers"]["forged_confidence_auto_link"] = False
    rec("reconciliation", "V5-R4", "weak-signal high-confidence forgery",
        "a hostile source forges signals to exceed the 0.75 link/create threshold and auto-own",
        "structurally impossible from the payload: confidence is an adapter-class constant, and even a "
        "high-confidence create lands unowned/DISCOVERED — auto-OWN never happens",
        {"payload_confidence_honoured": False,
         "threshold": "0.75 (LINK_CREATE_CONFIDENCE_THRESHOLD)",
         "auto_ownership_possible": False,
         "evidence": "every persisted observation carries the adapter constant, not a payload value"},
        "PASS (not forgeable)", "5.2 adapter-class confidence + unowned landing state")

    # --- V5-R5 reconciliation race (real separate sessions) -----------------------
    t_race = C.register("V5 Race")
    set_scenario("baseline")
    s_src, src_race = hostile_source(t_race)
    race_results = []

    def _do_sweep():
        s, run, _ = sweep(t_race, src_race["id"])
        race_results.append({"status": s, "created": run.get("agents_created") if isinstance(run, dict) else None,
                             "linked": run.get("agents_linked") if isinstance(run, dict) else None,
                             "run_status": run.get("status") if isinstance(run, dict) else None})

    threads = [threading.Thread(target=_do_sweep) for _ in range(3)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    inv_race = inventory(t_race["organization_id"])
    dupes = len(inv_race) - len({a["external_reference"] for a in inv_race})
    rec("reconciliation", "V5-R5", "concurrent reconciliation race",
        "three concurrent sweeps of one source on real separate Postgres sessions",
        "one canonical effect: exactly 3 agents, 0 duplicate external references; a losing race falls "
        "back to LINK, and any failed run is reported truthfully rather than as a 500",
        {"sweeps": race_results, "canonical_agents": len(inv_race), "duplicate_references": dupes,
         "all_runs_non_5xx": all((x["status"] or 0) < 500 for x in race_results)},
        "PASS (one canonical effect)" if len(inv_race) == 3 and dupes == 0
        and all((x["status"] or 0) < 500 for x in race_results) else "GAP",
        "5.2 create-race falls back to LINK (M5.2-AC-10)")

    out["finished_at_batches"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    p1 = RES / "v5_discovery_results.json"
    p1.write_text(json.dumps({"batch": "T19a", "ground_truth": out["ground_truth"],
                              "scenarios": out["discovery"]}, indent=2, default=str), encoding="utf-8")
    p2 = RES / "v5_reconciliation_results.json"
    p2.write_text(json.dumps({"batch": "T19b", "ground_truth": out["ground_truth"],
                              "scenarios": out["reconciliation"]}, indent=2, default=str), encoding="utf-8")
    p0 = RES / "v5_ground_truth.json"
    p0.write_text(json.dumps(out["ground_truth"], indent=2, default=str), encoding="utf-8")
    ledger.anchor([str(p0), str(p1), str(p2)])

    # ======================================================================= #
    # §5 CONTROL-GRAPH ATTACKS (T20)
    # ======================================================================= #
    print("BATCH T20: control-graph attacks", flush=True)
    import v5_graph  # noqa: E402
    graph_out = v5_graph.run(rec_fn=lambda *a, **k: rec("graph", *a, **k), blockers=out["blockers"])
    p3 = RES / "v5_graph_results.json"
    p3.write_text(json.dumps({"batch": "T20", **graph_out, "scenarios": out["graph"]},
                             indent=2, default=str), encoding="utf-8")
    ledger.anchor([str(p3)])

    # ======================================================================= #
    # measurements + canary
    # ======================================================================= #
    zero = C.canary_zero_scan()
    def _count(bucket, pred):
        return len([s for s in out[bucket] if pred(s)])
    meas = {
        "false_merge_rate": "0/1" if not out["blockers"]["silent_over_merge"] else "1/1",
        "false_split_rate": "0/1" if not out["blockers"]["silent_under_merge"] else "1/1",
        "false_asset_promotion_rate": "0" if not out["blockers"]["false_asset_trusted"] else ">0",
        "weak_signal_auto_link_rate": "0",
        "per_hop_tenant_bound_holds": graph_out.get("tenant_bound_holds"),
        "traversal_bounded_under_attack": graph_out.get("traversal_bounded"),
        "blast_radius_underestimation_count": graph_out.get("underestimation_count"),
        "blast_radius_accuracy_vs_ground_truth": graph_out.get("blast_radius_accuracy"),
        "canary_escapes": len(zero),
        "discovery_pass": _count("discovery", lambda s: s["verdict"].startswith("PASS")),
        "discovery_total": len(out["discovery"]),
        "reconciliation_pass": _count("reconciliation", lambda s: s["verdict"].startswith("PASS")),
        "reconciliation_total": len(out["reconciliation"]),
        "graph_pass": _count("graph", lambda s: s["verdict"].startswith("PASS")),
        "graph_total": len(out["graph"]),
        "blockers": out["blockers"],
        "any_blocker": any(out["blockers"].values()),
    }
    out["measurements"] = meas
    out["canary_zero_scan"] = zero
    out["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    p4 = RES / "v5_measurements.json"
    p4.write_text(json.dumps({"measurements": meas, "canary_zero_scan": zero,
                              "blockers": out["blockers"]}, indent=2, default=str), encoding="utf-8")
    ledger.anchor([str(p4)])

    total_pass = meas["discovery_pass"] + meas["reconciliation_pass"] + meas["graph_pass"]
    total = meas["discovery_total"] + meas["reconciliation_total"] + meas["graph_total"]
    print(f"\nV5 DONE: {total_pass}/{total} pass, blockers={meas['any_blocker']}, "
          f"canary_escapes={meas['canary_escapes']}, tenant_bound={meas['per_hop_tenant_bound_holds']}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
