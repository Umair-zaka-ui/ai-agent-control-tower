"""STDIO-transport MCP-shaped server -- BUILT, NEVER LAUNCHED BY AN AGENT IN V2.

Represents the transport class V1 documented (design-level command execution
from configuration; 12+ CVEs, CISA KEV CVE-2026-42271). This file is the
inert artifact: it reads JSON-RPC lines on stdin and answers on stdout with
canned data. The *dangerous* pattern is the CONFIGURATION shape in
lab/mcp/stdio_config.json, where a host would run `command` + `args` as a
subprocess. In V2 nothing launches it; the harness only records that ACT's
inventory has no field for the transport at all (G-3).
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    for line in sys.stdin:
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        m = req.get("method")
        if m == "initialize":
            res = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "lab-stdio-mcp", "version": "0.1.0"}}
        elif m == "tools/list":
            res = {"tools": [{"name": "echo", "description": "Echo (lab, inert).", "inputSchema": {"type": "object"}}]}
        elif m == "tools/call":
            res = {"content": [{"type": "text", "text": "inert"}], "isError": False}
        else:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32601, "message": "method not found"}}) + "\n"); sys.stdout.flush(); continue
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req.get("id"), "result": res}) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
