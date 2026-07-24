"""Phase 5.7a.1 SRS ACT-MDL-FR-001..010 — model provider abstraction.

``base.py`` defines the ``ModelProvider`` contract every implementation
satisfies; ``types.py`` is the provider-neutral internal representation
every adapter translates to/from; ``registry.py`` resolves a provider
identifier to an implementation (explicit registration, not directory-
scanning discovery); ``mock.py`` is the first (and, this sub-phase, only)
concrete provider. Real providers (OpenAI-compatible, etc.) land in
Phase 5.7a.2 as additional modules in this package — nothing here should
need to change to add one.
"""

from __future__ import annotations
