import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive, Bot, CheckCircle2, GitBranch, Loader2, Pause, PlayCircle, Plus, Rocket, ShieldCheck, Wrench,
} from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService } from '@/services'
import type { ID, RuntimeEnvironment } from '@/types'
import { RuntimeNav } from './components/RuntimeNav'
import {
  AGENT_LIFECYCLE_VARIANT, CRITICALITY_VARIANT, formatDate, VERSION_STATUS_VARIANT,
} from './utils'

const ENVIRONMENTS: RuntimeEnvironment[] = ['DEVELOPMENT', 'TEST', 'STAGING', 'PRODUCTION', 'SANDBOX']

/** Phase 5.0 §71 — agent details: overview, lifecycle actions, versions
 * (create/validate/approve/publish/deploy), capabilities and tools. */
export function AgentDetailPage() {
  const { id } = useParams<{ id: ID }>()
  const agentId = id as ID
  const qc = useQueryClient()
  const [deployEnv, setDeployEnv] = useState<Record<string, RuntimeEnvironment>>({})
  const [capabilityId, setCapabilityId] = useState('')
  const [toolId, setToolId] = useState('')

  const agent = useQuery({ queryKey: ['runtime-agent', agentId], queryFn: () => runtimeService.agent(agentId) })
  const versions = useQuery({ queryKey: ['runtime-versions', agentId], queryFn: () => runtimeService.versions(agentId) })
  const capabilities = useQuery({ queryKey: ['runtime-capabilities'], queryFn: () => runtimeService.capabilities() })
  const agentCapabilities = useQuery({
    queryKey: ['runtime-agent-capabilities', agentId],
    queryFn: () => runtimeService.agentCapabilities(agentId),
  })
  const tools = useQuery({ queryKey: ['runtime-tools'], queryFn: () => runtimeService.tools() })
  const agentTools = useQuery({
    queryKey: ['runtime-agent-tools', agentId],
    queryFn: () => runtimeService.agentTools(agentId),
  })

  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')
  const invalidateAgent = () => void qc.invalidateQueries({ queryKey: ['runtime-agent', agentId] })
  const invalidateVersions = () => void qc.invalidateQueries({ queryKey: ['runtime-versions', agentId] })

  const lifecycle = useMutation({
    mutationFn: (action: 'validate' | 'approve' | 'activate' | 'suspend' | 'deprecate' | 'archive' | 'retire') => {
      const fn = {
        validate: runtimeService.validateAgent, approve: runtimeService.approveAgent,
        activate: runtimeService.activateAgent, suspend: runtimeService.suspendAgent,
        deprecate: runtimeService.deprecateAgent, archive: runtimeService.archiveAgent,
        retire: runtimeService.retireAgent,
      }[action]
      return fn(agentId)
    },
    onSuccess: () => { invalidateAgent(); toast.success('Agent updated') },
    onError,
  })

  const createVersion = useMutation({
    mutationFn: () => runtimeService.createVersion(agentId, {
      model_configuration: { provider: 'MOCK', model: 'mock-model' },
    }),
    onSuccess: () => { invalidateVersions(); toast.success('Version created') },
    onError,
  })
  const versionAction = useMutation({
    mutationFn: ({ versionId, action }: { versionId: ID; action: 'validate' | 'approve' | 'publish' | 'deprecate' | 'revoke' }) => {
      const fn = {
        validate: runtimeService.validateVersion, approve: runtimeService.approveVersion,
        publish: runtimeService.publishVersion, deprecate: runtimeService.deprecateVersion,
        revoke: runtimeService.revokeVersion,
      }[action]
      return fn(agentId, versionId)
    },
    onSuccess: () => { invalidateVersions(); toast.success('Version updated') },
    onError,
  })
  const deployVersion = useMutation({
    mutationFn: async (versionId: ID) => {
      const environment = deployEnv[versionId] ?? 'DEVELOPMENT'
      const deployment = await runtimeService.createDeployment(agentId, { agent_version_id: versionId, environment })
      return runtimeService.deploy(deployment.id)
    },
    onSuccess: (d) => toast.success(`Deployed to ${d.environment} (${d.status})`),
    onError,
  })

  const assignCapability = useMutation({
    mutationFn: () => runtimeService.assignCapability(agentId, capabilityId),
    onSuccess: () => {
      setCapabilityId('')
      void qc.invalidateQueries({ queryKey: ['runtime-agent-capabilities', agentId] })
      toast.success('Capability assigned')
    },
    onError,
  })
  const assignTool = useMutation({
    mutationFn: () => runtimeService.assignTool(agentId, toolId),
    onSuccess: () => {
      setToolId('')
      void qc.invalidateQueries({ queryKey: ['runtime-agent-tools', agentId] })
      toast.success('Tool assigned')
    },
    onError,
  })

  if (agent.isLoading || !agent.data) {
    return <div className="flex justify-center p-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
  }
  const a = agent.data
  const cap = { validate: 'DRAFT', approve: 'VALIDATED', activate: ['APPROVED', 'SUSPENDED'] }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Bot}
        title={a.name}
        description={a.description ?? 'No description provided.'}
        backTo={ROUTES.RUNTIME_AGENTS}
        backLabel="Agents"
      />
      <RuntimeNav />

      <Card>
        <CardHeader><CardTitle className="text-base">Overview</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Badge variant={AGENT_LIFECYCLE_VARIANT[a.lifecycle_status]}>{a.lifecycle_status}</Badge>
            <Badge variant={CRITICALITY_VARIANT[a.criticality]}>{a.criticality}</Badge>
            <Badge variant="outline">{a.default_environment}</Badge>
            <Badge variant="outline">{a.data_classification}</Badge>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" disabled={a.lifecycle_status !== cap.validate || lifecycle.isPending}
                    onClick={() => lifecycle.mutate('validate')}>
              <CheckCircle2 className="h-3.5 w-3.5" /> Validate
            </Button>
            <Button size="sm" variant="outline" disabled={a.lifecycle_status !== cap.approve || lifecycle.isPending}
                    onClick={() => lifecycle.mutate('approve')}>
              <ShieldCheck className="h-3.5 w-3.5" /> Approve
            </Button>
            <Button size="sm" variant="outline"
                    disabled={!cap.activate.includes(a.lifecycle_status) || lifecycle.isPending}
                    onClick={() => lifecycle.mutate('activate')}>
              <PlayCircle className="h-3.5 w-3.5" /> Activate
            </Button>
            <Button size="sm" variant="outline" disabled={a.lifecycle_status !== 'ACTIVE' || lifecycle.isPending}
                    onClick={() => lifecycle.mutate('suspend')}>
              <Pause className="h-3.5 w-3.5" /> Suspend
            </Button>
            <Button size="sm" variant="outline"
                    disabled={!['ACTIVE', 'SUSPENDED'].includes(a.lifecycle_status) || lifecycle.isPending}
                    onClick={() => lifecycle.mutate('deprecate')}>
              Deprecate
            </Button>
            <Button size="sm" variant="destructive" disabled={a.lifecycle_status === 'RETIRED' || lifecycle.isPending}
                    onClick={() => lifecycle.mutate('retire')}>
              <Archive className="h-3.5 w-3.5" /> Retire
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">Versions</CardTitle>
          <Button size="sm" disabled={createVersion.isPending} onClick={() => createVersion.mutate()}>
            {createVersion.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            New version
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          {versions.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (versions.data ?? []).length === 0 ? (
            <EmptyState icon={GitBranch} title="No versions yet" description="Create the first version above." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Version</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Checksum</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(versions.data ?? []).map((v) => (
                  <TableRow key={v.id}>
                    <TableCell className="font-medium">v{v.version} <span className="text-muted-foreground">({v.semantic_version})</span></TableCell>
                    <TableCell><Badge variant={VERSION_STATUS_VARIANT[v.status]}>{v.status}</Badge></TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{v.checksum.slice(0, 12)}…</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(v.created_at)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex flex-wrap justify-end gap-2">
                        {v.status === 'DRAFT' && (
                          <Button size="sm" variant="outline" disabled={versionAction.isPending}
                                  onClick={() => versionAction.mutate({ versionId: v.id, action: 'validate' })}>
                            Validate
                          </Button>
                        )}
                        {v.status === 'READY_FOR_REVIEW' && (
                          <Button size="sm" variant="outline" disabled={versionAction.isPending}
                                  onClick={() => versionAction.mutate({ versionId: v.id, action: 'approve' })}>
                            Approve
                          </Button>
                        )}
                        {v.status === 'APPROVED' && (
                          <Button size="sm" variant="outline" disabled={versionAction.isPending}
                                  onClick={() => versionAction.mutate({ versionId: v.id, action: 'publish' })}>
                            Publish
                          </Button>
                        )}
                        {v.status === 'PUBLISHED' && (
                          <>
                            <Select className="w-32" aria-label="Environment" value={deployEnv[v.id] ?? 'DEVELOPMENT'}
                                    options={ENVIRONMENTS.map((e) => ({ value: e, label: e }))}
                                    onChange={(e) => setDeployEnv((prev) => ({ ...prev, [v.id]: e.target.value as RuntimeEnvironment }))} />
                            <Button size="sm" disabled={deployVersion.isPending} onClick={() => deployVersion.mutate(v.id)}>
                              <Rocket className="h-3.5 w-3.5" /> Deploy
                            </Button>
                            <Button size="sm" variant="outline" disabled={versionAction.isPending}
                                    onClick={() => versionAction.mutate({ versionId: v.id, action: 'deprecate' })}>
                              Deprecate
                            </Button>
                          </>
                        )}
                        {!['REVOKED', 'DRAFT'].includes(v.status) && (
                          <Button size="sm" variant="destructive" disabled={versionAction.isPending}
                                  onClick={() => versionAction.mutate({ versionId: v.id, action: 'revoke' })}>
                            Revoke
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Capabilities</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-3">
            <Select className="w-64" aria-label="Capability" value={capabilityId} placeholder="Select a capability…"
                    options={(capabilities.data ?? []).map((c) => ({ value: c.id, label: c.display_name }))}
                    onChange={(e) => setCapabilityId(e.target.value)} />
            <Button size="sm" disabled={!capabilityId || assignCapability.isPending} onClick={() => assignCapability.mutate()}>
              <Plus className="h-4 w-4" /> Assign
            </Button>
          </div>
          {(agentCapabilities.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No capabilities assigned.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {(agentCapabilities.data ?? []).map((ac) => {
                const cdef = capabilities.data?.find((c) => c.id === ac.capability_id)
                return (
                  <Badge key={ac.id} variant={ac.status === 'APPROVED' ? 'success' : 'secondary'}>
                    {cdef?.display_name ?? ac.capability_id} · {ac.status}
                  </Badge>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Tools</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-3">
            <Select className="w-64" aria-label="Tool" value={toolId} placeholder="Select a tool…"
                    options={(tools.data ?? []).map((t) => ({ value: t.id, label: t.display_name }))}
                    onChange={(e) => setToolId(e.target.value)} />
            <Button size="sm" disabled={!toolId || assignTool.isPending} onClick={() => assignTool.mutate()}>
              <Wrench className="h-4 w-4" /> Assign
            </Button>
          </div>
          {(agentTools.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No tools assigned.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {(agentTools.data ?? []).map((at) => {
                const tdef = tools.data?.find((t) => t.id === at.tool_id)
                return (
                  <Badge key={at.id} variant={at.status === 'APPROVED' ? 'success' : 'secondary'}>
                    {tdef?.display_name ?? at.tool_id} · {at.status}
                  </Badge>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
