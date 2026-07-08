import { Link, useLocation } from 'react-router-dom'
import { MailWarning } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'

/** Copy for each way an invitation link can be dead (SRS §16, §18). */
const REASONS: Record<string, { title: string; body: string }> = {
  INVITATION_EXPIRED: {
    title: 'This invitation has expired',
    body: 'Invitations are valid for 7 days. Ask an administrator of your organization to send you a new one.',
  },
  INVITATION_ALREADY_USED: {
    title: 'This invitation was already used',
    body: 'An account already exists for this invitation. Try signing in instead.',
  },
  INVITATION_CANCELLED: {
    title: 'This invitation was cancelled',
    body: 'An administrator revoked this invitation. Contact them if you believe this is a mistake.',
  },
  INVITATION_NOT_FOUND: {
    title: 'This invitation link is not valid',
    body: 'The link may have been mistyped, or truncated by an email client. Check the original email, or ask for a new invitation.',
  },
}

const FALLBACK = REASONS.INVITATION_NOT_FOUND

/**
 * A dead invitation link is a dead end for the user — so the page names *which* kind
 * of dead it is, because each has a different next step. One generic "invalid link"
 * would leave an invitee guessing whether to wait, re-ask, or sign in.
 */
export function InvitationExpiredPage() {
  const location = useLocation()
  const code = (location.state as { code?: string } | null)?.code
  const reason = (code && REASONS[code]) || FALLBACK

  return (
    <Card>
      <CardContent className="space-y-4 p-6 text-center" role="alert">
        <MailWarning className="mx-auto h-10 w-10 text-warning" aria-hidden="true" />
        <h2 className="text-lg font-semibold text-foreground">{reason.title}</h2>
        <p className="text-sm text-muted-foreground">{reason.body}</p>
        <p className="text-sm">
          <Link to={ROUTES.LOGIN} className="text-primary hover:underline">
            Back to sign in
          </Link>
        </p>
      </CardContent>
    </Card>
  )
}
