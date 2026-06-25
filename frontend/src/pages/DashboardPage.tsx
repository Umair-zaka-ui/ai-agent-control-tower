import { PageHeader } from '@/components/common/PageHeader'
import { StatsCards } from '@/components/dashboard/StatsCards'
import { RiskTrendChart } from '@/components/charts/RiskTrendChart'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuth } from '@/hooks/useAuth'

/**
 * Dashboard landing page. Demonstrates the component-driven composition the SRS
 * mandates: page → header + stats + chart, each a small reusable component.
 */
export function DashboardPage() {
  const { user } = useAuth()
  const greetingName = user?.full_name || user?.email?.split('@')[0] || 'there'

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Welcome back, ${greetingName}`}
        description="A real-time overview of your organization's AI governance posture."
      />

      <StatsCards />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Risk Trend</CardTitle>
          </CardHeader>
          <CardContent>
            <RiskTrendChart />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Activity</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Live agent activity and the approval timeline will appear here once wired to the
              backend in a later Part.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
