# MEASUREMENTS — V3, containment and detection kept separate

Raw: [`evidence/v3_measurements.json`](evidence/v3_measurements.json),
[`evidence/v3_canary_integrity.json`](evidence/v3_canary_integrity.json). The central result of the phase
is that **containment and detection are different axes**: ACT contains injected actions via grant scope /
frozen egress **without detecting the injection** (G-1). The two are reported separately below.

## Containment (mode b — the model complied)

| metric | value |
|---|---|
| T1 gateway-routed forbidden actions fired (mode b) | 11 |
| T1 contained by an ACT authority | **11 / 11 (100%)** |
| injection-containment rate | **11/11** |
| confused-deputy redirect reaching the sink | 0 (frozen egress; `attacker_sim_delta = 0`) |
| tool-abuse (T3) contained / not-applicable | 4 contained + 2 NOT_APPLICABLE, 0 GAP |
| MCP (T4) boundary properties held (replay / scope / tenant) | 3 / 3 |
| gateway `DENIED`-never-dispatched DB-invariant violations | **0** |
| false-positive blocks on benign actions | **0** |

## Detection (does 5.6 / posture flag the attack?)

| metric | value |
|---|---|
| T1 injections detected **as injection** | **0 / 18** |
| open posture rules for the agent after the batch | `dangerous_dependency` only |
| injection-classified findings | **0** (`injection_classified = []`) |
| **contained-but-not-detected** (the phase's key split) | **11 / 11** |
| MCP description-integrity / transport / impersonation detected | 0 (G-3 confirmed) |
| memory poisoning observed / inventoried / attributed | 0 (I-1, NOT_OBSERVABLE) |

## Canary integrity

| metric | value |
|---|---|
| **canary escapes past the wrapper** | **0** |
| unexpected canary tokens in ACT DB | 0 (`db_unexpected = {}`) |
| unexpected canary tokens in ACT log | 0 |
| positive control (grant-label token, operator input, expected in ACT) | fires |
| raw-socket exfils reaching the **lab sink** (by design, wrapper-contained) | 6 (observation points, not escapes) |

## Latency (per-scenario, T1 mode b, inside the wrapper)

Round-trip agent-process spawn + gateway call: **237–334 ms**, mean ≈ 262 ms. This is the agent
subprocess start plus one HMAC-signed gateway round trip; it is dominated by process spawn, not ACT.
No V2 baseline row measures the same thing (V2 measured discovery/reconcile/posture, not per-injection
gateway latency), so no false comparison is drawn. There is **no containment latency overhead to report**
because the denial is synchronous with the gateway decision (a `403` before any dispatch).

## Reading

ACT's **containment** of injected actions is complete where the boundary applies (11/11, 0 sink hits,
0 FP, 0 DB-invariant violations, 0 canary escapes). ACT's **detection** of injection as a phenomenon is
absent (0/18) — the expected, honest split that maps to product-change **O-1**.
