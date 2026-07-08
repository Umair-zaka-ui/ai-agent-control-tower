# ADR-0001 — Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** Platform engineering
- **Supersedes:** —

## Context

The platform has grown to 24 tables, three API surfaces, a governance pipeline
with four engines, and two coexisting authentication systems. Phase 4 is underway
and the identity layer is being rebuilt beside the legacy one.

Several decisions in the codebase are non-obvious and, read cold, look like
mistakes:

- Why does `/auth/login` still exist next to `/api/v1/auth/login`?
- Why is the password policy defined in `identity/security/` rather than in the
  `PasswordService` that owns it?
- Why does a revoked session's access token still work?
- Why is there no LLM anywhere near the decision engine?

Each has a real answer. None of them is written down anywhere. As the team and
the external audience grow — enterprise buyers, auditors, investors — "nobody
remembers why" becomes an actual liability: it stalls diligence, invites
re-litigation of settled questions, and makes deliberate design look accidental.

## Options considered

### Option A — Keep decisions in commit messages and PR descriptions
- Pros: zero new process; already happening.
- Cons: not discoverable; a decision spans many commits; PR threads rot and are
  invisible to anyone outside GitHub; cannot be handed to an auditor.

### Option B — A single `ARCHITECTURE.md` narrative
- Pros: one file, easy to read end-to-end.
- Cons: no per-decision history. Edits overwrite the reasoning trail — you can see
  the current answer but never *what changed and why*. Merge conflicts on a hot file.

### Option C — Lightweight ADRs (Nygard-style), one file per decision
- Pros: immutable, append-only, per-decision provenance; reviewable in the PR that
  makes the change; industry-recognised in diligence and audit.
- Cons: process overhead; goes stale if not enforced; tempting to write for
  trivia.

## Decision

We adopt **Option C**: numbered, append-only ADRs in `docs/architecture/adr/`.

An accepted ADR is never edited except to add a `Superseded by` line. Changing a
decision means writing a new ADR. Commit messages remain the record of *what*
changed; ADRs are the record of *why*.

Rejected Option B specifically because its failure mode — silently overwriting
past reasoning — destroys the exact property that makes this worth doing.

## Consequences

### Positive
- New engineers can answer "why is it like that?" without archaeology.
- Security reviewers see accepted risks stated deliberately, with rationale.
- Diligence gets a reasoning trail rather than a snapshot.

### Negative / accepted cost
- Real overhead per significant decision. Some will not get written.
- ADRs describing code that later moves will drift; the mitigation is the
  maintenance table in [`../README.md`](../README.md), not vigilance.
- Retroactive ADRs (0002–0006) reconstruct reasoning after the fact. They are
  labelled as such. Reconstructed reasoning is weaker evidence than contemporaneous
  reasoning, and we should not pretend otherwise.

### Residual risk
The process is enforced by convention. Nothing in CI checks that an
architecturally significant PR carries an ADR, and nothing can — "significant" is
a judgement call.

## Revisit when

An ADR-linting or CODEOWNERS-based gate becomes worth its cost — realistically,
when more than three engineers merge to `main` in a week.
