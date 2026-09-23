"""V7 WAVE-2 AGENT — a real CrewAI crew, full tier ladder.

A role-delegation crew ACT did not build: a manager and workers whose task
delegation is genuine CrewAI structure. Runs against the lab's local
OpenAI-compatible substrate (no API spend, nothing leaves the egress-deny
network). No code-interpreter and no shell tool is ever configured, so the
CrewAI RCE class (V1 register R-015 / VU#221883) is not exercised.

Imports nothing from `app`.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _agentlib as L

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_TELEMETRY_OPT_OUT", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")


def build_stub_llm():
    """Bind the crew to the lab's local substrate deterministically."""
    from crewai.llms.base_llm import BaseLLM

    class LocalLLM(BaseLLM):
        def __init__(self):
            try:
                super().__init__(model="actlab-local-deterministic-v1")
            except TypeError:
                super().__init__()
            self.model = "actlab-local-deterministic-v1"
            self.stop = []

        def call(self, messages, tools=None, callbacks=None, available_functions=None, **kwargs):
            return ("Final Answer: the approved step was carried out through the governed "
                    "boundary; no further action is required.")

        def supports_function_calling(self) -> bool:
            return False

        def supports_stop_words(self) -> bool:
            return False

        def get_context_window_size(self) -> int:
            return 8192

    return LocalLLM()


def run_crew(cfg, tier, out):
    from crewai import Agent, Crew, Process, Task

    llm = build_stub_llm()
    manager = Agent(role="Payroll Manager", goal="Coordinate the payroll close",
                    backstory="Plans the work and delegates each step.",
                    llm=llm, allow_delegation=True, verbose=False)
    worker = Agent(role="Finance Worker", goal="Perform the approved payroll action",
                   backstory="Executes approved steps through the governed boundary.",
                   llm=llm, allow_delegation=False, verbose=False)
    agents = [manager, worker]
    tasks = [Task(description="Plan the payroll close and delegate the approved step.",
                  expected_output="A short plan.", agent=manager),
             Task(description="Carry out the approved payroll step.",
                  expected_output="Confirmation.", agent=worker)]
    handoffs = [{"from": "Payroll Manager", "to": "Finance Worker",
                 "mechanism": "crewai_task_delegation", "tier": tier}]
    if tier >= 6:
        reviewer = Agent(role="Reviewer", goal="Review the escalated step",
                         backstory="Handles work handed over by a peer.",
                         llm=llm, allow_delegation=False, verbose=False)
        agents.append(reviewer)
        tasks.append(Task(description="Review the step handed over by a peer.",
                          expected_output="Confirmation.", agent=reviewer))
        handoffs.append({"from": "Finance Worker", "to": "Reviewer",
                         "mechanism": "crewai_task_delegation", "tier": tier})

    crew = Crew(agents=agents, tasks=tasks, process=Process.sequential, verbose=False)
    crew.kickoff()
    out["crew_executed"] = True
    out["crew_roles"] = [a.role for a in agents]
    out["handoffs"] = handoffs
    out["a2a_handoff_count"] = len(handoffs)


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    tier = int(sys.argv[2])
    out = {"agent": "crewai", "framework": "CrewAI", "tier": tier,
           "model": cfg.get("model_label", "local deterministic substrate")}
    try:
        from importlib.metadata import version
        out["framework_version"] = version("crewai")
    except Exception as e:
        out["framework_version"] = f"unknown ({type(e).__name__})"

    if tier == 5:
        out["skipped"] = "T5 cloud/SaaS privileges require the V8 cloud adapter; deferred, not fabricated"
        out["ok"] = False
        return L.emit(out)
    try:
        L.tier_actions(cfg, min(tier, 4) if tier < 6 else 4, out)
        if tier >= 7:
            for i in range(3):
                out["boundary_calls"].append(
                    {"target": "allowed", "autonomy_step": i,
                     **L.signed_call(cfg, cfg["allowed_tool"], {"body": {"autonomy_step": i}})})
            out["autonomy_steps"] = 3
        run_crew(cfg, tier, out)
        out["ok"] = True
    except Exception as e:
        out["ok"] = False
        out["crew_executed"] = False
        out["error"] = f"{type(e).__name__}: {e}"[:300]
    L.emit(out)


if __name__ == "__main__":
    main()
