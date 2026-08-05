"""Phase 2.2.1 SRS ACT-INT-FR-104 — response extraction.

Maps a REST endpoint's raw JSON response to the tool's declared output: a
dotted ``response_field`` path (e.g. ``"data.items"``) navigates into the
body and returns whatever is found there; no ``response_field`` at all
means "the whole body is the output," the simplest and most common case.
Reuses ``jsonschema`` directly for the optional ``output_schema`` check —
the same library, called the same way, ``app/integration/base.py``'s
``validate_configuration_schema`` and ``app/runtime/services.py``'s own
``_validate_schema`` already use; not imported from either (both are a
sibling module's private/domain-specific helper, not a published shared
utility — the same reasoning ``base.py``'s own docstring gives for not
importing ``app.runtime.services``'s private validator)."""

from __future__ import annotations

from typing import Any, Mapping

import jsonschema


class ResponseExtractionError(Exception):
    """A REST endpoint's response could not be extracted or validated per
    its own declaration — see ``invoker.py`` for how this becomes
    ``RestExtractionFailedError`` at the platform boundary."""


def extract_output(payload: Any, response_field: str | None) -> Any:
    """Navigates ``response_field`` (dot-separated) into ``payload``, or
    returns ``payload`` unchanged when no field is declared."""
    if not response_field:
        return payload
    node = payload
    for part in response_field.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise ResponseExtractionError(f"field path '{response_field}' was not found in the response body")
    return node


def validate_output_schema(output: Any, schema: Mapping[str, Any]) -> None:
    try:
        jsonschema.validate(instance=output, schema=dict(schema))
    except jsonschema.ValidationError as exc:
        raise ResponseExtractionError(f"extracted output does not match the declared output_schema: {exc.message}") from exc
    except jsonschema.SchemaError as exc:
        raise ResponseExtractionError(f"the endpoint's own output_schema is invalid: {exc.message}") from exc
