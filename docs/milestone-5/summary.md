# Milestone 5 — Universal Agent Control & Security Fabric: COMPLETE

Closed 2026-09-16 by Phase 5.10. Ten phases, 5.1 through 5.10.

## What the milestone set out to do

Govern the AI you didn't build. Before M5, ACT was a control plane for agents
it created and executed. After M5 it discovers, inventories, maps, governs,
secures and contains a **heterogeneous** estate — including agents that came
from somewhere else and run somewhere else — and it does so **truthfully**,
never claiming control it does not have.

## What each phase established

| Phase | Established |
|---|---|
| 5.1 | One canonical `agents` registry describing native, external, discovered, claimed, registered and governed agents; `control_state` server-authoritative |
| 5.2 | Discovery as **evidence**, reconciliation deriving canonical state; no silent merge, no duplicate; fails open |
| 5.3 | A relational control graph representing authority — never granting it |
| 5.4 | Dependencies, blast radius and MCP-via-Tool; recursive CTEs, **no graph database** (ADR-0017) |
| 5.5 | Deterministic, explainable posture; shadow as a **derived, disputable finding**, never a flag |
| 5.6 | Runtime threat detection; containment routed **only** to existing authorities; **truthful refusal** where ACT has no authority; kill-switch dominance |
| 5.7 | External governance at a **real boundary**; four enforcement modes each bounded to what ACT can do; `NATIVE_ENFORCED` **not storable** — derived from `control_state` |
| 5.8 | The command center; affordances computed from server truth, never a client guess |
| 5.9 | Assurance as **evidence and mappings, never a verdict**; `INSUFFICIENT_EVIDENCE` first-class; a stale pass **unrepresentable**; the frontend build restored |
| 5.10 | The end-to-end proof across **two real process boundaries**; all eighteen §44 gates closed; one real defect found and fixed |

## The thread that runs through all ten

Every phase was built to be **honest about reach**, and each one made that
honesty structural rather than a matter of discipline:

- 5.6 refuses containment it cannot perform, with a real reason.
- 5.7 cannot store the strongest enforcement mode; it has to be *true*.
- 5.8 derives no affordance in the browser; a test rejects any client-side
  `control_state ===` comparison.
- 5.9 cannot store a stale PASS and has no `compliant` field to render.

The 5.10 proof is the same principle applied to the milestone gate: it asserts
that a kill of an external agent is **REFUSED**, because a proof asserting a
successful kill would pass only if the platform lied.

## Gates closed (§44, A–R)

All eighteen, each to a named passing proof. The four 5.10 owns directly:
**N** adversarial per-hop tenant isolation, **O** measured scale with no graph
database, **Q** the full M1–5.9 regression unchanged, **R** the cross-process
end-to-end proof. See [`proof.md`](proof.md).

## The wider platform arc

| Milestone | ACT can… |
|---|---|
| M1 | execute real governed AI |
| M2 | integrate with the enterprise in both directions |
| M3 | deploy and operate versions safely at production scale |
| M4 | understand, govern and financially manage what its agents do at runtime |
| M4.11 / M4.11a | keep its own cryptographic identity recoverable and fail-safe |
| **M5** | **discover, inventory, map, govern, secure and contain the heterogeneous AI estate — including agents it did not create — truthfully** |

## What comes next

The approved next step is the post-M5 **Enterprise Validation Lab & Red-Team
Gate**: a release-candidate validation against real infrastructure. Milestone 5
was designed so that gate needs no architectural rework — the proof harnesses
(a real external agent in its own process, a real registry on a real socket,
real separate Postgres sessions for races) are exactly the instruments that
lab will drive harder. **No new milestone was begun.**
