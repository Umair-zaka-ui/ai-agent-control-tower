import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type { AnalyticsReport } from '../types'

/** Renders a generated report's sections (SRS §Reports Center / §ReportsPanel). */
export function ReportsPanel({ report, loading }: { report?: AnalyticsReport; loading?: boolean }) {
  if (loading || !report) {
    return (
      <div className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Card key={i} className="p-6">
            <Skeleton className="h-5 w-24" />
            <Skeleton className="mt-4 h-24 w-full" />
          </Card>
        ))}
      </div>
    )
  }
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {report.sections.map((section) => (
        <Card key={section.title}>
          <CardHeader>
            <CardTitle className="text-base">{section.title}</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="space-y-2">
              {section.rows.map((row) => (
                <div key={row.label} className="flex items-center justify-between border-b border-border/60 pb-1.5 text-sm last:border-0">
                  <dt className="text-muted-foreground">{row.label}</dt>
                  <dd className="font-medium tabular-nums">{row.value}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
