import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AtSign, KeyRound, LayoutDashboard, LogOut, ShieldAlert, ShieldQuestion } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { PERMISSIONS } from '@/constants/permissions'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import type { AuthDevice, AuthSession } from '@/types'
import { InvitationsPanel } from '@/modules/identity/components/InvitationsPanel'
import { AdminSessionsPanel } from './components/AdminSessionsPanel'
import { ConfirmDialog } from './components/ConfirmDialog'
import { SecurityEventList } from './components/SecurityEventList'
import { DeviceCard } from './components/DeviceCard'
import { SessionCard } from './components/SessionCard'
import {
  useBlockDevice,
  useDevices,
  useLogoutAllDevices,
  useMySecurityEvents,
  useRevokeSession,
  useSessions,
  useTrustDevice,
} from './hooks/useSessions'

type PendingAction =
  | { kind: 'revoke'; session: AuthSession }
  | { kind: 'block'; device: AuthDevice }
  | { kind: 'logout-all' }
  | null

function ListSkeleton() {
  return (
    <div className="space-y-3">
      {[0, 1].map((i) => (
        <Skeleton key={i} className="h-24 w-full rounded-lg" />
      ))}
    </div>
  )
}

/**
 * Settings → Security → Sessions (SRS §24).
 *
 * Shows every active session and every known device, and lets the user end any
 * of them. Because revocation is enforced server-side on every request
 * (Part 4.2.2.2), "Revoke" here genuinely ends the other device's access — it is
 * not merely a local token drop.
 */
