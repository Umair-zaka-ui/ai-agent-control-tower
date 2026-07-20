import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertOctagon, HeartPulse, Loader2, Server } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { runtimeService } from '@/services'
import { RuntimeNav } from './components/RuntimeNav'
import { formatDate } from './utils'

/** Phase 5.0 §75, §60, §66 — operations center: worker/platform health and
 * the emergency kill switch. Kill-switch activation requires elevated
 * permission and is always confirmed before firing (§60). */
export function OperationsPage() {
  const { user } = useAuth()
  const organizationId = user?.organization_id
  const [reason, setReason] = useState('')
  const [agentId, setAgentId] = useState('')

  const health = useQuery({ queryKey: ['runtime-health'], queryFn: () => runtimeService.platformHealth() })
  const workers = useQuery({ queryKey: ['runtime-workers'], queryFn: () => runtimeService.workers(), refetchInterval: 15000 })
  const agents = useQuery({ queryKey: ['runtime-agents'], queryFn: () => runtimeService.agents() })

  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')

  const killAgent = useMutation({
    mutationFn: () => runtimeService.killAgent(agentId, reason),
    onSuccess: (r) => toast.success(`Kill switch activated — ${r.executions_cancelled} execution(s) cancelled`),
    onError,
  })
  const killOrg = useMutation({
    mutationFn: () => runtimeService.killOrganization(organizationId ?? '', reason),
    onSuccess: (r) => toast.success(`Kill switch activated — ${r.executions_cancelled} execution(s) cancelled`),
    onError,
  })

  const confirmAndRun = (label: string, run: () => void) => {
    if (!reason.trim()) { toast.error('A reason is required before activating the kill switch.'); return }
    if (window.confirm(`${label} This immediately cancels active executions and cannot be undone. Continue?`)) run()
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Server}
        title="Operations center"
        description="Live runtime health, worker status and the emergency kill switch."
        backTo={ROUTES.RUNTIME_DASHBOARD}
        backLabel="Runtime overview"
      />
      <RuntimeNav />

      <Card>
        <CardHeader><CardTitle className="text-base">Deployment health</CardTitle></CardHeader>
        <CardContent>
          {health.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : Object.keys(health.data ?? {}).length === 0 ? (
            <p className="text-sm text-muted-foreground">No active deployments yet.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {Object.entries(health.data ?? {}).map(([status, count]) => (
                <span key={status} className="rounded-lg bg-muted px-3 py-2 text-sm font-medium text-foreground ring-1 ring-inset ring-border">
                  {status} <span className="font-normal text-muted-foreground">· {count}</span>
                </span>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Workers</CardTitle></CardHeader>
        <CardContent className="p-0">
          {workers.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (workers.data ?? []).length === 0 ? (
            <EmptyState icon={HeartPulse} title="No worker heartbeats yet"
                        description="This environment runs the worker inline per execution — dedicated worker heartbeats appear once an out-of-process poller is configured." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow><TableHead>Worker</TableHead><TableHead>Status</TableHead><TableHead>Last seen</TableHead></TableRow>
              </TableHeader>
              <TableBody>
                {(workers.data ?? []).map((w) => (
                  <TableRow key={w.worker_id}>
                    <TableCell className="font-mono text-xs">{w.worker_id}</TableCell>
                    <TableCell><Badge variant={w.status === 'HEALTHY' ? 'success' : 'warning'}>{w.status}</Badge></TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(w.last_seen)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card className="border-destructive/30">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base text-destructive">
            <AlertOctagon className="h-4 w-4" /> Emergency kill switch
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Immediately blocks new executions and cancels in-flight ones at the chosen scope. Always audited.
          </p>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required)"
                 aria-label="Kill switch reason" />
          <div className="flex flex-wrap items-center gap-2">
            <Select className="w-56" aria-label="Agent to suspend" value={agentId} placeholder="Select an agent…"
                    options={(agents.data ?? []).map((a) => ({ value: a.id, label: a.name }))}
                    onChange={(e) => setAgentId(e.target.value)} />
            <Button variant="destructive" size="sm" disabled={!agentId || killAgent.isPending}
                    onClick={() => confirmAndRun('Suspend this agent and cancel its active executions.', () => killAgent.mutate())}>
              Kill agent
            </Button>
            <Button variant="destructive" size="sm" disabled={killOrg.isPending}
                    onClick={() => confirmAndRun('Suspend every active deployment and cancel every active execution in this organization.', () => killOrg.mutate())}>
              Kill entire organization
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
