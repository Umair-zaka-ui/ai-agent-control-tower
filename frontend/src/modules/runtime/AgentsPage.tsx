import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Loader2, Plus } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService } from '@/services'
import type { Criticality } from '@/types'
import { RuntimeNav } from './components/RuntimeNav'
import { AGENT_LIFECYCLE_VARIANT, CRITICALITY_VARIANT, formatDate } from './utils'

const CRITICALITIES: Criticality[] = ['LOW', 'MEDIUM', 'HIGH', 'MISSION_CRITICAL']

/** Phase 5.0 §16, §66 — the agent registry: every AI agent as a managed
 * enterprise workload with a stable identity, owner and lifecycle. */
export function AgentsPage() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [entrypoint, setEntrypoint] = useState('')
  const [criticality, setCriticality] = useState<Criticality>('MEDIUM')

  const agents = useQuery({ queryKey: ['runtime-agents'], queryFn: () => runtimeService.agents() })
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['runtime-agents'] })
  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')

  const register = useMutation({
    mutationFn: () => runtimeService.registerAgent({
      name, criticality,
      definition: { name: `${name} definition`, entrypoint, framework: 'CUSTOM', entrypoint_type: 'FUNCTION' },
    }),
    onSuccess: () => { setName(''); setEntrypoint(''); invalidate(); toast.success('Agent registered') },
    onError,
  })

  const canCreate = name.trim() && entrypoint.trim()

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Bot}
        title="Agents"
        description="Register agents with a stable identity, owner and criticality, then validate, approve and activate them for deployment."
        backTo={ROUTES.RUNTIME_DASHBOARD}
        backLabel="Runtime overview"
      />
      <RuntimeNav />

      <Card>
        <CardHeader><CardTitle className="text-base">Register a new agent</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-3">
            <Input value={name} placeholder="Agent name" className="w-64" aria-label="Agent name"
                   onChange={(e) => setName(e.target.value)} />
            <Input value={entrypoint} placeholder="Entrypoint (e.g. agents.claims:handle)" className="flex-1"
                   aria-label="Entrypoint" onChange={(e) => setEntrypoint(e.target.value)} />
            <Select className="w-48" aria-label="Criticality" value={criticality}
                    options={CRITICALITIES.map((c) => ({ value: c, label: c.replace('_', ' ') }))}
                    onChange={(e) => setCriticality(e.target.value as Criticality)} />
          </div>
          <Button disabled={!canCreate || register.isPending} onClick={() => register.mutate()}>
            {register.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Register agent
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {agents.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (agents.data ?? []).length === 0 ? (
            <EmptyState icon={Bot} title="No agents registered yet"
                        description="Register an agent above to start its lifecycle." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Agent</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Criticality</TableHead>
                  <TableHead>Lifecycle</TableHead>
                  <TableHead>Registered</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(agents.data ?? []).map((a) => (
                  <TableRow key={a.id} className="cursor-pointer">
                    <TableCell className="font-medium">
                      <Link to={ROUTES.RUNTIME_AGENT_DETAIL.replace(':id', a.id)}
                            className="hover:underline">{a.name}</Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{a.agent_type}</TableCell>
                    <TableCell><Badge variant={CRITICALITY_VARIANT[a.criticality]}>{a.criticality}</Badge></TableCell>
                    <TableCell><Badge variant={AGENT_LIFECYCLE_VARIANT[a.lifecycle_status]}>{a.lifecycle_status}</Badge></TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(a.created_at)}</TableCell>
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
