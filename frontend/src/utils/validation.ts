import { z } from 'zod'

/** Reusable Zod schemas shared across forms (React Hook Form resolvers). */

export const emailSchema = z.string().trim().min(1, 'Email is required').email('Enter a valid email')

export const passwordSchema = z.string().min(8, 'Password must be at least 8 characters')

export const loginSchema = z.object({
  email: emailSchema,
  password: z.string().min(1, 'Password is required'),
})

export type LoginFormValues = z.infer<typeof loginSchema>
