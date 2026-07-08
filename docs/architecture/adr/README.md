# Architecture Decision Records

An ADR captures **one architecturally significant decision**: the context that
forced it, the options considered, what was chosen, and what it cost.

## Why bother

Six months from now, someone — a new engineer, a security reviewer, a
due-diligence analyst, you — will look at a piece of this system and ask *"why on
earth is it like that?"* Without ADRs the honest answer is usually "nobody
remembers." That answer is expensive: it makes people afraid to change things,
and it makes the platform look accidental to anyone evaluating it.

An ADR is not documentation of *what* the code does. That's what the rest of
[`docs/architecture/`](../) is for. An ADR records *why the alternative was
rejected*.

## Index

| ADR | Title | Status |
| --- | ----- | ------ |
| [0001](./0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](./0002-postgresql-as-sole-datastore.md) | PostgreSQL as the sole datastore | Accepted |
| [0003](./0003-stateless-jwt-with-rotating-refresh-tokens.md) | Stateless JWT access tokens with rotating refresh tokens | Accepted |
| [0004](./0004-single-source-password-policy.md) | One password policy, defined once, argon2id | Accepted |
| [0005](./0005-additive-identity-layer-alongside-legacy-auth.md) | Build the identity layer additively beside legacy auth | Accepted |
| [0006](./0006-deterministic-governance-pipeline.md) | Keep the governance decision path deterministic (no LLM) | Accepted |

## Status values

| Status | Meaning |
| ------ | ------- |
| `Proposed` | Under discussion; not yet binding |
| `Accepted` | In force. The code reflects this. |
| `Superseded by ADR-XXXX` | No longer in force; kept for the reasoning trail |
| `Deprecated` | No longer relevant (e.g. the component was removed) |

**Never delete or rewrite an accepted ADR.** If the decision changes, write a new
ADR that supersedes it and add the `Superseded by` line to the old one. The value
of this directory is the trail, and a trail with holes in it proves nothing.

Several ADRs here are marked *retroactively recorded* — the decision was made in
code before the ADR existed. That is normal when introducing ADRs to a live
codebase, and saying so is more honest than backdating.

## When to write one

Write an ADR when a decision is **hard to reverse** or **surprising without
context**:

- Choosing (or refusing) a datastore, framework, protocol, or external dependency
- A security trade-off with a residual risk — *especially* then
- A structural pattern others must follow (layering, error handling, tenancy)
- Deliberately accepting a known limitation

Don't write one for: naming, formatting, library micro-choices, or anything a
reader would guess correctly on the first try.

## Template

Copy [`_template.md`](./_template.md). Number sequentially; never reuse a number.

The `Consequences` section is the one that matters. If it contains only benefits,
the ADR is not finished — every real decision costs something, and the reader
needs to know what.
