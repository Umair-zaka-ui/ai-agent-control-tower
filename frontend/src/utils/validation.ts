import { z } from 'zod'

/** Reusable Zod schemas shared across forms (React Hook Form resolvers). */

export const emailSchema = z.string().trim().min(1, 'Email is required').email('Enter a valid email')

// Mirrors the backend policy floor (12 chars). The full policy — character
// classes, blocklist, no email/username substring — is enforced server-side and
// returned as a 422; this is a fast-fail, not the policy.
export const passwordSchema = z
  .string()
  .min(12, 'Password must be at least 12 characters')

export const loginSchema = z.object({
  email: emailSchema,
  password: z.string().min(1, 'Password is required'),
  /**
   * Extends the session's ABSOLUTE ceiling to 7 days; idle timeout still applies.
   * No `.default()`: it makes the schema's *input* type optional, which no longer
   * matches `LoginFormValues` and breaks the zodResolver. The form supplies the
   * default via `defaultValues`.
   */
  rememberMe: z.boolean(),
})

export type LoginFormValues = z.infer<typeof loginSchema>
