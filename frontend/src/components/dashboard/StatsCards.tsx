import { Bot, CheckSquare, ShieldAlert, Activity } from 'lucide-react'

import { StatCard } from './StatCard'

/**
 * Dashboard KPI row. Part 1 renders placeholder figures; a later Part swaps the
 * static values for `useDashboardSummary()` data.
 */
export function StatsCards() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard label="Active Agents" value="—" icon={Bot} hint="Awaiting backend" />
      <StatCard
        label="Pending Approvals"
        value="—"
        icon={CheckSquare}
        hint="Awaiting backend"
        accentClassName="bg-warning/15 text-warning"
      />
      <StatCard
        label="High-Risk Actions"
        value="—"
        icon={ShieldAlert}
        hint="Awaiting backend"
        accentClassName="bg-destructive/15 text-destructive"
      />
      <StatCard
        label="Total Actions"
        value="—"
        icon={Activity}
        hint="Awaiting backend"
        accentClassName="bg-success/15 text-success"
      />
    </div>
  )
}
