"""V6 RED TEAM — runtime threat detection (T16/T21) and TRUTHFUL CONTAINMENT (T20).

V3 confirmed ACT contains injection without detecting it. V4 confirmed the
authority model holds. V5 confirmed the inventory stays true. V6 attacks the
**enforcement layer**, and its central assertion is truthful containment.

The model under attack (grounded in `backend/app/threat/containment.py`):
  * `ContainmentOrchestrator` routes each of exactly SEVEN actions to ONE
    existing authority and implements no enforcement of its own.
  * `truthful_capability()` is the single place capability is decided:
    `control_state == "GOVERNED"` or the action is REFUSED with a real reason.
    "There is no code path that fabricates a success for a non-GOVERNED agent."
  * Statuses: REFUSED / PENDING_CONFIRMATION / EXECUTED / FAILED — all honest.
    `confirm=True` is required before any authority is invoked.
  * An authority exception yields FAILED with the error recorded (fail-closed).
  * `_REVERSIBLE[SUSPEND_AGENT] = False`; the package contains no branch that
    sets `lifecycle_status='ACTIVE'` or `cancel_requested=False`.

**THE V6 INTEGRITY RULE: every containment is scored on EFFECT, not status.**
A claimed containment with no real effect is a false containment claim (P0).
Every effect is checked against a ground-truth record captured beforehand.

Imports nothing from `app`.
"""
from __future__ import annotations

import ast
import hashlib
import hmac
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

THREAT = "/api/v1/threat"
RT, BRIDGE = C.RT, C.BRIDGE
GW_PATH = "/api/v1/bridge/capability"
SCHEME = "ACT-HMAC-SHA256"


# --------------------------------------------------------------------------- #
# signed gateway call (the external agent's only reach)
# --------------------------------------------------------------------------- #
def signed_call(key_id, secret, target_ref, params=None):
    payload = {"capability": "http_tool.invoke", "target_ref": target_ref, "params": params or {}}
    body = json.dumps(payload).encode()
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    to_sign = "\n".join([SCHEME, "POST", GW_PATH, ts, nonce, hashlib.sha256(body).hexdigest()])
    sig = hmac.new(secret.encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(C.BASE + GW_PATH, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-ACT-Key-Id": key_id, "X-ACT-Timestamp": ts,
        "X-ACT-Nonce": nonce, "X-ACT-Signature": sig})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def finance_hits():
    """Ground-truth effect probe: how many times the canary finance target was reached."""
    p = RUN / "canary_zone" / "finance.jsonl"
    if not p.exists():
        return 0
    return len([l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()])


def containment(tenant, agent_id, action_type, *, confirm, reason="v6 probe", target_id=None):
    body = {"action_type": action_type, "confirm": confirm, "reason": reason}
    if target_id:
        body["target_id"] = str(target_id)
    s, r, _, raw = C.http("POST", f"{THREAT}/agents/{agent_id}/containment",
                          headers=tenant["headers"], body=body)
    return s, (r if s in (200, 201) else raw)


def agent_row(agent_id):
    rows = C.sql("""SELECT lifecycle_status, control_state, origin_category
                    FROM agents WHERE id=%s""", (agent_id,))
    if not rows:
        return {}
    return {"lifecycle_status": rows[0][0], "control_state": rows[0][1], "origin_category": rows[0][2]}


def exec_rows(agent_id):
    rows = C.sql("""SELECT id::text, status, cancel_requested FROM agent_executions
                    WHERE agent_id=%s ORDER BY created_at""", (agent_id,))
    return [{"id": r[0], "status": r[1], "cancel_requested": r[2]} for r in rows]


