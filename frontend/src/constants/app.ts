/** Misc app-wide constants. */

/** localStorage key for the persisted JWT access token. */
export const AUTH_TOKEN_KEY = 'act.auth.token'

/** localStorage key for the persisted theme preference. */
export const THEME_KEY = 'act.theme'

/** Risk score thresholds mirrored from the backend decision engine (Phase 1). */
export const RISK_THRESHOLDS = {
  ALLOW_MAX: 40,
  APPROVAL_MAX: 80,
} as const

/** Dashboard auto-refresh interval (SRS Part 3.1: every 60 seconds). */
export const DASHBOARD_REFRESH_MS = 60_000
