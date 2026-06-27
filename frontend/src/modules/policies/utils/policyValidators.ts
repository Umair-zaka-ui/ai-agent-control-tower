import { z } from 'zod'

import type { JsonObject } from '@/types'

/** Step 1 (Basic Information) validation for the policy builder. */
export const policyBasicSchema = z.object({
  name: z.string().trim().min(1, 'Policy name is required'),
  description: z.string().trim().min(1, 'Description is required'),
  severity: z.enum(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']),
})

export type PolicyBasicValues = z.infer<typeof policyBasicSchema>

/** Parse the conditions JSON editor; returns the object or an error message. */
export function parseConditions(text: string): { ok: true; value: JsonObject } | { ok: false; error: string } {
  const trimmed = text.trim()
  if (trimmed === '') return { ok: true, value: {} }
  try {
    const parsed = JSON.parse(trimmed)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return { ok: false, error: 'Conditions must be a JSON object.' }
    }
    return { ok: true, value: parsed as JsonObject }
  } catch {
    return { ok: false, error: 'Invalid JSON.' }
  }
}
