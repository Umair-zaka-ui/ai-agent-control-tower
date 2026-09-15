# Assurance, Evidence & Compliance

Phase 5.9 / M5.9. See also
[ADR-0022](../architecture/adr/0022-assurance-evidence-not-verdict.md).

ACT turns the evidence Phases M1–5.8 already produce — ownership, provenance,
governance decisions, findings, containment, cost, SLOs, traces, authority
chains — into control evaluations an auditor can use.

It produces **evidence and control mappings**. It does not produce a compliance
verdict, and it is built so that it cannot.

## Three results

| Result | Means | Example |
|---|---|---|
| `PASS` | Evidence exists, is fresh, and satisfies the control | An owner is recorded on the agent |
| `FAIL` | Evidence exists **and shows the control unmet** | `owner_id IS NULL` — conclusive |
| `INSUFFICIENT_EVIDENCE` | ACT **cannot tell either way** | Posture never ran; no executions; evidence stale |

**The line between the last two is the whole phase.** Both directions of
confusion are failures:

- Calling **absence a pass** is the false-green — a control reported green
  because nobody ever evaluated it. An auditor relying on that is misled about
  their own posture and finds out during a real audit.
- Calling a **conclusive negative "insufficient"** is the mirror error — it
  hides a real finding behind a shrug.

So: an agent with no owner **FAILs** (the row is the evidence, and it is
conclusive). An agent with no executions is **INSUFFICIENT_EVIDENCE** for
traceability (ACT cannot see what it does not run; calling it FAIL would invent
a violation).

## "Has anyone actually looked?"

Controls backed by Phase 5.5 read `posture_findings` — but they check the
`POSTURE_EVALUATED` **audit event first**. The findings table alone cannot tell
"evaluated and clean" apart from "never looked", because both produce zero open
findings. The immutable audit trail is the evidence that an evaluation happened.

No evaluation event → `INSUFFICIENT_EVIDENCE`, never `PASS`.

This is why a fresh installation shows a wall of amber. That is accurate, and
each result's `remediation` names the evaluation to run.

## Freshness

Evidence older than the freshness policy (default 30 days) downgrades a would-be
pass to `INSUFFICIENT_EVIDENCE` with `stale=true`. "We checked six weeks ago"
does not substantiate a claim about today.

This is not left to the evaluator's good behaviour. The schema enforces it:

```sql
CHECK (NOT (stale AND result = 'PASS'))   -- ck_assurance_eval_stale_never_passes
```

A stale pass is **unrepresentable**.

The practical consequence: without the `assurance.evaluate` scheduled sweep,
assurance decays toward "we cannot tell" rather than toward a stale green. That
is the correct direction, and it makes the scheduler handler operationally
important rather than optional.

## The controls

Twelve agent-scoped controls, each a pure function of its evidence, each naming
what it read — or the absence it found.

| Control | Evidence |
|---|---|
| `ACT.OWNERSHIP.ACCOUNTABLE_OWNER` | `agents.owner_id` (5.1) |
| `ACT.PROVENANCE.KNOWN_ORIGIN` | `agents.origin_category` (5.2) |
| `ACT.GOVERNANCE.POLICY_COVERAGE` | 4.3 policies via posture |
| `ACT.RELIABILITY.SLO_COVERAGE` | 4.7 SLOs via posture |
| `ACT.CREDENTIAL.LIFECYCLE` | `agent_api_keys` via posture |
| `ACT.SUPPLY_CHAIN.MCP_TRUST` | 5.4 MCP/dependency graph via posture |
| `ACT.TOOL.LEAST_PRIVILEGE` | `agent_tools` via posture |
| `ACT.MODEL.APPROVED` | version model config via posture |
| `ACT.RUNTIME.TRACEABLE` | `agent_executions` (4.1/4.2) |
| `ACT.COST.GOVERNED` | `budgets` (4.4) |
| `ACT.AUTHORITY.CHAIN_PROVABLE` | `control_graph_edges` (5.3) |
| `ACT.INCIDENT.RECONSTRUCTABLE` | 5.6 findings + containment + audit |

Deterministic and versioned (`ASSURANCE_CATALOG_VERSION`): same evidence in,
same result out, no ML (AST-asserted, the 4.5/5.5 precedent).

## Framework mappings

A mapping says:

> "The evidence ACT's control X produces is **relevant to** NIST AI RMF
> GOVERN-1.1."

It never says:

> ~~"Satisfying X means you comply with GOVERN-1.1."~~

Three frameworks ship, each carrying a `scope_note` that travels **with the
data** rather than living as a UI label: **NIST AI RMF 1.0**, **ISO/IEC
42001:2023**, **SOC 2 (2017, rev. 2022)**.

**Mappings are partial on purpose.** Every framework covers far more than ACT
observes — personnel security, physical controls, vendor management, training —
and those are **absent rather than stubbed**. An absent mapping honestly means
"ACT holds no evidence here"; a stub evaluating to PASS would be a fabrication.

Mappings live in versioned code (`app/assurance/frameworks.py`), not a table:
a claim about what ACT's evidence means for a published control is logic to
review in a diff, not data an operator can edit into an unsubstantiated claim.

## What does not exist

There is **no** `compliant`, `status`, `score`, `coverage`, `verdict`, `grade`
or `rating` — not as a column, not as a schema field, not as a response key.
A badge cannot be rendered from data that does not exist, and that absence is
asserted structurally rather than intended.

A percentage would additionally need a denominator ACT does not know: the full
control set in the customer's chosen audit scope. And it would compress
`INSUFFICIENT_EVIDENCE` into the same number as `PASS`, which is the one thing
this phase must never do.

What is reported instead: three counts, separately.

## Exceptions

A documented exception records that someone accepted a risk — who, why, and
when — and is audited (`ASSURANCE_EXCEPTION_RECORDED`).

**It does not change the result.** A FAIL with an exception still reads FAIL. An
exception that turned it green would be indistinguishable from the control
actually being met. It also survives re-evaluation, because a routine sweep must
not silently discard a human decision.

## Evidence export

`POST /api/v1/assurance/export` produces a tenant-scoped bundle of evaluations,
recorded with a digest in `assurance_evidence_bundles`.

**`assurance.export` is a distinct, stronger permission**, never implied by
`assurance.view` or `assurance.manage`. Reading a result and extracting a
portable bundle of an organization's control evidence are different acts: once
the bundle leaves ACT, ACT's tenant isolation and audit no longer protect it.
Every export is audited.

Bundles are **DSSE-signed** over the canonicalized document, reusing M4.11's own
`pae` encoding, signing provider and key service rather than reimplementing
them.

When signing is unavailable the bundle exports **unsigned and says so** —
`signed: false`, with `tamper_evidence` spelling it out in words. The asymmetry
with M4.11 is deliberate: M4.11 fails closed on an unsigned agent version,
because that is an integrity hole in something ACT executes. A bundle is a
read-only report, and an auditor who receives it unsigned-and-labelled is better
served than one who receives nothing. What must never happen is an unsigned
bundle presented as tamper-evident.

The bundle row stores the **digest and signature, never the payload** — the
payload is reconstructable from the evaluations it names, and a second stored
copy could drift from the rows it claims to summarize.

No secret, credential, token or key material appears in a bundle.

## The Assurance view

In the 5.8 command center. `INSUFFICIENT_EVIDENCE` gets **its own tile and its
own colour** — a dashboard showing only passes and failures would quietly
convert every unevaluated control into a green one. The server's disclaimer is
rendered verbatim, not paraphrased.
