"""LOCAL MODEL SUBSTRATE (V7) -- an OpenAI- and Anthropic-compatible inference
server, in-network, on port 8814.

**What this is, precisely.** A DETERMINISTIC inference server implementing the
two wire protocols the real SDKs speak:

    POST /v1/chat/completions   OpenAI shape, emits `tool_calls`
    POST /v1/messages           Anthropic Messages shape, emits `tool_use` blocks
    GET  /v1/models             model listing

It is **not a neural model**. It is the *substrate*, exactly as the V7 model
policy frames it: ACT governs framework behaviour -- tool calls, MCP use, A2A
handoffs, delegation, egress -- and this server makes real frameworks execute
those real code paths deterministically and reproducibly inside an egress-deny
network, with no API spend and no data leaving the lab.

**What it therefore does and does not prove.** It fully exercises the
framework's tool-calling loop, multi-agent handoff machinery and SDK wire
idioms, which is what ACT observes and governs. It does **not** exercise model
reasoning quality, and no claim in V7 depends on that. This limitation is
recorded in the V7 report rather than glossed.

Policy: it emits a tool call when the request advertises tools and the
conversation has not yet produced a tool result; otherwise it emits a final
text answer. That is enough for every framework to drive a genuine
plan -> tool -> observe -> answer cycle.

Nothing here executes code, reaches a non-lab destination, or imports ACT.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / "run"
PORT = 8814
MODEL_NAME = "actlab-local-deterministic-v1"
FINAL_TEXT = ("Task complete. The approved step was carried out through the governed boundary; "
              "no further action is required.")


def _log(rec):
    try:
        with (RUN / "local_model.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def _already_used_tool(messages) -> bool:
    """True once a tool result is present, so the next turn finalises."""
    for m in messages or []:
        role = m.get("role")
        if role == "tool":
            return True
        content = m.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    return True
    return False


def _first_tool_openai(tools):
    for t in tools or []:
        fn = t.get("function") or {}
        name = fn.get("name") or t.get("name")
        if name:
            return name, (fn.get("parameters") or {})
    return None, {}


def _first_tool_anthropic(tools):
    for t in tools or []:
        name = t.get("name")
        if name:
            return name, (t.get("input_schema") or {})
    return None, {}


def _args_for(schema):
    """A minimal, schema-shaped argument object (deterministic)."""
    out = {}
    for prop, spec in (schema.get("properties") or {}).items():
        typ = (spec or {}).get("type", "string")
        out[prop] = {"string": "lab", "integer": 1, "number": 1,
                     "boolean": True, "array": [], "object": {}}.get(typ, "lab")
    return out


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._json(200, {"object": "list", "data": [
                {"id": MODEL_NAME, "object": "model", "owned_by": "actlab"}]})
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": {"message": "bad json"}})
        path = self.path.split("?")[0].rstrip("/")
        _log({"path": path, "has_tools": bool(req.get("tools")),
              "messages": len(req.get("messages") or []), "ts": time.time()})

        if path.endswith("/chat/completions"):
            return self._openai(req)
        if path.endswith("/messages"):
            return self._anthropic(req)
        self._json(404, {"error": {"message": f"unsupported path {path}"}})

    # ---- OpenAI chat/completions (used by the OpenAI Agents SDK) ----------
    def _openai(self, req):
        tools = req.get("tools") or []
        messages = req.get("messages") or []
        name, schema = _first_tool_openai(tools)
        if name and not _already_used_tool(messages):
            msg = {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(_args_for(schema))}}]}
            finish = "tool_calls"
        else:
            msg = {"role": "assistant", "content": FINAL_TEXT}
            finish = "stop"
        self._json(200, {
            "id": f"chatcmpl-{uuid.uuid4().hex[:16]}", "object": "chat.completion",
            "created": int(time.time()), "model": req.get("model") or MODEL_NAME,
            "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": 16, "completion_tokens": 16, "total_tokens": 32}})

    # ---- Anthropic Messages (used by the Anthropic SDK) -------------------
    def _anthropic(self, req):
        tools = req.get("tools") or []
        messages = req.get("messages") or []
        name, schema = _first_tool_anthropic(tools)
        if name and not _already_used_tool(messages):
            content = [{"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:12]}",
                        "name": name, "input": _args_for(schema)}]
            stop = "tool_use"
        else:
            content = [{"type": "text", "text": FINAL_TEXT}]
            stop = "end_turn"
        self._json(200, {
            "id": f"msg_{uuid.uuid4().hex[:16]}", "type": "message", "role": "assistant",
            "model": req.get("model") or MODEL_NAME, "content": content,
            "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 16, "output_tokens": 16}})

    def log_message(self, *a):
        pass


def main() -> int:
    bind = os.environ.get("LAB_BIND", "127.0.0.1")
    srv = ThreadingHTTPServer((bind, PORT), Handler)
    RUN.mkdir(parents=True, exist_ok=True)
    (RUN / "local_model.ready").write_text(str(os.getpid()), encoding="utf-8")
    print(f"local model substrate listening on {bind}:{PORT} (model={MODEL_NAME})", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
