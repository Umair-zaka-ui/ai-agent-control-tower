import { Clock, LogOut, MapPin, Monitor, Shield, Smartphone, Tablet } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { AuthSession } from '@/types'
import { bandLabel, bandVariant, describeClient, describeLocation, expiresIn, timeAgo } from '../utils'

function DeviceIcon({ type }: { type: string | null }) {
  const className = 'h-5 w-5 text-muted-foreground'
  if (type === 'mobile') return <Smartphone className={className} />
  if (type === 'tablet') return <Tablet className={className} />
  return <Monitor className={className} />
}

interface SessionCardProps {
  session: AuthSession
  onRevoke: (session: AuthSession) => void
  pending?: boolean
}

/** One row of the session list (SRS §18, §19). */
export function SessionCard({ session, onRevoke, pending }: SessionCardProps) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-start gap-3">
        <div className="mt-0.5">
          <DeviceIcon type={session.device_type} />
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-medium text-foreground">{describeClient(session)}</span>
            {session.is_current && (
              <Badge variant="default" data-testid="current-session-badge">
                Current device
              </Badge>
            )}
            {session.is_trusted && <Badge variant="outline">Trusted</Badge>}
            <Badge variant={bandVariant(session.security_band)}>
              <Shield className="mr-1 h-3 w-3" />
              {bandLabel(session.security_band)} · {session.security_score}
            </Badge>
          </div>

          <div className="mt-1 space-y-0.5 text-sm text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <MapPin className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{describeLocation(session)}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 shrink-0" />
              <span>
                Active {timeAgo(session.last_activity_at ?? session.last_seen_at)} · signs out in{' '}
                {expiresIn(session.idle_expires_at)} if idle
              </span>
            </div>
          </div>
        </div>
      </div>

      <Button
        variant={session.is_current ? 'outline' : 'destructive'}
        size="sm"
        onClick={() => onRevoke(session)}
        disabled={pending}
        className="shrink-0 self-start sm:self-center"
      >
        <LogOut className="mr-1.5 h-4 w-4" />
        {session.is_current ? 'Sign out' : 'Revoke'}
      </Button>
    </div>
  )
}
