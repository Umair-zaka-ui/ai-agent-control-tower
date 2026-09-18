# ISOLATION_WRAPPER — V2.1 (2026-09-19)

## Mechanism chosen: an `internal: true` Docker network on Docker Desktop, with the whole lab inside it

**Why this one.** The host is a Windows 11 developer machine running Docker Desktop 29.6.1 (Linux VM,
overlayfs, cgroup v2). Of the preference order in the V2.1 brief:

| option | available here? | decision |
|---|---|---|
| disposable VM with a host-only / NAT-denied network | Hyper-V is not provisioned for this program and a VM image would not be "built from committed artifacts, unattended" on this host without new tooling | rejected for V2.1 (recommended for T12, see `WRAPPER_LIMITS.md`) |
| Linux network namespace with an explicit egress-deny ruleset | not directly on Windows; the Docker Desktop VM *is* a Linux host, and a Docker network with `internal: true` is exactly a namespace set with **no default route and no masquerade rule** installed by Docker's netfilter management | **chosen** — it is the namespace option as this host exposes it |
| isolated Docker network + firewall rules | same as above; Docker's own rules are the firewall (no `MASQUERADE`, no `DOCKER-USER` forward for the network, no gateway route) | chosen |
| loopback-only binding | the V2 state (DG-1) | insufficient on its own, superseded |

Every lab component — ACT, its dedicated Postgres, the registry, the canary zone, the OTLP collector,
the five MCP-shaped servers, the harness runner, the boundary-proof probe — is a container attached
**only** to `actlab-wrapped_lab_net` (`internal: true`). **No service publishes a port.** The host
reaches the lab only through `docker compose exec` (a control-plane channel that is not a network
path) and reads results through the bind-mounted `lab/` directory (filesystem, not network).

## How each required property is met

| property | requirement | how met | evidence |
|---|---|---|---|
| Egress default | DENY | the network is `internal: true`: containers get no default route and Docker installs no NAT; packets to anything off-network have nowhere to go | `BOUNDARY_PROOF.md` §1–§3: `ip route` shows only the on-link route; external, host and metadata attempts fail with network-unreachable / timeout |
| Allowed destinations | only lab-owned | the only reachable addresses are the other containers on `lab_net` (attacker-sim, canary targets, MCP zone, registry, DB, ACT) | `BOUNDARY_PROOF.md` §4 |
| Independence from ACT | denial enforced outside ACT | the denial is Docker/VM netfilter + routing; it applies to a stock `alpine:3.20` probe container with no ACT code, and it applies identically with the ACT container **stopped** | `BOUNDARY_PROOF.md` §5 (`boundary_proof_act_stopped.txt`) |
| Host protection | no path to host services, host LAN, non-lab paths | no gateway → `host.docker.internal:8000/5432` and the host LAN IP are unreachable; the dev API on `:8000` and dev Postgres on `:5432` stay up on the host and are provably not reachable from inside | `BOUNDARY_PROOF.md` §2 |
| Production separation | no path to production keys/DB/`backend/.keys`/`backend/.env`/real credentials | ACT's source tree is bind-mounted **read-only**; `/app/.keys` is masked by an empty **tmpfs**; `/app/.env` is masked by `lab/wrapper/empty.env`; the image is built from `requirements.txt` only (never `COPY . .`, which would have copied `backend/.keys/`); the only key material inside is bootstrapped fresh into `/lab/.keys` per build; the dev database on the host is unreachable (above) | ACT entrypoint log line `[act] /app/.env size: … bytes (masked); /app/.keys entries: 0 (masked tmpfs)`; `WRAPPED_REBUILD.md` |
| Disposability | clean teardown, no residue | `wrap_down.py`: `compose down -v --remove-orphans`, then asserts no container, network or volume with the project label remains, and deletes `lab/.keys` and `lab/run` | `WRAPPED_REBUILD.md` |
| Reproducibility | committed, unattended | `lab/wrapper/*` committed; `wrap_up.py` builds, starts, waits healthy, runs proofs and the baseline with no manual step | `WRAPPED_REBUILD.md` |

## Build / teardown artifacts

`lab/wrapper/docker-compose.wrapped.yml` · `Dockerfile.act` · `Dockerfile.runner` · `act-lab-wrapped.env`
(synthetic) · `empty.env` · `act-entrypoint.sh` · `boundary_proof.sh` · `wrap_up.py` · `wrap_down.py`.
The V2 host-mode lab (`lab/harness/lab_up.py`) is unchanged in behaviour; the services gained a
`LAB_BIND` switch (loopback in host mode, all interfaces of the internal network in wrapped mode) and
the harness gained endpoint variables — isolation changed, observations did not.

## What "inside the boundary by design" means

The attacker-sim endpoint, the canary metadata **decoy** (`canary:8824`, cloud-metadata-*shaped*, lab-owned,
returns `LAB DECOY - detectably fake`) and every canary target are deliberately reachable: they are the
instruments V3 uses to observe an attempted exfiltration *land somewhere ACT owns*. The real
link-local metadata address `169.254.169.254` is **not** reachable (proof §3), which is what makes the
decoy distinguishable.
