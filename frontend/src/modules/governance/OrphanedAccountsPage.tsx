import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, ScanSearch, UserX } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { governanceService } from '@/services'
import { GovernanceNav } from './components/GovernanceNav'
import { FINDING_STATUS_VARIANT, formatDate } from './utils'

const REASON_LABELS: Record<string, string> = {
  DISABLED_WITH_ACTIVE_ACCESS: 'Disabled user, still has active access',
  INACTIVE_OVER_90_DAYS: 'No activity for 90+ days',
  STALE_API_KEY: 'API key unused for 90+ days',
  UNUSED_ROLE: 'Role has zero assignments',
}

/** §12 — orphaned identity detection: disabled users with active access,
 * inactive accounts, stale API keys and unused roles. */
export function OrphanedAccountsPage() {
  const qc = useQueryClient()
  const findings = useQuery({
    queryKey: ['gov-orphaned-accounts'],
    queryFn: () => governanceService.orphanedAccounts(),
  })
  const scan = useMutation({
    mutationFn: () => governanceService.scanOrphanedAccounts(),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: ['gov-orphaned-accounts'] })
      toast.success(
        `Scanned ${result.scanned_users} users, ${result.scanned_api_keys} keys, ` +
        `${result.scanned_roles} roles — ${result.findings_created} new finding(s)`,
      )
    },
    onError: (e: unknown) => toast.error((e as { message?: string }).message ?? 'Scan failed'),
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={UserX}
        title="Orphaned accounts"
        description="Disabled/inactive identities, stale API keys and unused roles."
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
            <EmptyState icon={UserX} title="No orphaned identities found"
                        description="Scan now to check for disabled-but-granted users, inactive accounts, stale API keys and unused roles." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Identity / resource</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead>Detected</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(findings.data ?? []).map((f) => {
                  const reason = (f.details as { reason?: string })?.reason ?? ''
                  return (
                    <TableRow key={f.id}>
                      <TableCell className="font-medium">{f.identity_label ?? '—'}</TableCell>
                      <TableCell className="text-muted-foreground">{REASON_LABELS[reason] ?? reason}</TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(f.detected_at)}</TableCell>
                      <TableCell><Badge variant={FINDING_STATUS_VARIANT[f.status]}>{f.status}</Badge></TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
