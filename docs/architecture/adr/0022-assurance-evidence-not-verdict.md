# ADR-0022 — Assurance produces evidence and control mappings, never a compliance verdict; insufficient evidence is a first-class result

- **Status:** Accepted
- **Date:** 2026-09-16
- **Deciders:** Phase 5.9 / M5.9 (Milestone 5 — Universal Agent Control & Security Fabric)
- **Supersedes:** —
- **Relates to:** ADR-0019 (posture findings — this ADR reads them as evidence
  and inherits their INSUFFICIENT_DATA discipline), ADR-0021 (truthful
  enforcement modes — the same "never claim what you cannot substantiate" rule,
  applied to compliance instead of enforcement), ADR-0008 (telemetry as a
  derived plane — why no materialized assurance projection was built),
  ADR-0014 (key material — the signing provider an evidence bundle reuses).

## Context

Milestone 5 spent eight phases making ACT honest about what it knows and what
it can do. 5.9 is where that evidence becomes something an auditor, CISO or
regulator-facing team can use — and it is the phase with the strongest
commercial pull toward dishonesty.

Two temptations were live, and both are worth naming plainly.

**1. The false green.** A compliance dashboard is bought on the strength of how
much of it is green. The cheapest way to be greener is to treat absence of
evidence as evidence of absence: no findings against a control, so the control
passes. This is a *very* easy thing to build by accident — a naive
implementation reads `posture_findings` for a control, finds none, and reports
PASS. That reads identically whether the control is genuinely satisfied or
whether nobody ever ran an evaluation. An auditor relying on it would be
actively misled about their own posture, and would only discover it during an
actual audit.

**2. The verdict.** "You are 87% SOC 2 compliant" is the single most saleable
sentence a governance platform can render, and ACT is not entitled to say it.
Compliance depends on audit scope, compensating controls, an assessor's
judgement and often a regulator's — none of which ACT observes. A percentage
additionally requires a denominator ACT does not have: the full control set in
the customer's chosen scope, most of which (personnel security, physical
controls, vendor management, training) ACT cannot see at all.

## Decision

**1. Three results, and the line between the last two is load-bearing.**

| Result | Means |
|---|---|
| `PASS` | Evidence exists, is fresh, and satisfies the control |
| `FAIL` | Evidence exists **and shows the control unmet** |
| `INSUFFICIENT_EVIDENCE` | ACT **cannot determine either way** |

Both directions of confusion are failures. Calling absence a pass is the
false-green. But calling a *conclusive negative* "insufficient" is the mirror
error — an agent row with `owner_id IS NULL` is not missing evidence, the row
**is** the evidence and it is conclusive, so that control FAILs. Each control in
the catalog states which case it is and why.

Concretely: an agent with **no owner** FAILs (conclusive). An agent with **no
executions** is INSUFFICIENT_EVIDENCE for traceability (ACT cannot see what it
does not run; calling it FAIL would invent a violation).

**2. "Has anyone actually looked?" is asked first.**

Controls backed by Phase 5.5 read `posture_findings` — but check the
`POSTURE_EVALUATED` **audit event** before reading them. The immutable audit
trail is the evidence that an evaluation happened; the findings table alone
cannot distinguish "evaluated and clean" from "never looked". No evaluation
event → INSUFFICIENT_EVIDENCE, never PASS.

**3. Stale evidence is never a pass, and the database enforces it.**

A control that would otherwise PASS on evidence older than the freshness policy
returns INSUFFICIENT_EVIDENCE with `stale=True`. This is not left to the
evaluator's good behaviour:
`CHECK (NOT (stale AND result = 'PASS'))` makes a stale pass **unrepresentable**.

**4. No verdict, enforced by absence.**

There is no `compliant`, `status`, `score`, `coverage` or `verdict` column in
either table, field in any schema, or key in any response. A badge cannot be
rendered from data that does not exist. Framework reports return mapped controls
and their evaluations, plus a disclaimer that travels **with the data** rather
than living as a UI label someone can drop.