export function SecuritySessionsPage() {
  const { logout, permissions } = useAuth()
  const canViewPasswordDashboard = permissions.includes(PERMISSIONS.CREDENTIAL_DASHBOARD)
  const canViewRecovery = permissions.includes(PERMISSIONS.RECOVERY_VIEW)
  const sessions = useSessions()
  const devices = useDevices()
  const revokeSession = useRevokeSession()
  const trustDevice = useTrustDevice()
  const blockDevice = useBlockDevice()
  const logoutAll = useLogoutAllDevices()
  const myEvents = useMySecurityEvents()

  const [pending, setPending] = useState<PendingAction>(null)

  const confirm = async () => {
    if (!pending) return

    if (pending.kind === 'revoke') {
      const isCurrent = pending.session.is_current
      await revokeSession.mutateAsync({ id: pending.session.id })
      setPending(null)
      // Revoking our own session already killed this access token server-side.
      // Clear auth state so ProtectedRoute sends us to /login; no manual navigate.
      if (isCurrent) logout()
      return
    }

    if (pending.kind === 'block') {
      await blockDevice.mutateAsync(pending.device.id)
      setPending(null)
      return
    }

    await logoutAll.mutateAsync()
    setPending(null)
    // The server already revoked every session; this clears local state.
    logout()
  }

  const busy =
    revokeSession.isPending || blockDevice.isPending || logoutAll.isPending || trustDevice.isPending

  const activeSessions = sessions.data ?? []
  const knownDevices = devices.data ?? []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Security</h1>
        <p className="text-sm text-muted-foreground">
          Review where you are signed in and which devices you trust.
        </p>
      </div>

      {/* Password (4.2.2.3.2) -------------------------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle>Password</CardTitle>
          <CardDescription>
            Change your password, or manage the organization's credential posture.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <Button asChild variant="outline" size="sm">
            <Link to={ROUTES.CHANGE_PASSWORD}>
              <KeyRound className="h-4 w-4" aria-hidden="true" />
              Change password
            </Link>
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link to={ROUTES.CHANGE_EMAIL}>
              <AtSign className="h-4 w-4" aria-hidden="true" />
              Change email
            </Link>
          </Button>
          {canViewPasswordDashboard && (
            <Button asChild variant="outline" size="sm">
              <Link to={ROUTES.SECURITY_PASSWORDS}>
                <LayoutDashboard className="h-4 w-4" aria-hidden="true" />
                Password dashboard
              </Link>
            </Button>
          )}
          {canViewRecovery && (
            <Button asChild variant="outline" size="sm">
              <Link to={ROUTES.SECURITY_RECOVERY}>
                <ShieldQuestion className="h-4 w-4" aria-hidden="true" />
                Recovery events
              </Link>
            </Button>
          )}
        </CardContent>
      </Card>

      {/* Sessions -------------------------------------------------------- */}
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
          <div>
            <CardTitle>Active sessions</CardTitle>
            <CardDescription>
              Each device you sign in from gets its own session. Ending one signs that device out
              immediately.
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPending({ kind: 'logout-all' })}
            disabled={busy || activeSessions.length === 0}
            className="shrink-0"
          >
            <LogOut className="mr-1.5 h-4 w-4" />
            Sign out everywhere
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {sessions.isLoading && <ListSkeleton />}
          {sessions.isError && (
            <p className="text-sm text-destructive">Could not load your sessions.</p>
          )}
          {!sessions.isLoading && activeSessions.length === 0 && (
            <p className="text-sm text-muted-foreground">No active sessions.</p>
          )}
          {activeSessions.map((session) => (
            <SessionCard
              key={session.id}
              session={session}
              pending={busy}
              onRevoke={(s) => setPending({ kind: 'revoke', session: s })}
            />
          ))}
        </CardContent>
      </Card>

      {/* Devices --------------------------------------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle>Devices</CardTitle>
          <CardDescription>
            Trusted devices are treated as lower risk. Blocking a device signs it out and prevents
            it from signing in again.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {devices.isLoading && <ListSkeleton />}
          {devices.isError && <p className="text-sm text-destructive">Could not load your devices.</p>}
          {!devices.isLoading && knownDevices.length === 0 && (
            <p className="text-sm text-muted-foreground">No devices recorded yet.</p>
          )}
          {knownDevices.map((device) => (
            <DeviceCard
              key={device.id}
              device={device}
              pending={busy}
              onTrust={(d) => trustDevice.mutate(d.id)}
              onBlock={(d) => setPending({ kind: 'block', device: d })}
            />
          ))}
        </CardContent>
      </Card>

      {/* My own security activity (SRS §25, §26) — how a user spots an intrusion. */}
      <Card>
        <CardHeader>
          <CardTitle>Recent security activity</CardTitle>
          <CardDescription>
            Sign-ins, new devices and session changes recorded against your account. If you do not
            recognise something here, revoke the session and change your password.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SecurityEventList
            data-testid="my-security-events"
            events={myEvents.data ?? []}
            loading={myEvents.isLoading}
            error={myEvents.isError}
            emptyMessage="No security activity recorded yet."
          />
        </CardContent>
      </Card>

      {/* Admin: who may join (4.2.2.3.1 §15). Renders only with invitation.view. */}
      <InvitationsPanel />

      {/* Admin: team sessions (SRS §17, §32). Renders only with session.view. */}
      <AdminSessionsPanel />

      {/* Confirmations (SRS §19) ----------------------------------------- */}
      <ConfirmDialog
        open={pending?.kind === 'revoke'}
        title={
          pending?.kind === 'revoke' && pending.session.is_current
            ? 'Sign out of this device?'
            : 'Revoke this session?'
        }
        description={
          pending?.kind === 'revoke' && pending.session.is_current
            ? 'You are using this session right now. You will be returned to the sign-in page.'
            : 'That device will be signed out immediately and will need to sign in again.'
        }
        confirmLabel={
          pending?.kind === 'revoke' && pending.session.is_current ? 'Sign out' : 'Revoke session'
        }
        pending={revokeSession.isPending}
        onConfirm={confirm}
        onCancel={() => setPending(null)}
      />

      <ConfirmDialog
        open={pending?.kind === 'block'}
        title="Block this device?"
        description="Any session on that device ends now, and it will not be able to sign in again until you unblock it."
        confirmLabel="Block device"
        pending={blockDevice.isPending}
        onConfirm={confirm}
        onCancel={() => setPending(null)}
      />

      <ConfirmDialog
        open={pending?.kind === 'logout-all'}
        title="Sign out of every device?"
        description="This ends all of your sessions, including this one. You will need to sign in again."
        confirmLabel="Sign out everywhere"
        pending={logoutAll.isPending}
        onConfirm={confirm}
        onCancel={() => setPending(null)}
      />

      {activeSessions.some((s) => s.security_band === 'HIGH_RISK') && (
        <div className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            One or more sessions are flagged high risk. If you do not recognise them, revoke them and
            change your password.
          </span>
        </div>
      )}
    </div>
  )
}
