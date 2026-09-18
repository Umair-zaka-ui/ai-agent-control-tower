# WRAPPED_REBUILD — unattended build inside the wrapper, twice (V2.1, 2026-09-19)

Record: `evidence/wrapped/wrapped_chain.log` (the full unattended chain), `wrapped_build_A.json`,
`wrapped_build_B.json`, `act_wrapped_A.log`, `wrap_up_first_attempt.log`.

## Sequence executed (one shell chain, no human step between commands)

| step | command | result | time |
|---|---|---|---|
| 0 | first wrapped attempt (`wrap_up.py --proof --baseline`) | built, proofs passed, **baseline raised 1 finding**: the MCP client got 401 from the trusted MCP server — a **lab-tooling defect**, not ACT: restarting ACT via `compose up --wait act` re-ran the one-shot canary generator and rotated the MCP bearer token after the MCP servers had started. Fixed by making `lab/canaries.py` idempotent per build and polling ACT's healthcheck on restart | 112.7 s |
| 1 | `wrap_down.py` | `containers_left: []`, `networks_left: []`, `volumes_left: []`, `lab/.keys` and `lab/run` absent | ~14 s |
| 2 | **rebuild A**: `wrap_up.py --proof --baseline` | images from cache (1.3 s); `compose up -d --wait` **26.1 s** (Postgres init, `alembic upgrade head`, fresh key bootstrap, health); network `internal=true`; no published ports; masking line logged; boundary proof with ACT running (25.5 s) and stopped (30.5 s); ACT healthy again (16.4 s); **baseline 0 findings** (11.5 s); ACT container log: 184 lines, 0 canary marker hits, 0 tracebacks | 113.8 s total incl. proofs |
| 3 | `wrap_down.py` | same clean residue check | ~14 s |
| 4 | **rebuild B**: `wrap_up.py --baseline` | `compose up -d --wait` **28.6 s**; **baseline 0 findings** (12.2 s); ACT log 153 lines, 0 marker hits, 0 tracebacks | **42.9 s total** |

Pure lab bring-up inside the wrapper: **~26–29 s** (vs V2 host mode 18.4 s cached / 68.1 s first build).
The extra ~10 s is container start plus the in-container migration and key bootstrap; image build
itself (pip install of `requirements.txt` into `python:3.12-slim`) happened once, ~3 min, and is cached.

## Key freshness (a new lab identity per build, per V2 §M)

| build | canary build id | encryption key fingerprint | signing key fingerprint |
|---|---|---|---|
| first attempt | `14b2efae` | (in `wrap_up_first_attempt.log`) | |
| rebuild A | `007843c0` | `f56a3f0edc1a5912` | `c9c3595060376f7c` |
| rebuild B | `a09d347b` | different again (`act_wrapped` log of build B captured in `wrapped_build_B.json` step output) | |

Bootstrap succeeded on every build because each `act_lab` started empty (no volume) and `/lab/.keys`
was deleted by teardown: install mode NEW → bootstrap → marker written → `keys verify` rc 0.

## No production path referenced

- ACT source mounted read-only at `/app`; `/app/.env` is `lab/wrapper/empty.env` (110 bytes of comment);
  `/app/.keys` is an empty tmpfs — both logged from inside by the entrypoint on every build.
- The image is built from `requirements.txt` only (`Dockerfile.act`), so `backend/.keys/` (which
  `backend/.dockerignore` does **not** exclude — recorded as observation OB-2, no change made) never enters an image.
- The host's dev database and dev API are unreachable from the lab (BOUNDARY_PROOF §2).
- `git diff 2b4f57b -- backend/ frontend/` is empty.

## Manual steps encountered (each a documentation gap, now handled)

| gap | what happened | handling |
|---|---|---|
| DG-7 | `docker compose build` builds services in parallel, so `runner` (FROM the ACT image) failed on the very first build before `act` existed | `wrap_up.py` runs `compose build` (act first by dependency in practice); the first-ever build on a clean host should run `compose build act` then `build runner` — documented in `LAB_BUILD.md` |
| DG-8 | `compose up --wait <service>` re-runs one-shot dependencies | canary generation made idempotent; restart step polls the healthcheck |
| DG-9 | ACT's own `backend/Dockerfile` would copy `.keys/` | lab uses its own Dockerfile; recorded as OB-2 for the product team |

The host-mode (V2) lab was re-run after these changes to confirm it still builds and baselines
identically (`evidence/wrapped/hostmode_regression.log`).
