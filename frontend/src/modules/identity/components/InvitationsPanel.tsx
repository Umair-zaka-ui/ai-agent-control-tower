import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Mail, MailWarning, RotateCw, UserPlus, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { PERMISSIONS } from '@/constants/permissions'
import { useAuth } from '@/hooks/useAuth'
import { invitationService } from '@/services/registrationService'
import type { ApiError, ID, Invitation, InvitationStatus } from '@/types'

const STATUS_VARIANT: Record<InvitationStatus, 'default' | 'success' | 'warning' | 'destructive'> = {
  PENDING: 'default',
  ACCEPTED: 'success',
  EXPIRED: 'warning',
  CANCELLED: 'destructive',
}

function expiresIn(iso: string): string {
  const days = Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000)
  if (days <= 0) return 'expired'
  return days === 1 ? 'expires tomorrow' : `expires in ${days} days`
}

const invitationKeys = {
  all: ['invitations'] as const,
  list: () => ['invitations', 'list'] as const,
}

/**
 * Settings → Security → **Invitations** (SRS §15, §24 criterion 2).
 *
 * Rendered only with `invitation.view`; the create/resend/cancel controls need
 * `invitation.manage`. The backend re-checks both on every call, so this gating only
 * hides controls that would 403 — it is never the security boundary.
 *
 * The invitation *token* never reaches this component. An administrator has no
 * business holding the invitee's single-use credential, so the API returns none and
 * a resend rotates it server-side.
 */
export function InvitationsPanel() {
  const { permissions } = useAuth()
  const canView = permissions.includes(PERMISSIONS.INVITATION_VIEW)
  const canManage = permissions.includes(PERMISSIONS.INVITATION_MANAGE)
  const queryClient = useQueryClient()

  const [email, setEmail] = useState('')

  const invitations = useQuery({
    queryKey: invitationKeys.list(),
    queryFn: () => invitationService.list(),
    enabled: canView,
  })

  const delivery = useQuery({
    queryKey: ['invitations', 'email-delivery'],
    queryFn: () => invitationService.emailDeliveryStatus(),
    enabled: canView,
    staleTime: 5 * 60_000,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: invitationKeys.all })

  const create = useMutation({
    mutationFn: (address: string) => invitationService.create({ email: address }),
    onSuccess: (invitation) => {
      setEmail('')
      void invalidate()
      toast.success(`Invitation sent to ${invitation.email}`)
    },
    onError: (error: ApiError) =>
      toast.error(
        error?.status === 409
          ? 'That email already belongs to a user.'
          : (error?.message ?? 'Could not send the invitation'),
      ),
  })

  const resend = useMutation({
    mutationFn: (id: ID) => invitationService.resend(id),
    onSuccess: () => {
      void invalidate()
      // Worth saying: the previous link is now dead.
      toast.success('New link sent. The previous link no longer works.')
    },
    onError: () => toast.error('Could not resend the invitation'),
  })

  const cancel = useMutation({
    mutationFn: (id: ID) => invitationService.cancel(id),
    onSuccess: () => {
      void invalidate()
      toast.success('Invitation cancelled. The link no longer works.')
    },
    onError: () => toast.error('Could not cancel the invitation'),
  })

  if (!canView) return null

  const busy = create.isPending || resend.isPending || cancel.isPending
  const rows = invitations.data ?? []

  return (
    <Card data-testid="invitations-panel">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Mail className="h-5 w-5 text-primary" aria-hidden="true" />
          <CardTitle>Invitations</CardTitle>
        </div>
        <CardDescription>
          People join this organization by invitation. Links expire after 7 days and can be used
          once.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {/*
          Never let a "PENDING" row imply an email is in flight when none was sent.
          The link still exists — it is written to the dev outbox — but nobody is going
          to receive it, and an invitee will wait for ever.
        */}
        {delivery.data && !delivery.data.enabled && (
          <div
            role="alert"
            data-testid="email-delivery-warning"
            className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning"
          >
            <MailWarning className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <div className="min-w-0">
              <p className="font-medium">Email delivery is disabled — no invitations are sent.</p>
              <p className="text-xs opacity-90">
                Links are written to{' '}
                <code className="break-all">{delivery.data.outbox_path}</code>. Set{' '}
                <code>NOTIFICATIONS_ENABLED=true</code> with SMTP credentials, then use{' '}
                <strong>Resend</strong> to issue a fresh link.
              </p>
            </div>
          </div>
        )}

        {canManage && (
          <form
            className="flex flex-wrap items-end gap-3"
            noValidate
            onSubmit={(event) => {
              event.preventDefault()
              if (email.trim()) create.mutate(email.trim())
            }}
          >
            <div className="min-w-56 flex-1 space-y-1">
              <Label htmlFor="inviteEmail">Invite by email</Label>
              <Input
                id="inviteEmail"
                type="email"
                placeholder="colleague@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <Button type="submit" disabled={!email.trim() || busy}>
              <UserPlus className="mr-1.5 h-4 w-4" aria-hidden="true" />
              Send invitation
            </Button>
          </form>
        )}

        {invitations.isLoading && <Skeleton className="h-20 w-full rounded-lg" />}
        {invitations.isError && (
          <p className="text-sm text-destructive">Could not load invitations.</p>
        )}
        {!invitations.isLoading && rows.length === 0 && (
          <p className="text-sm text-muted-foreground">No invitations yet.</p>
        )}

        {rows.map((invitation: Invitation) => {
          const pending = invitation.status === 'PENDING'
          return (
            <div
              key={invitation.id}
              className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate font-medium text-foreground">{invitation.email}</span>
                  <Badge variant={STATUS_VARIANT[invitation.status]}>{invitation.status}</Badge>
                  {invitation.resent_count > 0 && (
                    <Badge variant="outline">{`resent ×${invitation.resent_count}`}</Badge>
                  )}
                </div>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  {pending
                    ? expiresIn(invitation.expires_at)
                    : `${invitation.status.toLowerCase()} · invited ${new Date(invitation.created_at).toLocaleDateString()}`}
                </p>
              </div>

              {canManage && pending && (
                <div className="flex shrink-0 gap-2 self-start sm:self-center">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={() => resend.mutate(invitation.id)}
                  >
                    <RotateCw className="mr-1.5 h-4 w-4" aria-hidden="true" />
                    Resend
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={busy}
                    onClick={() => cancel.mutate(invitation.id)}
                  >
                    <XCircle className="mr-1.5 h-4 w-4" aria-hidden="true" />
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
