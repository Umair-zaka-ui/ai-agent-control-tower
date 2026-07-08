# AI Agent Control Tower — Architecture Repository

The authoritative, versioned description of how this platform is built and why.
Everything here is derived from the code in this repository, not from intent.
When the code and a diagram disagree, **the diagram is a bug**.

## Why this exists

Three audiences, one artifact set:

| Audience | What they need | Where they start |
| -------- | -------------- | ---------------- |
| Engineers | How a request flows; what a table means; why a decision was made | [C4](./c4/), [Sequences](./sequences/), [ADRs](./adr/) |
| Enterprise buyers / auditors | Trust boundaries, data handling, threat coverage | [Threat model](./security/threat-model.md), [Deployment](./deployment/) |
| Investors / diligence | That the system was designed, not accreted | [Context](./c4/01-context.md), [ADRs](./adr/) |

## Contents

| Artifact | Purpose |
| -------- | ------- |
| [`c4/01-context.md`](./c4/01-context.md) | System in its environment — actors, external systems |
| [`c4/02-container.md`](./c4/02-container.md) | Deployable units and how they talk |
| [`c4/03-component-backend.md`](./c4/03-component-backend.md) | Inside the API: routers, services, engines |
| [`data/erd.md`](./data/erd.md) | All 24 tables, grouped by bounded context |
| [`sequences/`](./sequences/) | Human login, token refresh + reuse, agent-action governance |
| [`deployment/deployment.md`](./deployment/deployment.md) | What ships today; what production needs |
| [`security/threat-model.md`](./security/threat-model.md) | STRIDE over the trust boundaries, with open risks |
| [`adr/`](./adr/) | Architecture Decision Records |

## Conventions

- **Diagrams are Mermaid**, embedded in Markdown. They render on GitHub, in the
  VS Code preview, and in most doc portals — no build step, no CDN, no image
  files to drift out of sync with the text beside them.
- **Diagrams describe `main`.** Planned work is labelled `(planned)` and drawn
  with a dashed edge. If it isn't merged, it isn't solid.
- **Every non-obvious decision gets an ADR**, including the ones we later regret.
  Superseded ADRs are never deleted — they are marked `Superseded by ADR-XXXX`.
  The value is the reasoning trail, and a trail with gaps is worthless.
- **Known gaps are written down.** A threat model that lists no accepted risks
  is not a threat model; it is marketing. Where the platform is knowingly
  incomplete, this repository says so and says why.

## Maintaining this

Update the architecture docs **in the same PR** as the change they describe.
Concretely:

| If you change… | Update… |
| -------------- | ------- |
| A SQLAlchemy model or migration | [`data/erd.md`](./data/erd.md) |
| A router, service, or engine | [`c4/03-component-backend.md`](./c4/03-component-backend.md) |
| An auth / token / session flow | [`sequences/`](./sequences/) + [`security/threat-model.md`](./security/threat-model.md) |
| `docker-compose.yml` / `Dockerfile` | [`deployment/deployment.md`](./deployment/deployment.md) |
| A choice with a plausible alternative | Add an [ADR](./adr/) |

The ERD is generated from `Base.metadata`, so it can be checked mechanically:

```bash
cd backend && python -c "import app.main; from app.core.database import Base; print(len(Base.metadata.tables))"
# must equal the table count in data/erd.md
```

## Related documents

The identity subsystem has its own deep-dive docs under [`docs/identity/`](../identity/).
This repository links to them rather than restating them:

- [Authentication architecture](../identity/authentication-architecture.md)
- [Trust model](../identity/trust-model.md) — identity-scoped trust zones
- [Token strategy](../identity/token-strategy.md) — incl. the access-token revocation gap
- [Human authentication](../identity/human-authentication.md)
- [Security events](../identity/security-events.md)