**5. Mappings are relevance claims, in versioned code.**

A mapping says *"the evidence ACT's control X produces is relevant to NIST AI
RMF GOVERN-1.1"* — never *"satisfying X means you comply with it"*. Mappings
live in `app/assurance/frameworks.py`, not a table, for the same reason 5.5's
rule catalog does: a claim about what ACT's evidence means for a published
control is logic that must be reviewed in a diff, not data an operator can
quietly edit into a claim ACT cannot substantiate.

Mappings are **partial on purpose**. Every framework covers far more than ACT
observes, and the uncovered controls are absent rather than stubbed — an absent
mapping honestly means "ACT holds no evidence here", while a stub evaluating to
PASS would be a fabrication.

**6. Exceptions document; they never flip a result.**

A FAIL with an accepted-risk exception still reads FAIL. The exception records
who accepted it and why, and is audited. An exception that turned a result green
would be indistinguishable from the control actually being met.

**7. Evidence bundles reuse M4.11's signing, and say when they are unsigned.**

A bundle is DSSE-signed over the canonicalized document using the same
`pae` encoding, signing provider and key service Phase M4.11 uses for version
attestations. The asymmetry with M4.11 is deliberate: M4.11 fails **closed**
when a published agent version cannot be signed, because an unsigned version is
an integrity hole in something ACT executes. A bundle is a read-only report, so
it exports **unsigned and explicitly labelled unsigned** — an auditor who gets
it with their own chain of custody is better served than one who gets nothing.
What must never happen is an unsigned bundle presented as tamper-evident, which
is why `signed` is returned explicitly rather than inferred from a null
signature.

## Consequences

**Good.**
- A green assurance result means "evidenced", never "we didn't check".
- The false-green is structurally unavailable: a stale PASS cannot be stored,
  and posture-backed controls cannot pass without an audit record proving an
  evaluation ran.
- A compliance badge cannot be rendered because there is no field to render.
- Every result names the evidence it read, or the absence it found, so an
  auditor can reconstruct the conclusion instead of trusting it.
- No new evidence source and no second audit system; assurance maps what
  M1–5.8 already produce.

**Costs, accepted.**
- **A fresh installation looks alarming.** Before any posture or threat
  evaluation has run, most controls report INSUFFICIENT_EVIDENCE — a wall of
  amber. That is accurate, and the alternative (defaulting to green) is the
  failure this ADR exists to prevent. The remediation text on each result says
  exactly which evaluation to run.
- **Assurance decays toward "cannot tell", not toward stale green.** Without a
  scheduled sweep, freshness eventually downgrades passing controls to
  INSUFFICIENT_EVIDENCE. That is the correct direction, but it means the
  `assurance.evaluate` scheduler handler is operationally important rather than
  optional.
- **Partial mappings can read as low coverage.** ACT maps roughly a dozen
  controls per framework out of hundreds. Stating that honestly costs a
  demo-friendly number; inventing the rest would cost the product's credibility
  the first time an auditor checked one.
- **No score means no single number for a board deck.** Three counts, reported
  separately, are less quotable than one percentage — deliberately.

## Alternatives rejected

- **Treat "no findings" as PASS.** Rejected: it is the false-green, and it is
  indistinguishable from "nobody ran an evaluation".
- **A coverage percentage or compliance score.** Rejected: requires a
  denominator ACT does not know, and compresses INSUFFICIENT_EVIDENCE into the
  same number as PASS.
- **A "compliant" status field, even one the UI chooses not to render.**
  Rejected: a field that exists will eventually be rendered. Absence is the
  control.
- **Control definitions and mappings in a database table.** Rejected: a claim
  about what evidence means for a published control belongs in reviewed code,
  not in rows an operator can edit.
- **Failing the export closed when signing is unavailable** (M4.11's rule).
  Rejected for a read-only report: unsigned-and-labelled serves an auditor;
  nothing serves nobody.
- **Inventing mappings for controls ACT cannot evidence.** Rejected outright —
  this is the regulatory-invention line the phase was told to stop at.
