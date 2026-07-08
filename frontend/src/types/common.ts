/** Shared primitive and envelope types used across the API layer. */

export type ID = string

/** ISO-8601 timestamp string (e.g. "2026-06-25T10:00:00Z"). */
export type ISODateString = string

/** Generic key/value object for opaque JSON payloads from the backend. */
export type JsonObject = Record<string, unknown>

/** Normalised shape every service throws on failure (see http client). */
export interface ApiError {
  status: number
  message: string
  /**
   * Machine-readable code from the identity error envelope
   * (`{ error: { code, message } }`). Absent on legacy `{ detail }` routes and on
   * network failures. Branch on this, never on the human-readable message: prose gets
   * reworded, codes are a contract.
   */
  code?: string
  detail?: unknown
}

/** Cursor/offset list response. The backend currently returns plain arrays; */
/** this envelope is here for when pagination is added in a later Part. */
export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}
