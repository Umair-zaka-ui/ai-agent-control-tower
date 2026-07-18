import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, ScanSearch, ShieldQuestion } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { governanceService } from '@/services'
import { GovernanceNav } from './components/GovernanceNav'
import { FINDING_STATUS_VARIANT, formatDate, SEVERITY_VARIANT } from './utils'

/** §9, §10 — detected SoD violations. Scan runs org-wide on demand; it also
 * runs automatically after every role assignment (continuous detection). */
export function SoDFindingsPage() {
  const qc = useQueryClient()
  const findings = useQuery({ queryKey: ['gov-sod-findings'], queryFn: () => governanceService.sodFindings() })
  const scan = useMutation({
    mutationFn: () => governanceService.scanSod(),
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: ['gov-sod-findings'] })
      toast.success(created.length ? `${created.length} new violation(s) found` : 'No new violations found')
    },
    onError: (e: unknown) => toast.error((e as { message?: string }).message ?? 'Scan failed'),
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={ShieldQuestion}
        title="SoD findings"
        description="Detected Separation-of-Duties violations."
        backTo={ROUTES.GOVERNANCE_DASHBOARD}
        backLabel="Governance overview"
        actions={
          <Button disabled={scan.isPending} onClick={() => scan.mutate()}>
            {scan.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ScanSearch className="h-4 w-4" />} Scan now
          </Button>
        }
      />
      <GovernanceNav />

      <Card>
        <CardContent className="p-0">
          {findings.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (findings.data ?? []).length === 0 ? (
            <EmptyState icon={ShieldQuestion} title="No SoD violations found"
                        description="Scan now, or wait for the automatic check that runs on every role assignment." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Identity</TableHead>
                  <TableHead>Rule</TableHead>
                  <TableHead>Detected</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(findings.data ?? []).map((f) => (
                  <TableRow key={f.id}>
                    <TableCell className="font-medium">{f.identity_label ?? '—'}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {(f.details as { rule_name?: string })?.rule_name ?? '—'}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(f.detected_at)}</TableCell>
                    <TableCell><Badge variant={SEVERITY_VARIANT[f.severity]}>{f.severity}</Badge></TableCell>
                    <TableCell><Badge variant={FINDING_STATUS_VARIANT[f.status]}>{f.status}</Badge></TableCell>
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
