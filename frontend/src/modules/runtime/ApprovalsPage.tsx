import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ClipboardCheck, Loader2, XCircle } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService } from '@/services'
import type { ID } from '@/types'
import { RuntimeNav } from './components/RuntimeNav'
import { formatDate } from './utils'

/** Phase 5.0 §39, §66 — runtime approval obligations raised for high-risk
 * deployments and executions. */
export function ApprovalsPage() {
  const qc = useQueryClient()
  const approvals = useQuery({
    queryKey: ['runtime-approvals'], queryFn: () => runtimeService.approvals('PENDING'),
    refetchInterval: 10000,
  })
  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')

  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: ID; decision: 'APPROVED' | 'REJECTED' }) =>
      runtimeService.decideApproval(id, decision),
    onSuccess: (_r, { decision }) => {
      void qc.invalidateQueries({ queryKey: ['runtime-approvals'] })
      toast.success(decision === 'APPROVED' ? 'Approved' : 'Rejected')
    },
    onError,
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={ClipboardCheck}
        title="Runtime approvals"
        description="Human approval obligations raised by the runtime for mission-critical deployments and executions."
        backTo={ROUTES.RUNTIME_DASHBOARD}
        backLabel="Runtime overview"
      />
      <RuntimeNav />

      <Card>
        <CardContent className="p-0">
          {approvals.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (approvals.data ?? []).length === 0 ? (
            <EmptyState icon={ClipboardCheck} title="No pending approvals"
                        description="Mission-critical production deployments and executions requiring approval appear here." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Action</TableHead><TableHead>Risk</TableHead><TableHead>Reason</TableHead>
                  <TableHead>Requested</TableHead><TableHead className="text-right">Decision</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(approvals.data ?? []).map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="font-medium">{a.requested_action}</TableCell>
                    <TableCell><Badge variant="outline">{a.risk_score ?? '—'}</Badge></TableCell>
                    <TableCell className="max-w-xs truncate text-muted-foreground">{a.reason ?? '—'}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(a.created_at)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button size="sm" variant="outline" disabled={decide.isPending}
                                onClick={() => decide.mutate({ id: a.id, decision: 'APPROVED' })}>
                          <CheckCircle2 className="h-3.5 w-3.5" /> Approve
                        </Button>
                        <Button size="sm" variant="destructive" disabled={decide.isPending}
                                onClick={() => decide.mutate({ id: a.id, decision: 'REJECTED' })}>
                          <XCircle className="h-3.5 w-3.5" /> Reject
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
