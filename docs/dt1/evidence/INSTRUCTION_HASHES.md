# DT1 Stage 1 — instruction provenance (recorded per the architecture approval)

| file | bytes | SHA-256 | role |
|---|---|---|---|
| `backend/instructions/DT1_S1_V2_INSTRUCTION.md` | 20,416 | `984688a1ee563fa8fef9e7a35363708ad8853dbb03f06b9db8d76e2addca1cc2` | the user's instruction file that requested the v2 prompt (read-verified before any action) |
| `backend/instructions/DT1_S1_V2_PROMPT_APPROVED.md` | 35,152 | `761c9decc7acdefa6f23e80f4032c50c1c2197c57ec866a4f4b5c725cdd55417` | the approved "ACT DT1 — STAGE 1 IMPLEMENTATION PROMPT v2", materialized to disk verbatim from the approved chat text by the executing session because no local copy existed; re-read and re-hashed before execution |

Approval text (verbatim from the authorizing message): `VERDICT: APPROVED FOR DT1-S1 EXECUTION`. Base commit at
execution: `ab27fe3a70e72bc3981e9b63afe36eacd5ce90c7` (`validation/v10-authorization-template`). Full hash list of the
sealed artifacts and both instruction files: [`SHA256SUMS.txt`](SHA256SUMS.txt); ledger entries: [`ledger_entries.jsonl`](ledger_entries.jsonl).
