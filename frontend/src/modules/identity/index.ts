// Public surface of the identity module (Phase 4 Part 4.1 foundation,
// extended by Part 4.2.2.3.1 with registration, invitations & verification).
export * from './types'
export { InvitationsPanel } from './components/InvitationsPanel'
export { PasswordStrengthMeter } from './components/PasswordStrengthMeter'
export { evaluatePassword, MIN_PASSWORD_LENGTH, STRENGTH_LABEL } from './passwordStrength'
export type { PasswordRule, PasswordStrength, StrengthLevel } from './passwordStrength'
export {
  AcceptInvitationPage,
  IdentityPage,
  InvitationExpiredPage,
  RegisterPage,
  RegistrationSuccessPage,
  VerifyEmailPage,
} from './pages'
