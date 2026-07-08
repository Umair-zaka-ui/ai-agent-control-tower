# Sequence — Token refresh, rotation, and reuse detection

> Traced from `AuthenticationService.refresh` and `frontend/src/services/tokenRefresh.ts`.
> This is the flow most likely to be probed in a security review.

## Normal rotation

```mermaid
sequenceDiagram
    autonumber
    participant SPA as Dashboard SPA
    participant R as auth/routes.py
    participant A as AuthenticationService
    participant RT as RefreshRotationService
    participant S as SessionLifecycleService
    participant T as TokenService
    participant DB as PostgreSQL

    Note over SPA: timer fires 5 min before expiry,<br/>or a 401 arrives
    SPA->>R: POST /api/v1/auth/refresh {refresh_token}
    R->>A: refresh(token, ip, ua)

    A->>RT: find(plaintext)
    RT->>DB: SELECT … WHERE token_hash = sha256(plaintext)
    DB-->>RT: record | None
    Note over A: None → 401 INVALID_REFRESH_TOKEN

    A->>RT: is_reuse(record)?
    Note over RT: revoked_at IS NOT NULL<br/>AND rotated_to_id IS NOT NULL
    RT-->>A: false

    A->>RT: is_valid(record)?  (not expired, not revoked)
    A->>DB: SELECT session
    A->>S: assert_usable(session)  (idle + absolute)
    A->>A: _assert_identity_active(user)

    A->>RT: rotate(record)
    RT->>DB: UPDATE old SET revoked_at, rotated_to_id
    RT->>DB: INSERT new refresh_token
    A->>S: touch(session) → slides idle deadline
    A->>T: create_access_token(ctx)
    A->>DB: COMMIT + TOKEN_REFRESHED event
    A-->>SPA: 200 {access_token, refresh_token}

    SPA->>SPA: setAuthTokens(); reschedule timer
```

Rotation is unconditional: **every** use of a refresh token revokes it and issues
a successor, chained by `rotated_to_id`. A refresh token is therefore single-use.

## Reuse detection — the theft path

```mermaid
sequenceDiagram
    autonumber
    actor Thief
    participant SPA as Legitimate SPA
    participant A as AuthenticationService
    participant RT as RefreshRotationService
    participant S as SessionSecurityService
    participant EV as SecurityEventService
    participant DB as PostgreSQL

    Note over Thief,SPA: Thief has exfiltrated refresh token RT₁<br/>(e.g. XSS against localStorage)

    SPA->>A: refresh(RT₁)
    A->>RT: rotate(RT₁) → RT₂
    Note right of DB: RT₁: revoked_at set, rotated_to_id = RT₂
    A-->>SPA: 200 {RT₂}

    Note over Thief: replay of a rotated token
    Thief->>A: refresh(RT₁)
    A->>RT: find(RT₁) → record
    A->>RT: is_reuse(record)?
    RT-->>A: TRUE — revoked AND rotated

    rect rgb(60,20,20)
    Note over A,DB: Theft response
    A->>RT: revoke_family(family_id)
    RT->>DB: UPDATE refresh_tokens SET revoked_at WHERE family_id = …
    A->>S: flag_token_reuse(session)
    S->>DB: UPDATE auth_sessions SET status=SUSPICIOUS,<br/>revoked_reason=TOKEN_REUSE, security_score-=80
    A->>EV: TOKEN_REUSE_DETECTED + REFRESH_TOKEN_REUSED
    A->>DB: COMMIT
    end

    A-->>Thief: 401 REFRESH_TOKEN_REUSED
    Note over SPA: RT₂ is now dead too.<br/>Both parties must re-authenticate.
```

The design intent: a stolen refresh token is *useful only until the legitimate
client next refreshes*. At that moment the replay is detected and the session
dies for everyone. The victim is logged out — that is the correct, deliberate
trade: an interrupted session beats a silently hijacked one.

## Revocation is immediate (closed in Part 4.2.2.2)

> Until Part 4.2.2.2 this section documented a **known gap**: `authenticate`
> validated the JWT signature without loading the session, so a revoked session's
> access token kept working for up to 15 minutes. That gap is closed.

`authenticate` now loads `auth_sessions` by primary key and revalidates it on every
authenticated request ([ADR-0007](../adr/0007-stateful-session-validation.md)).

```mermaid
sequenceDiagram
    participant Thief
    participant D as dependency.authenticate
    participant L as SessionLifecycleService
    participant DB as PostgreSQL

    Note over Thief: holds access token AT₁ (≤15 min TTL)<br/>session was just revoked
    Thief->>D: GET /api/v1/auth/me  (Bearer AT₁)
    D->>D: validate JWT signature + exp
    D->>DB: SELECT auth_sessions WHERE id = session_id
    D->>L: assert_usable(session)
    L-->>D: raise SESSION_REVOKED
    D-->>Thief: 401 ✅
```

One primary-key lookup answers every question at once: revoked? absolutely expired?
idle? suspicious? Each raises a **distinct** error code, because a client must tell
"you were logged out" apart from "you idled out" apart from "we think your token was
stolen" — the three demand different UX.

| Surface | Worst case after revocation |
| ------- | --------------------------- |
| `/api/v1/auth` | **immediate** — next request is refused |
| Legacy `/auth/login` | **24 hours** — no `session_id` claim, so no session to check |

The legacy surface is now the platform's only non-revocable credential, and the
strongest argument for completing
[ADR-0005](../adr/0005-additive-identity-layer-alongside-legacy-auth.md).

Pinned by `test_access_token_dies_with_the_session` — the inverse of the assertion
that used to guard the gap.

## Client-side behaviour

`frontend/src/services/tokenRefresh.ts` coalesces concurrent refreshes into one
network round-trip via a module-level `inFlight` promise, and uses a **bare axios
instance** so a refresh can never recurse through the 401 interceptor.

```mermaid
flowchart LR
    t["Silent timer<br/>expiry − 5 min"] --> f{"inFlight?"}
    e["401 from apiClient"] --> f
    f -->|yes| j["await existing promise"]
    f -->|no| n["POST /auth/refresh<br/>(bare axios)"]
    n -->|200| ok["setAuthTokens()"]
    n -->|4xx| bad["clearAuthStorage()<br/>→ session-expired modal"]
```

Tokens live in `localStorage`, which is readable by any script on the origin.
This is a deliberate, documented risk — see
[threat model](../security/threat-model.md#i-information-disclosure).
