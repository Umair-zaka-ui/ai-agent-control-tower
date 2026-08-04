"""Phase 2.1.2 SRS ACT-INT-FR-027 — mutual TLS scheme.

A client certificate and private key configure the outbound TLS
handshake itself, not a header — ``apply()`` sets
``OutboundRequest.tls_client_cert`` rather than a header value. The
private key never crosses this method as anything other than the same
PEM string that was decrypted one call frame up
(``ConnectorCredentialService.resolve_and_apply``); nothing here writes
it to a file, a log, or a second variable that outlives this call,
mirroring the signing-key discipline Phase 5.2.4 established for private
key material."""

from __future__ import annotations

from typing import Any, Mapping

from app.integration.auth.base import AuthScheme, OutboundRequest


class MTLSScheme(AuthScheme):
    def required_fields(self) -> tuple[str, ...]:
        return ("client_cert_pem", "client_key_pem")

    def apply(self, request: OutboundRequest, credential: Mapping[str, Any]) -> OutboundRequest:
        return request.with_tls_client_cert(
            str(credential["client_cert_pem"]), str(credential["client_key_pem"]),
        )
