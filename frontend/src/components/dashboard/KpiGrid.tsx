import { useNavigate } from 'react-router-dom'
import { Activity, Ban, Bot, CheckCircle2, ClipboardList, ShieldCheck } from 'lucide-react'

import { ROUTES } from '@/constants/routes'
import { useDashboardSummary } from '@/hooks/useDashboardSummary'
import { formatNumber } from '@/utils/format'
import { KpiCard } from './KpiCard'

/**
 * The six headline KPI cards. Pulls live counts from /dashboard/summary; shows
 * skeletons while loading. The "Pending Approvals" card links to /approvals.
 */
export function KpiGrid() {
  const navigate = useNavigate()
  const { data, isLoading, isError } = useDashboardSummary()

  const loading = isLoading || isError
  const value = (n: number | undefined) => (data ? formatNumber(n ?? 0) : '—')

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <KpiCard title="Total Agents" value={value(data?.agents)} icon={Bot} accent="blue" loading={loading} />
      <KpiCard
        title="Active Agents"
        value={value(data?.active_agents)}
        icon={CheckCircle2}
        accent="green"
        loading={loading}
      />
      <KpiCard
        title="Pending Approvals"
        value={value(data?.pending_approvals)}
        icon={ClipboardList}
        accent="orange"
        loading={loading}
        onClick={() => navigate(ROUTES.APPROVALS)}
      />
      <KpiCard
        title="Blocked Actions"
        value={value(data?.blocked_actions)}
        icon={Ban}
        accent="red"
        loading={loading}
      />
      <KpiCard
        title="Total Policies"
        value={value(data?.policies)}
        icon={ShieldCheck}
        accent="blue"
        loading={loading}
      />
      <KpiCard
        title="Today's Actions"
        value={value(data?.today_actions)}
        icon={Activity}
        accent="green"
        loading={loading}
      />
    </div>
  )
}
