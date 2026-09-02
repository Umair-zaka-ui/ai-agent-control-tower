# Key management, backup, recovery & rotation

> **Phase M4.11 — Production Integrity Closure.** This document is the
> operator-facing procedure for ACT's platform key material: how a fresh
> install bootstraps, how normal startup validates, how to back the keys up,
> how to restore them, what a missing or wrong key does now (it fails loud —
> it no longer silently regenerates), how signing and encryption continuity
> are preserved, and the rotation architecture.
>
> See also: [ADR-0014](../architecture/adr/0014-key-material-recovery-and-fail-loud-integrity.md),
> [RECOVERY.md](../../RECOVERY.md), `app/security/`.

## What key material exists

| Path | Setting | Protects | Public half in DB? |
|---|---|---|---|
| `backend/.keys/model_credentials.key` | `MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH` (or `MODEL_CREDENTIAL_ENCRYPTION_KEY` inline) | **Every ciphertext in the database** — provider credentials, connector credentials, connector OAuth tokens, tool credentials, federation client secrets | n/a (symmetric) |
| `backend/.keys/{key_id}.v{n}.pem` | `SIGNING_KEY_PATH` | Ed25519 **private** signing keys behind every version attestation | Yes — `signing_keys`, `signing_key_versions` |

Both directories are gitignored. **Neither rebuilds itself** — that is the
whole point of M4.11.

## NEW install vs EXISTING install (the signal)

The platform decides which situation it is in by **whether the database holds
any encrypted or signed state** — not by whether a key file exists:

- **NEW_INSTALL** — no provider/connector/tool credential, no cached OAuth
  token, no federation client secret, no signed attestation. A deliberate
  bootstrap is safe.
- **EXISTING_INSTALL** — any of the above. A missing or wrong key is *lost or
  invalid key material*. The platform fails loud; it never bootstraps.

A restored database with rows but no key file is therefore **always EXISTING**
— the rows are the proof. `python -m app.security.keys status` shows the
detected mode and which tables carry encrypted state.

## Fresh install — deliberate bootstrap

A genuine new installation has no key. Provision one, once, deliberately:

```bash
cd backend
# option A — let the platform generate and persist local key material:
.venv/Scripts/python.exe -m app.security.keys bootstrap
# option B — supply your own Fernet key (production-recommended):
#   set MODEL_CREDENTIAL_ENCRYPTION_KEY=<urlsafe-base64 32-byte key> in backend/.env
```

`bootstrap` refuses to run if the database already holds encrypted or signed
state (`BOOTSTRAP_REFUSED_EXISTING_INSTALL`) — nothing overrides that. It
provisions the encryption key, the default signing identity, and the
key-validation canary, and prints their non-secret fingerprints.

For a container's first run you may instead set `ENCRYPTION_KEY_ALLOW_BOOTSTRAP=1`,
which lets the **startup check** bootstrap *only* when the database has zero
encrypted state. It is off by default.

**Immediately back up the new key material** (next section).

## Normal startup — validation

On every startup, before serving any request, `app.main`'s lifespan calls
`verify_key_material(db)`:

1. Detect install mode.
2. Encryption key: present? valid Fernet key? Then — does the
   `key_material_canary` row for this key's fingerprint decrypt to the known
   constant? If there is no canary row yet (first startup after the `0052`
   migration), trial-decrypt a sample of real ciphertext; if that works, write
   the canary.
3. Signing: every `signing_keys` row must still have a usable private key on
   disk whose public half matches the database.

Success logs one line:
`key-material integrity OK — install=EXISTING_INSTALL encryption[provider=LOCAL fp=… validation=CANARY_MATCH] signing[keys=1 validation=OK]`.

Any failure raises `KeyMaterialError` and aborts startup. Every failure
message names the operational problem and the remediation and **contains no
key, secret, or ciphertext**.

| Code | Means | Do |
|---|---|---|
| `ENCRYPTION_KEY_MISSING_ESTABLISHED_INSTALL` | rows exist, no key | restore `model_credentials.key` from the recovery archive |
| `ENCRYPTION_KEY_MISMATCH` / `ENCRYPTION_KEY_CANNOT_DECRYPT` | wrong key | restore the correct key; do not start with this one |
| `ENCRYPTION_KEY_MISSING_NEW_INSTALL` | no rows, no key | `python -m app.security.keys bootstrap` |
| `SIGNING_PRIVATE_KEY_MISSING` | `signing_keys` row but no `.pem` | restore `backend/.keys/{key_id}.v{n}.pem` |
| `SIGNING_KEY_MISMATCH` | `.pem` present but wrong | restore the correct `.pem` |

## Backup

```bash
cd backend
.venv/Scripts/python.exe -m app.security.keys backup C:\path\to\recovery-target\key-material
```