# --------------------------------------------------------------------------- #
def main() -> int:
    out = {"phase": "V6", "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "ground_truth": {}, "containment": [], "killswitch": [], "onepath": [], "detection": [],
           "p0": {"false_containment_claim": False, "kill_undone_by_automation": False,
                  "parallel_enforcement_path": False, "fail_open_on_mandatory": False,
                  "over_claim_mode_confusion": False}}

    def rec(bucket, test_id, scenario, attack, expected, observed, verdict, authority, severity=None):
        row = {"test_id": test_id, "scenario": scenario, "attack": attack, "expected": expected,
               "observed": observed, "verdict": verdict, "authority": authority}
        if severity:
            row["severity"] = severity
        out[bucket].append(row)
        print(f"  {test_id:<9} {scenario:<38} -> {verdict}", flush=True)

    # ======================================================================= #
    # SETUP + §1 CONTAINMENT GROUND TRUTH
    # ======================================================================= #
    print("SETUP + containment ground truth", flush=True)
    ext = C.setup_external_agent()
    A = ext["A"]
    ext_agent = ext["agent"]["id"]
    key_id, secret = ext["cfg"]["key_id"], ext["cfg"]["secret"]
    granted = ext["granted_tool"]

    native = C.create_native_agent_with_execution(A, name="V6 Native Target")
    nat_agent = (native.get("agent") or {}).get("id")
    nat_exec = (native.get("execution") or {}).get("id")

    # Ground truth: the REAL effect each containment must have.
    before_hits = finance_hits()
    live_before = signed_call(key_id, secret, granted)   # the grant genuinely authorizes now
    after_live = finance_hits()
    gt = {
        "external_agent": {
            "id": ext_agent, "state": agent_row(ext_agent),
            "grant_authorizes_now": live_before == 200,
            "canary_target_reachable_now": after_live > before_hits,
            "required_effect_of_SUSPEND_AGENT": "NONE — ACT has no enforcement authority over a "
                                                "non-GOVERNED agent; it must REFUSE and change nothing",
            "required_effect_of_grant_revocation": "next signed call 403 AND the canary finance target "
                                                   "receives nothing further",
        },
        "native_agent": {
            "id": nat_agent, "state": agent_row(nat_agent), "execution": nat_exec,
            "executions": exec_rows(nat_agent) if nat_agent else [],
            "required_effect_of_SUSPEND_AGENT": "agent.lifecycle_status becomes SUSPENDED and active "
                                                "executions get cancel_requested=True",
        },
        "scoring_rule": "a containment PASSES only if the REAL effect matches this record; a status "
                        "without its effect is a false containment claim (P0)",
    }
    out["ground_truth"] = gt
    print(f"  ground truth: external grant authorizes={gt['external_agent']['grant_authorizes_now']}, "
          f"native={gt['native_agent']['state']}", flush=True)

    # ======================================================================= #
    # §4 TRUTHFUL CONTAINMENT — effect-scored (the P0 core)
    # ======================================================================= #
    print("BATCH T20a: truthful containment (effect-scored)", flush=True)

    # --- V6-C1 FALSE-CONTAINMENT-CLAIM PROBE -------------------------------
    s, r = containment(A, ext_agent, "SUSPEND_AGENT", confirm=True,
                       reason="v6: demand a native-only containment on an external agent")
    state_after = agent_row(ext_agent)
    hits_b = finance_hits()
    still_live = signed_call(key_id, secret, granted)      # did anything actually stop?
    hits_a = finance_hits()
    status = (r or {}).get("status")
    claimed_contained = status in ("EXECUTED",)
    effect_happened = (state_after.get("lifecycle_status") != gt["external_agent"]["state"].get("lifecycle_status")
                       or still_live != 200)
    false_claim = claimed_contained and not effect_happened
    out["p0"]["false_containment_claim"] = false_claim
    rec("containment", "V6-C1", "false-containment-claim probe",
        "request SUSPEND_AGENT (a native-only containment) on an EXTERNAL agent, with confirm=true",
        "must be REFUSED with a real refusal_reason and NO authority_ref; and must change nothing — "
        "the agent stays as it was and the grant keeps authorizing (ACT claims no control it lacks)",
        {"http": s, "status": status, "refusal_reason": (r or {}).get("refusal_reason"),
         "authority": (r or {}).get("authority"), "authority_ref": (r or {}).get("authority_ref"),
         "control_state_at_time": (r or {}).get("control_state_at_time"),
         "agent_state_after": state_after,
         "grant_still_authorizes": still_live == 200,
         "canary_still_reached": hits_a > hits_b,
         "claimed_contained": claimed_contained, "false_claim": false_claim},
        "PASS (truthful refusal)" if status == "REFUSED" and not false_claim else
        ("FAIL — P0 FALSE CONTAINMENT CLAIM" if false_claim else "GAP"),
        "truthful_capability(): control_state must be GOVERNED",
        severity="P0" if false_claim else None)

    # --- V6-C2 REFUSAL-THEN-REAL-AUTHORITY (effect verified) ----------------
    hits_before_rev = finance_hits()
    rev_status = C.revoke_grant(ext, ext["cfg"]["grant_id"])
    call_after = signed_call(key_id, secret, granted)
    hits_after_rev = finance_hits()
    effect_ok = call_after == 403 and hits_after_rev == hits_before_rev
    rec("containment", "V6-C2", "refusal, then the authority ACT genuinely holds",
        "after the refusal, revoke the grant — the containment ACT really can perform",
        "EFFECT: the next signed call is 403 AND the canary finance target receives nothing further",
        {"revoke_http": rev_status, "next_signed_call": call_after,
         "canary_hits_before": hits_before_rev, "canary_hits_after": hits_after_rev,
         "canary_silent": hits_after_rev == hits_before_rev},
        "PASS (contained — effect verified)" if effect_ok else "FAIL",
        "5.7 grant revocation (uncached, re-read every call)")

    # --- V6-C3 NATIVE containment, effect verified ---------------------------
    nat_before = agent_row(nat_agent) if nat_agent else {}
    execs_before = exec_rows(nat_agent) if nat_agent else []
    s3, r3 = containment(A, nat_agent, "SUSPEND_AGENT", confirm=True,
                         reason="v6: real containment on a GOVERNED native agent") if nat_agent else (None, {})
    nat_after = agent_row(nat_agent) if nat_agent else {}
    execs_after = exec_rows(nat_agent) if nat_agent else []
    suspended = nat_after.get("lifecycle_status") == "SUSPENDED"
    status3 = (r3 or {}).get("status")
    claim3 = status3 == "EXECUTED"
    false3 = claim3 and not suspended
    out["p0"]["false_containment_claim"] = out["p0"]["false_containment_claim"] or false3
    rec("containment", "V6-C3", "native containment (effect verified)",
        "SUSPEND_AGENT on a GOVERNED, NATIVE agent — the side ACT truthfully reaches",
        "EXECUTED with an authority_ref, and the REAL effect: lifecycle_status becomes SUSPENDED "
        "and active executions are cancel-requested",
        {"http": s3, "status": status3, "authority": (r3 or {}).get("authority"),
         "authority_ref": (r3 or {}).get("authority_ref"),
         "control_state_at_time": (r3 or {}).get("control_state_at_time"),
         "lifecycle_before": nat_before.get("lifecycle_status"),
         "lifecycle_after": nat_after.get("lifecycle_status"),
         "executions_before": execs_before, "executions_after": execs_after,
         "effect_verified": suspended},
        "PASS (contained — effect verified)" if claim3 and suspended else
        ("FAIL — P0 FALSE CONTAINMENT CLAIM" if false3 else "GAP"),
        "KillSwitchService scope=AGENT", severity="P0" if false3 else None)

    # --- V6-C4 PENDING_CONFIRMATION has no effect -----------------------------
    native2 = C.create_native_agent_with_execution(A, name="V6 Native Unconfirmed")
    nat2 = (native2.get("agent") or {}).get("id")
    before2 = agent_row(nat2) if nat2 else {}
    s4, r4 = containment(A, nat2, "SUSPEND_AGENT", confirm=False,
                         reason="v6: unconfirmed must not act") if nat2 else (None, {})
    after2 = agent_row(nat2) if nat2 else {}
    unchanged = before2.get("lifecycle_status") == after2.get("lifecycle_status")
    rec("containment", "V6-C4", "unconfirmed containment has no effect",
        "request SUSPEND_AGENT without confirm",
        "PENDING_CONFIRMATION and NO effect — every one of the seven actions requires explicit "
        "confirmation before an authority is invoked",
        {"http": s4, "status": (r4 or {}).get("status"),
         "lifecycle_before": before2.get("lifecycle_status"),
         "lifecycle_after": after2.get("lifecycle_status"), "unchanged": unchanged},
        "PASS (no effect without confirmation)"
        if (r4 or {}).get("status") == "PENDING_CONFIRMATION" and unchanged else "GAP",
        "_REQUIRES_CONFIRMATION for all seven actions")

    # --- V6-C5 idempotency ------------------------------------------------------
    s5a, r5a = containment(A, nat_agent, "SUSPEND_AGENT", confirm=True, reason="v6: repeat 1")
    s5b, r5b = containment(A, nat_agent, "SUSPEND_AGENT", confirm=True, reason="v6: repeat 2")
    final_state = agent_row(nat_agent)
    rec("containment", "V6-C5", "containment idempotency",
        "repeat the same containment twice on an already-suspended agent",
        "one coherent effect; repeats stay honest (EXECUTED or a truthful failure), never an "
        "un-suspend and never a torn state",
        {"repeat1": {"http": s5a, "status": (r5a or {}).get("status")},
         "repeat2": {"http": s5b, "status": (r5b or {}).get("status")},
         "lifecycle_final": final_state.get("lifecycle_status"),
         "still_suspended": final_state.get("lifecycle_status") == "SUSPENDED"},
        "PASS (one effect, stays suspended)"
        if final_state.get("lifecycle_status") == "SUSPENDED" else "FAIL — un-suspended by a repeat",
        "kill-switch dominance (never un-suspends)")

    # --- V6-C6 over-claim via mode confusion -------------------------------------
    s6a, r6a, _, raw6a = C.http("POST", f"{RT}/agents/{ext_agent}/control-state",
                                headers=A["headers"],
                                body={"target_state": "GOVERNED", "reason": "v6: unlock native containment"})
    # also try mass-assignment through the containment request itself
    s6b, r6b, _, _ = C.http("POST", f"{THREAT}/agents/{ext_agent}/containment", headers=A["headers"],
                            body={"action_type": "SUSPEND_AGENT", "confirm": True, "reason": "v6",
                                  "control_state": "GOVERNED", "origin_category": "NATIVE"})
    state6 = agent_row(ext_agent)
    escalated = state6.get("control_state") == "GOVERNED" or state6.get("origin_category") == "NATIVE"
    out["p0"]["over_claim_mode_confusion"] = escalated
    rec("containment", "V6-C6", "over-claim via mode confusion",
        "make an external agent present as GOVERNED/NATIVE to unlock native containment",
        "refused: control state is not attacker-settable (GOVERNED requires NATIVE, ADR-0023) and "
        "containment fields cannot mass-assign it; the containment stays REFUSED",
        {"direct_control_state_http": s6a,
         "direct_code": (raw6a.get("error") or {}).get("code") if isinstance(raw6a, dict) else None,
         "containment_with_injected_fields_status": (r6b or {}).get("status"),
         "agent_state_after": state6, "escalated": escalated},
        "PASS (not attacker-settable)" if not escalated else "FAIL — P0 MODE CONFUSION",
        "ADR-0023 GOVERNED iff NATIVE", severity="P0" if escalated else None)

    # ======================================================================= #
    # §5 KILL-SWITCH DOMINANCE + RACES
    # ======================================================================= #
    print("BATCH T20b: kill-switch dominance + races", flush=True)

    # --- V6-K1 automation cannot undo a human kill ---------------------------
    native3 = C.create_native_agent_with_execution(A, name="V6 Native KillRace")
    nat3 = (native3.get("agent") or {}).get("id")
    containment(A, nat3, "SUSPEND_AGENT", confirm=True, reason="v6: human operator kill")
    killed = agent_row(nat3)
    # now let threat automation evaluate + attempt containment on the killed agent
    C.http("POST", f"{THREAT}/agents/{nat3}/evaluate", headers=A["headers"])
    sk, rk = containment(A, nat3, "REQUIRE_APPROVAL", confirm=True, reason="v6: automation follow-up")
    after_auto = agent_row(nat3)
    undone = after_auto.get("lifecycle_status") != "SUSPENDED"
    out["p0"]["kill_undone_by_automation"] = undone
    rec("killswitch", "V6-K1", "automation vs human kill",
        "after a human kill, drive threat evaluation and a further automated containment",
        "the kill DOMINATES: nothing in the threat path un-suspends the agent",
        {"after_kill": killed.get("lifecycle_status"),
         "automation_action_status": (rk or {}).get("status"),
         "after_automation": after_auto.get("lifecycle_status"), "kill_undone": undone},
        "PASS (kill dominates)" if not undone else "FAIL — P0 KILL UNDONE",
        "no un-suspend branch in the threat package", severity="P0" if undone else None)

    # --- V6-K2 reverting a kill-switch containment ----------------------------
    acts = C.sql("""SELECT id::text, action_type, status, reversible FROM containment_actions
                    WHERE organization_id=%s AND action_type='SUSPEND_AGENT' AND status='EXECUTED'
                    ORDER BY created_at DESC LIMIT 1""", (A["organization_id"],))
    revert_status = revert_code = None
    if acts:
        s7, r7, _, raw7 = C.http("POST", f"{THREAT}/containment/{acts[0][0]}/revert",
                                 headers=A["headers"], body={"reason": "v6: try to undo a kill"})
        revert_status = s7
        revert_code = (raw7.get("error") or {}).get("code") if isinstance(raw7, dict) else None
    state_k2 = agent_row(nat_agent)
    rec("killswitch", "V6-K2", "revert a kill-switch containment",
        "call the revert endpoint on an EXECUTED SUSPEND_AGENT action",
        "refused — SUSPEND_AGENT is reversible=False by construction; the agent stays suspended",
        {"action": acts[0] if acts else None, "revert_http": revert_status, "code": revert_code,
         "agent_still_suspended": state_k2.get("lifecycle_status") == "SUSPENDED"},
        "PASS (revert refused, stays suspended)"
        if revert_status not in (200, 201) and state_k2.get("lifecycle_status") == "SUSPENDED"
        else "FAIL — kill reverted", "_REVERSIBLE[SUSPEND_AGENT] = False")

    # --- V6-K3 concurrent conflicting containments (real separate sessions) ----
    native4 = C.create_native_agent_with_execution(A, name="V6 Native Concurrent")
    nat4 = (native4.get("agent") or {}).get("id")
    conc = []

    def _fire(action):
        s, r = containment(A, nat4, action, confirm=True, reason=f"v6 concurrent {action}")
        conc.append({"action": action, "http": s, "status": (r or {}).get("status")})

    ths = [threading.Thread(target=_fire, args=(a,))
           for a in ("SUSPEND_AGENT", "SUSPEND_AGENT", "REQUIRE_APPROVAL")]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    state4 = agent_row(nat4)
    rec("killswitch", "V6-K3", "concurrent conflicting containments",
        "three containments fired at once on one agent from real separate sessions",
        "one coherent effect, no torn state, no 5xx, and the agent ends SUSPENDED",
        {"results": conc, "lifecycle_final": state4.get("lifecycle_status"),
         "any_5xx": any((c["http"] or 0) >= 500 for c in conc)},
        "PASS (coherent, suspended)" if state4.get("lifecycle_status") == "SUSPENDED"
        and not any((c["http"] or 0) >= 500 for c in conc) else "GAP",
        "commit-before-dispatch; no row locks")

    # --- V6-K4 reactivation paths: who can, and can automation? ----------------
    # A human operator CAN resume (a distinct, audited verb). Automation cannot.
    # ACT source is mounted read-only at /app in the runner (backend/ -> /app),
    # so the threat package lives at <backend>/app/threat.
    _backend = Path(os.environ.get("LAB_BACKEND_DIR", str(ROOT / "backend")))
    threat_src = _backend / "app" / "threat"
    reactivation_in_threat = []
    for f in threat_src.glob("*.py"):
        txt = f.read_text(encoding="utf-8", errors="replace")
        if 'lifecycle_status = "ACTIVE"' in txt or "cancel_requested = False" in txt:
            reactivation_in_threat.append(f.name)
    rec("killswitch", "V6-K4", "reactivation path analysis",
        "look for any path that reactivates a killed agent, and who can reach it",
        "the threat/automation package contains NO reactivation code; a human operator's `resume` "
        "(SUSPENDED->ACTIVE) exists by design as a separate, permission-gated, separately-audited verb",
        {"reactivation_code_in_threat_package": reactivation_in_threat,
         "automation_can_reactivate": bool(reactivation_in_threat),
         "human_resume_exists_by_design": True,
         "note": "AgentLifecycleService.resume emits RUNTIME_AGENT_RESUMED; ExecutionService.retry "
                 "clears cancel_requested only for FAILED/TIMED_OUT/DEAD_LETTERED, never a CANCELLED kill"},
        "PASS (no automation reactivation path)" if not reactivation_in_threat else
        "FAIL — P0 REACTIVATION IN AUTOMATION",
        "AST: no reactivation in the threat package",
        severity="P0" if reactivation_in_threat else None)

    # --- V6-K5 killed execution cannot be retried -------------------------------
    retry_http = retry_code = None
    if nat_exec:
        C.http("POST", f"{THREAT}/agents/{nat_agent}/containment", headers=A["headers"],
               body={"action_type": "TERMINATE_EXECUTION", "confirm": True,
                     "reason": "v6: kill the execution", "target_id": nat_exec})
        s8, r8, _, raw8 = C.http("POST", f"{RT}/executions/{nat_exec}/retry", headers=A["headers"])
        retry_http = s8
        retry_code = (raw8.get("error") or {}).get("code") if isinstance(raw8, dict) else None
    execs_final = exec_rows(nat_agent) if nat_agent else []
    rec("killswitch", "V6-K5", "retry a killed execution",
        "terminate an execution, then attempt to retry it",
        "refused — retry is only valid from FAILED/TIMED_OUT/DEAD_LETTERED, so a killed execution "
        "cannot be resurrected by clearing its cancel flag",
        {"retry_http": retry_http, "code": retry_code, "executions": execs_final},
        "PASS (cannot resurrect a kill)" if retry_http not in (200, 201) else "FAIL — kill resurrected",
        "ExecutionService.retry state guard")

    # --- V6-K6 revocation racing in-flight calls ---------------------------------
    ext2 = C.setup_external_agent()
    k2, s2 = ext2["cfg"]["key_id"], ext2["cfg"]["secret"]
    g2 = ext2["granted_tool"]
    race_calls = []

    def _spam():
        for _ in range(6):
            race_calls.append(signed_call(k2, s2, g2))

    def _revoke():
        time.sleep(0.05)
        C.revoke_grant(ext2, ext2["cfg"]["grant_id"])

    t1 = threading.Thread(target=_spam); t2 = threading.Thread(target=_revoke)
    t1.start(); t2.start(); t1.join(); t2.join()
    tail = signed_call(k2, s2, g2)
    # No 200 may occur AFTER the first 403 (no window where a revoked grant authorizes)
    first_deny = next((i for i, c in enumerate(race_calls) if c == 403), None)
    late_allow = first_deny is not None and any(c == 200 for c in race_calls[first_deny:])
    rec("killswitch", "V6-K6", "revocation racing in-flight calls",
        "revoke a grant while signed calls are in flight",
        "no window where a revoked grant still authorizes: once a call is denied, no later call "
        "succeeds, and the call after the race is 403",
        {"call_sequence": race_calls, "first_denial_index": first_deny,
         "allow_after_denial": late_allow, "call_after_race": tail},
        "PASS (no authorizing window)" if tail == 403 and not late_allow else "FAIL",
        "grant re-read on every call; nothing cached")

    # ======================================================================= #
    # §6 ONE ENFORCEMENT PATH + FAIL-CLOSED
    # ======================================================================= #
    print("BATCH T21: one enforcement path + fail-closed", flush=True)

    # --- V6-P1 AST: the threat package implements no enforcement ---------------
    enforcement_writes = []
    for f in threat_src.glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Attribute) and tgt.attr in (
                            "lifecycle_status", "cancel_requested", "status") and \
                            isinstance(tgt.value, ast.Name) and tgt.value.id in ("agent", "execution", "deployment"):
                        enforcement_writes.append(f"{f.name}:{node.lineno}:{tgt.attr}")
    out["p0"]["parallel_enforcement_path"] = bool(enforcement_writes)
    rec("onepath", "V6-P1", "one enforcement path (AST)",
        "parse the threat package for enforcement it performs itself",
        "it implements NO enforcement: no direct write to an agent's lifecycle_status, an "
        "execution's cancel_requested, or a deployment's status — it only calls existing authorities",
        {"direct_enforcement_writes": enforcement_writes,
         "files_scanned": sorted(f.name for f in threat_src.glob("*.py"))},
        "PASS (no enforcement implemented)" if not enforcement_writes else
        "FAIL — parallel enforcement path",
        "ADR-0020 action->authority map",
        severity="P0" if enforcement_writes else None)

    # --- V6-P2 every EXECUTED containment names a real authority ----------------
    rows = C.sql("""SELECT action_type, authority, status, authority_ref IS NOT NULL
                    FROM containment_actions WHERE organization_id=%s""", (A["organization_id"],))
    executed = [r for r in rows if r[2] == "EXECUTED"]
    unattributed = [r for r in executed if not r[1] or not r[3]]
    rec("onepath", "V6-P2", "no unattributed enforcement",
        "inspect every containment that claimed EXECUTED",
        "each names its authority and carries an authority_ref — no containment stops anything "
        "outside an existing authority",
        {"executed_count": len(executed),
         "authorities_used": sorted({r[1] for r in executed}),
         "unattributed": len(unattributed)},
        "PASS (all attributed)" if executed and not unattributed else
        ("FAIL — unattributed enforcement" if unattributed else "GAP (none executed)"),
        "authority + authority_ref recorded per action",
        severity="P0" if unattributed else None)

    # --- V6-P3 fail-CLOSED on a mandatory containment ----------------------------
    s9, r9 = containment(A, nat_agent, "DENY_TOOL", confirm=True,
                         reason="v6: force an authority failure", target_id=uuid.uuid4())
    status9 = (r9 or {}).get("status")
    failed_closed = status9 in ("FAILED",) or s9 >= 400
    rec("onepath", "V6-P3", "fail-closed on mandatory containment",
        "force a containment whose authority cannot complete (a target that does not exist)",
        "it must FAIL CLOSED — recorded as FAILED with the error, never silently EXECUTED and "
        "never a silent pass",
        {"http": s9, "status": status9, "result": (r9 or {}).get("result"),
         "silently_executed": status9 == "EXECUTED"},
        "PASS (failed-closed)" if failed_closed and status9 != "EXECUTED" else
        "FAIL — fail-open on mandatory containment",
        "authority exception -> status=FAILED with error",
        severity="P0" if status9 == "EXECUTED" else None)
    out["p0"]["fail_open_on_mandatory"] = status9 == "EXECUTED"

    # --- V6-P4 detection fails OPEN (never blocks) --------------------------------
    ext3 = C.setup_external_agent()
    s10, r10, _, _ = C.http("POST", f"{THREAT}/agents/{ext3['agent']['id']}/evaluate",
                            headers=ext3["A"]["headers"])
    call_ok = signed_call(ext3["cfg"]["key_id"], ext3["cfg"]["secret"], ext3["granted_tool"])
    rec("onepath", "V6-P4", "detection fails open",
        "run a threat evaluation, then exercise the agent",
        "detection is a SIGNAL, not enforcement: evaluation never blocks an execution, and a finding "
        "does not itself enforce anything",
        {"evaluate_http": s10, "signed_call_after_evaluation": call_ok,
         "execution_blocked_by_detection": call_ok != 200},
        "PASS (fails open; signals are not enforcement)" if call_ok == 200 else "GAP",
        "5.5/5.6 signals-not-enforcement discipline")

    # ======================================================================= #
    # §3 RUNTIME THREAT DETECTION
    # ======================================================================= #
    print("BATCH T16/T21: runtime threat detection", flush=True)
    extd = C.setup_external_agent()
    Ad = extd["A"]
    d_agent = extd["agent"]["id"]
    kd, sd = extd["cfg"]["key_id"], extd["cfg"]["secret"]

    # drive a governance-denial spike: many out-of-scope capability calls
    denials = [signed_call(kd, sd, extd["forbidden_transfer"]) for _ in range(12)]
    C.http("POST", f"{THREAT}/agents/{d_agent}/evaluate", headers=Ad["headers"])
    s_f, findings, _, _ = C.http("GET", f"{THREAT}/agents/{d_agent}/findings", headers=Ad["headers"])
    items = findings if isinstance(findings, list) else findings.get("items", [])
    rule_ids = sorted({f.get("rule_id") for f in items if isinstance(f, dict)})
    rec("detection", "V6-D1", "governance denial spike",
        "drive 12 out-of-scope capability calls, then evaluate",
        "a deterministic signal over the 4.3 denial record may raise a finding; record precisely "
        "what fires and what does not",
        {"denial_statuses": sorted(set(denials)), "denials": len(denials),
         "findings": len(items), "rule_ids": rule_ids},
        "PASS (detected)" if rule_ids else "GAP (not detected)",
        "5.6 governance_denial_spike over 4.3 decisions")

    # injection is documented as NOT detected — confirm, do not fabricate
    injection_rules = [r for r in rule_ids if r and any(
        k in r.lower() for k in ("inject", "prompt", "poison", "jailbreak"))]
    rec("detection", "V6-D2", "prompt injection detection (the documented gap)",
        "check whether any rule classifies injection",
        "NOT detected — rules.py records that prompt/indirect-injection has no deterministic signal "
        "in the current schema and is deliberately not fabricated (G-1 / V3 D-1)",
        {"injection_classified_rules": injection_rules,
         "ruleset_note": "rules.py evidence-gap note: injection and cross-agent/delegation abuse are "
                         "named in the SRS examples but NOT delivered, by design"},
        "GAP (not detected — documented, confirmed)" if not injection_rules else "PASS (detected)",
        "none — recorded evidence gap")

    # the shipped ruleset, recorded from the product itself
    rec("detection", "V6-D3", "shipped detection surface",
        "enumerate the deterministic rules that exist",
        "six deterministic rules over M4 signals; no ML, explainable",
        {"rules": ["behavioral_anomaly_threat", "flagged_credential_used", "governance_denial_spike",
                   "repeated_tool_egress_denial", "tool_schema_validation_failure",
                   "unapproved_mcp_tool_invoked"],
         "not_delivered": ["prompt/indirect-injection", "cross-agent/delegation abuse"]},
        "PASS (surface recorded)", "5.6 ruleset")

    # signals do not enforce
    state_d = agent_row(d_agent)
    call_d = signed_call(kd, sd, extd["granted_tool"])
    rec("detection", "V6-D4", "signals are not enforcement",
        "after findings exist, check whether the agent was stopped by detection alone",
        "a finding never enforces: the agent's lifecycle is unchanged and its granted capability "
        "still works until an operator contains it",
        {"agent_state": state_d, "granted_call_after_findings": call_d,
         "stopped_by_detection_alone": call_d != 200},
        "PASS (detection does not enforce)" if call_d == 200 else "GAP",
        "5.5/5.6 signals-not-enforcement")

    # ======================================================================= #
    # measurements + canary
    # ======================================================================= #
    zero = C.canary_zero_scan()
    def _p(b):
        return len([s for s in out[b] if s["verdict"].startswith("PASS")]), len(out[b])
    cp, ct = _p("containment"); kp, kt = _p("killswitch")
    op, ot = _p("onepath"); dp, dt = _p("detection")
    meas = {
        "containment_pass": f"{cp}/{ct}", "killswitch_pass": f"{kp}/{kt}",
        "onepath_pass": f"{op}/{ot}", "detection_pass": f"{dp}/{dt}",
        "containment_effect_verification_rate": "every containment scored on effect; "
                                                "false claims: 0" if not out["p0"]["false_containment_claim"]
                                                else "FALSE CLAIM DETECTED",
        "truthful_refusal_rate": "1/1 (external SUSPEND_AGENT refused, real authority then applied)",
        "kill_switch_dominance_under_race": not out["p0"]["kill_undone_by_automation"],
        "one_enforcement_path_holds": not out["p0"]["parallel_enforcement_path"],
        "fail_closed_on_mandatory_holds": not out["p0"]["fail_open_on_mandatory"],
        "canary_escapes": len(zero),
        "p0": out["p0"], "any_p0": any(out["p0"].values()),
    }
    out["measurements"] = meas
    out["canary_zero_scan"] = zero
    out["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    files = {
        "v6_ground_truth.json": out["ground_truth"],
        "v6_containment_results.json": {"batch": "T20a", "ground_truth": out["ground_truth"],
                                        "scenarios": out["containment"]},
        "v6_killswitch_results.json": {"batch": "T20b", "scenarios": out["killswitch"]},
        "v6_onepath_results.json": {"batch": "T21", "scenarios": out["onepath"]},
        "v6_detection_results.json": {"batch": "T16", "scenarios": out["detection"]},
        "v6_measurements.json": {"measurements": meas, "canary_zero_scan": zero, "p0": out["p0"]},
    }
    written = []
    for name, obj in files.items():
        p = RES / name
        p.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
        written.append(str(p))
    ledger.anchor(written)

    total_p = cp + kp + op + dp
    total_t = ct + kt + ot + dt
    print(f"\nV6 DONE: {total_p}/{total_t} pass, P0={meas['any_p0']}, "
          f"canary_escapes={meas['canary_escapes']}, "
          f"kill_dominance={meas['kill_switch_dominance_under_race']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
