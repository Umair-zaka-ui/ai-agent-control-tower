# ADR-0006 — Keep the governance decision path deterministic (no LLM)

- **Status:** Accepted *(retroactively recorded 2026-07-08; decision made in Phase 1)*
- **Deciders:** Platform engineering
- **Supersedes:** —

## Context

The Control Tower decides whether an AI agent may perform an attempted action. The
inputs are a `(resource, action, input_payload)` triple, the agent's permissions and
risk configuration, and the organisation's policies.

There is obvious temptation to use an LLM here. The payloads are natural language
and semi-structured JSON; policies are, conceptually, natural-language rules;
"is this action dangerous?" reads like a classification problem that a model would
do well at. Several competing products do exactly this.

Two constraints push the other way:

1. **The audit trail is the product.** An auditor will ask: *"On 3 March, why was
   this action blocked?"* The answer must be reproducible from stored data.
2. **The adversary is the agent itself.** A prompt-injected agent submits
   attacker-controlled text in `input_payload`. If that text reaches an LLM that
   decides the agent's fate, the attacker is talking directly to the judge.

## Options considered

### Option A — LLM classifies intent and recommends allow/block
- Pros: handles novel actions and fuzzy policies with no rule authoring. Demos well.
- Cons: **non-reproducible** — same input, different answer, especially across model
  versions. Cannot be replayed for audit. Adds a network dependency to the hot path
  (latency, availability, cost per decision). Above all: `input_payload` is
  attacker-controlled, so the decision path becomes **directly prompt-injectable**.
  The agent could argue for its own authorisation.

### Option B — Deterministic rules, LLM as an advisory signal fed into the score
- Pros: keeps determinism for the final call; LLM adds nuance to risk.
- Cons: if the signal changes the decision it must be persisted and versioned to stay
  replayable, and it is *still* injectable. If it does not change the decision, it is
  decoration. The audit story becomes "reproducible except for one non-deterministic
  input", which is not a story an auditor accepts.

### Option C — Fully deterministic: permissions → risk → policy → decision
- Pros: reproducible, replayable, explainable, fast, free, un-injectable. The decision
  is a pure function of data we already store.
- Cons: policies must be authored by humans. Novel dangerous actions are not caught
  unless a rule or risk heuristic covers them. Less impressive in a demo.

## Decision

We chose **Option C**. `process_agent_action` runs a fixed seven-step pipeline. No
LLM is consulted anywhere in it. `risk_engine.calculate_risk_breakdown` and
`decision_engine.make_decision` are pure functions.

Every decision persists its full derivation: `risk_score`, the risk breakdown
(`action_score`, `resource_score`, `modifiers`), `matched_policy`, `decision`, and
`decision_reason`. Given an `agent_actions` row and the policies in force at that
moment, the decision can be recomputed exactly.

Option A is rejected primarily on **security**, not reproducibility: routing
attacker-controlled text into the component that authorises the attacker is a
category error. Prompt injection stops being a content problem and becomes a
privilege-escalation problem.

## Consequences

### Positive
- **Replayable.** Any historical decision can be recomputed and defended.
- **Un-injectable.** `input_payload` is scored by pure functions; it never becomes an
  instruction. A fully compromised agent cannot argue itself into a permission.
- **Cheap and fast.** No per-decision inference cost, no external latency, no vendor
  availability in the hot path. The platform governs AI without depending on AI —
  a claim enterprise buyers check.
- Blocked actions are audited identically to allowed ones. Both are evidence.

### Negative / accepted cost
- **Policy authoring is a human burden.** Coverage is exactly as good as the rules
  written. A dangerous action nobody anticipated, within a granted permission and
  below the risk threshold, is allowed.
- Risk scoring is heuristic (`action_score` + `resource_score` + modifiers). It does
  not understand semantics. `delete` on `staging_scratch` and on `customers` score
  by configured resource weight, not by meaning.
- We will lose demos to competitors whose product "understands" the action.
- Novel attack patterns require a policy change, i.e. a human in the loop and a deploy.

### Residual risk
The residual risk is **the blast radius of a legitimately-granted permission**. If an
agent holds `database:delete` and is prompt-injected, the pipeline correctly allows
the delete — the grant was the vulnerability, not the pipeline.

The mitigation is architectural — least privilege plus human approval on high-risk
actions — not detective. Today that means: the permission grant, the org's policies,
and two global risk thresholds (`≤40` allow, `41–80` approval, `>80` block).

**The per-agent columns intended to bound this — `max_allowed_risk`,
`human_approval_required`, `auto_suspend_threshold` — are persisted but read by no
engine.** They are dead configuration. An operator who sets
`human_approval_required=true` on a high-blast-radius agent gets no additional
protection, which is precisely the situation this ADR's reasoning assumes is
covered. Closing that gap is the highest-value follow-up to this decision.

## Revisit when

- An LLM is wanted **outside** the decision path — summarising audit trails, drafting
  policies for human review, explaining a decision after the fact. All are safe:
  none authorises anything, and none is fed back into the pipeline. This ADR does not
  forbid them.
- A customer demands semantic risk assessment. The correct shape is Option B *with*
  the signal persisted and model-versioned — and even then, only as an input to
  `PENDING_APPROVAL`, never to `ALLOW`. An LLM may escalate to a human; it must never
  be able to authorise.
