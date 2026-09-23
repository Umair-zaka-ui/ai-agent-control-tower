# RESULTS_LEDGER — hash-anchored evidence chain (V7)

Same mechanism as V3–V6 ([`lab/harness/ledger.py`](../../../lab/harness/ledger.py)): an append-only
SHA-256 chain over every result file. Copy: [`evidence/ledger.jsonl`](evidence/ledger.jsonl).

| seq | file | sha256 (12) | entry_hash (12) | note |
|---|---|---|---|---|
| 0 | GENESIS | `9c8e771d0da0` | `9acb17eb0290` | |
| 1 | v3_preflight.json | `97f7a8df43e9` | `10f804e921ee` | pre-flight |
| 2 | v7_ground_truth.json | `98b77a3e919a` | `44a5ca9d2e58` | run 1 (superseded) |
| 3 | act_wrapped_v7.log | `9a072f7696fb` | `4558d56f1a34` | |
| 4 | v7_ground_truth.json | `17fd6fb9f4ba` | `4f740b1e2e10` | run 2 (superseded) |
| 5 | v7_agent_matrix.json | `513ea6e8f331` | `62a99240aeb3` | run 2 |
| 6 | v7_interop_results.json | `0acbf0492fda` | `985a0a4e7d11` | run 2 |
| 7 | v7_measurements.json | `5f0ddae6d3cb` | `a2f6c06a8b1b` | run 2 |
| 8 | **v7_ground_truth.json** | `6367efab8e4d` | `59c17954ae5c` | **final** |
| 9 | **v7_agent_matrix.json** | `53f3d454ef0f` | `62c591dfd170` | **final** |
| 10 | **v7_interop_results.json** | `2ccb1d7f3c5d` | `16d810932538` | **final** |
| 11 | **v7_measurements.json** | `5f0ddae6d3cb` | `0093dcb2695a` | **final** |

**The per-agent ground truth is anchored before any governance observation in every run** (seq 2, 4
and 8 each precede that run's results), so the expected picture is hash-committed ahead of what is
measured against it.

## The chain records three runs, deliberately

V7 ran three times. The chain keeps all of them rather than starting clean, so the corrections are
auditable:

| run | outcome | why |
|---|---|---|
| 1 | aborted at build | **F7-1**: CrewAI and the OpenAI Agents SDK cannot share a Python environment (`ResolutionImpossible`). Fixed by giving the SDK agent its own interpreter — a real finding, not a workaround |
| 2 | 9/11 assertions, 3 agents blocked | **HD7-1**: only the first discovered agent row was made `GATEWAY_ENFORCED`, so grants for agents mapped to the other rows failed and their configs carried no secret. Three framework agents could not authenticate. Fixed by governing every discovered row before issuing grants |
| 3 | **final: 7/7 agents at Tier 7, 10/11 assertions** | **HD7-2**: assertion 7 asserted "shadow fires" while V7's own setup *claims* every agent, removing the unowned precondition. Strengthened to test both directions with an unowned control agent |

All three are **harness** defects, not ACT defects. Notably HD7-1 masqueraded as three framework
failures (LangGraph, CrewAI and Anthropic all reported errors) that were in fact one missing setup
step — a reminder to chase a shared root cause before blaming three components.

## Lab-tooling changes in V7

| change | why |
|---|---|
| `lab/services/local_model.py` (new) | the local model substrate, serving both OpenAI and Anthropic wire shapes in-network |
| `lab/agents/v7/` (new, 7 agents + `_agentlib.py`) | the uniform T0–T7 tier protocol across five stacks |
| `lab/wrapper/Dockerfile.wave2` (rewritten) | two Python environments (F7-1) plus `nodejs`; versions captured at build |
| `local_model` compose service, `LAB_MODEL_BASE_URL` on wave2 | wire the substrate to the frameworks |
| `lab/harness/v7_interop.py`, `lab/wrapper/v7_run.py` (new) | ground truth, the ladder, the eleven assertions, and the host orchestrator |

No ACT product code, test, schema, migration or CI file was changed in V7;
`git diff e810113 -- backend/ frontend/` is empty.
