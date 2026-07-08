/** Misc app-wide constants. */

/** localStorage key for the persisted JWT access token. */
export const AUTH_TOKEN_KEY = 'act.auth.token'

/** localStorage key for the persisted refresh token (SRS 4.2.2.1 §8). */
export const REFRESH_TOKEN_KEY = 'act.auth.refresh'

/** localStorage key for the access-token absolute expiry (epoch ms). */
export const TOKEN_EXPIRY_KEY = 'act.auth.expiry'

/** Silent-refresh lead time: refresh this long before expiry (SRS §20 — 5 min). */
export const SILENT_REFRESH_LEAD_MS = 5 * 60_000

/** localStorage key for the persisted theme preference. */
export const THEME_KEY = 'act.theme'

/** Risk score thresholds mirrored from the backend decision engine (Phase 1). */
export const RISK_THRESHOLDS = {
  ALLOW_MAX: 40,
  APPROVAL_MAX: 80,
} as const

/** Dashboard auto-refresh interval (SRS Part 3.1: every 60 seconds). */
export const DASHBOARD_REFRESH_MS = 60_000
