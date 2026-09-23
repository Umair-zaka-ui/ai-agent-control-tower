# KILLSWITCH_RACE_RESULTS — V6 (T20b): dominance under concurrency

Raw: [`evidence/v6_killswitch_results.json`](evidence/v6_killswitch_results.json). Fired 2026-09-23 on
real separate Postgres sessions. **6 / 6 pass. Kill-switch dominance 100 %. No reactivation path
reachable by automation.**

## Results

| # | scenario | observed | verdict |
|---|---|---|---|
| V6-K1 | **automation vs human kill** — after a human kill, drive threat evaluation and a further automated containment | after kill `SUSPENDED`; automation action `EXECUTED`; **after automation still `SUSPENDED`** | **PASS (kill dominates)** |
| V6-K2 | **revert a kill** — call revert on an `EXECUTED` `SUSPEND_AGENT` | **`409 CONTAINMENT_ACTION_NOT_REVERSIBLE`**; agent still suspended | **PASS (revert refused)** |
| V6-K3 | **concurrent conflicting containments** — 3 fired at once from separate sessions | one `EXECUTED`, one **truthfully `FAILED`**, one `EXECUTED`; final state `SUSPENDED`; **no 5xx** | **PASS (coherent)** |
| V6-K4 | **reactivation path analysis** | **no reactivation code in the threat package**; a human `resume` exists by design | **PASS (no automation path)** |
| V6-K5 | **retry a killed execution** | **`409 INVALID_LIFECYCLE_TRANSITION`** | **PASS (cannot resurrect)** |
| V6-K6 | **revocation racing in-flight calls** | sequence `[200, 200, 403, 403, 403, 403]`, **no allow after the first denial**, call after the race `403` | **PASS (no authorizing window)** |

## Dominance held under every race

The kill was never undone. In the automation race (K1) a *further* automated containment executed
successfully — and the agent remained `SUSPENDED`, because nothing in the threat path can un-suspend.
In the three-way concurrent race (K3) the outcome was one coherent effect with no torn state and no
server error; notably one of the three reported **`FAILED`**, which is the honest outcome for a losing
concurrent writer rather than a silent success or a 500.

## The reactivation question, answered precisely

Two code paths in the product *can* clear a kill-shaped flag. Neither is reachable by automation, and
both are worth naming rather than glossing:

| path | who can reach it | why it is not a dominance break |
|---|---|---|
| `AgentLifecycleService.resume()` (`SUSPENDED → ACTIVE`) | a **human operator** with the permission | a deliberate, separately-audited verb emitting `RUNTIME_AGENT_RESUMED`. A human un-suspending an agent they own is an operator decision, not automation undoing a kill |
| `ExecutionService.retry()` (clears `cancel_requested`) | a human operator | guarded to `FAILED` / `TIMED_OUT` / `DEAD_LETTERED` only — a **killed/cancelled execution cannot be retried**, confirmed live at K5 (`409`) |

The threat package itself contains **no** statement setting `lifecycle_status` to `ACTIVE` or
`cancel_requested` to `False` (AST-scanned across all seven of its modules), so the automated
containment path has no route to either. `SUSPEND_AGENT` and `TERMINATE_EXECUTION` are marked
`reversible=False` by construction, which is why the revert endpoint refuses them outright (K2).

## Revocation leaves no authorizing window

K6 is the sharpest concurrency result: with six signed calls in flight and a revocation landing
mid-stream, the call sequence went `200, 200, 403, 403, 403, 403`. **No call succeeded after the first
denial**, and the call issued after the race also failed. There is no window in which a revoked grant
still authorizes, because every call re-reads the grant and nothing about it is cached.
