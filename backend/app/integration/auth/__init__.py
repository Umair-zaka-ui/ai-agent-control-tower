"""Phase 2.1.2 SRS ACT-INT-FR-020..028 — the connector authentication framework.

A pluggable set of ``AuthScheme`` implementations (static API key, bearer
token, HTTP basic, OAuth2 client credentials, OAuth2 authorization code,
mTLS) that apply a resolved credential to an outbound request. Credential
*storage* and *resolution* (``service.py``) reuse
``app/runtime/providers/credential_crypto.py`` directly — this package
never encrypts anything itself.
"""
