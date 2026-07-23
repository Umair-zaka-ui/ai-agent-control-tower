"""Phase 5.2.4 SRS ACT-VER-FR-060..071 — signing provider abstraction.

``SigningProvider`` (``base.py``) is the interface every implementation
must satisfy; ``LocalKeyProvider`` (``local.py``) is the only one today.
``registry.py`` selects one from settings, so swapping to Azure Key Vault
at deployment is a configuration change, not a rewrite of any calling code.
"""

from __future__ import annotations
