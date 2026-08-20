import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { History, Loader2, RotateCcw } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Card, CardContent, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { operationsService } from '@/services'
import { OperationsNav } from './components/OperationsNav'
import { formatMoment } from './components/format'

/**
 * Phase 3.10 view 3 — Release History (M3-3.10-FR-003).
 *
 * The audited release timeline: every lifecycle transition and every rollback,
 * newest first, across the whole organization.
 *
 * SRS §13 requires that a release be *reconstructable*. Until this view, the
 * data existed but was only reachable one deployment at a time — you had to
 * already know a deployment's id to ask what happened to it, which is no use
 * when the question is "what shipped last night?".
 *
 * Rollbacks are visually distinct because they are the entries someone
 * scanning this page is looking for. An automatic rollback shows as
 * *automation* rather than being attributed to a person: Phase 3.7 leaves
 * `initiated_by` null on purpose, and inventing a name here would undo that.
 *
 * Fed by `GET /runtime/operations/release-history`.
 */
export function ReleaseHistoryPage() {
  const [environmentId, setEnvironmentId] = useState('')

  const environments = useQuery({
    queryKey: ['ops-environments'],
    queryFn: () => operationsService.environments(),
  })
  const history = useQuery({
    queryKey: ['ops-release-history', environmentId],
    queryFn: () => operationsService.releaseHistory({
      environment_id: environmentId || undefined, limit: 200,
    }),
  })

  const entries = history.data ?? []

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={History}
        title="Release history"
        description="Every deployment, promotion and rollback, in order — the audited record §13 requires a release be reconstructable from."
        backTo={ROUTES.OPS_OVERVIEW}
        backLabel="Release operations"
        actions={
          <Select
            aria-label="Filter by environment"
            value={environmentId}
            onChange={(e) => setEnvironmentId(e.target.value)}
            placeholder="All environments"
            options={(environments.data ?? []).map((env) => ({
              value: env.id, label: env.display_name || env.name,
            }))}
          />
        }
      />
      <OperationsNav />

      <Card>
        <CardContent className="p-0">
          {history.isLoading ? (
            <div className="flex justify-center p-10">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : entries.length === 0 ? (
            <EmptyState
              icon={History}
              title="No release activity yet"
              description="Deployments, promotions and rollbacks appear here as they happen."
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Event</TableHead>
                    <TableHead>Agent</TableHead>
                    <TableHead>Environment</TableHead>
                    <TableHead>Transition</TableHead>
                    <TableHead>By</TableHead>
                    <TableHead>Reason</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {entries.map((entry) => (
                    <TableRow
                      key={`${entry.kind}-${entry.id}`}
                      className={entry.kind === 'ROLLBACK' ? 'bg-destructive/5' : undefined}
                    >
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatMoment(entry.occurred_at)}
                      </TableCell>
                      <TableCell>
                        {entry.kind === 'ROLLBACK' ? (
                          <Badge variant="destructive">
                            <RotateCcw className="mr-1 h-3 w-3" aria-hidden />
                            {entry.event_type.replace(/_/g, ' ')}
                          </Badge>
                        ) : (
                          <Badge variant="outline">{entry.event_type.replace(/_/g, ' ')}</Badge>
                        )}
                      </TableCell>
                      <TableCell className="font-medium">
                        {entry.deployment_id ? (
                          <Link
                            to={ROUTES.OPS_DEPLOYMENT_DETAIL.replace(':id', entry.deployment_id)}
                            className="hover:underline"
                          >
                            {entry.agent_name ?? entry.agent_id}
                          </Link>
                        ) : (entry.agent_name ?? '—')}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{entry.environment_name ?? '—'}</Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {entry.from_state ? `${entry.from_state} → ${entry.to_state}` : entry.to_state}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {entry.actor_id
                          ? <span className="font-mono text-xs">{entry.actor_id.slice(0, 8)}</span>
                          : <span title="No human initiated this — Phase 3.7 records automatic rollbacks with no actor rather than attributing them to a system user.">
                              automation
                            </span>}
                      </TableCell>
                      <TableCell className="max-w-xs truncate text-muted-foreground" title={entry.reason ?? ''}>
                        {entry.reason ?? '—'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
