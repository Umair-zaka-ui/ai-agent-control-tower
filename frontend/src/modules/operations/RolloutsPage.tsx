import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Rocket } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { operationsService } from '@/services'
import { OperationsNav } from './components/OperationsNav'
import {
  RolloutStateBadge,
} from './components/state'
import { formatMoment } from './components/format'

/**
 * Phase 3.10 view 5 — Rollout Timeline (M3-3.10-FR-005).
 *
 * Every canary and rolling deployment, live ones first.
 *
 * This view is only possible because Phase 3.10 added `GET /runtime/rollouts`.
 * Phase 3.5 shipped `GET /rollouts/{id}` and no list, which meant a rollout
 * was findable only if you had kept the id returned when you created it — a
 * canary could be advancing through production traffic with no way to see it
 * in the API at all.
 */
export function RolloutsPage() {
  const [liveOnly, setLiveOnly] = useState(true)
  const rollouts = useQuery({
    queryKey: ['ops-rollouts', liveOnly],
    queryFn: () => operationsService.rollouts({ active_only: liveOnly }),
    refetchInterval: 20_000,
  })

  const rows = rollouts.data ?? []

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Rocket}
        title="Rollouts"
        description="Canary and rolling deployments — their stage, their state, and what they are promoting."
        backTo={ROUTES.OPS_OVERVIEW}
        backLabel="Release operations"
        actions={
          <Button variant="outline" onClick={() => setLiveOnly((v) => !v)}>
            {liveOnly ? 'Show all rollouts' : 'Show live only'}
          </Button>
        }
      />
      <OperationsNav />

      <Card>
        <CardContent className="p-0">
          {rollouts.isLoading ? (
            <div className="flex justify-center p-10">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : rows.length === 0 ? (
            <EmptyState
              icon={Rocket}
              title={liveOnly ? 'No rollouts in flight' : 'No rollouts yet'}
              description={liveOnly
                ? 'Nothing is currently promoting. Switch to "all rollouts" to see completed ones.'
                : 'Start a canary from an agent, or a rolling deployment from a deployment detail page.'}
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Agent</TableHead>
                    <TableHead>Kind</TableHead>
                    <TableHead>Environment</TableHead>
                    <TableHead>Promoting</TableHead>
                    <TableHead>Stage</TableHead>
                    <TableHead>State</TableHead>
                    <TableHead>Started</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((rollout) => (
                    <TableRow key={rollout.id} className={rollout.is_live ? undefined : 'opacity-70'}>
                      <TableCell className="font-medium">
                        <Link
                          to={ROUTES.OPS_ROLLOUT_DETAIL.replace(':id', rollout.id)}
                          className="hover:underline"
                        >
                          {rollout.agent_name ?? rollout.agent_id}
                        </Link>
                      </TableCell>
                      <TableCell><Badge variant="outline">{rollout.kind}</Badge></TableCell>
                      <TableCell className="text-muted-foreground">{rollout.environment_name ?? '—'}</TableCell>
                      <TableCell className="whitespace-nowrap font-mono text-xs">
                        {rollout.stable_version ?? '—'} → {rollout.candidate_version ?? '—'}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {rollout.current_stage_index + 1} / {rollout.stage_count}
                      </TableCell>
                      <TableCell><RolloutStateBadge state={rollout.state} /></TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatMoment(rollout.created_at)}
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
