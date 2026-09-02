# ADR-0014 — Key material is a recoverable, fail-loud asset (never silently regenerated)

- **Status:** Accepted (amended 2026-09-03 by Phase M4.11a — see the Amendment section)
- **Date:** 2026-09-02
- **Deciders:** Phase M4.11 (Milestone 4 — Production Integrity Closure); amended by Phase M4.11a (Install-Mode Classification Hardening)
- **Supersedes:** —
- **Relates to:** ADR-0002 (PostgreSQL as sole datastore), the `ACT-VER-NFR-002`
  Known Deviation (local signing keys), `credential_crypto.py`'s Known Deviation
  (local Fernet key). Prerequisite for Milestone 5 (the security & trust
  milestone).

## Context

ACT holds two kinds of platform key material on the local filesystem
(`backend/.keys/`, gitignored):

1. **The Fernet encryption key** (`model_credentials.key`) — protects *every*
   ciphertext in the database: per-organization model-provider credentials,
   connector credentials, cached connector OAuth tokens, tool credentials, and
   identity-federation client secrets.
2. **The Ed25519 signing private keys** (`*.pem`) — behind every version
   attestation. Public keys live in the database (`signing_keys`,
   `signing_key_versions`), so historical signatures verify without the private
   key; but the identity cannot *sign again* without it.

Before M4.11 there were three compounding problems:

- **Neither is in any backup.** `.gitignore` excludes them from the Git bundle;
  `Export-ControlTowerSecrets.ps1` archived a fixed list that did not include
  them. RECOVERY.md documented this as "the one gap the scripts do not close."
- **A missing key was silently replaced.** `credential_crypto._load_or_generate_key()`
  and `LocalKeyProvider.ensure_key()` both generated and persisted a fresh key
  when the file was absent. On an established installation that means: new
  secrets encrypt and decrypt normally while *every pre-existing ciphertext
  silently becomes undecryptable*, and nothing fails loudly.
- **"File missing ⇒ new install" is the wrong signal.** A restored database has
  rows but no key file — indistinguishable, by that test, from a fresh install.

A control plane that asks a CISO to secure their AI estate cannot itself
silently destroy its own trust foundation on a restore.

## Decision

**Key material is treated as a recoverable asset with a fail-loud lifecycle,
not as throwaway local state.**

1. **The signal for NEW vs EXISTING is the presence of encrypted state in the
   database, not the absence of a file.** `detect_install_mode` probes every
   ciphertext-bearing table and the signed-attestation tables. Any row ⇒
   EXISTING. A restored database with rows and no key is therefore *always*
   EXISTING and can never be mistaken for a fresh install (M4.11-FR-012).

2. **An established install missing or holding the wrong key fails loud.**
   `verify_key_material(db)` runs once at startup (before serving traffic) and
   raises `KeyMaterialError` — deterministic, operator-actionable, **carrying no
   key or secret in the message**. It never generates a replacement.

3. **A wrong key fails too, not only an absent one.** A `key_material_canary`
   row stores `Fernet(key).encrypt(<public constant>)` keyed by the key's
   non-secret fingerprint. Startup decrypts it and asserts the constant comes
   back. On first upgrade (valid key, no canary yet) the canary is written only
   after a sample of real ciphertext independently decrypts.

4. **`credential_crypto` and `LocalKeyProvider` no longer generate key material
   as a side effect.** Generation moved behind an explicit `bootstrap()` /
   `python -m app.security.keys bootstrap`, which refuses to run on an EXISTING
   install. A genuine new install bootstraps deliberately; nothing is inferred.

5. **The key is obtained through an `EncryptionKeyProvider` seam** mirroring the
   existing `SigningProvider`. `LocalEncryptionKeyProvider` is the recovery-safe
   default. A KMS/Vault adapter attaches at the registry — documented as future
   work, no vendor SDK in the core (M4.11-FR-040/041).

6. **Backup and recovery are real and tested.** `app/security/backup.py`
   produces a manifest that *names* the required artifacts with SHA-256
   checksums and non-secret fingerprints — never their contents. Restore copies
   the files back (refusing to overwrite), then `python -m app.security.keys
   verify` runs the continuity check as part of the restore.

7. **Rotation is additive and does not re-encrypt everything.** The key ring is
   a `MultiFernet` over the active key plus `MODEL_CREDENTIAL_ENCRYPTION_KEYS`
   (retained prior keys). New data uses the active key; old data still decrypts.
   A full background re-encrypt pass is deferred with its architecture recorded
   (`docs/security/key-management.md`); nothing in M4.11 makes it harder.

## Consequences

- **A restore that omits the key material now fails at startup with a clear
  message**, instead of appearing to work while quietly corrupting access to
  every stored secret. This is strictly safer and is the point of the phase.
