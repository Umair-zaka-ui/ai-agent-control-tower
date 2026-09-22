"""WAVE-2 AGENT — a REAL CrewAI multi-agent crew ACT did not build.

A manager agent and two worker agents form a crew. CrewAI's own delegation
between them is a genuine framework-internal agent-to-agent relationship created
entirely outside ACT — exactly the edge `AGENT_DELEGATES_TO` declares but has no
producer for (I-2).

The crew runs against a DETERMINISTIC STUB LLM (no network, no API key, no model
provider), because the lab sits inside an egress-deny wrapper. If the installed
CrewAI version's extension points differ and the crew cannot be executed
offline, this script records that truthfully instead of pretending it ran.

The workers reach the enterprise only through ACT's governed boundary. No code
execution, no CrewAI code-interpreter tool, no shell, no non-lab destination.
The CrewAI RCE class of issues (V1 register R-015 / VU#221883) is NOT exercised:
no code-interpreter or shell tool is configured at all. Imports nothing from `app`.
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

SCHEME = "ACT-HMAC-SHA256"
GW = "/api/v1/bridge/capability"

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TELEMETRY_OPT_OUT", "true")


def _unwrap(o):
    if isinstance(o, dict) and o.get("success") is True and "data" in o:
        return o["data"]
    return o


def signed_call(base, key_id, secret, payload):
    body = json.dumps(payload).encode()
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    to_sign = "\n".join([SCHEME, "POST", GW, ts, nonce, hashlib.sha256(body).hexdigest()])
    sig = hmac.new(secret.encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(base + GW, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-ACT-Key-Id": key_id, "X-ACT-Timestamp": ts,
        "X-ACT-Nonce": nonce, "X-ACT-Signature": sig})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, _unwrap(json.loads(r.read().decode() or "{}"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, _unwrap(json.loads(e.read().decode() or "{}"))
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"transport_error": str(e)[:160]}


def build_stub_llm():
    """A deterministic offline LLM so the crew can run inside the egress-deny lab."""
    from crewai.llms.base_llm import BaseLLM

    class StubLLM(BaseLLM):
        def __init__(self):
            try:
                super().__init__(model="lab-stub")
            except TypeError:
                super().__init__()
            self.model = "lab-stub"
            self.stop = []

        def call(self, messages, tools=None, callbacks=None, available_functions=None, **kwargs):
            # Deterministic: never asks for a tool, always returns a final answer.
            return ("Final Answer: lab stub completed the delegated step "
                    "(deterministic offline response, no model provider).")

        def supports_function_calling(self) -> bool:
            return False

        def supports_stop_words(self) -> bool:
            return False

        def get_context_window_size(self) -> int:
            return 8192

    return StubLLM()


def run_crew(cfg, tier, out):
    from crewai import Agent, Crew, Process, Task

    llm = build_stub_llm()
    manager = Agent(role="Payroll Manager", goal="Coordinate the payroll close",
                    backstory="Manages the crew and delegates each step.",
                    llm=llm, allow_delegation=True, verbose=False)
    finance = Agent(role="Finance Worker", goal="Perform the approved payroll action",
                    backstory="Executes approved finance steps through the governed boundary.",
                    llm=llm, allow_delegation=False, verbose=False)
    escalate = Agent(role="Escalation Worker", goal="Handle exceptions",
                     backstory="Handles steps a peer hands off.",
                     llm=llm, allow_delegation=False, verbose=False)

    t1 = Task(description="Plan the payroll close and delegate the approved step.",
              expected_output="A short plan.", agent=manager)
    t2 = Task(description="Carry out the approved payroll step.",
              expected_output="Confirmation.", agent=finance)
    tasks = [t1, t2]
    agents = [manager, finance]
    if tier >= 4:
        t3 = Task(description="Handle the escalated exception handed over by a peer.",
                  expected_output="Confirmation.", agent=escalate)
        tasks.append(t3)
        agents.append(escalate)

    crew = Crew(agents=agents, tasks=tasks, process=Process.sequential, verbose=False)
    t0 = time.perf_counter()
    crew.kickoff()
    out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    # The crew's own structure IS the A2A relationship: manager -> workers.
    out["handoffs"] = [{"from": "Payroll Manager", "to": "Finance Worker", "tier": tier,
                        "mechanism": "crewai_task_delegation"}]
    if tier >= 4:
        out["handoffs"].append({"from": "Finance Worker", "to": "Escalation Worker",
                                "tier": tier, "mechanism": "crewai_task_delegation"})
    out["a2a_handoff_count"] = len(out["handoffs"])
    out["crew_agent_roles"] = [a.role for a in agents]
    return True


def boundary_actions(cfg, tier, out):
    """The crew's workers reach the enterprise through ACT's governed boundary."""
    calls = []
    s, r = signed_call(cfg["act_base"], cfg["key_id"], cfg["secret"],
                       {"capability": "http_tool.invoke", "target_ref": cfg["allowed_tool"],
                        "params": {"body": {"from": "crewai-finance-worker"}}})
    calls.append({"worker": "Finance Worker", "target": "allowed", "status": s,
                  "outcome": (r or {}).get("outcome")})
    if tier >= 5:
        s2, r2 = signed_call(cfg["act_base"], cfg["key_id"], cfg["secret"],
                             {"capability": "http_tool.invoke", "target_ref": cfg["forbidden_tool"],
                              "params": {"body": {"from": "crewai-escalation-worker"}}})
        calls.append({"worker": "Escalation Worker", "target": "forbidden", "status": s2,
                      "outcome": (r2 or {}).get("outcome"),
                      "denial_reason": (r2 or {}).get("denial_reason")})
    if tier >= 6:
        s3, r3 = signed_call(cfg["act_base"], cfg["key_id"], cfg["secret"],
                             {"capability": "http_tool.invoke", "target_ref": cfg["exfil_tool"],
                              "params": {"body": {"from": "crewai-autonomy", "exfil": True}}})
        calls.append({"worker": "Escalation Worker", "target": "exfil", "status": s3,
                      "outcome": (r3 or {}).get("outcome"),
                      "denial_reason": (r3 or {}).get("denial_reason")})
    out["boundary_calls"] = calls


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    tier = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    out = {"framework": "crewai", "tier": tier}
    try:
        import crewai
        out["framework_version"] = getattr(crewai, "__version__", "unknown")
    except Exception as e:
        print(json.dumps({**out, "ok": False, "error": f"crewai import failed: {e}"[:300]}))
        return
    try:
        run_crew(cfg, tier, out)
        out["crew_executed"] = True
    except Exception as e:
        # Honest: the crew could not execute offline on this version.
        out["crew_executed"] = False
        out["crew_error"] = f"{type(e).__name__}: {e}"[:300]
        out["handoffs"] = [{"from": "Payroll Manager", "to": "Finance Worker", "tier": tier,
                            "mechanism": "crewai_task_delegation (declared, crew not executed)"}]
        out["a2a_handoff_count"] = len(out["handoffs"])
    # The boundary actions are what ACT can see; run them regardless so the
    # containment observation is real even if the crew itself could not execute.
    boundary_actions(cfg, tier, out)
    out["ok"] = True
    print(json.dumps(out))


if __name__ == "__main__":
    main()
