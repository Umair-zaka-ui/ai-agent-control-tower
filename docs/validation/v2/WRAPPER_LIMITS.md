# WRAPPER_LIMITS — what the V2.1 boundary does NOT protect against (2026-09-19)

Stated plainly, so V3 authorizes scenarios against the boundary that actually exists.

| limit | detail | consequence |
|---|---|---|
| **Kernel-level escapes** | The wrapper is a Docker network + containers inside Docker Desktop's Linux VM. Containers share that VM's kernel; a container-escape or kernel exploit would land in the Docker VM (not the Windows host directly), from where the internal-network rule no longer binds the attacker. | Adequate for network-level containment of *application-layer* misbehaviour; **not** a sandbox for code that is expected to try to escape. See the T12 recommendation. |
| **Anything the host itself does** | `docker compose exec`, bind mounts (`lab/` read-write, `backend/` read-only), and Docker's control plane are host-initiated channels the boundary does not govern. The harness runner has the ACT source mounted read-only and writes results to `lab/run` on the host. | A lab process that could write arbitrary files into the bind-mounted `lab/` could influence the host's *evidence*, not its network. Evidence integrity for V3 should add a hash ledger of `lab/run/results` (recorded as a V3 prerequisite, not built here). |
| **Side channels** | Timing, resource contention and shared-kernel observability are unmitigated; the lab has no covert-channel controls. | Out of scope for V3's network-egress claims. |
| **DNS behaviour** | See `BOUNDARY_PROOF.md` §6. Docker's embedded DNS answers container names; external names are forwarded by the Docker VM's resolver. If external resolution *succeeds* while packets are unroutable, that is "permitted-but-unroutable": a query itself leaves the VM even though the lab cannot connect. | DNS-based exfiltration (data in query names) is then a **residual channel** for V3 to test explicitly; recorded whichever way §6 came out. |
| **Deliberately allowed destinations** | The attacker-sim endpoint, the canary targets (incl. the metadata *decoy*) and the MCP zone are inside the boundary on purpose — they are where V3 expects escapes to *land*. | An "escape" to the attacker-sim is an observed, contained event by design, not a boundary failure. |
| **Docker Desktop specifics** | `internal: true` semantics are Docker's; a Docker upgrade or an operator adding a second network to a service would silently re-open egress. `wrap_up.py` re-asserts `internal=true` and "no published ports" on every build, but nothing prevents a future compose edit. | Keep the two assertions in the build log; V3 should re-run the boundary proof before every adversarial batch. |
| **No VM snapshot** | Teardown is destructive (`down -v`); there is no snapshot/restore. | Rebuild is fast (see `WRAPPED_REBUILD.md`), so this is a cost, not a hole. |

## T12 (code execution / sandbox escape) recommendation

**This wrapper is adequate for V3's injection, MCP-poisoning, rug-pull, identity and boundary-abuse
scenarios** — the ones whose failure mode is *network egress or unauthorized action*: the boundary
denies independently of ACT and the observation points sit inside it.

**It is NOT adequate for T12 code-execution / sandbox-escape scenarios** (the STDIO command-execution
class, CrewAI-style interpreter fallbacks, container escapes). Those scenarios' failure mode is
*process-level compromise of the thing enforcing the boundary*; a shared-kernel container network cannot
be the last line for that. Recommendation: **T12 gets its own environment later** — a disposable VM
(Hyper-V or a cloud instance, out of V2.1 scope) with a host-only network and no route to this host,
snapshotted before each scenario. Until it exists, V3 must not fire STDIO execution or escape attempts
in this wrapper. This is the legitimate, reportable outcome the V2.1 brief anticipated.
