import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpCircle, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService } from '@/services'
import { RuntimeNav } from '../components/RuntimeNav'

const STATUS_VARIANT: Record<string, 'success' | 'warning' | 'destructive' | 'secondary'> = {
  MIGRATION_READY: 'success',
  MISSING_ORGANIZATION: 'destructive',
  MISSING_OWNER: 'warning',
  MISSING_IDENTITY: 'warning',
  MISSING_DEFINITION: 'warning',
  REQUIRES_MANUAL_REVIEW: 'warning',
  INVALID: 'destructive',
}

/** Phase 5.1 SRS §70-§73 — classifies agents registered under Phase 5.0's
 * simpler flow against the current registry requirements. Classification is
 * read-only/advisory: it never changes an agent's lifecycle status itself,
 * it only flags what a manual review would need to fix (see
 * `AgentMigrationService` for why there is no automatic state change). */
export function MigrationPage() {
  const qc = useQueryClient()
  const [lastBatch, setLastBatch] = useState<string | null>(null)

  const records = useQuery({
    queryKey: ['runtime-migration-records'], queryFn: () => runtimeService.migrationRecords(),
  })

  const classify = useMutation({
    mutationFn: () => runtimeService.classifyLegacyAgents(),
    onSuccess: (rows) => {
      setLastBatch(rows[0]?.migration_batch_id ?? null)
      toast.success(rows.length ? `${rows.length} agent(s) classified` : 'All agents already classified')
      void qc.invalidateQueries({ queryKey: ['runtime-migration-records'] })
    },
    onError: (e: unknown) => toast.error((e as { message?: string }).message ?? 'Classification failed'),
  })

  const rows = records.data ?? []

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={ArrowUpCircle}
        title="Legacy agent migration"
        description="Classify agents registered before Phase 5.1 against the current registry requirements — ownership, identity, and definition completeness."
        backTo={ROUTES.RUNTIME_AGENTS}
        backLabel="Agent inventory"
      />
      <RuntimeNav />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">Classification runs</CardTitle>
          <Button size="sm" disabled={classify.isPending} onClick={() => classify.mutate()}>
            {classify.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Classify unclassified agents
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          {records.isLoading ? (
            <div className="p-4"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : rows.length === 0 ? (
            <EmptyState icon={ArrowUpCircle} title="No migration records yet"
                        description="Run classification to inventory every legacy agent in this organization." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Agent</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Warnings</TableHead>
                  <TableHead>Batch</TableHead>
                  <TableHead>Migrated at</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.id} className={r.migration_batch_id === lastBatch ? 'bg-muted/30' : undefined}>
                    <TableCell className="font-mono text-xs">{r.agent_id}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[r.migration_status] ?? 'secondary'}>{r.migration_status}</Badge>
                    </TableCell>
                    <TableCell className="max-w-xs text-xs text-muted-foreground">
                      {r.mapping_warnings.join('; ') || '—'}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{r.migration_batch_id}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(r.migrated_at).toLocaleString()}
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
