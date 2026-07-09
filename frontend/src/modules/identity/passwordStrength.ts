/**
 * Password strength for the registration form (SRS §17).
 *
 * **This mirrors the backend policy; it does not define it.** The server
 * (`identity/security/passwords.py`, ADR-0004) is the only authority: ≥12 chars,
 * upper + lower + digit + special, a common-password blocklist, and no email or
 * username substring. A password that passes here can still be refused with a 422,
 * and the form must render that server error rather than insisting it is fine.
 *
 * The point of the meter is to tell the user *what is missing* before they submit,
 * not to be a second gate.
 */

export interface PasswordRule {
  id: string
  label: string
  satisfied: boolean
}

export type StrengthLevel = 'empty' | 'weak' | 'fair' | 'good' | 'strong'

export interface PasswordStrength {
  level: StrengthLevel
  /** 0–4, for the meter width. */
  score: number
  rules: PasswordRule[]
  /** Every hard requirement met — enables the submit button. */
  meetsPolicy: boolean
}

export const MIN_PASSWORD_LENGTH = 12

// A short, high-signal list mirroring the server's. The server holds the real one;
// duplicating all of it here would guarantee the two drift apart.
const COMMON = new Set([
  'password',
  'password1',
  'password123',
  'password1234',
  'passw0rd',
  '12345678',
  '123456789',
  '1234567890',
  'welcome123',
  'qwerty123',
  'admin123',
  'letmein123',
  'iloveyou123',
  'changeme123',
  'abc12345',
  'administrator',
])

const SPECIALS = /[!@#$%^&*()\-_=+[\]{};:,.<>?/|\\`~"']/

// Mirrors the backend sequence/repeat rules (`identity/security/passwords.py`).
const SEQUENCES = ['abcdefghijklmnopqrstuvwxyz', '0123456789', 'qwertyuiop', 'asdfghjkl', 'zxcvbnm']

function isCommon(password: string): boolean {
  const lowered = password.toLowerCase()
  if (COMMON.has(lowered)) return true
  // `Password123!` normalises to `password123` (exact); `password123!AA` normalises
  // to `password123aa` which *begins with* the weak stem — appending does not save it.
  const alnum = lowered.replace(/[^a-z0-9]/g, '')
  if (COMMON.has(alnum)) return true
  return [...COMMON].some((common) => alnum.startsWith(common))
}

function hasSequence(password: string, length = 4): boolean {
  const lowered = password.toLowerCase()
  return SEQUENCES.some((seq) => {
    const runs = [seq, [...seq].reverse().join('')]
    return runs.some((source) => {
      for (let i = 0; i + length <= source.length; i += 1) {
        if (lowered.includes(source.slice(i, i + length))) return true
      }
      return false
    })
  })
}

function hasRepeat(password: string, run = 4): boolean {
  const lowered = password.toLowerCase()
  let count = 1
  for (let i = 1; i < lowered.length; i += 1) {
    count = lowered[i] === lowered[i - 1] ? count + 1 : 1
    if (count >= run) return true
  }
  return false
}

/** Does the password contain the email local-part or the user's name? */
function containsIdentity(password: string, identity: string[]): boolean {
  const lowered = password.toLowerCase()
  return identity.some((value) => {
    const token = value.trim().toLowerCase()
    return token.length >= 3 && lowered.includes(token)
  })
}

export function evaluatePassword(password: string, identity: string[] = []): PasswordStrength {
  const rules: PasswordRule[] = [
    {
      id: 'length',
      label: `At least ${MIN_PASSWORD_LENGTH} characters`,
      satisfied: password.length >= MIN_PASSWORD_LENGTH,
    },
    { id: 'upper', label: 'An uppercase letter', satisfied: /[A-Z]/.test(password) },
    { id: 'lower', label: 'A lowercase letter', satisfied: /[a-z]/.test(password) },
    { id: 'digit', label: 'A number', satisfied: /\d/.test(password) },
    { id: 'special', label: 'A special character', satisfied: SPECIALS.test(password) },
    {
      id: 'uncommon',
      label: 'Not a common password',
      satisfied: password.length > 0 && !isCommon(password),
    },
    {
      id: 'nosequence',
      label: 'No keyboard or number sequences (e.g. 1234, qwer)',
      satisfied: password.length > 0 && !hasSequence(password) && !hasRepeat(password),
    },
    {
      id: 'identity',
      label: 'Does not contain your name or email',
      satisfied: password.length > 0 && !containsIdentity(password, identity),
    },
  ]

  const meetsPolicy = rules.every((rule) => rule.satisfied)
  const satisfied = rules.filter((rule) => rule.satisfied).length

  if (!password) return { level: 'empty', score: 0, rules, meetsPolicy: false }

  let level: StrengthLevel
  if (meetsPolicy && password.length >= 16) level = 'strong'
  else if (meetsPolicy) level = 'good'
  else if (satisfied >= 5) level = 'fair'
  else level = 'weak'

  const score = { empty: 0, weak: 1, fair: 2, good: 3, strong: 4 }[level]
  return { level, score, rules, meetsPolicy }
}

export const STRENGTH_LABEL: Record<StrengthLevel, string> = {
  empty: '',
  weak: 'Weak',
  fair: 'Fair',
  good: 'Good',
  strong: 'Strong',
}
