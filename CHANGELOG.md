# Changelog

All notable changes to the AI Agent Control Tower are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/); the project is pre-1.0 and
versions track the roadmap phases rather than semver guarantees.

## [0.4.0] — Phase 4.2.2 · Enterprise Human Authentication

The identity platform now spans authentication → sessions → registration → password
policy → recovery → account protection, closed out by an integration & release pass.

### Part 4.2.2.3.5 — Backend APIs, integration & release (close-out)

- **Added** cross-cutting HTTP middleware (`app/core/middleware.py`):
  - `RequestContextMiddleware` — a stable `X-Request-ID` on every request/response
    (inbound if supplied, else a generated UUID4), threaded into the error envelope (§15).
  - `SecurityHeadersMiddleware` — `X-Content-Type-Options: nosniff`, `X-Frame-Options:
    DENY`, `Referrer-Policy`, deny-by-default `Content-Security-Policy`,
    `Permissions-Policy`, and opt-in HSTS on every response, errors included (§16, §23).
- **Added** `SECURITY_*` and `REQUEST_ID_HEADER` settings; `docs/api/http-conventions.md`
  (consolidated endpoint map, response format, error codes, correlation & headers);
  `docs/testing/strategy.md`; this changelog.
- **Verified** the §4 API contract end-to-end against the shipped surface. Documented the
  deliberate deviations rather than retrofitting them: **bare success bodies** with an
  **enveloped error** contract (§5), and admin/invitation/password routes living under
  `/identity` & `/security`. No unreachable `logout-all`/`device-delete` stubs added.
- **Tests**: backend **346 passing** (+5 hardening tests); measured **92%** line coverage
  on `app.identity` + `app.core`. Frontend tsc + production build clean.

### Part 4.2.2.3.4 — Account protection & risk-based authentication

- **Added** risk scoring (0–100), progressive lockout (15m→30m→1h→24h→review),
  brute-force/credential-stuffing detection, blocked IPs, protection-rule engine, adaptive
  rate limiting and a CAPTCHA seam. Tables `account_locks`, `identity_risk_events`,
  `blocked_ips`, `identity_protection_rules` (migration `0015`). Security console UI.
- **Known limitations**: MFA `CHALLENGE` decisions fail-safe **deny** until MFA enrolment
  lands; CAPTCHA is a disabled, provider-agnostic seam.

### Part 4.2.2.3.3 — Password reset, account recovery & email change

- **Added** forgot/reset password (30-min single-use tokens, non-enumerating responses,
  revokes all sessions), verified email change, recovery-events dashboard (migration `0014`).

### Part 4.2.2.3.2 — Enterprise password policy & credential management

- **Added** single-source password policy, password history (no reuse of last 10), 90-day
  expiration with warnings, admin temporary-password reset, mandatory first-login change
  (migration `0013`).

### Part 4.2.2.3.1 — Registration, invitations & email verification

- **Added** invited + self-serve registration, invitation lifecycle, email verification,
  Postgres-backed rate limiting (migrations `0011`–`0012`).

### Part 4.2.2.2 — Login, logout & session lifecycle

- **Added** stateful session validation on every request (immediate revocation), device
  trust/block, refresh-token families with reuse detection, admin session management
  (migrations `0009`–`0010`).

### Part 4.2.2.1 — Enterprise human authentication

- **Added** `/api/v1/auth/*` on argon2id, rotating refresh tokens, account lockout, login
  history, silent refresh (migration `0008`).

## [0.3.0] — Phase 3 · Enterprise Dashboard UI

- React 19 + TypeScript SPA: agents, policies, approvals, audit, analytics dashboards.

## [0.2.0] — Phase 2 · Production-oriented platform

- Agent API-key auth, database-driven policy engine, advanced RBAC, email notifications,
  forensic audit, dashboard APIs, risk engine v2, Docker.

## [0.1.0] — Phase 1 · Backend MVP

- FastAPI + PostgreSQL control plane: agents, permissions, risk scoring, approvals,
  immutable audit logs, JWT auth.
