# THREAT_DETECTION_RESULTS — V6 (T16/T21): what fires, and what does not

Raw: [`evidence/v6_detection_results.json`](evidence/v6_detection_results.json). Fired 2026-09-23.
**2 pass, 2 recorded GAPs, 0 failures.** Detection is reported entirely separately from containment,
the V3 discipline: ACT may contain without detecting, and here it does.

| # | scenario | observed | verdict |
|---|---|---|---|
| V6-D1 | **governance denial spike** — 12 out-of-scope capability calls, then evaluate | all 12 denied `403`; **0 findings, 0 rules fired** | **GAP (not detected)** |
| V6-D2 | **prompt-injection detection** | no rule classifies injection | **GAP (not detected — documented, confirmed)** |
| V6-D3 | **shipped detection surface** | six deterministic rules enumerated from the product | **PASS (surface recorded)** |
| V6-D4 | **signals are not enforcement** | after findings exist, the agent's granted call still returns `200`; lifecycle unchanged | **PASS (detection does not enforce)** |

## The shipped surface

Six deterministic, explainable rules over M4 signals — no ML:

`behavioral_anomaly_threat` · `flagged_credential_used` · `governance_denial_spike` ·
`repeated_tool_egress_denial` · `tool_schema_validation_failure` · `unapproved_mcp_tool_invoked`

## The V6-D1 gap, located precisely

The `governance_denial_spike` rule **exists** and its threshold is 3, yet 12 denials produced nothing.
That is not a threshold or timing artefact — it is structural, and worth stating exactly:

```
governance_denial_count =
    SELECT count(runtime_governance_decisions.id)
      JOIN agent_executions ON agent_executions.id = runtime_governance_decisions.execution_id
     WHERE agent_executions.agent_id = <this agent>
```

The rule counts governance STOP/DENY decisions **on the agent's executions**. A gateway-enforced
**external** agent produces **no `agent_executions` rows at all** — its denials live in
`external_gateway_calls`. The join therefore returns 0 no matter how hard such an agent probes.

**So the detection plane is execution-centric.** Every one of the six rules keys off ACT-run execution
signals (`runtime_governance_decisions`, `tool_calls`, `behavioral_findings`), which means an external
gateway-enforced agent sits almost entirely outside detection even though it sits fully inside
containment and attribution. This is recorded as finding **F6-1**, and it is the detection analogue of
V4's **F-2** (the authority-chain surface likewise does not cover external agents, for the same
structural reason).

Worth being clear about what this is and is not: ACT does not *claim* to detect these and did not
report a false negative as clean — it simply has no signal wired from the gateway plane into the
threat plane. And the same probing that went undetected was still **contained** 12 times out of 12
(`403`), which is the whole point of keeping the two axes apart.

## The V6-D2 gap, already documented by the product

`rules.py` carries an explicit evidence-gap note, which V6 confirms live rather than rediscovers:

> "prompt/indirect-injection" and "cross-agent/delegation abuse" are named in the SRS's rule examples
> but are **NOT delivered here**. Neither has a deterministic signal in the current schema … Recorded
> here and in `docs/threat/rules.md` rather than fabricated.

This is G-1 / V3 D-1, now confirmed at the detection layer itself. Declining to ship a rule that would
have to guess is the correct engineering call; the gap is real and is recorded, not papered over.

## Signals are not enforcement

V6-D4 confirms the 5.5/5.6 discipline directly: with findings present, the agent's lifecycle was
unchanged and its granted capability still worked. A finding recommends; only a containment, through
an authority, acts. Nothing in the detection plane enforced anything on its own.
