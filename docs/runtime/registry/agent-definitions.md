# Agent definitions

`AgentDefinition` (`app/models/runtime.py`) already existed in Phase 5.0
(framework/entrypoint/schemas); this phase adds the requirement-declaration
fields SRS §7 describes: `framework_version`, `runtime_language`,
`capability_declarations`, `tool_declarations`, `model_requirements`,
`memory_requirements`, `data_requirements`, `network_requirements`,
`secret_requirements`, `runtime_requirements` — all JSONB, all intent
declarations rather than grants ("The user declares intended capabilities/
tools/... — these declarations do not grant actual access," §23). Real
capability/tool access is still assigned separately via the Capabilities/
Tools tabs (Phase 5.0's `CapabilityService`/`ToolRegistryService`).

The SRS's `definition_name`/`definition_description` field names map onto
this table's pre-existing `name`/`description` columns rather than being
renamed — consistent with how `extra_metadata` already maps to the SRS's
"metadata" naming (SQLAlchemy reserves the literal attribute name
`metadata` on its declarative base).

## Framework/entrypoint-type leniency

Phase 5.0 registered agents with `framework="CUSTOM"` and
`entrypoint_type="FUNCTION"` as defaults — values not in this phase's SRS
§8/§10 enumerations (`NATIVE_PYTHON`/.../`CUSTOM` and
`PYTHON_MODULE`/.../`CUSTOM` respectively). Rather than break every
existing agent, the validation engine's `_FRAMEWORKS`/`_ENTRYPOINT_TYPES`
sets (`app/runtime/registry/validation.py`) include both the SRS's new
enumeration and the Phase 5.0 legacy values, and an unrecognized value is a
`WARNING`, not a `BLOCKING` finding — see [validation.md](validation.md).

## Reading a definition

`GET /agents/{id}/definitions` (plural — Phase 5.0's original path) and
`GET /agents/{id}/definition` (singular — the SRS's own naming) both list
every definition version for an agent, newest first; the frontend's
Definition and Contracts tabs both read `[0]` (the latest).
