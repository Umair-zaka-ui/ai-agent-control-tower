import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  Ban,
  Loader2,
  LockKeyhole,
  ScrollText,
  ShieldAlert,
  SlidersHorizontal,
} from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { protectionService } from '@/services'

interface Widget {
  label: string
  value: number
  icon: React.ReactNode
  to?: string
  tone?: string
}

/**
 * Security dashboard (SRS §23). At-a-glance protection posture, each widget a door
 * into the detail page. Requires `security.protection`.
 */
export function SecurityDashboardPage() {
  const summary = useQuery({
    queryKey: ['protection-summary'],
    queryFn: () => protectionService.summary(),
  })

  if (summary.isLoading) {
    return (
      <div className="flex justify-center p-10" role="status" aria-label="Loading">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />
      </div>
    )
  }
  if (summary.isError || !summary.data) {
    return (
      <div className="p-6 text-sm text-destructive" role="alert">
        Could not load the security dashboard.
      </div>
    )
  }

  const d = summary.data
  const widgets: Widget[] = [
    {
      label: 'Failed logins (24h)',
      value: d.failed_logins_today,
      icon: <ShieldAlert className="h-5 w-5" aria-hidden="true" />,
      to: ROUTES.SECURITY_LOGIN_ATTEMPTS,
    },
    {
      label: 'Locked accounts',
      value: d.locked_accounts,
      icon: <LockKeyhole className="h-5 w-5" aria-hidden="true" />,
      to: ROUTES.SECURITY_ACCOUNT_LOCKS,
      tone: d.locked_accounts > 0 ? 'text-warning' : undefined,
    },
    {
      label: 'High-risk attempts (24h)',
      value: d.high_risk_attempts,
      icon: <AlertTriangle className="h-5 w-5" aria-hidden="true" />,
      to: ROUTES.SECURITY_RISK_EVENTS,
      tone: d.high_risk_attempts > 0 ? 'text-destructive' : undefined,
    },
    {
      label: 'Blocked IPs',
      value: d.blocked_ips,
      icon: <Ban className="h-5 w-5" aria-hidden="true" />,
      to: ROUTES.SECURITY_BLOCKED_IPS,
    },
    {
      label: 'Active rules',
      value: d.active_rules,
      icon: <SlidersHorizontal className="h-5 w-5" aria-hidden="true" />,
      to: ROUTES.SECURITY_PROTECTION_RULES,
    },
    {
      label: 'Recent risk events',
      value: d.risk_events_recent,
      icon: <ScrollText className="h-5 w-5" aria-hidden="true" />,
      to: ROUTES.SECURITY_RISK_EVENTS,
    },
  ]

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Account protection</h1>
        <p className="text-sm text-muted-foreground">
          Risk-based authentication posture for your organization.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="protection-widgets">
        {widgets.map((w) => {
          const body = (
            <Card className="h-full transition-colors hover:border-primary/50">
              <CardContent className="flex items-center gap-3 p-4">
                <span className={`shrink-0 ${w.tone ?? 'text-muted-foreground'}`}>{w.icon}</span>
                <div>
                  <p className={`text-2xl font-semibold ${w.tone ?? 'text-foreground'}`}>{w.value}</p>
                  <p className="text-xs text-muted-foreground">{w.label}</p>
                </div>
              </CardContent>
            </Card>
          )
          return w.to ? (
            <Link key={w.label} to={w.to} className="block">
              {body}
            </Link>
          ) : (
            <div key={w.label}>{body}</div>
          )
        })}
      </div>
    </div>
  )
}
