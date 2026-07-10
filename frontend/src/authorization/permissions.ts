/**
 * Client-side permission matching (Phase 4.3.2 §23, §24).
 *
 * Mirrors the backend WildcardResolver so the UI can hide controls the user
 * cannot use. This is a convenience only — the server re-checks every request and
 * is the sole source of truth (§26). Never treat a client "allow" as security.
 */

/** Does the granted set cover `code`? Supports `*` and `resource.*` wildcards. */
export function permissionGranted(granted: readonly string[], code: string): boolean {
  for (const p of granted) {
    if (p === '*') return true
    if (p === code) return true
    if (p.endsWith('.*') && code.split('.', 1)[0] === p.slice(0, -2)) return true
  }
  return false
}
