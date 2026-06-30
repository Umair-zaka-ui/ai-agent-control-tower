import { AlertCircle, RefreshCw, ScrollText, ShieldAlert, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'

import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import {
  AuditEventCard,
  AuditStatistics,
  AuditTimeline,
  AuditToolbar,
  CompliancePanel,
  SecurityPanel,
} from '../components'
import {
  useAudit,
  useAuditStatistics,
  useAuditTimeline,
  useComplianceSummary,
  useSecurityEvents,
} from '../hooks'
import { canExportAudit } from '../utils/permissions'

export function AuditDashboardPage() {
  const { permissions } = useAuth()
  const canExport = canExportAudit(permissions)

  const stats = useAuditStatistics()
  const timeline = useAuditTimeline(12)
  const recent = useAudit({ limit: 8 })

  const recentEvents = recent.data ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit & Compliance"
        description="Every significant action across the platform — who did what, when, why, and what happened."
        actions={
          <AuditToolbar
            refreshing={stats.isFetching || timeline.isFetching || recent.isFetching}
            canExport={canExport}
            onRefresh={() => {
              void stats.refetch()
              void timeline.refetch()
              void recent.refetch()
            }}
          />
        }
      />

      <AuditStatistics stats={stats.data} loading={stats.isLoading} />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Event Timeline</CardTitle>
          </CardHeader>
          <CardContent>
            {timeline.isError ? (
              <SectionError onRetry={() => void timeline.refetch()} />
            ) : (
              <AuditTimeline items={timeline.data ?? []} loading={timeline.isLoading} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Recent Events</CardTitle>
            <Link to={`${ROUTES.AUDIT}/events`} className="text-xs text-primary hover:underline">
              View all
            </Link>
          </CardHeader>
          <CardContent>
            {recent.isError ? (
              <SectionError onRetry={() => void recent.refetch()} />
            ) : recent.isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="h-14 animate-pulse rounded-md bg-muted" />
                ))}
              </div>
            ) : recentEvents.length === 0 ? (
              <EmptyState
                icon={ScrollText}
                title="No audit events available"
                description="Once users and AI agents begin operating, audit events will appear here."
              />
            ) : (
              <div className="space-y-2">
                {recentEvents.map((event) => (
                  <AuditEventCard key={event.id} event={event} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {canExport && <SecuritySnapshot />}
      {canExport && <ComplianceSnapshot />}
    </div>
  )
}

/** Security overview — only mounted (and fetched) for audit.export holders. */
function SecuritySnapshot() {
  const { data, isLoading, isError, refetch } = useSecurityEvents()
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldAlert className="h-4 w-4 text-destructive" />
          Security Events
        </CardTitle>
        <Link to={`${ROUTES.AUDIT}/security`} className="text-xs text-primary hover:underline">
          Security dashboard
        </Link>
      </CardHeader>
      <CardContent>
        {isError ? (
          <SectionError onRetry={() => void refetch()} />
        ) : (
          <SecurityPanel summary={data} loading={isLoading} />
        )}
      </CardContent>
    </Card>
  )
}

/** Compliance overview — only mounted (and fetched) for audit.export holders. */
function ComplianceSnapshot() {
  const { data, isLoading, isError, refetch } = useComplianceSummary()
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck className="h-4 w-4 text-success" />
          Compliance Summary
        </CardTitle>
        <Link to={`${ROUTES.AUDIT}/compliance`} className="text-xs text-primary hover:underline">
          Compliance dashboard
        </Link>
      </CardHeader>
      <CardContent>
        {isError ? (
          <SectionError onRetry={() => void refetch()} />
        ) : (
          <CompliancePanel summary={data} loading={isLoading} />
        )}
      </CardContent>
    </Card>
  )
}

function SectionError({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 py-10 text-center">
      <AlertCircle className="h-6 w-6 text-destructive" />
      <p className="text-sm text-muted-foreground">Unable to load audit information.</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        <RefreshCw className="h-4 w-4" />
        Retry
      </Button>
    </div>
  )
}
