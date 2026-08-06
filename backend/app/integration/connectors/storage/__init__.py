"""Phase 2.2.3 SRS ACT-INT-FR-140..145 — the generic file & object storage
connector.

The direct analogue of 2.2.2's "the model never writes SQL": **a
model-supplied path can never escape its declared scope.** Where the
database connector made raw SQL structurally unreachable, this connector
makes an out-of-scope filesystem path or object-store key structurally
unreachable — a supplied path is canonicalized, then proven to resolve
inside its declared boundary, *before* any read or write is attempted.
Anything that cannot be proven in-scope is denied, never "sanitized and
allowed anyway."

Five modules, the same split 2.2.2 established:

- ``scope.py`` — the security core. Pure stdlib, zero platform
  dependencies, isolated and exhaustively unit-testable with no live
  storage: given a declared boundary and a supplied path/key, answers
  "is the resolved target inside scope?" Canonicalize, then contain —
  never the reverse, and never validate one string while operating on a
  different, later-resolved one (no TOCTOU gap).
- ``declaration.py`` — the config schema, per-scope declaration parsing,
  and ``tool_contracts_for``. SDK-surface-restricted, plus one narrow,
  documented deviation (see its own module docstring) for
  ``STORAGE_SCOPE_INVALID``, exactly the shape 2.2.2's ``connector.py``
  established for ``DB_WRITE_NOT_PERMITTED``.
- ``backends.py`` — filesystem and S3-compatible object storage behind
  one dispatch interface (Azure Blob is backend-pending, mirroring
  2.2.2's SQL Server precedent). Raises its own local exceptions,
  translated to platform errors by ``invoker.py`` only.
- ``connector.py`` — ``StorageConnector``, built through the SDK
  surface, plus the same one documented deviation
  (``StorageWriteNotPermittedError``) 2.2.2's ``connector.py`` used for
  its own read-only rejection.
- ``invoker.py`` — the tool-invocation bridge (mirrors 2.2.2's
  ``invoker.py`` exactly): resolves the instance, resolves its
  credential, calls ``scope.resolve_and_contain`` before any backend
  call, dispatches through ``backends.py``, and records every access in
  the platform audit trail. Not wired into the model-driven tool loop —
  Milestone 1 stays untouched."""
