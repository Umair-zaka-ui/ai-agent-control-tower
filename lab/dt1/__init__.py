"""DT1 - the Digital Twin (Stage 1: the canonical estate and its truth).

Lab tooling. Imports nothing from the ACT product (``app``); the one exception is
``grounding.py``, which introspects model metadata read-only before generation
and is excluded from the architecture guard by name. Everything else here runs
without a database and without ACT.

Version constants are inputs to determinism (§7 of the approved prompt):
same ``DT1_CANONICAL_SEED`` + same ``GENERATOR_VERSION`` + same
``schema_grounding_version`` => byte-identical artifacts.
"""

from .dt1_versions import (  # noqa: F401 - single source of truth for the version constants
    AGENT_PROPERTY_MATRIX_VERSION, DT1_CANONICAL_SEED, ESTATE_TRUTH_SCHEMA_VERSION, GENERATOR_VERSION,
    OBSERVABILITY_CONTRACT_VERSION,
)

REALITY_CLASSES = (
    "ACTIVE_REAL_PROCESS_REQUIRED_STAGE2",
    "REAL_EXTERNAL_SERVICE_REQUIRED_STAGE2",
    "SIMULATED_ASSET",
    "DORMANT_ASSET",
)
OBSERVABILITY_CLASSES = ("OBSERVE", "PARTIALLY_OBSERVE", "NOT_OBSERVE", "ENFORCE", "REFUSE")
