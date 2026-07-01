import { useState } from 'react'
import { Download } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { useAuth } from '@/hooks/useAuth'
import { useNotifications } from '@/hooks/useNotifications'
import { AnalyticsLayout, ExportDialog, ReportsPanel } from '../components'
import { useReports } from '../hooks'
import { AnalyticsAccessDenied } from './AnalyticsAccessDenied'
import type { ReportPeriod } from '../types'
import { type ReportFormat, exportReportCsv, exportReportJson } from '../utils/export'
import { canViewAnalytics } from '../utils/permissions'

const PERIODS = [
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'quarterly', label: 'Quarterly' },
  { value: 'annual', label: 'Annual' },
]

export function ReportsCenterPage() {
  const { permissions } = useAuth()
  if (!canViewAnalytics(permissions)) {
    return <AnalyticsAccessDenied surface="reports center" permission="analytics.view" />
  }
  return <ReportsContent />
}

function ReportsContent() {
  const notify = useNotifications()
  const [period, setPeriod] = useState<ReportPeriod>('weekly')
  const [dialogOpen, setDialogOpen] = useState(false)
  const { data, isLoading, isError, refetch } = useReports(period)

  const handleExport = (format: ReportFormat) => {
    if (!data) return
    if (format === 'json') exportReportJson(data)
    else exportReportCsv(data)
    notify.success(`Report exported as ${format.toUpperCase()}`)
    setDialogOpen(false)
  }

  return (
    <AnalyticsLayout
      title="Reports Center"
      description="Generate and export operational AI reports for any reporting period."
      actions={
        <div className="flex items-center gap-2">
          <Select
            aria-label="Report period"
            className="h-9 w-32"
            value={period}
            options={PERIODS}
            onChange={(e) => setPeriod(e.target.value as ReportPeriod)}
          />
          <Button size="sm" onClick={() => setDialogOpen(true)} disabled={!data}>
            <Download className="h-4 w-4" />
            Export
          </Button>
        </div>
      }
    >
      {isError ? (
        <div role="alert" className="flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-sm text-muted-foreground">Unable to load analytics.</p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Retry
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          {data ? <p className="text-sm text-muted-foreground">{data.label}</p> : null}
          <ReportsPanel report={data} loading={isLoading} />
        </div>
      )}

      <ExportDialog open={dialogOpen} onOpenChange={setDialogOpen} onConfirm={handleExport} />
    </AnalyticsLayout>
  )
}
