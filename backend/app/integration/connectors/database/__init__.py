"""Phase 2.2.2 SRS ACT-INT-FR-120..127 — the generic database connector.

Turns declared, parameterized queries against PostgreSQL or MySQL (SQL
Server: driver-pending, see ``drivers.py``) into governed tools. **The
model never writes SQL** — not sanitized, not escaped, not validated:
absent. An integration engineer declares named queries with parameter
placeholders at configuration time; a model names one and supplies bound
parameter *values*. There is no code path anywhere in this package that
takes model-derived text and places it into SQL structure — see
``executor.py``'s module docstring for exactly how that absence is
enforced by construction, not convention.

Five modules, mirroring 2.2.1's own split:

- ``declaration.py`` — the declared-query model, its JSON Schema,
  ``parse_declaration``/``tool_contracts_for`` (one ``ToolContract`` per
  declared query, ``ACT-INT-FR-121``), and ``classify_query`` (read vs.
  write, by inspecting *declared, trusted* SQL — never model output).
- ``drivers.py`` — the PostgreSQL/MySQL dialect abstraction: connection
  URL construction (credential never rendered to a string), and a
  per-instance connection-pool cache.
- ``executor.py`` — the security-critical component. Its only public
  entry point takes a declared query plus a validated parameter mapping;
  it has no method that accepts raw SQL from a caller. Bound parameters,
  a row limit, and a timeout are enforced here.
- ``connector.py`` — ``DatabaseConnector`` itself.
- ``invoker.py`` — the platform bridge (mirrors
  ``app/integration/connectors/rest/invoker.py`` exactly) that resolves an
  instance, applies its credential, and actually runs a declared query —
  the first genuinely invocable database tool in this codebase.

``declaration.py`` imports only from ``app.integration.sdk`` and the
standard library. ``drivers.py``/``executor.py`` additionally import
SQLAlchemy (the platform's own existing, already-relied-upon database
toolkit — not a new dependency; only ``PyMySQL``, a pure-Python DBAPI
driver, was newly added, see ``requirements.txt``). ``connector.py``
additionally imports one specific, documented, justified exception type
from ``app.integration.errors`` for its config-time write-permission
check (``ACT-INT-FR-125`` needs its own error code, unlike anything
2.2.1 needed at configuration time) — see that module's own docstring.
``invoker.py`` is platform bridge code, not SDK-surface-restricted,
exactly as 2.2.1's own ``invoker.py`` is."""
