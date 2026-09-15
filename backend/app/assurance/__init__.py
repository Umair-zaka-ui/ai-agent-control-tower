"""Phase 5.9 (M5.9) - Assurance, Evidence & Compliance.

A sibling package (not a child of ``app.posture`` / ``app.threat`` /
``app.bridge``). It turns the evidence Phases M1-5.8 already produce into
something an auditor can use, and it is defined as much by what it refuses to
produce as by what it does.

The four sentences that govern every module here:

  * **Absence is never a pass.** Every control returns PASS, FAIL, or
    ``INSUFFICIENT_EVIDENCE``, and the distinction between the last two is the
    point: FAIL means the evidence exists and shows the control unmet;
    INSUFFICIENT_EVIDENCE means ACT genuinely cannot tell. A compliance surface
    that reports "no findings" as "compliant" is the most dangerous false-green
    there is, and the database refuses to store a stale PASS at all
    (``ck_assurance_eval_stale_never_passes``).

  * **Evidence and mappings, never a verdict.** ACT says "this evidence is
    relevant to NIST AI RMF GOVERN-1.1"; it never says "you comply with it".
    There is no ``compliant`` field, no status, no score and no coverage
    percentage anywhere in this package — a percentage would need a denominator
    ACT does not know, and a verdict is a judgement only an accredited assessor
    can make. The absence is asserted structurally, not merely intended.

  * **It maps existing evidence; it creates none.** No new evidence source and
    no second audit system. The controls read ``agents``, ``posture_findings``,
    ``agent_executions``, ``budgets``, ``control_graph_edges``,
    ``threat_findings`` and the immutable audit trail. Where 5.5's posture rules
    already answer a question, the control reads their findings rather than
    re-deriving the rule.

  * **"Has anyone actually looked?" is a question with an answer.** Controls
    backed by posture first ask whether a posture evaluation ever ran, using the
    ``POSTURE_EVALUATED`` audit event as the evidence that it did. Findings alone
    cannot distinguish "evaluated and clean" from "never looked", and treating
    the second as the first would be the exact failure this package exists to
    prevent.

Export is a distinct, stronger permission (``assurance.export``): a bundle
leaves ACT, and past that point ACT's tenant isolation and audit no longer
protect it. Bundles are DSSE-signed via M4.11's own primitives where signing is
available, and explicitly labelled unsigned where it is not — never presented as
tamper-evident when they are not.
"""