This writes `keys/` (a copy of the encryption key file and every signing
`.pem`), `MANIFEST.json` (which **names** the artifacts and records a SHA-256
and a non-secret fingerprint for each — never the contents), and
`SHA256SUMS.txt`.

The written files contain raw key bytes. Store the containing folder with the
**same AES-256 treatment as a database snapshot** — 7-Zip to the marked
recovery target, passphrase in a password manager (see RECOVERY.md). The
platform module writes the plain files; encrypting the container is the
operator step, exactly as for `Export-ControlTowerSecrets.ps1`.

Do this after every bootstrap and after every rotation.

## Restore

A full recovery restores three things, in order:

1. **Database** — `scripts/backup/Restore-ControlTower.ps1` (unchanged;
   refuses a non-empty target, restores in one transaction, verifies against
   the snapshot manifest).
2. **Key material** — decrypt the key-material archive to a scratch directory
   and copy `keys/*` into `backend/.keys/` (mode `0600` where supported). The
   `restore_key_material_archive` helper does this and **refuses to overwrite
   an existing encryption key file** — the restore-into-unsafe-target
   safeguard.
3. **`.env`** — create `backend/.env` (or decrypt the secret archive).

Then run the continuity check **before serving traffic**:

```bash
cd backend
.venv/Scripts/python.exe -m app.security.keys verify
```

It must print `OK`. If it prints `FAIL …`, the message says which key is
wrong or missing and what to restore. A half-restored state fails loud here;
it does not partially serve.

## Continuity guarantees

After an authorized restore with the correct key material:

- **Historical ciphertext decrypts** — the key ring is unchanged, so every
  stored credential/token/secret reads back exactly as before.
- **Historical signatures verify** — public keys are in the database and were
  restored with it; `AttestationService.verify` re-checks them live.
- **New signing continues** — the restored private key signs again under the
  same identity. Rotation history (`signing_key_versions`) is intact.

The negative proofs (`test_key_material_integrity.py`): restore the database
**without** the key ⇒ loud deterministic failure, no regeneration, does not
serve; restore with the **wrong** key ⇒ deterministic safe failure.

## Rotation architecture

### Encryption key

Implemented (bounded, no migration, no big re-encrypt transaction):

1. `python -m app.security.keys rotate-encryption` prints a new key and the
   procedure.
2. Set `MODEL_CREDENTIAL_ENCRYPTION_KEY` to the **new** key; move the old key
   into `MODEL_CREDENTIAL_ENCRYPTION_KEYS` (a list, newest-first).
3. Restart. The key ring is a `MultiFernet`: new writes use the new key, all
   existing ciphertext still decrypts under the retained old key. The startup
   check registers a canary for the new fingerprint.
4. Re-encrypt lazily (every credential re-encrypts under the active key on its
   next write) **or** run a background re-encrypt pass.

**Deferred with architecture recorded:** a first-class background re-encrypt
job (batched, resumable, per-tenant, audited) that walks every ciphertext
table and rewrites each row under the active key, then lets the old key be
dropped from `MODEL_CREDENTIAL_ENCRYPTION_KEYS`. It is a scheduler handler
(Phase 3.8 shape), not a single transaction. Nothing in M4.11 blocks it —
the key ring and the fingerprint-keyed canary are exactly the seams it needs.

### Signing key

Already implemented (Phase 5.2.4): `SigningKeyService.rotate(key_id)` mints a
new version, retains every prior version's public key in
`signing_key_versions` (so old signatures stay verifiable forever), and makes
the new version current. `revoke(key_id)` marks affected signatures
`KEY_REVOKED` without altering the bytes. M4.11 adds only the fail-loud check
that the current version's private key is actually present and matches.

Active-key identification: `signing_keys.current_version`. Previous-key
retention: `signing_key_versions`. Revocation: `signing_keys.status` +
per-signature `verification_status`. Rollback: restore the prior `.pem` and
`current_version`.

## External provider seam (KMS / Vault) — future work

`EncryptionKeyProvider` (`app/security/encryption_provider.py`) mirrors
`SigningProvider`. `LocalEncryptionKeyProvider` is the default. A production
adapter — AWS KMS, HashiCorp Vault, or Azure Key Vault — implements the same
four methods (`is_present`, `get_key`, `fallback_keys`, `bootstrap`) and
registers in `_REGISTRY`, selected by `ENCRYPTION_KEY_PROVIDER`. It would
fetch key bytes from the vault at startup rather than reading a file; a
misconfigured or unreachable vault raises `KeyMaterialError` (fail loud) — it
never falls back to generating a key.

**No vendor lock-in:** the core imports no vendor SDK (asserted structurally
by `test_key_material_integrity.py`). At most one external provider ships per
the phase scope; the others are this paragraph.
