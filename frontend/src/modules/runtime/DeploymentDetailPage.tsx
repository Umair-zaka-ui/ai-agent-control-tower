import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HeartPulse, Layers, Loader2, PauseCircle, PlayCircle, RotateCcw, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService } from '@/services'
import type { ID } from '@/types'
import { RuntimeNav } from './components/RuntimeNav'
import { DEPLOYMENT_STATUS_VARIANT, formatDate } from './utils'

/** Phase 5.0 §57, §66 — deployment details: status, health history and
 * lifecycle actions (suspend/resume/rollback/retire). */
export function DeploymentDetailPage() {
  const { id } = useParams<{ id: ID }>()
  const deploymentId = id as ID
  const qc = useQueryClient()
  const [rollbackTarget, setRollbackTarget] = useState('')

  const deployment = useQuery({
    queryKey: ['runtime-deployment', deploymentId], queryFn: () => runtimeService.deployment(deploymentId),
  })
  const health = useQuery({
    queryKey: ['runtime-deployment-health', deploymentId], queryFn: () => runtimeService.deploymentHealth(deploymentId),
  })
  const versions = useQuery({
    queryKey: ['runtime-versions', deployment.data?.agent_id],
    queryFn: () => runtimeService.versions(deployment.data!.agent_id),
    enabled: !!deployment.data,
  })

  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['runtime-deployment', deploymentId] })

  const action = useMutation({
    mutationFn: (a: 'suspend' | 'resume' | 'retire') => ({
      suspend: runtimeService.suspendDeployment, resume: runtimeService.resumeDeployment,
      retire: runtimeService.retireDeployment,
    })[a](deploymentId),
    onSuccess: () => { invalidate(); toast.success('Deployment updated') },
    onError,
  })
  const rollback = useMutation({
    mutationFn: () => runtimeService.rollbackDeployment(deploymentId, rollbackTarget),
    onSuccess: () => { invalidate(); toast.success('Rolled back') },
    onError,
  })

  if (deployment.isLoading || !deployment.data) {
    return <div className="flex justify-center p-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
  }
  const d = deployment.data
  const publishedVersions = (versions.data ?? []).filter((v) => v.status === 'PUBLISHED' || v.status === 'DEPRECATED')

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Layers}
        title={`Deployment · ${d.environment}`}
        description={`${d.deployment_strategy} strategy · ${d.desired_replicas} desired replica(s)`}
        backTo={ROUTES.RUNTIME_DEPLOYMENTS}
        backLabel="Deployments"
      />
      <RuntimeNav />

      <Card>
        <CardHeader><CardTitle className="text-base">Status</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Badge variant={DEPLOYMENT_STATUS_VARIANT[d.status]}>{d.status}</Badge>
            <Badge variant="outline">Health: {d.health_status}</Badge>
            <Badge variant="outline">{d.active_replicas}/{d.desired_replicas} replicas</Badge>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" disabled={d.status !== 'ACTIVE' || action.isPending}
                    onClick={() => action.mutate('suspend')}>
              <PauseCircle className="h-3.5 w-3.5" /> Suspend
            </Button>
            <Button size="sm" variant="outline" disabled={d.status !== 'SUSPENDED' || action.isPending}
                    onClick={() => action.mutate('resume')}>
              <PlayCircle className="h-3.5 w-3.5" /> Resume
            </Button>
            <Select className="w-48" aria-label="Rollback target version" value={rollbackTarget}
                    placeholder="Rollback to version…"
                    options={publishedVersions.map((v) => ({ value: v.id, label: `v${v.version}` }))}
                    onChange={(e) => setRollbackTarget(e.target.value)} />
            <Button size="sm" variant="outline" disabled={!rollbackTarget || rollback.isPending}
                    onClick={() => rollback.mutate()}>
              <RotateCcw className="h-3.5 w-3.5" /> Rollback
            </Button>
            <Button size="sm" variant="destructive" disabled={d.status === 'RETIRED' || action.isPending}
                    onClick={() => action.mutate('retire')}>
              <Trash2 className="h-3.5 w-3.5" /> Retire
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Health history</CardTitle></CardHeader>
        <CardContent className="p-0">
          {health.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (health.data ?? []).length === 0 ? (
            <EmptyState icon={HeartPulse} title="No health samples yet"
                        description="Health samples appear once workers or the deployment report a heartbeat." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Worker</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Checked</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(health.data ?? []).map((h) => (
                  <TableRow key={h.id}>
                    <TableCell className="font-mono text-xs">{h.worker_id ?? '—'}</TableCell>
                    <TableCell><Badge variant="outline">{h.status}</Badge></TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(h.checked_at)}</TableCell>
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
