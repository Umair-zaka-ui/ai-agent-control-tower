"""Phase 5.2.4 SRS ACT-VER-FR-060..071 — signing provider selection.

Swapping providers (e.g. to Azure Key Vault at deployment) is a
configuration change here (``settings.SIGNING_PROVIDER``), not a rewrite of
any calling code — that is the entire point of the ``SigningProvider``
abstraction in ``base.py``.
"""

from __future__ import annotations

from app.core.config import settings
from app.runtime.versioning.signing.base import SigningProvider
from app.runtime.versioning.signing.local import LocalKeyProvider

_PROVIDERS: dict[str, type[SigningProvider]] = {
    "LOCAL": LocalKeyProvider,
}


def get_signing_provider() -> SigningProvider:
    provider_cls = _PROVIDERS.get(settings.SIGNING_PROVIDER)
    if provider_cls is None:
        raise ValueError(
            f"Signing provider '{settings.SIGNING_PROVIDER}' is not configured in this "
            f"environment. Supported: {sorted(_PROVIDERS)}."
        )
    return provider_cls()