- **A fresh checkout on a new machine must bootstrap or restore a key** before
  the platform starts, where previously one was auto-generated. This is the
  intended behaviour; the bootstrap command and `ENCRYPTION_KEY_ALLOW_BOOTSTRAP`
  (for container first-run) make it a one-liner.
- **One additive table** (`key_material_canary`, migration `0052`), reversible,
  downgrade-tested, changing no decrypt behaviour for any existing row.
- **The `ACT-VER-NFR-002` deviation is mitigated, not fully closed.** A local
  symmetric key still enters process memory. The seam that makes an external
  KMS/Vault a config change is now in place for both encryption and signing.

## Residual risk

- **First-upgrade-with-the-wrong-key.** If an operator's very first M4.11
  startup already holds the wrong key *and* there is no canary yet *and* the
  trial-decrypt sample happens to be empty, the canary would be written for the
  wrong key. Mitigated by trial-decrypting real ciphertext before writing the
  canary on an EXISTING install; the only unguarded window is an EXISTING install
  with zero currently-readable ciphertext, which is vanishingly rare and still
  surfaces on the next real decrypt.
- **Trial-decrypt is a sample.** It reads the 200 most-recent rows per table. In
  the (production-forbidden) case of multiple encryption keys in one database it
  can be inconclusive. Documented; the canary is authoritative once written.
- **The archive contains raw key bytes.** It must be stored with the same
  AES-256 treatment as a database snapshot — the module writes the files, the
  operator encrypts the container (RECOVERY.md), exactly as for
  `Export-ControlTowerSecrets.ps1`.

## Amendment — Phase M4.11a (2026-09-03): the durable bootstrap marker

**The defect this amends.** Decision point 1 above — *"the signal for NEW vs
EXISTING is the presence of encrypted state in the database"* — was
incomplete. Presence of ciphertext is a *sufficient* EXISTING signal but not a
*necessary* one. An established installation can legitimately hold
organizations, agents, policies and deployments while having **zero** encrypted
credential rows and no signed attestation; under the as-built logic
`detect_install_mode` classified such an install NEW, and if it had lost its
key, `verify_encryption_material` would take the NEW path — silently minting a
fresh cryptographic identity under `ENCRYPTION_KEY_ALLOW_BOOTSTRAP`, or (worse)
directing the operator to bootstrap. That is the same silent-identity-loss this
ADR exists to kill, surviving in the one path M4.11 did not harden.

**The correction.** NEW is now a **positive durable fact**, not an inference
from absence:

- A single-row `installation_bootstrap` table (migration `0053`, additive,
  reversible, tenant-neutral) records **once** that this installation completed
  key bootstrap — a timestamp, the active key's non-secret fingerprint, the
  provider, a schema tag. No key, no secret.
- `detect_install_mode` ⇒ **EXISTING iff the marker is present OR any
  encrypted/signed state exists**; **NEW iff the marker is absent AND there is
  no such state**. Ciphertext/signed state stays a sufficient fast-path.
- The marker is written atomically with the canary + signing identity at a
  deliberate bootstrap, and **backfilled once at startup** after an existing
  key is verified (canary match or trial-decrypt) — so an install that
  bootstrapped under M4.11 becomes correctly EXISTING with no window in which
  it reads as NEW.
- A **five-state key taxonomy** (`KEY_ABSENT`, `KEY_MALFORMED`,
  `KEY_PRESENT_BUT_WRONG`, `KEY_PROVIDER_UNAVAILABLE`,
  `INSTALLATION_NEVER_BOOTSTRAPPED`) makes every failure mode a distinct,
  operator-actionable error code with no material leak.
  `KEY_PROVIDER_UNAVAILABLE` is explicitly **not** an install-mode signal — a
  transient provider outage never makes an established install look NEW and
  never falls back to generating a key.

**Consequence.** A restored/cloned database carries the marker, so a restore
without the key fails loud **even if the ciphertext tables were empty at backup
time** — strengthening the negative-proof anchor. Every other M4.11 guarantee
is unchanged; the classification only *tightens* (nothing that was EXISTING
becomes NEW).

**Residual risk retired.** The M4.11 residual note *"the only unguarded window
is an EXISTING install with zero currently-readable ciphertext"* is closed by
the marker.

## Revisit when

- **An external KMS/Vault provider is implemented.** Confirm `verify_key_material`
  validates a vault-held key (it currently deep-validates only `LocalKeyProvider`),
  and that its `check_available()` raises `ProviderUnavailableError` on a real
  outage so the `KEY_PROVIDER_UNAVAILABLE` path engages.
- **A right-to-erasure requirement reaches domain content.** Key rotation and
  crypto-shredding interact; that is a new phase.
- **Signing moves to Azure Key Vault** (closes `ACT-VER-NFR-002`). The signing
  half of `verify_key_material` becomes a vault reachability + identity check.
