"""Phase 2.2.1 SRS ACT-INT-FR-100..106 — the generic REST connector.

Turns any HTTP/JSON API into governed tools by declaration: a connector
instance's ``configuration`` names a base URL, an authentication scheme, and
a set of endpoints (method, path template, argument mapping, response
extraction, optional pagination) — no code. See
``docs/integration/connectors.md``'s "Generic REST Connector (Phase 2.2.1)"
section for the full declaration reference and the worked vendor-like
example.

This package is split into five modules exactly as the build prompt's own
§6 lists them, each with a narrow job:

- ``declaration.py`` — the declaration's shape (``RestEndpoint``,
  ``RestDeclaration``), its JSON Schema, and ``parse_declaration``/
  ``tool_contracts_for`` (structural + semantic validation, and the
  endpoint -> ``ToolContract`` derivation ``ACT-INT-FR-102`` asks for).
- ``templating.py`` — injection-safe request templating: tool arguments
  become path/query/header/body values, never structure.
- ``extraction.py`` — response -> tool output, plus output-schema
  validation where declared.
- ``pagination.py`` — bounded offset/limit, page-number, and cursor
  pagination drivers.
- ``connector.py`` — ``RestConnector`` itself, the ``Connector`` ABC
  implementation.

Every one of the five imports only from ``app.integration.sdk`` (plus the
standard library) or from each other — the same containment discipline
2.1.4's worked example established, now proven against a connector that
does a real job (see ``tests/integration/test_rest_connector.py``'s AST
import-inspection test). ``invoker.py`` is deliberately **not** one of the
five: it is the platform bridge that makes a configured instance's
endpoints actually invocable (``ACT-INT-FR-102``'s other half — "a REST
connector nobody can invoke proves nothing", build prompt §3), and sits
above the connector exactly where ``app/integration/health.py`` and
``app/integration/service.py`` already sit above every ``Connector``
implementation — it may, and does, import the registry and the
authentication framework directly."""
