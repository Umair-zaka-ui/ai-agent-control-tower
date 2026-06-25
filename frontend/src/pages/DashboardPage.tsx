import { lazy, Suspense } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, Plus } from 'lucide-react'

import { EmptyState } from '@/components/common/EmptyState'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { DashboardHeader } from '@/components/dashboard/DashboardHeader'
import { KpiGrid } from '@/components/dashboard/KpiGrid'
import { PendingApprovalWidget } from '@/components/dashboard/PendingApprovalWidget'
import { RecentAgentActions } from '@/components/dashboard/RecentAgentActions'
import { RecentAuditLogs } from '@/components/dashboard/RecentAuditLogs'
import { SystemHealthWidget } from '@/components/dashboard/SystemHealthWidget'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { useDashboardSummary } from '@/hooks/useDashboardSummary'

// Charts are heavy (Recharts) — load them lazily so the dashboard shell paints fast.
const AgentActivityChart = lazy(() =>
  import('@/components/dashboard/AgentActivityChart').then((m) => ({
    default: m.AgentActivityChart,
  })),
)
const RiskTrendChart = lazy(() =>
  import('@/components/dashboard/RiskTrendChart').then((m) => ({ default: m.RiskTrendChart })),
)

function ChartSkeleton() {
  return (
    <Card>
      <CardContent className="space-y-3 p-6">
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-[228px] w-full" />
      </CardContent>
    </Card>
  )
}

/**
 * Operational dashboard home. Every widget pulls live data from the backend and
 * auto-refreshes every 60s. When the org has no agents yet we show a welcome /
 * onboarding empty state instead.
 */
export function DashboardPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const { data: summary, isSuccess } = useDashboardSummary()

  const greetingName = user?.full_name || user?.email?.split('@')[0] || 'there'
  const hasNoAgents = isSuccess && summary?.agents === 0

  if (hasNoAgents) {
    return (
      <div className="space-y-6">
        <DashboardHeader greetingName={greetingName} />
        <EmptyState
          icon={Bot}
          title="Welcome to AI Agent Control Tower"
          description="Register your first AI agent to start governing its actions."
          action={
            <Button onClick={() => navigate(ROUTES.AGENTS)}>
              <Plus className="h-4 w-4" />
              Create Agent
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <DashboardHeader greetingName={greetingName} />

      <KpiGrid />

      <div className="grid gap-4 lg:grid-cols-2">
        <Suspense fallback={<ChartSkeleton />}>
          <AgentActivityChart />
        </Suspense>
        <Suspense fallback={<ChartSkeleton />}>
          <RiskTrendChart />
        </Suspense>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <PendingApprovalWidget />
        </div>
        <SystemHealthWidget />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <RecentAgentActions />
        <RecentAuditLogs />
      </div>
    </div>
  )
}
