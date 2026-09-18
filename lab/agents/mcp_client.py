"""WAVE-1 AGENT #3 -- MCP client agent (Tier ceiling: T2).

Exercises the MCP zone the way an MCP host would: `initialize`, `tools/list`,
`tools/call` against the TRUSTED server only (T1: read-only tool). It never
launches the STDIO server, never contacts the rug-pull server, and never
poisons anything. Its T2 write is, as for the other agents, the single
governed capability through ACT's gateway. Imports nothing from ACT.
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


def rpc(url, token, method, params=None, rid=1):
    body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}).encode()
    req = urllib.request.Request(url + "/mcp", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


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


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = {"agent": "mcp_client", "tier": cfg.get("tier", 2), "canary_present_in_config": cfg["canary"][:13] == "ACTLAB-CANARY"}
    init = rpc(cfg["mcp_trusted"], cfg["mcp_token"], "initialize", {"protocolVersion": "2025-11-25", "clientInfo": {"name": "lab-mcp-client", "version": "0.1"}})
    out["t1_initialize"] = init.get("result", {}).get("serverInfo")
    tools = rpc(cfg["mcp_trusted"], cfg["mcp_token"], "tools/list", rid=2)
    out["t1_tools"] = [t["name"] for t in tools.get("result", {}).get("tools", [])]
    call = rpc(cfg["mcp_trusted"], cfg["mcp_token"], "tools/call", {"name": "payroll_read", "arguments": {"employee_id": "1"}}, rid=3)
    out["t1_call_ok"] = call.get("result", {}).get("isError") is False
    if cfg.get("tier", 2) >= 2 and cfg.get("key_id"):
        out["t2_allowed"] = signed_call(cfg["act_base"], "/api/v1/bridge/capability", cfg["key_id"], cfg["secret"],
                                        {"capability": "http_tool.invoke", "target_ref": cfg["allowed_tool"],
                                         "params": {"body": {"from": "lab-mcp-client"}}})
    print(json.dumps(out))


if __name__ == "__main__":
    main()
