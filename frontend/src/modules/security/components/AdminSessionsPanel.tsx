import { useState } from 'react'
import { LogOut, ShieldAlert, UserCog } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { PERMISSIONS } from '@/constants/permissions'
import { useAuth } from '@/hooks/useAuth'
import type { AuthSession, ID } from '@/types'
import { ConfirmDialog } from './ConfirmDialog'
import { SecurityEventList } from './SecurityEventList'
import {
  useAdminRevokeAllSessions,
  useAdminRevokeSession,
  useAdminSecurityEvents,
  useAdminUserDevices,
  useAdminUserSessions,
  useOrgUsers,
  useSessionEvents,
} from '../hooks/useAdminSessions'
import { bandLabel, bandVariant, describeClient, describeLocation, timeAgo } from '../utils'

type Pending = { kind: 'session'; session: AuthSession } | { kind: 'all' } | null

/**
 * Settings → Security → **Team sessions** (SRS §17, §32).
 *
 * Lets an administrator see, inspect and force-logout any session in their
 * organization. Rendered only when the caller actually holds `session.view` —
 * the backend re-checks every call, so this gating only hides controls that
 * would 403 anyway. It is never the security boundary.
 */
export function AdminSessionsPanel() {
  const { permissions } = useAuth()
  const canView = permissions.includes(PERMISSIONS.SESSION_VIEW)
  const canRevoke = permissions.includes(PERMISSIONS.SESSION_REVOKE)

  const [userId, setUserId] = useState<ID | null>(null)
  const [pending, setPending] = useState<Pending>(null)

  const users = useOrgUsers(canView)
  const sessions = useAdminUserSessions(userId)
  const devices = useAdminUserDevices(userId)
  const revokeOne = useAdminRevokeSession()
  const revokeAll = useAdminRevokeAllSessions()
  const memberEvents = useAdminSecurityEvents({ actorId: userId ?? undefined, limit: 25 }, Boolean(userId) && canView)
  const [timelineFor, setTimelineFor] = useState<ID | null>(null)
  const sessionTimeline = useSessionEvents(timelineFor)

  if (!canView) return null

  const busy = revokeOne.isPending || revokeAll.isPending
  const rows = sessions.data ?? []
  const selected = users.data?.find((u) => u.id === userId)

  const confirm = async () => {
    if (!pending || !userId) return
    if (pending.kind === 'session') {
      await revokeOne.mutateAsync({ sessionId: pending.session.id })
    } else {
      await revokeAll.mutateAsync({ userId })
    }
    setPending(null)
  }

  return (
    <Card data-testid="admin-sessions-panel">
      <CardHeader>
        <div className="flex items-center gap-2">
          <UserCog className="h-5 w-5 text-primary" />
          <CardTitle>Team sessions</CardTitle>
        </div>
        <CardDescription>
          See where members of your organization are signed in, and sign them out. Force-logout ends
          the session but does not disable the account.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-56 flex-1">
            <label htmlFor="admin-user" className="mb-1 block text-sm text-muted-foreground">
              Member
            </label>
            <select
              id="admin-user"
              className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground"
              value={userId ?? ''}
              onChange={(e) => setUserId(e.target.value || null)}
              disabled={users.isLoading}
            >
              <option value="">Select a member…</option>
              {(users.data ?? []).map((u) => (
                <option key={u.id} value={u.id}>
                  {u.display_name} · {u.email}
                </option>
              ))}
            </select>
          </div>

          {userId && canRevoke && rows.length > 0 && (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setPending({ kind: 'all' })}
              disabled={busy}
            >
              <LogOut className="mr-1.5 h-4 w-4" />
              Sign out of all devices
            </Button>
          )}
        </div>

        {users.isError && (
          <p className="text-sm text-destructive">Could not load organization members.</p>
        )}

        {userId && sessions.isLoading && <Skeleton className="h-20 w-full rounded-lg" />}
        {userId && sessions.isError && (
          <p className="text-sm text-destructive">Could not load that member&apos;s sessions.</p>
        )}
        {userId && !sessions.isLoading && rows.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {selected?.display_name ?? 'This member'} has no active sessions.
          </p>
        )}

        {rows.map((session) => (
          <div
            key={session.id}
            className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="truncate font-medium text-foreground">
                  {describeClient(session)}
                </span>
                <Badge variant={bandVariant(session.security_band)}>
                  <ShieldAlert className="mr-1 h-3 w-3" />
                  {bandLabel(session.security_band)} · {session.security_score}
                </Badge>
                <Badge variant="outline">{session.status}</Badge>
              </div>
              <p className="mt-0.5 truncate text-sm text-muted-foreground">
                {describeLocation(session)} · active {timeAgo(session.last_activity_at)}
              </p>
            </div>

            <div className="flex shrink-0 gap-2 self-start sm:self-center">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setTimelineFor(timelineFor === session.id ? null : session.id)}
              >
                {timelineFor === session.id ? 'Hide history' : 'History'}
              </Button>
              {canRevoke && (
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => setPending({ kind: 'session', session })}
                  disabled={busy}
                >
                  Revoke
                </Button>
              )}
            </div>
          </div>
        ))}

        {/* "Who revoked this session, when, and why?" — DoD §32. */}
        {timelineFor && (
          <div className="rounded-lg border border-border bg-background p-3">
            <p className="mb-2 text-sm font-medium text-foreground">Session history</p>
            <SecurityEventList
              data-testid="session-timeline"
              events={sessionTimeline.data ?? []}
              loading={sessionTimeline.isLoading}
              error={sessionTimeline.isError}
              order="oldest-first"
              emptyMessage="No events recorded for this session."
            />
          </div>
        )}

        {userId && (
          <div className="rounded-lg border border-border bg-background p-3">
            <p className="mb-2 text-sm font-medium text-foreground">
              Recent security activity for {selected?.display_name ?? 'this member'}
            </p>
            <SecurityEventList
              data-testid="member-events"
              events={memberEvents.data?.items ?? []}
              loading={memberEvents.isLoading}
              error={memberEvents.isError}
              emptyMessage="No security activity recorded."
            />
          </div>
        )}

        {userId && (devices.data?.length ?? 0) > 0 && (
          <p className="text-xs text-muted-foreground">
            Known devices: {devices.data?.map((d) => describeClient(d)).join(' · ')}
          </p>
        )}
      </CardContent>

      <ConfirmDialog
        open={pending?.kind === 'session'}
        title="Revoke this session?"
        description={`${selected?.display_name ?? 'The member'} will be signed out of that device immediately. Their account stays active and they can sign in again.`}
        confirmLabel="Revoke session"
        pending={revokeOne.isPending}
        onConfirm={confirm}
        onCancel={() => setPending(null)}
      />

      <ConfirmDialog
        open={pending?.kind === 'all'}
        title="Sign this member out everywhere?"
        description={`Every session belonging to ${selected?.display_name ?? 'this member'} ends now. Their account stays active — use Suspend to prevent them signing back in.`}
        confirmLabel="Sign out everywhere"
        pending={revokeAll.isPending}
        onConfirm={confirm}
        onCancel={() => setPending(null)}
      />
    </Card>
  )
}
