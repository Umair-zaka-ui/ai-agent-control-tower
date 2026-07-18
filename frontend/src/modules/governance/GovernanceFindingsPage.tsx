import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, ShieldQuestion, Wrench } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { governanceService } from '@/services'
import type { FindingType, ID } from '@/types'
import { GovernanceNav } from './components/GovernanceNav'
import { FINDING_STATUS_VARIANT, formatDate, labelForFindingType, SEVERITY_VARIANT } from './utils'

const TYPES: (FindingType | '')[] = ['', 'SOD_VIOLATION', 'TOXIC_PERMISSION', 'ORPHANED_ACCOUNT', 'PRIVILEGED_REVIEW_DUE']
const STATUSES = ['', 'OPEN', 'ACKNOWLEDGED', 'REMEDIATED', 'DISMISSED']

/** §17 — every detected governance issue, across SoD, toxic permission,
 * orphaned identity and privileged-review-due findings, with triage actions. */
export function GovernanceFindingsPage() {
  const qc = useQueryClient()
  const [findingType, setFindingType] = useState('')
  const [status, setStatus] = useState('OPEN')

  const findings = useQuery({
    queryKey: ['gov-findings', findingType, status],
    queryFn: () => governanceService.findings({
      finding_type: findingType || undefined, status: status || undefined,
    }),
  })

  const resolve = useMutation({
    mutationFn: ({ id, next }: { id: ID; next: string }) =>
      governanceService.remediateFinding(id, next),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['gov-findings'] })
      toast.success('Finding updated')
    },
    onError: (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed'),
  })

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={ShieldQuestion}
        title="Governance findings"
        description="Every detected governance issue in one explorer, across all finding types."
        backTo={ROUTES.GOVERNANCE_DASHBOARD}
        backLabel="Governance overview"
      />
      <GovernanceNav />

      <div className="flex flex-wrap gap-3">
        <Select className="w-56" aria-label="Finding type" value={findingType}
                options={TYPES.map((t) => ({ value: t, label: t ? labelForFindingType(t) : 'All types' }))}
                onChange={(e) => setFindingType(e.target.value)} />
        <Select className="w-44" aria-label="Status" value={status}
                options={STATUSES.map((s) => ({ value: s, label: s || 'All statuses' }))}
                onChange={(e) => setStatus(e.target.value)} />
      </div>

      <Card>
        <CardContent className="p-0">
          {findings.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (findings.data ?? []).length === 0 ? (
            <EmptyState icon={ShieldQuestion} title="No findings match this filter" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Type</TableHead>
                  <TableHead>Identity</TableHead>
                  <TableHead>Detected</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(findings.data ?? []).map((f) => (
                  <TableRow key={f.id}>
                    <TableCell className="font-medium">{labelForFindingType(f.finding_type)}</TableCell>
                    <TableCell className="text-muted-foreground">{f.identity_label ?? '—'}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(f.detected_at)}</TableCell>
                    <TableCell><Badge variant={SEVERITY_VARIANT[f.severity]}>{f.severity}</Badge></TableCell>
                    <TableCell><Badge variant={FINDING_STATUS_VARIANT[f.status]}>{f.status}</Badge></TableCell>
                    <TableCell className="text-right">
                      {f.status === 'OPEN' && (
                        <div className="flex justify-end gap-2">
                          <Button size="sm" variant="outline"
                                  onClick={() => resolve.mutate({ id: f.id, next: 'ACKNOWLEDGED' })}>
                            Acknowledge
                          </Button>
                          <Button size="sm" variant="outline"
                                  onClick={() => resolve.mutate({ id: f.id, next: 'DISMISSED' })}>
                            Dismiss
                          </Button>
                          <Link to={`${ROUTES.GOVERNANCE_REMEDIATION}?findingId=${f.id}`}>
                            <Button size="sm" variant="outline"><Wrench className="h-3.5 w-3.5" /> Remediate</Button>
                          </Link>
                        </div>
                      )}
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
