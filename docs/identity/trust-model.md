# Trust Model (Phase 4 Part 4.2.1)

## Trust zones (SRS §4)

```
Browser / Dashboard        (untrusted)
        ↓
Public API boundary        (untrusted input)
        ↓
Authentication layer       ← establishes trust
        ↓
Authorization layer        ← enforces what the identity may do
        ↓
Business services          (trusted; act on IdentityContext only)
        ↓
Database / secrets / audit (trusted)
```

**Nothing outside the authentication layer is trusted.** A request carrying a
token is not trusted until the token is validated.

## What every request is validated for

Even a well-formed token is checked for all of:

| Check | Where |
| ----- | ----- |
| Signature | `TokenService.decode` (JWT signature) |
| Expiration | `decode` → `TOKEN_EXPIRED` |
| Issuer (`iss`) | `decode` (issuer=`ai-agent-control-tower`) |
| Audience (`aud`) | `decode` (audience=`ai-agent-control-tower-api`) |
| Token type | `validate_access_token` (must be `access`) |
| Identity status | `AuthenticationService._assert_identity_active` (ACTIVE only) |
| Session status | `SessionService.is_active` (not revoked/expired) |
| Revocation status | `TokenService.is_revoked` (token_revocations — Part 4.2.2) |
| Permission scope | authorization layer / `require_scope` |

## Identity types & their trust posture (SRS §3)

| Type | Authenticates via | Session? | Notes |
| ---- | ----------------- | -------- | ----- |
| `HUMAN_USER` | password → JWT + refresh | yes | dashboard users |
| `AI_AGENT` | API key / agent token | no (usage history) | autonomous work |
| `SERVICE_ACCOUNT` | client secret / service token | no | backend automation |
| `EXTERNAL_CLIENT` | client credentials | no | Power BI, Zapier, … |
| `SYSTEM` | internal (`SYSTEM_INTERNAL`) | no | policy/risk/audit engines |

## Threat model (SRS §23)

| Threat | Mitigation | Status in 4.2.1 |
| ------ | ---------- | --------------- |
| Token theft | short-lived access tokens (15 min) | ✅ |
| Refresh token replay | rotation + reuse detection → family revoke | ✅ (session-family) |
| API key leakage | keys stored hashed; expiry + status | ✅ storage; verify wired 4.2.2 |
| Credential stuffing / brute force | login attempt tracking + generic errors | ⏳ table planned (4.2.2) |
| Session hijacking | session revocation; device binding placeholder | ✅ revoke; binding planned |
| Privilege escalation | permissions resolved server-side per request | ✅ |
| Expired token reuse | expiry validated every request | ✅ |
| Disabled identity using old token | identity status checked on every request | ✅ |
| Compromised service account | status/expiry checks + revocation | ✅ model; enforce 4.2.2 |
| Single-factor account takeover | assurance levels (AAL) + step-up MFA seam; `require_assurance(AAL2)` gates sensitive routes | ✅ seam; verifier 4.2.x |
| Challenge-token misuse | `mfa_pending` tokens rejected by `require_scope` / `require_assurance` | ✅ |

Legend: ✅ implemented in 4.2.1 · ⏳ designed, table/enforcement in 4.2.2/4.2.3.

## Authentication assurance (SRS §24)

Every context/token carries an Authenticator Assurance Level:

| Level | Meaning | Issued by |
| ----- | ------- | --------- |
| `AAL0` | primary factor verified, MFA still pending | login when `_mfa_required` (challenge token) |
| `AAL1` | single factor (password / API key / secret) | standard login |
| `AAL2` | multi-factor satisfied | `complete_mfa` after second factor |

An `AAL0` (`mfa_pending`) token can only be exchanged at the MFA-verify step; it
never satisfies `require_scope` or `require_assurance`.
