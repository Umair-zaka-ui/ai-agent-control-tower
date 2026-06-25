import type { ApiError } from '@/types'

/**
 * Extract a human-readable message from any caught/rejected value. Our http
 * client rejects with an ApiError shape; TanStack types errors as `Error`, so
 * this normalises both without unsafe casts at the call site.
 */
export function apiErrorMessage(error: unknown, fallback = 'Something went wrong'): string {
  const message = (error as ApiError | undefined)?.message
  return message ?? fallback
}
