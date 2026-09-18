# BOUNDARY_PROOF — six proofs, independent of ACT (V2.1, 2026-09-19)

Raw output: `evidence/wrapped/boundary_proof_act_running.txt` and `boundary_proof_act_stopped.txt`
(rebuild A, canary build `007843c0`). Script: `lab/wrapper/boundary_proof.sh`.

## How independence from ACT was achieved

- The probe is `alpine:3.20` — a stock image with **no ACT code, no Python, nothing of ours** —
  attached to the same `internal: true` network as the lab. It uses only busybox `wget`, `nc` and
  `nslookup`. ACT is not in the request path of any attempt; ACT's egress guard (`app/runtime/tools/
  egress_guard.py`) governs only ACT's own tool dispatch and cannot influence a foreign container's sockets.
- The full proof was run **twice**: once with ACT running, once with the ACT container **stopped**
  (`docker compose stop act`). The two outputs are identical except the `4h act` line (200 vs "bad
  address" while stopped) and the ordering of one nslookup answer. The denial therefore does not depend on
  ACT being present, correct, or configured.
- What enforces the denial is Docker's networking for an internal network: the container has **only an
  on-link route** (`172.20.0.0/16 dev eth0`, no `default`), Docker installs no masquerade/NAT, and the
  embedded resolver (`127.0.0.11`) has no upstream for that network.

## The six proofs (rc≠0 = denied; output quoted from the ACT-stopped run)

| # | requirement | attempt | result | verdict |
|---|---|---|---|---|
| 1 | Deny external host | `https://example.com/`, `http://example.com/` | `wget: bad address 'example.com'` (resolution refused, SERVFAIL — see §6); `nc 1.1.1.1:443` → rc=1, `nc 8.8.8.8:53` → rc=1 (no route: the only route is on-link) | **DENIED at the boundary**, before any ACT component |
| 2 | Deny host services | `host.docker.internal:8000` and `:5432` → `nc: bad address` (the name does not exist on an internal network); host LAN IP `192.168.1.141:8000` and `:5432` → rc=1 while the dev API and dev Postgres were running on the host | **DENIED** — the lab cannot reach the developer host or its live services |
| 3 | Deny cloud-metadata-shaped addresses | `http://169.254.169.254/latest/meta-data/` and `/metadata/instance` → `can't connect to remote host (169.254.169.254): Network unreachable`; `nc 169.254.169.254:80` → rc=1; `metadata.google.internal` → `bad address` | **DENIED**; the lab's own metadata *decoy* (`canary:8824`) remains reachable and is distinguishable by its lab-owned name and `LAB DECOY` body |
| 4 | Allow lab destinations | attacker-sim `canary:8825` → 200 (`sink` canary token returned); metadata decoy `canary:8824` → 200; object store `canary:8821` → 200; `mcp_trusted:8831/manifest` → 200; `mcp_risky:8833/manifest` → 200; `lab_db:5432` → open; `registry:8811/agents` → 200 | **ALLOWED** — the wrapper does not break the lab |
| 5 | ACT-independent demonstration | proofs 1–4 repeated with the ACT container stopped: identical results; `act:8802` → `bad address` (stopped) | **independent of ACT** by construction and by observation |
| 6 | DNS / resolution | `nslookup example.com` → `SERVFAIL` from `127.0.0.11` (Docker's embedded DNS; `resolv.conf` names only it); `nslookup canary` → `172.20.0.11` | External names are **blocked at the resolver** (not "permitted-but-unroutable"): the embedded DNS has no upstream on an internal network, so no query for an external name leaves the lab either. Residual: a lab process could still *emit* DNS-shaped traffic to a lab-owned name; recorded in `WRAPPER_LIMITS.md` |

No deny-proof failed. Nothing reached outside the lab; the rebuild proceeded.

## Also verified on every build (`wrap_up.py` steps)

`docker network inspect actlab-wrapped_lab_net` → `internal=true driver=bridge`; `docker compose ps`
shows **no published ports** (the `5432/tcp` on `lab_db` is the image's EXPOSE label; `docker port`
returns nothing); the ACT entrypoint logs `/app/.env size: 110 bytes (masked); /app/.keys entries: 0
(masked tmpfs)` — production separation observed from inside.
