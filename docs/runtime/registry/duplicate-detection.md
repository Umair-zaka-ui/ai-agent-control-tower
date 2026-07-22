# Duplicate detection (§32, §33, §64)

`AgentDuplicateDetectionService.check` (`app/runtime/registry/duplicates.py`)
compares one agent against every other agent in the same organization and
persists an `agent_duplicate_matches` row for every candidate that matched
anything.

## No fuzzy-matching library

Similarity scoring uses stdlib `difflib.SequenceMatcher` — no fuzzy-matching
library (rapidfuzz, python-Levenshtein, …) is installed in this codebase and
none is needed at this organization-inventory scale (hundreds, not millions,
of agents).

## Exact matches (§32.1)

- Same `identity_id` (only reachable if the DB's uniqueness on `slug`/
  `external_reference` didn't already prevent the scenario — those two
  exact-match signals from the SRS are effectively unreachable in this
  implementation precisely *because* they're DB-uniqueness-enforced at
  write time, not because the check is missing).
- Same `repository_url` + same `entrypoint`.
- Same `entrypoint_type == "HTTP_ENDPOINT"` + same `entrypoint`.
- Same `entrypoint_type == "CONTAINER_IMAGE"` + same `entrypoint` + same
  `business_purpose`.
- Same `project_id` + case-normalized identical `name`.

Any exact match → `status = "CONFIRMED_DUPLICATE"` immediately (§32.4:
"confirmed duplicates block registration").

## Similarity matches (§32.2)

A weighted average of `difflib` ratios: name (50%), description (25%),
business_purpose (25%), plus a same-owner signal. Thresholds:
`≥0.85 → LIKELY_DUPLICATE`, `≥0.72 → POSSIBLE_DUPLICATE`, below that → not
recorded at all.

## Review (§64)

`POST /agents/{id}/duplicate-matches/{matchId}/review` — one of
`CONFIRM_DUPLICATE`/`NOT_DUPLICATE`/`MERGE_REQUIRED`/
`JUSTIFIED_SEPARATE_AGENT`, with a mandatory reason; `CONFIRM_DUPLICATE`
promotes the match's `status` to `CONFIRMED_DUPLICATE` if it wasn't already.
Every review is audited (`RUNTIME_AGENT_DUPLICATE_REVIEWED`). The frontend's
`DuplicateReviewPage` is a dedicated route
(`/runtime/agents/:id/duplicates`), not one of the 12 detail-page tabs — the
SRS's own §60 routing table lists it separately from the §38 tab set.

## Where this is checked automatically

Only during bulk import (`AgentImportService._import_one` runs a duplicate
check on every newly created row and surfaces a warning if a confirmed
duplicate turns up) — `POST /agents` itself does **not** run a duplicate
check automatically; a caller (or the registration wizard's Review step, in
a future enhancement) triggers it explicitly via
`POST /agents/{id}/duplicate-check`.
