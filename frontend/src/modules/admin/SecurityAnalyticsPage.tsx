import { useQuery } from '@tanstack/react-query'
import { Activity, Loader2 } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { adminService } from '@/services'
import { AdminNav } from './components/AdminNav'

/** §17 — security analytics for the authorization platform. */
export function SecurityAnalyticsPage() {
  const analytics = useQuery({
    queryKey: ['admin-analytics'],
    queryFn: adminService.analytics,
    refetchInterval: 60_000,
  })

  const stats = analytics.data
  const tiles = stats ? [
    { label: 'Denied (24h)', value: stats.denied_requests_24h },
    { label: 'Denied (7d)', value: stats.denied_requests_7d },
    { label: 'High-risk (24h)', value: stats.high_risk_decisions_24h },
    { label: 'MFA challenges', value: stats.mfa_challenges_total },
    { label: 'Approvals', value: stats.approval_requests_total },
    { label: 'Approval rate', value: `${(stats.approval_approval_rate * 100).toFixed(0)}%` },
    { label: 'Latency avg', value: `${stats.authorization_latency_ms_avg.toFixed(1)}ms` },
    { label: 'Latency p95', value: `${stats.authorization_latency_ms_p95.toFixed(1)}ms` },
    { label: 'Cache hit ratio', value: `${(stats.cache_hit_ratio * 100).toFixed(0)}%` },
    { label: 'ABAC denies', value: stats.abac_denies_total },
    { label: 'ABAC challenges', value: stats.abac_challenges_total },
    { label: 'Policy errors', value: stats.policy_errors_total },
  ] : []

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
      <PageHeader
        icon={Activity}
        title="Security analytics"
        description="Operational security metrics for the authorization platform."
        backTo={ROUTES.ADMIN_DASHBOARD}
        backLabel="Administration overview"
      />
      <AdminNav />

      {analytics.isLoading ? (
        <div className="flex justify-center p-10">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : analytics.isError ? (
        <p className="p-4 text-sm text-destructive">Failed to load analytics.</p>
      ) : stats ? (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
               data-testid="analytics-tiles">
            {tiles.map((t) => (
              <Card key={t.label}>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">{t.label}</p>
                  <p className="text-2xl font-semibold text-foreground">
                    {typeof t.value === 'number' ? t.value.toLocaleString() : t.value}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle className="text-base">Denied requests (7d)</CardTitle></CardHeader>
              <CardContent className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={stats.denied_trend}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis dataKey="date" fontSize={11} />
                    <YAxis allowDecimals={false} fontSize={11} />
                    <Tooltip />
                    <Line type="monotone" dataKey="denied" stroke="#ef4444" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="text-base">Top denied permissions</CardTitle></CardHeader>
              <CardContent className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={stats.top_denied_permissions} layout="vertical">
                    <XAxis type="number" allowDecimals={false} fontSize={11} />
                    <YAxis type="category" dataKey="permission" width={170} fontSize={11} />
                    <Tooltip />
                    <Bar dataKey="denied" fill="#ef4444" />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            <Card className="lg:col-span-2">
              <CardHeader><CardTitle className="text-base">Resource sharing trend (7d)</CardTitle></CardHeader>
              <CardContent className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={stats.sharing_trend}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis dataKey="date" fontSize={11} />
                    <YAxis allowDecimals={false} fontSize={11} />
                    <Tooltip />
                    <Line type="monotone" dataKey="shares" stroke="#6366f1" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  )
}
