import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Cpu, Loader2, Play } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Select, Textarea,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService } from '@/services'
import { RuntimeNav } from './components/RuntimeNav'
import { EXECUTION_STATUS_VARIANT, formatCost, formatDate, formatMs } from './utils'

/** Phase 5.0 §26, §66 — run agents through the Runtime Gateway and browse
 * execution history. */
export function ExecutionsPage() {
  const qc = useQueryClient()
  const [agentId, setAgentId] = useState('')
  const [payload, setPayload] = useState('{}')

  const executions = useQuery({
    queryKey: ['runtime-executions'], queryFn: () => runtimeService.executions({ limit: 100 }),
    refetchInterval: 10000,
  })
  const agents = useQuery({ queryKey: ['runtime-agents'], queryFn: () => runtimeService.agents() })
  const activeAgents = (agents.data ?? []).filter((a) => a.lifecycle_status === 'ACTIVE')
  const agentName = (id: string) => agents.data?.find((a) => a.id === id)?.name ?? id

  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')

  const run = useMutation({
    mutationFn: () => {
      let input_payload: Record<string, unknown> = {}
      try { input_payload = JSON.parse(payload || '{}') } catch { /* fall back to {} */ }
      return runtimeService.requestExecution({ agent_id: agentId, input_payload })
    },
    onSuccess: (e) => {
      void qc.invalidateQueries({ queryKey: ['runtime-executions'] })
      toast.success(`Execution ${e.status.toLowerCase()}`)
    },
    onError,
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Cpu}
        title="Executions"
        description="Request agent executions through the Runtime Gateway — authorization, runtime policy and approvals are enforced before anything runs."
        backTo={ROUTES.RUNTIME_DASHBOARD}
        backLabel="Runtime overview"
      />
      <RuntimeNav />

      <Card>
        <CardHeader><CardTitle className="text-base">Run an agent</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-3">
            <Select className="w-64" aria-label="Agent" value={agentId} placeholder="Select an active agent…"
                    options={activeAgents.map((a) => ({ value: a.id, label: a.name }))}
                    onChange={(e) => setAgentId(e.target.value)} />
          </div>
          <Textarea value={payload} onChange={(e) => setPayload(e.target.value)} rows={4}
                    aria-label="Input payload (JSON)" placeholder='{"question": "..."}' className="font-mono text-xs" />
          <Button disabled={!agentId || run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Run
          </Button>
          {activeAgents.length === 0 && (
            <p className="text-xs text-muted-foreground">No active agents yet — activate one first.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {executions.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (executions.data ?? []).length === 0 ? (
            <EmptyState icon={Cpu} title="No executions yet" description="Run an agent above to see it here." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Agent</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Cost</TableHead>
                  <TableHead>Requested</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(executions.data ?? []).map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="font-medium">
                      <Link to={ROUTES.RUNTIME_EXECUTION_DETAIL.replace(':id', e.id)} className="hover:underline">
                        {agentName(e.agent_id)}
                      </Link>
                    </TableCell>
                    <TableCell><Badge variant={EXECUTION_STATUS_VARIANT[e.status]}>{e.status}</Badge></TableCell>
                    <TableCell className="text-muted-foreground">{formatMs(e.duration_ms)}</TableCell>
                    <TableCell className="text-muted-foreground">{formatCost(e.cost)}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(e.created_at)}</TableCell>
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
