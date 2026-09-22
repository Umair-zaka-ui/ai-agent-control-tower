"""V4 BATCH T6 — IDENTITY RED TEAM against the 5.7 external-identity boundary.

The model under attack (from `backend/app/bridge/identity.py`): an external agent
holds a secret it never transmits and signs each request over
`SCHEME\\nMETHOD\\nPATH\\nTIMESTAMP\\nNONCE\\nSHA256(body)`. ACT recomputes the HMAC
with the stored secret and compares in constant time. The grant names an `agents`
row and nothing else — no `users` row, no session, no role, no token any other ACT
surface accepts. Replay is stopped by a timestamp window plus a
`(grant_id, nonce)` unique constraint. Scope *bounds* reach; `AuthorizationGateway`
decides authority on every call. Revocation is immediate (every call re-reads the
grant; nothing is cached).

**P0 (§0):** if any path turns a scoped external identity into an internal
principal, or bypasses the gateway, STOP. This batch probes that line explicitly.

Expected behaviour for every scenario is written BEFORE execution (the `expected`
field) and is never redefined afterwards. Imports nothing from `app`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
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

SCHEME = "ACT-HMAC-SHA256"
GW_PATH = "/api/v1/bridge/capability"


def signed_headers(key_id, secret, *, method="POST", path=GW_PATH, body=b"",
                   ts=None, nonce=None, scheme=SCHEME, sig_override=None,
                   body_for_digest=None):
    ts = ts if ts is not None else str(int(time.time()))
    nonce = nonce if nonce is not None else uuid.uuid4().hex
    digest = hashlib.sha256(body_for_digest if body_for_digest is not None else body).hexdigest()
    to_sign = "\n".join([scheme, method.upper(), path, ts, nonce, digest])
    sig = hmac.new(secret.encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    if sig_override is not None:
        sig = sig_override
    h = {"Content-Type": "application/json", "X-ACT-Key-Id": key_id,
         "X-ACT-Timestamp": ts, "X-ACT-Nonce": nonce, "X-ACT-Signature": sig}
    return h


def send(headers, body=b"", path=GW_PATH, method="POST"):
    req = urllib.request.Request(C.BASE + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode() or "{}"
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw[:300]}
    except Exception as e:  # transport
        return 0, {"transport_error": str(e)[:200]}


def err_code(resp):
    if isinstance(resp, dict):
        return (resp.get("error") or {}).get("code")
    return None


def gateway_body(target_ref, params=None):
    return json.dumps({"capability": "http_tool.invoke", "target_ref": target_ref,
                       "params": params or {}}).encode()


def main() -> int:
    out = {"batch": "T6", "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "scenarios": [],
           "p0": {"external_to_internal_escalation": False, "gateway_bypass": False}}
    ctx = C.setup_external_agent()
    out["agent_id"] = ctx["agent"]["id"]
    out["tenant_a"] = ctx["A"]["organization_id"]
    key_id, secret = ctx["cfg"]["key_id"], ctx["cfg"]["secret"]
    granted, forbidden = ctx["granted_tool"], ctx["forbidden_transfer"]

    def rec(test_id, scenario, attack, expected, observed, verdict, authority, severity=None):
        row = {"test_id": test_id, "threat": "T6", "scenario": scenario, "attack": attack,
               "expected": expected, "observed": observed, "verdict": verdict,
               "authority": authority}
        if severity:
            row["severity"] = severity
        out["scenarios"].append(row)
        print(f"  T6 {test_id:<8} {scenario:<34} -> {verdict}", flush=True)

    # --- 1. baseline: a correctly signed, in-scope call succeeds (control) ------
    b = gateway_body(granted)
    s, r = send(signed_headers(key_id, secret, body=b), b)
    rec("T6-01", "valid signed call (control)", "correctly signed, in-scope",
        "200 ALLOWED — the control proving the rejections below are meaningful",
        {"status": s, "outcome": r.get("data", {}).get("outcome") if "data" in r else r.get("outcome")},
        "PASS (control)" if s == 200 else "FAIL (control did not succeed)", "grant scope + gateway")

    # --- 2. signed-request replay (nonce reuse) --------------------------------
    b = gateway_body(granted)
    h = signed_headers(key_id, secret, body=b)
    s1, _ = send(h, b)
    s2, r2 = send(h, b)
    rec("T6-02", "signed-request replay (nonce reuse)", "resend identical signed request",
        "second must be rejected — (grant_id,nonce) unique constraint",
        {"first": s1, "second": s2, "code": err_code(r2)},
        "PASS (contained)" if s2 in (401, 409) and s1 == 200 else "FAIL",
        "5.7 nonce replay defense")

    # --- 3. stale timestamp (outside signing window) ---------------------------
    b = gateway_body(granted)
    stale = str(int(time.time()) - 3600)
    s, r = send(signed_headers(key_id, secret, body=b, ts=stale), b)
    rec("T6-03", "stale timestamp", "timestamp an hour outside the signing window",
        "reject — outside the signing window",
        {"status": s, "code": err_code(r)}, "PASS (contained)" if s == 401 else "FAIL",
        "5.7 timestamp window")

    # --- 4. forged signature: wrong secret --------------------------------------
    b = gateway_body(granted)
    s, r = send(signed_headers(key_id, "wrong-secret-" + uuid.uuid4().hex, body=b), b)
    rec("T6-04", "forged signature (wrong key)", "sign with an attacker-chosen secret",
        "reject — HMAC mismatch (constant-time compare)",
        {"status": s, "code": err_code(r)}, "PASS (contained)" if s == 401 else "FAIL",
        "5.7 HMAC verification")

    # --- 5. stripped signature --------------------------------------------------
    b = gateway_body(granted)
    h = signed_headers(key_id, secret, body=b); h["X-ACT-Signature"] = ""
    s, r = send(h, b)
    rec("T6-05", "stripped signature", "empty X-ACT-Signature",
        "reject — no signature is not a valid signature",
        {"status": s, "code": err_code(r)}, "PASS (contained)" if s == 401 else "FAIL",
        "5.7 HMAC verification")

    # --- 6. algorithm / scheme confusion ----------------------------------------
    b = gateway_body(granted)
    s, r = send(signed_headers(key_id, secret, body=b, scheme="ACT-NONE"), b)
    rec("T6-06", "algorithm/scheme confusion", "sign with a different scheme line (e.g. 'none')",
        "reject — the scheme is part of the signing string; there is no algorithm negotiation",
        {"status": s, "code": err_code(r)}, "PASS (contained)" if s == 401 else "FAIL",
        "5.7 fixed single scheme in the signing string")

    # --- 7. body tampering after signing (digest mismatch) -----------------------
    signed_body = gateway_body(granted)
    tampered = gateway_body(forbidden)
    h = signed_headers(key_id, secret, body_for_digest=signed_body)
    s, r = send(h, tampered)
    rec("T6-07", "body tampering after signing", "swap the body for a forbidden target after signing",
        "reject — the body digest is inside the signature",
        {"status": s, "code": err_code(r)}, "PASS (contained)" if s == 401 else "FAIL",
        "5.7 body digest binding")

    # --- 8. path / method tampering ---------------------------------------------
    b = gateway_body(granted)
    h = signed_headers(key_id, secret, body=b, path="/api/v1/bridge/other")
    s, r = send(h, b)
    rec("T6-08", "path tampering", "sign for one path, send to another",
        "reject — method and path are inside the signature",
        {"status": s, "code": err_code(r)}, "PASS (contained)" if s in (401, 404) else "FAIL",
        "5.7 method/path binding")

    # --- 9. unknown key id --------------------------------------------------------
    b = gateway_body(granted)
    s, r = send(signed_headers("act_" + uuid.uuid4().hex[:16], secret, body=b), b)
    rec("T6-09", "unknown key id", "present a key id ACT never issued",
        "reject — no grant resolves",
        {"status": s, "code": err_code(r)}, "PASS (contained)" if s == 401 else "FAIL",
        "5.7 grant lookup")

    # --- 10. expired grant ---------------------------------------------------------
    exp = C.issue_grant(ctx, label="v4 expired probe", target=granted, expires_in_seconds=-60)
    if exp.get("key_id"):
        b = gateway_body(granted)
        s, r = send(signed_headers(exp["key_id"], exp["secret"], body=b), b)
        # errors.py maps EXTERNAL_GRANT_EXPIRED -> 403 (a rejection, like 401)
        verdict = "PASS (contained)" if s in (401, 403) else "FAIL"
        obs = {"status": s, "code": err_code(r), "documented_mapping": "EXTERNAL_GRANT_EXPIRED -> 403"}
    else:
        verdict, obs = "PASS (contained at issue)", {"issue_rejected": exp.get("issue_status"),
                                                     "note": "ACT refused to issue an already-expired grant"}
    rec("T6-10", "expired grant", "present a grant past its expiry",
        "reject — expiry checked before HMAC", obs, verdict, "5.7 grant expiry")

    # --- 11. revoked grant ---------------------------------------------------------
    rv = C.issue_grant(ctx, label="v4 revoke probe", target=granted)
    C.revoke_grant(ctx, rv["grant_id"])
    b = gateway_body(granted)
    s, r = send(signed_headers(rv["key_id"], rv["secret"], body=b), b)
    rec("T6-11", "revoked grant", "act on a revoked grant",
        "reject immediately — every call re-reads the grant; nothing cached",
        {"status": s, "code": err_code(r), "documented_mapping": "EXTERNAL_GRANT_REVOKED -> 403"},
        "PASS (contained)" if s in (401, 403) else "FAIL",
        "5.7 revocation (uncached)")

    # --- 12. identity substitution (agent B's grant for agent A's target) ----------
    other = C.second_agent_grant(ctx)
    b = gateway_body(granted)  # granted belongs to agent A's scope
    s, r = send(signed_headers(other["key_id"], other["secret"], body=b), b)
    attributed = C.last_gateway_call_agent(ctx, other["agent_id"])
    rec("T6-12", "identity substitution", "agent B signs for a target scoped to agent A",
        "reject (outside B's scope); the call is attributed to B, never to A",
        {"status": s, "outcome": (r.get("data") or r).get("outcome") if isinstance(r, dict) else None,
         "attributed_to_agent": attributed, "is_agent_b": attributed == other["agent_id"]},
        "PASS (contained + correctly attributed)" if s == 403 and attributed == other["agent_id"] else "FAIL",
        "grant scope + per-grant attribution")

    # --- 13. P0: external -> internal identity escalation ---------------------------
    internal_probes = [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/delegations"),
        ("POST", "/api/v1/graph/trust-edges"),
        ("GET", "/api/v1/command-center/agents"),
        ("GET", "/api/v1/runtime/tools"),
    ]
    esc = []
    for method, path in internal_probes:
        body = b"{}" if method == "POST" else b""
        h = signed_headers(key_id, secret, method=method, path=path, body=body)
        s, r = send(h, body, path=path, method=method)
        esc.append({"method": method, "path": path, "status": s, "authenticated": s in (200, 201)})
    escalated = [e for e in esc if e["authenticated"]]
    out["p0"]["external_to_internal_escalation"] = bool(escalated)
    rec("T6-13", "P0: external -> internal escalation",
        "present the signed external identity at internal (user-principal) endpoints",
        "every internal endpoint must reject: the signed identity is accepted ONLY at the "
        "gateway capability endpoint and mints no session, role or internal principal",
        {"probes": esc, "any_authenticated": bool(escalated)},
        "PASS (no escalation path)" if not escalated else "FAIL — P0 ESCALATION",
        "5.7: grant names an agents row, never a users row", severity="P0" if escalated else None)

    # --- 14. gateway bypass attempt --------------------------------------------------
    # Try to reach a dispatch without the gateway deciding: unsigned + bearer-shaped.
    bypass = []
    for hdrs, label in (({"Content-Type": "application/json"}, "unsigned"),
                        ({"Content-Type": "application/json",
                          "Authorization": f"Bearer {secret}"}, "grant-secret-as-bearer"),
                        ({"Content-Type": "application/json",
                          "X-ACT-Key-Id": key_id}, "key-id-without-signature")):
        b2 = gateway_body(granted)
        s, r = send(hdrs, b2)
        bypass.append({"variant": label, "status": s, "accepted": s in (200, 201)})
    bypassed = [x for x in bypass if x["accepted"]]
    out["p0"]["gateway_bypass"] = bool(bypassed)
    rec("T6-14", "P0: gateway bypass", "invoke the capability without a valid signed identity",
        "reject — there is no unsigned path and the secret is not a bearer credential",
        {"variants": bypass, "any_accepted": bool(bypassed)},
        "PASS (no bypass)" if not bypassed else "FAIL — P0 BYPASS",
        "5.7 signed-request-only boundary", severity="P0" if bypassed else None)

    # --- 15. machine-identity collision ------------------------------------------------
    coll = C.colliding_identity_probe(ctx)
    rec("T6-15", "machine-identity collision",
        "two agents contrive the same name/identity strings",
        "ACT keys on the agent row + grant, not the advertised name; B never gains A's authority",
        coll, "PASS (distinguished)" if coll.get("b_cannot_use_a_authority") else "FAIL",
        "per-agent grant identity")

    # --- 16. weak-signal reconciliation --------------------------------------------------
    weak = C.weak_signal_reconciliation_probe(ctx)
    rec("T6-16", "weak-signal reconciliation",
        "a hostile discovery source forges a near-identical identity to force a merge",
        "must not auto-merge on weak signals — a distinct external_reference stays a distinct row",
        weak, "PASS (no auto-merge)" if weak.get("no_false_merge") else "GAP",
        "5.2 deterministic reconciliation + duplicate review")

    # --- 17. credential theft via config -------------------------------------------------
    theft = C.credential_theft_probe(ctx)
    rec("T6-17", "credential/token theft via config",
        "exfiltrate a canary credential found in an agent config",
        "the forbidden exfil capability is denied by grant scope; no canary reaches ACT's records",
        theft, "PASS (contained)" if theft.get("exfil_denied") else "FAIL",
        "grant scope + canary zero-scan")

    out["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    fails = [s for s in out["scenarios"] if s["verdict"].startswith("FAIL")]
    # identity-rejection rate = forged / replayed / expired / revoked / tampered
    # identity attempts ACT rejected, over those attempted (control T6-01 excluded).
    reject_tests = [s for s in out["scenarios"] if s["test_id"] in
                    ("T6-02", "T6-03", "T6-04", "T6-05", "T6-06", "T6-07",
                     "T6-08", "T6-09", "T6-10", "T6-11")]
    rejected = [s for s in reject_tests if s["verdict"].startswith("PASS")]
    out["summary"] = {
        "total": len(out["scenarios"]),
        "passes": len([s for s in out["scenarios"] if s["verdict"].startswith("PASS")]),
        "fails": len(fails),
        "identity_rejection_rate": f"{len(rejected)}/{len(reject_tests)}",
        "p0_triggered": out["p0"]["external_to_internal_escalation"] or out["p0"]["gateway_bypass"],
    }
    p = RES / "v4_identity_results.json"
    p.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    ledger.anchor([str(p)])
    print(f"\nT6 DONE: {out['summary']['passes']}/{out['summary']['total']} pass, "
          f"{out['summary']['fails']} fail, P0={out['summary']['p0_triggered']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
