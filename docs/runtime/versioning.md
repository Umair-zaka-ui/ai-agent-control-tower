# Versioning

`/runtime/agents/{id}` (Versions section) · `runtime.version.*` permissions.

## Immutability & checksums (§11, §12)

An `agent_versions` row snapshots everything an execution needs: model
configuration, prompt, capability/tool references, and a policy snapshot —
so a running deployment is never affected by later edits to the agent's
definition. `checksum` is `sha256` of the canonical (sorted-key) JSON of
`{configuration_snapshot, prompt_snapshot, model_configuration,
capabilities_snapshot, tools_snapshot, policy_snapshot}`
(`app/runtime/services.py::_checksum`).

`AgentVersionService.publish()` recomputes the checksum and compares it to
the stored one before allowing `APPROVED → PUBLISHED`; a mismatch raises
`AGENT_VERSION_IMMUTABLE`. This is the tamper check §78 requires ("checksums
must detect tampering") — see `test_published_version_tamper_is_detected`.

## Lifecycle (§11)

```
DRAFT → READY_FOR_REVIEW → APPROVED → PUBLISHED → DEPRECATED
                                              └──→ REVOKED
```

(This environment's `validate()` goes straight to `READY_FOR_REVIEW`
synchronously — same simplification as the agent lifecycle; see
[agent-lifecycle.md](agent-lifecycle.md).)

- **DRAFT** — editable. `configuration_schema`, capability/tool references
  and `model_configuration` can all still change (by creating the version
  fresh; there is no in-place PATCH on a version — see below).
- **READY_FOR_REVIEW** — `validate()` checked `model_configuration.provider`
  is present and the checksum still matches.
- **APPROVED** — a human (or a future approval workflow) signed off.
- **PUBLISHED** — immutable from here on. `published_at` is set. Only a
  published (or later-deprecated) version can be deployed
  (`AGENT_VERSION_NOT_PUBLISHED` otherwise).
- **DEPRECATED** — still executable (existing deployments keep working,
  §10.7 applies the same idea to agents), but new deployments should move
  off it.
- **REVOKED** — terminal. `AGENT_VERSION_REVOKED` blocks new executions
  immediately, from any prior state.

There is intentionally no version-edit endpoint: creating a new version is
the only way to change behavior, which is what "immutable" means in
practice. `POST /agents/{id}/versions` auto-increments `version` per agent
(`1, 2, 3, …`) and defaults `semantic_version` to `0.1.0` if not supplied
(§12 — the platform tracks the internal integer `version`; `semantic_version`
is the human-facing MAJOR.MINOR.PATCH string, not parsed or validated
against SemVer rules in this implementation).

## Capability/tool references on a version

`capability_ids`/`tool_ids` passed at version creation both (a) get
recorded in the immutable `capabilities_snapshot`/`tools_snapshot` JSON
arrays, and (b) create `agent_capabilities`/`agent_tools` assignment rows
scoped to that version (`status=REQUESTED`). This is separate from — and in
addition to — assigning a capability/tool directly to the agent (no
`agent_version_id`) from the agent detail page; see
[capabilities-and-tools.md](capabilities-and-tools.md).
