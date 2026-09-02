"""Phase M4.11 — the one exception this package raises when key material is
missing or invalid on an established installation.

It is raised to **stop the platform loudly**, so its contract matters:

- ``code`` is a stable, greppable identifier an operator (or a runbook) can
  match on.
- ``str(exc)`` and every attribute are safe to print, log and surface —
  they identify *the operational problem* (which key, where it is expected,
  what to do), and **never contain a key, a secret, a Fernet token or a
  canary plaintext** (M4.11-FR-003, AC-04, AC-14). Callers may log this
  exception verbatim.
"""

from __future__ import annotations


class KeyMaterialError(RuntimeError):
    """Deterministic, operator-actionable failure. Fail loud, never
    regenerate."""

    def __init__(self, code: str, problem: str, *, remediation: str) -> None:
        self.code = code
        self.problem = problem
        self.remediation = remediation
        super().__init__(f"{code}: {problem} — {remediation}")
