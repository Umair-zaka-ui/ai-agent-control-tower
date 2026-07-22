# JSON Schema validation (§29-§31)

## DoS guards

`check_schema_dos_guards` (`app/runtime/registry/validation.py`) wraps
`jsonschema` — which enforces none of this on its own — with:

- **Size limit**: serialized schema over 65,536 bytes → `BLOCKING`
  (`AGENT_SCHEMA_TOO_LARGE`), checked before anything else so an oversized
  payload never gets walked.
- **Nesting-depth limit**: over 20 levels deep → `BLOCKING`
  (`AGENT_SCHEMA_TOO_DEEP`), computed by `_json_depth` with its own
  short-circuit at `max_depth + 5` so a pathologically deep structure can't
  make the depth-check itself expensive.
- **Draft validity**: `jsonschema.Draft202012Validator.check_schema` — an
  invalid schema is `BLOCKING`, not a 500.

Called on every contract schema (`input_schema`/`output_schema`/
`configuration_schema`) as part of the validation engine — see
[validation.md](validation.md).

## Sample-payload testing (§30)

`validate_sample_payload` — the same `jsonschema.validate` call Phase 5.0's
execution-time `_validate_schema` uses. Exposed two ways:

- `POST /agents/{id}/schemas/test` — tests a payload against the agent's
  *current* definition's schema (used by the Contracts tab).
- The registration wizard's Contracts step does a lightweight client-side
  JSON-well-formedness check only (full schema validation needs the agent
  to already exist, so it happens after registration via the endpoint
  above).

## Entrypoint validation (§31)

`validate_entrypoint(entrypoint_type, entrypoint)`:

| Type | Rule |
|---|---|
| `PYTHON_MODULE` | must match `module.path:function_name` |
| `HTTP_ENDPOINT` / `EXTERNAL_SERVICE` | must start with `https://`; rejects embedded credentials |
| `CONTAINER_IMAGE` | must include a tag or a `sha256:` digest |
| `SERVERLESS_FUNCTION` | must look like `provider:region:function-id` |
| `FUNCTION` (Phase 5.0 legacy default) | accepted leniently, no format check |
| anything else | `WARNING` — unrecognized type, not a hard failure |

Network calls (checking a domain is "approved," verifying a container
registry) are deliberately not made — SRS §31 itself says this should be
"optional and controlled," and this environment makes no outbound calls
during validation at all.

## URL credential rejection (§69)

`check_url_for_embedded_credentials` — a `scheme://user:pass@host` pattern
in `documentation_url`/`repository_url` is `BLOCKING`, both at registration
time (`POST /agents`) and update time (`PATCH /agents/{id}`).
