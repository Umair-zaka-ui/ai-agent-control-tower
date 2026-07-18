import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Crown, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { governanceService } from '@/services'
import type { PrivilegedAccount } from '@/types'
import { GovernanceNav } from './components/GovernanceNav'
import { formatDate, RISK_BAND_VARIANT } from './utils'

/** §11 — privileged access governance: periodic review, approval and risk
 * scoring for platform-owner/admin/security-admin/org-admin/compliance-admin
 * grants. */
export function PrivilegedAccessPage() {
  const qc = useQueryClient()
  const accounts = useQuery({
    queryKey: ['gov-privileged-accounts'],
    queryFn: () => governanceService.privilegedAccounts(),
  })

  const invalidate = () => void qc.invalidateQueries({ queryKey: ['gov-privileged-accounts'] })
  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')

  const requestReview = useMutation({
    mutationFn: (a: PrivilegedAccount) =>
      governanceService.requestPrivilegedReview(a.identity_id, a.role_name, a.assignment_id),
    onSuccess: () => { invalidate(); toast.success('Review requested') },
    onError,
  })

  const approveOrRevoke = useMutation({
    mutationFn: async ({ account, decision }: { account: PrivilegedAccount; decision: 'APPROVED' | 'REVOKED' }) => {
      const review = await governanceService.requestPrivilegedReview(
        account.identity_id, account.role_name, account.assignment_id)
      return governanceService.decidePrivilegedReview(review.id, decision, account.assignment_id)
    },
    onSuccess: (_r, { decision }) => {
      invalidate()
      toast.success(decision === 'REVOKED' ? 'Access revoked' : 'Access approved')
    },
    onError,
  })

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Crown}
        title="Privileged access"
        description="Platform Owner, Platform Admin, Security Admin, Organization Admin and Compliance Admin grants, with risk scoring and review/approval."
        backTo={ROUTES.GOVERNANCE_DASHBOARD}
        backLabel="Governance overview"
      />
      <GovernanceNav />

      <Card>
        <CardContent className="p-0">
          {accounts.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (accounts.data ?? []).length === 0 ? (
            <EmptyState icon={Crown} title="No privileged accounts found"
                        description="No identity in this organization currently holds a tracked privileged role." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Identity</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Last active</TableHead>
                  <TableHead>Review</TableHead>
                  <TableHead>Risk</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(accounts.data ?? []).map((a) => (
                  <TableRow key={`${a.identity_id}-${a.role_name}`}>
                    <TableCell className="font-medium">{a.identity_label}</TableCell>
                    <TableCell className="text-muted-foreground">{a.role_name}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(a.last_activity_at)}</TableCell>
                    <TableCell className="text-muted-foreground">{a.review_status ?? '—'}</TableCell>
                    <TableCell>
                      <Badge variant={RISK_BAND_VARIANT[a.risk_band] ?? 'secondary'}>
                        {a.risk_band} ({a.risk_score})
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button size="sm" variant="outline" disabled={requestReview.isPending}
                                onClick={() => requestReview.mutate(a)}>
                          Request review
                        </Button>
                        <Button size="sm" variant="outline" disabled={approveOrRevoke.isPending}
                                onClick={() => approveOrRevoke.mutate({ account: a, decision: 'APPROVED' })}>
                          Approve
                        </Button>
                        <Button size="sm" variant="destructive" disabled={approveOrRevoke.isPending}
                                onClick={() => approveOrRevoke.mutate({ account: a, decision: 'REVOKED' })}>
                          Revoke
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
