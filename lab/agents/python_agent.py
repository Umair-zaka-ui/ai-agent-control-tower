"""WAVE-1 AGENT #1 -- Python reference external agent (Tier ceiling: T2).

A REAL agent outside ACT: imports nothing from `app`, holds no database
handle, speaks to ACT only over HTTP with ACT-HMAC-SHA256 signed requests
(the 5.7/5.10 protocol). Its "identity" is a scoped ACT grant it is handed on
the command line; its config file carries a canary token that must never
appear in ACT's records.

Tiers exercised: T0 (read its own config / registry), T1 (read-only tool: the
canary object store listing), T2 (ONE controlled write tool: the governed
`http_tool.invoke` capability routed THROUGH ACT's gateway). Nothing else.
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
    # ACT's success envelope is {success, data, meta}; errors are {success:false, error:{...}}
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
        return e.code, _unwrap(json.loads(e.read().decode() or "{}"))


def plain_get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, json.loads(r.read().decode())


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    base, key_id, secret = cfg["act_base"], cfg.get("key_id", ""), cfg.get("secret", "")
    out = {"agent": "python", "tier": cfg.get("tier", 2), "canary_present_in_config": cfg["canary"][:13] == "ACTLAB-CANARY"}
    # T0/T1: read-only lab data (loopback only)
    out["t1_object_store"] = plain_get(cfg["object_store"] + "/objects")[0]
    if cfg.get("tier", 2) >= 2 and key_id:
        # T2: the one controlled write -- through ACT's gateway
        out["t2_allowed"] = signed_call(base, "/api/v1/bridge/capability", key_id, secret,
                                        {"capability": "http_tool.invoke", "target_ref": cfg["allowed_tool"],
                                         "params": {"body": {"from": "lab-python-agent"}}})
        out["t2_forbidden"] = signed_call(base, "/api/v1/bridge/capability", key_id, secret,
                                          {"capability": "http_tool.invoke", "target_ref": cfg["forbidden_tool"]})
    print(json.dumps(out))


if __name__ == "__main__":
    main()
