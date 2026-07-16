import { useQuery } from '@tanstack/react-query'
import { Loader2, ShieldCheck } from 'lucide-react'
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
import { adminService } from '@/services'
import { AdminNav } from './components/AdminNav'

const WIDGETS: { key: keyof import('@/types').AdminDashboardWidgets; label: string;
                 format?: (v: number) => string }[] = [
  { key: 'total_users', label: 'Total users' },
  { key: 'active_roles', label: 'Active roles' },
  { key: 'active_permissions', label: 'Permissions' },
  { key: 'active_policies', label: 'Active policies' },
  { key: 'active_sessions', label: 'Active sessions' },
  { key: 'authorization_requests_24h', label: 'Authz requests (24h)' },
  { key: 'denied_requests_24h', label: 'Denied (24h)' },
  { key: 'approval_requests_pending', label: 'Approvals pending' },
  { key: 'mfa_challenges_total', label: 'MFA challenges' },
  { key: 'high_risk_decisions_24h', label: 'High-risk (24h)' },
  { key: 'cache_hit_ratio', label: 'Cache hit ratio',
    format: (v) => `${(v * 100).toFixed(0)}%` },
  { key: 'policy_evaluation_latency_ms', label: 'Eval latency',
    format: (v) => `${v.toFixed(1)}ms` },
]

/** §6 — operational overview of authorization health. */
export function AdminDashboardPage() {
  const dashboard = useQuery({
    queryKey: ['admin-dashboard'],
    queryFn: adminService.dashboard,
    refetchInterval: 60_000,
  })

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold text-foreground">
          <ShieldCheck className="h-5 w-5" /> Authorization administration
        </h1>
        <p className="text-sm text-muted-foreground">
          The operational control plane for identity and access management.
        </p>
      </div>
      <AdminNav />

      {dashboard.isLoading ? (
        <div className="flex justify-center p-10">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : dashboard.isError ? (
        <p className="p-4 text-sm text-destructive">Failed to load the dashboard.</p>
      ) : dashboard.data ? (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
               data-testid="dashboard-widgets">
            {WIDGETS.map(({ key, label, format }) => (
              <Card key={key}>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p className="text-2xl font-semibold text-foreground">
                    {format
                      ? format(dashboard.data.widgets[key])
                      : dashboard.data.widgets[key].toLocaleString()}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle className="text-base">Authorization trend (7d)</CardTitle></CardHeader>
              <CardContent className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={dashboard.data.charts.authorization_trend}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis dataKey="date" fontSize={11} />
                    <YAxis allowDecimals={false} fontSize={11} />
                    <Tooltip />
                    <Line type="monotone" dataKey="total" stroke="#6366f1" dot={false} />
                    <Line type="monotone" dataKey="denied" stroke="#ef4444" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="text-base">Top requested permissions</CardTitle></CardHeader>
              <CardContent className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={dashboard.data.charts.top_permissions} layout="vertical">
                    <XAxis type="number" allowDecimals={false} fontSize={11} />
                    <YAxis type="category" dataKey="permission" width={160} fontSize={11} />
                    <Tooltip />
                    <Bar dataKey="total" fill="#6366f1" />
                    <Bar dataKey="denied" fill="#ef4444" />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="text-base">Policy matches</CardTitle></CardHeader>
              <CardContent>
                {dashboard.data.charts.policy_matches.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No policy matches recorded.</p>
                ) : (
                  <ul className="space-y-1">
                    {dashboard.data.charts.policy_matches.map((p) => (
                      <li key={p.policy} className="flex justify-between text-sm">
                        <span className="truncate text-foreground">{p.policy}</span>
                        <span className="text-muted-foreground">{p.matches}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="text-base">Approval queue</CardTitle></CardHeader>
              <CardContent>
                {dashboard.data.charts.approval_queue.length === 0 ? (
                  <p className="text-sm text-muted-foreground">The approval queue is empty.</p>
                ) : (
                  <ul className="space-y-1">
                    {dashboard.data.charts.approval_queue.map((row) => (
                      <li key={row.status} className="flex justify-between text-sm">
                        <span className="text-foreground">{row.status}</span>
                        <span className="text-muted-foreground">{row.total}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  )
}
