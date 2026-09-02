"""Phase M4.11 — Production Integrity Closure: key-material recovery &
fail-loud integrity.

This package makes ACT's encryption and signing key material a recoverable,
fail-safe asset rather than a silent-loss hazard. Its guarantee, in one
sentence: **an established installation that is missing or holding the wrong
encryption/signing key fails loud and recoverable — it never silently
regenerates key material and continues, which would render every
pre-existing ciphertext undecryptable while nothing appeared wrong.**

Structure:

- ``errors``            — ``KeyMaterialError`` (deterministic, operator-actionable, no secret in the message)
- ``encryption_provider`` — the ``EncryptionKeyProvider`` seam (mirrors ``SigningProvider``) + the local recovery-safe default
- ``install_mode``      — ``detect_install_mode`` — NEW vs EXISTING, decided by the *presence of encrypted state in the database*, not the absence of a file
- ``canary``            — the key-validation canary: a wrong key fails, not only an absent one
- ``key_integrity``     — ``verify_key_material`` — the fail-loud startup/first-use check (called from ``app.main``'s lifespan)
- ``bootstrap``         — the deliberate, documented new-install bootstrap contract (``python -m app.security.keys``)
- ``backup``            — the supported key-material recovery archive (names artifacts + checksums, never exposes contents)
"""
