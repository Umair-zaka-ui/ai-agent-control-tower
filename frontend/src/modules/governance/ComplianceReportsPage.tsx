import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileCheck2, Loader2, Plus } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Button, Card, CardContent, CardHeader, CardTitle, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { governanceService } from '@/services'
import type { ComplianceFramework, ID } from '@/types'
import { GovernanceNav } from './components/GovernanceNav'
import { formatDate } from './utils'

/** §15, §16 — compliance evidence reports mapped to SOC 2, ISO 27001, HIPAA,
 * GDPR, NIST and CIS controls. Exports as JSON or CSV; PDF/Excel are produced
 * client-side from this payload (print-to-PDF / paste-to-Excel), matching the
 * export pattern used elsewhere in this app. */
export function ComplianceReportsPage() {
  const qc = useQueryClient()
  const [framework, setFramework] = useState<ComplianceFramework>('SOC2')

  const frameworks = useQuery({
    queryKey: ['gov-compliance-frameworks'],
    queryFn: () => governanceService.complianceFrameworks(),
  })
  const reports = useQuery({
    queryKey: ['gov-compliance-reports'],
    queryFn: () => governanceService.complianceReports(),
  })

  const generate = useMutation({
    mutationFn: () => governanceService.generateComplianceReport({ framework }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['gov-compliance-reports'] })
      toast.success('Report generated')
    },
    onError: (e: unknown) => toast.error((e as { message?: string }).message ?? 'Generation failed'),
  })

  const exportJson = (report: { id: ID; framework: string; payload: unknown }) => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `compliance-${report.framework}-${report.id}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const exportCsv = async (id: ID, framework2: string) => {
    const csv = await governanceService.exportComplianceReportCsv(id)
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `compliance-${framework2}-${id}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={FileCheck2}
        title="Compliance reports"
        description="Audit-ready evidence snapshots mapped to organizational compliance frameworks."
        backTo={ROUTES.GOVERNANCE_DASHBOARD}
        backLabel="Governance overview"
      />
      <GovernanceNav />

      <Card>
        <CardHeader><CardTitle className="text-base">Generate report</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Select className="w-48" aria-label="Framework" value={framework}
                  options={(frameworks.data ?? []).map((f) => ({ value: f.framework, label: f.display_name }))}
                  onChange={(e) => setFramework(e.target.value as ComplianceFramework)} />
          <Button disabled={generate.isPending} onClick={() => generate.mutate()}>
            <Plus className="h-4 w-4" /> Generate
          </Button>
        </CardContent>
      </Card>

      {frameworks.data && (
        <Card>
          <CardHeader><CardTitle className="text-base">Control mapping</CardTitle></CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            {frameworks.data.map((f) => (
              <div key={f.framework} className="rounded-lg border border-border p-3">
                <p className="text-sm font-medium text-foreground">{f.display_name}</p>
                {f.controls.map((c) => (
                  <p key={c.control} className="mt-1 text-xs text-muted-foreground">
                    {c.control} <span className="text-foreground/60">→</span> {c.platform_evidence}
                  </p>
                ))}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          {reports.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (reports.data ?? []).length === 0 ? (
            <EmptyState icon={FileCheck2} title="No reports generated yet" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Framework</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Generated</TableHead>
                  <TableHead className="text-right">Export</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(reports.data ?? []).map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-medium">{r.framework}</TableCell>
                    <TableCell className="text-muted-foreground">{r.report_type}</TableCell>
                    <TableCell className="text-muted-foreground">{r.version}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(r.generated_at)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button size="sm" variant="ghost" aria-label="Export JSON" onClick={() => exportJson(r)}>
                          <Download className="h-4 w-4" /> JSON
                        </Button>
                        <Button size="sm" variant="ghost" aria-label="Export CSV"
                                onClick={() => void exportCsv(r.id, r.framework)}>
                          <Download className="h-4 w-4" /> CSV
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
