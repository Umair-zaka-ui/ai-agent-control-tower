import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive, Bot, CheckCircle2, Copy, FileCode2, GitBranch, KeyRound, Loader2, Pause, PlayCircle, Plus,
  RotateCcw, Rocket, ScrollText, ShieldCheck, Sparkles, UserCog, Wrench, XCircle,
} from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Label, Select, Textarea,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService } from '@/services'
import type { ID, OwnerRole, RuntimeEnvironment } from '@/types'
import { RuntimeNav } from './components/RuntimeNav'
import {
  AGENT_LIFECYCLE_VARIANT, CRITICALITY_VARIANT, formatDate, VERSION_STATUS_VARIANT,
} from './utils'

const ENVIRONMENTS: RuntimeEnvironment[] = ['DEVELOPMENT', 'TEST', 'STAGING', 'PRODUCTION', 'SANDBOX']

const TABS = [
  'Overview', 'Definition', 'Ownership', 'Identity', 'Contracts', 'Risk & Data',
  'Capabilities', 'Tools', 'Validation', 'Lifecycle', 'Audit', 'Settings',
] as const
type Tab = (typeof TABS)[number]

/** Phase 5.1 §38 — agent detail: the 12-tab layout (Overview, Definition,
 * Ownership, Identity, Contracts, Risk & Data, Capabilities, Tools,
 * Validation, Lifecycle, Audit, Settings). */
export function AgentDetailPage() {
  const { id } = useParams<{ id: ID }>()
  const agentId = id as ID
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('Overview')

  const agent = useQuery({ queryKey: ['runtime-agent', agentId], queryFn: () => runtimeService.agent(agentId) })

  const invalidateAgent = () => void qc.invalidateQueries({ queryKey: ['runtime-agent', agentId] })
  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')

  if (agent.isLoading || !agent.data) {
    return <div className="flex justify-center p-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
  }
  const a = agent.data

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Bot}
        title={a.display_name || a.name}
        description={a.description ?? 'No description provided.'}
        backTo={ROUTES.RUNTIME_AGENTS}
        backLabel="Agent inventory"
      />
      <RuntimeNav />

      <div className="flex flex-wrap gap-2">
        <Badge variant={AGENT_LIFECYCLE_VARIANT[a.lifecycle_status] ?? 'secondary'}>{a.lifecycle_status}</Badge>
        <Badge variant={CRITICALITY_VARIANT[a.criticality]}>{a.criticality}</Badge>
        <Badge variant="outline">{a.risk_level} risk</Badge>
        <Badge variant="outline">{a.data_classification}</Badge>
        <Badge variant="outline">{a.autonomy_level}</Badge>
      </div>

      <TabBar tab={tab} onChange={setTab} />

      {tab === 'Overview' && <OverviewTab agentId={agentId} onError={onError} onChanged={invalidateAgent} />}
      {tab === 'Definition' && <DefinitionTab agentId={agentId} />}
      {tab === 'Ownership' && <OwnershipTab agentId={agentId} onError={onError} />}
      {tab === 'Identity' && <IdentityTab agentId={agentId} onError={onError} onChanged={invalidateAgent} />}
      {tab === 'Contracts' && <ContractsTab agentId={agentId} />}
      {tab === 'Risk & Data' && <RiskAndDataTab agentId={agentId} />}
      {tab === 'Capabilities' && <CapabilitiesTab agentId={agentId} onError={onError} />}
      {tab === 'Tools' && <ToolsTab agentId={agentId} onError={onError} />}
      {tab === 'Validation' && <ValidationTab agentId={agentId} onError={onError} onChanged={invalidateAgent} />}
      {tab === 'Lifecycle' && <LifecycleTab agentId={agentId} />}
      {tab === 'Audit' && <AuditTab agentId={agentId} />}
      {tab === 'Settings' && <SettingsTab agentId={agentId} onError={onError} onChanged={invalidateAgent} />}
    </div>
  )
}

function TabBar({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  return (
    <div className="flex flex-wrap gap-1 border-b border-border pb-px" role="tablist">
      {TABS.map((t) => (
        <button
          key={t}
          role="tab"
          aria-selected={tab === t}
          onClick={() => onChange(t)}
          className={
            tab === t
              ? 'rounded-t-md border-b-2 border-primary bg-muted/50 px-3 py-1.5 text-sm font-medium text-foreground'
              : 'rounded-t-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted/30 hover:text-foreground'
          }
        >
          {t}
        </button>
      ))}
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Overview — lifecycle actions + versions/deployments
// --------------------------------------------------------------------------- //
type LifecycleAction =
  | 'register' | 'validate' | 'submit' | 'approve' | 'reject' | 'activate' | 'suspend' | 'resume'
  | 'deprecate' | 'archive' | 'restore' | 'retire'

const LIFECYCLE_ALLOWED_FROM: Record<LifecycleAction, string[]> = {
  register: ['DRAFT', 'VALIDATION_FAILED', 'REJECTED'],
  validate: ['REGISTERED', 'VALIDATION_FAILED'],
  submit: ['VALIDATED'],
  approve: ['PENDING_APPROVAL'],
  reject: ['PENDING_APPROVAL'],
  activate: ['APPROVED'],
  suspend: ['ACTIVE'],
  resume: ['SUSPENDED'],
  deprecate: ['ACTIVE', 'SUSPENDED'],
  archive: ['DRAFT', 'REGISTERED', 'VALIDATION_FAILED', 'VALIDATED', 'REJECTED', 'APPROVED', 'DEPRECATED'],
  restore: ['ARCHIVED'],
  retire: ['ACTIVE', 'SUSPENDED', 'DEPRECATED'],
}

function OverviewTab({ agentId, onError, onChanged }: {
  agentId: ID; onError: (e: unknown) => void; onChanged: () => void
}) {
  const qc = useQueryClient()
  const agent = useQuery({ queryKey: ['runtime-agent', agentId], queryFn: () => runtimeService.agent(agentId) })
  const versions = useQuery({ queryKey: ['runtime-versions', agentId], queryFn: () => runtimeService.versions(agentId) })
  const [deployEnv, setDeployEnv] = useState<Record<string, RuntimeEnvironment>>({})
  const [rejectReason, setRejectReason] = useState('')

  const invalidateVersions = () => void qc.invalidateQueries({ queryKey: ['runtime-versions', agentId] })

  const lifecycle = useMutation({
    mutationFn: ({ action, reason }: { action: LifecycleAction; reason?: string }) => {
      const fn: Record<LifecycleAction, (id: ID, ...args: string[]) => Promise<unknown>> = {
        register: runtimeService.registerLifecycleAction, validate: runtimeService.validateAgent,
        submit: runtimeService.submitForApproval, approve: runtimeService.approveAgent,
        reject: (id: ID) => runtimeService.rejectAgent(id, reason ?? ''),
        activate: runtimeService.activateAgent, suspend: runtimeService.suspendAgent,
        resume: runtimeService.resumeAgent, deprecate: runtimeService.deprecateAgent,
        archive: runtimeService.archiveAgent, restore: runtimeService.restoreAgent,
        retire: runtimeService.retireAgent,
      }
      return fn[action](agentId)
    },
    onSuccess: () => { onChanged(); toast.success('Agent updated'); setRejectReason('') },
    onError,
  })

  const createVersion = useMutation({
    mutationFn: () => runtimeService.createVersion(agentId, { model_configuration: { provider: 'MOCK', model: 'mock-model' } }),
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

  if (!agent.data) return null
  const status = agent.data.lifecycle_status
  const can = (action: LifecycleAction) => LIFECYCLE_ALLOWED_FROM[action].includes(status)

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader><CardTitle className="text-base">Lifecycle actions</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" disabled={!can('register') || lifecycle.isPending}
                    onClick={() => lifecycle.mutate({ action: 'register' })}>
              Register
            </Button>
            <Button size="sm" variant="outline" disabled={!can('validate') || lifecycle.isPending}
                    onClick={() => lifecycle.mutate({ action: 'validate' })}>
              <CheckCircle2 className="h-3.5 w-3.5" /> Validate
            </Button>
            <Button size="sm" variant="outline" disabled={!can('submit') || lifecycle.isPending}
                    onClick={() => lifecycle.mutate({ action: 'submit' })}>
              Submit for approval
            </Button>
            <Button size="sm" variant="outline" disabled={!can('approve') || lifecycle.isPending}
                    onClick={() => lifecycle.mutate({ action: 'approve' })}>
              <ShieldCheck className="h-3.5 w-3.5" /> Approve
            </Button>
            <Button size="sm" variant="outline" disabled={!can('activate') || lifecycle.isPending}
                    onClick={() => lifecycle.mutate({ action: 'activate' })}>
              <PlayCircle className="h-3.5 w-3.5" /> Activate
            </Button>
            <Button size="sm" variant="outline" disabled={!can('suspend') || lifecycle.isPending}
                    onClick={() => lifecycle.mutate({ action: 'suspend' })}>
              <Pause className="h-3.5 w-3.5" /> Suspend
            </Button>
            <Button size="sm" variant="outline" disabled={!can('resume') || lifecycle.isPending}
                    onClick={() => lifecycle.mutate({ action: 'resume' })}>
              <PlayCircle className="h-3.5 w-3.5" /> Resume
            </Button>
            <Button size="sm" variant="outline" disabled={!can('deprecate') || lifecycle.isPending}
                    onClick={() => lifecycle.mutate({ action: 'deprecate' })}>
              Deprecate
            </Button>
            <Button size="sm" variant="outline" disabled={!can('archive') || lifecycle.isPending}
                    onClick={() => lifecycle.mutate({ action: 'archive' })}>
              <Archive className="h-3.5 w-3.5" /> Archive
            </Button>
            <Button size="sm" variant="outline" disabled={!can('restore') || lifecycle.isPending}
                    onClick={() => lifecycle.mutate({ action: 'restore' })}>
              <RotateCcw className="h-3.5 w-3.5" /> Restore
            </Button>
            <Button size="sm" variant="destructive" disabled={!can('retire') || lifecycle.isPending}
                    onClick={() => lifecycle.mutate({ action: 'retire' })}>
              Retire
            </Button>
          </div>
          {can('reject') && (
            <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
              <Input value={rejectReason} onChange={(e) => setRejectReason(e.target.value)}
                     placeholder="Reason for rejection (required)" className="max-w-sm" />
              <Button size="sm" variant="destructive" disabled={!rejectReason.trim() || lifecycle.isPending}
                      onClick={() => lifecycle.mutate({ action: 'reject', reason: rejectReason })}>
                <XCircle className="h-3.5 w-3.5" /> Reject
              </Button>
            </div>
          )}
          <Link to={ROUTES.RUNTIME_AGENT_DUPLICATES.replace(':id', agentId)}
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:underline">
            <Copy className="h-3 w-3" /> Check for duplicate agents
          </Link>
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
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Definition
// --------------------------------------------------------------------------- //
function DefinitionTab({ agentId }: { agentId: ID }) {
  const definitions = useQuery({
    queryKey: ['runtime-agent-definitions', agentId], queryFn: () => runtimeService.agentDefinitions(agentId),
  })
  const latest = definitions.data?.[0]
  if (definitions.isLoading) return <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
  if (!latest) return <EmptyState icon={FileCode2} title="No definition" description="This agent has no technical definition yet." />
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Technical definition</CardTitle></CardHeader>
      <CardContent>
        <dl className="divide-y divide-border rounded-md border border-border text-sm">
          {[
            ['Framework', latest.framework], ['Framework version', latest.framework_version ?? '—'],
            ['Entrypoint type', latest.entrypoint_type], ['Entrypoint', latest.entrypoint],
            ['Runtime language', latest.runtime_language ?? '—'],
            ['Capability declarations', latest.capability_declarations.join(', ') || '—'],
            ['Tool declarations', latest.tool_declarations.join(', ') || '—'],
          ].map(([label, value]) => (
            <div key={label} className="flex justify-between gap-4 px-3 py-2">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="text-right font-medium">{value}</dd>
            </div>
          ))}
        </dl>
        {latest.system_instructions && (
          <div className="mt-4 space-y-1">
            <Label>System instructions</Label>
            <p className="whitespace-pre-wrap rounded-md border border-border bg-muted/30 p-3 text-sm">
              {latest.system_instructions}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// --------------------------------------------------------------------------- //
// Ownership
// --------------------------------------------------------------------------- //
const OWNER_ROLES: OwnerRole[] = ['BUSINESS_OWNER', 'TECHNICAL_OWNER', 'COMPLIANCE_OWNER', 'SECURITY_OWNER', 'DATA_OWNER']

function OwnershipTab({ agentId, onError }: { agentId: ID; onError: (e: unknown) => void }) {
  const qc = useQueryClient()
  const ownership = useQuery({ queryKey: ['runtime-ownership', agentId], queryFn: () => runtimeService.getOwnership(agentId) })
  const history = useQuery({ queryKey: ['runtime-ownership-history', agentId], queryFn: () => runtimeService.ownershipHistory(agentId) })
  const [ownerRole, setOwnerRole] = useState<OwnerRole>('BUSINESS_OWNER')
  const [newOwnerId, setNewOwnerId] = useState('')
  const [reason, setReason] = useState('')

  const transfer = useMutation({
    mutationFn: () => runtimeService.transferOwnership(agentId, {
      owner_role: ownerRole, new_owner_type: 'USER', new_owner_id: newOwnerId, reason,
    }),
    onSuccess: () => {
      setNewOwnerId(''); setReason('')
      void qc.invalidateQueries({ queryKey: ['runtime-ownership', agentId] })
      void qc.invalidateQueries({ queryKey: ['runtime-ownership-history', agentId] })
      void qc.invalidateQueries({ queryKey: ['runtime-agent', agentId] })
      toast.success('Ownership transferred')
    },
    onError,
  })

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader><CardTitle className="text-base">Current ownership</CardTitle></CardHeader>
        <CardContent>
          <dl className="grid gap-3 sm:grid-cols-2">
            <div><dt className="text-xs text-muted-foreground">Business owner</dt><dd className="text-sm">{ownership.data?.owner_id ?? '—'}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Technical owner</dt><dd className="text-sm">{ownership.data?.technical_owner_id ?? '—'}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Compliance owner</dt><dd className="text-sm">{ownership.data?.compliance_owner_id ?? '—'}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Owner type</dt><dd className="text-sm">{ownership.data?.owner_type ?? '—'}</dd></div>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Transfer ownership</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <Select aria-label="Owner role" value={ownerRole} options={OWNER_ROLES.map((r) => ({ value: r, label: r }))}
                    onChange={(e) => setOwnerRole(e.target.value as OwnerRole)} />
            <Input aria-label="New owner user ID" value={newOwnerId} onChange={(e) => setNewOwnerId(e.target.value)}
                   placeholder="New owner user ID" />
            <Input aria-label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason" />
          </div>
          <Button size="sm" disabled={!newOwnerId.trim() || !reason.trim() || transfer.isPending}
                  onClick={() => transfer.mutate()}>
            <UserCog className="h-3.5 w-3.5" /> Transfer
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Ownership history</CardTitle></CardHeader>
        <CardContent className="p-0">
          {(history.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No ownership changes recorded.</p>
          ) : (
            <Table>
              <TableHeader><TableRow><TableHead>Role</TableHead><TableHead>From</TableHead><TableHead>To</TableHead>
                <TableHead>Reason</TableHead><TableHead>When</TableHead></TableRow></TableHeader>
              <TableBody>
                {(history.data ?? []).map((h) => (
                  <TableRow key={h.id}>
                    <TableCell>{h.owner_role}</TableCell>
                    <TableCell className="font-mono text-xs">{h.previous_owner_id ?? '—'}</TableCell>
                    <TableCell className="font-mono text-xs">{h.new_owner_id}</TableCell>
                    <TableCell>{h.reason}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(h.changed_at)}</TableCell>
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

// --------------------------------------------------------------------------- //
// Identity
// --------------------------------------------------------------------------- //
function IdentityTab({ agentId, onError, onChanged }: {
  agentId: ID; onError: (e: unknown) => void; onChanged: () => void
}) {
  const qc = useQueryClient()
  const identity = useQuery({ queryKey: ['runtime-identity', agentId], queryFn: () => runtimeService.getIdentity(agentId) })
  const [clientId, setClientId] = useState('')
  const [reason, setReason] = useState('')

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['runtime-identity', agentId] })
    onChanged()
  }
  const create = useMutation({
    mutationFn: () => runtimeService.createAndAssociateIdentity(agentId, { client_id: clientId }),
    onSuccess: () => { setClientId(''); invalidate(); toast.success('Machine identity created') },
    onError,
  })
  const rotate = useMutation({
    mutationFn: () => runtimeService.replaceIdentity(agentId, { client_id: clientId, reason }),
    onSuccess: () => { setClientId(''); setReason(''); invalidate(); toast.success('Identity credential rotated') },
    onError,
  })

  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Machine identity</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {identity.data ? (
          <dl className="grid gap-3 sm:grid-cols-2">
            <div><dt className="text-xs text-muted-foreground">Client ID</dt><dd className="font-mono text-sm">{identity.data.client_id}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Status</dt><dd><Badge variant={identity.data.status === 'ACTIVE' ? 'success' : 'warning'}>{identity.data.status}</Badge></dd></div>
            <div><dt className="text-xs text-muted-foreground">Credential type</dt><dd className="text-sm">{identity.data.credential_type}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Expires</dt><dd className="text-sm">{identity.data.expires_at ? formatDate(identity.data.expires_at) : 'Never'}</dd></div>
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">No machine identity yet — required before this agent can be activated.</p>
        )}

        <div className="space-y-2 border-t border-border pt-4">
          <Label>{identity.data ? 'Rotate credential (replace)' : 'Create and associate identity'}</Label>
          <div className="flex flex-wrap gap-2">
            <Input value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="client-id" className="max-w-xs font-mono text-xs" />
            {identity.data && (
              <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason for rotation" className="max-w-xs" />
            )}
            <Button
              size="sm" disabled={!clientId.trim() || (identity.data ? !reason.trim() : false) || create.isPending || rotate.isPending}
              onClick={() => (identity.data ? rotate.mutate() : create.mutate())}
            >
              <KeyRound className="h-3.5 w-3.5" /> {identity.data ? 'Rotate' : 'Create'}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// --------------------------------------------------------------------------- //
// Contracts
// --------------------------------------------------------------------------- //
function ContractsTab({ agentId }: { agentId: ID }) {
  const definitions = useQuery({
    queryKey: ['runtime-agent-definitions', agentId], queryFn: () => runtimeService.agentDefinitions(agentId),
  })
  const latest = definitions.data?.[0]
  const [schemaType, setSchemaType] = useState<'INPUT' | 'OUTPUT' | 'CONFIGURATION'>('INPUT')
  const [payloadText, setPayloadText] = useState('{}')
  const [result, setResult] = useState<{ valid: boolean; errors: string[] } | null>(null)

  const test = useMutation({
    mutationFn: () => {
      let payload: Record<string, unknown> = {}
      try { payload = JSON.parse(payloadText || '{}') } catch { /* invalid JSON handled below */ }
      return runtimeService.testSchema(agentId, { schema_type: schemaType, payload })
    },
    onSuccess: setResult,
  })

  if (!latest) return <EmptyState icon={FileCode2} title="No contracts" description="This agent has no definition yet." />

  return (
    <div className="space-y-6">
      {(['input_schema', 'output_schema', 'configuration_schema'] as const).map((key) => (
        <Card key={key}>
          <CardHeader><CardTitle className="text-base capitalize">{key.replace('_', ' ')}</CardTitle></CardHeader>
          <CardContent>
            <pre className="max-h-64 overflow-auto rounded-md border border-border bg-muted/30 p-3 text-xs">
              {JSON.stringify(latest[key] ?? {}, null, 2)}
            </pre>
          </CardContent>
        </Card>
      ))}

      <Card>
        <CardHeader><CardTitle className="text-base">Sample payload testing</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Select aria-label="Schema type" value={schemaType}
                    options={[{ value: 'INPUT', label: 'Input' }, { value: 'OUTPUT', label: 'Output' },
                             { value: 'CONFIGURATION', label: 'Configuration' }]}
                    onChange={(e) => setSchemaType(e.target.value as typeof schemaType)} className="w-40" />
          </div>
          <Textarea value={payloadText} onChange={(e) => setPayloadText(e.target.value)} rows={4} className="font-mono text-xs" />
          <Button size="sm" disabled={test.isPending} onClick={() => test.mutate()}>Test payload</Button>
          {result && (
            <p className={result.valid ? 'text-sm text-success' : 'text-sm text-destructive'}>
              {result.valid ? 'Valid ✓' : result.errors.join('; ')}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Risk & Data
// --------------------------------------------------------------------------- //
function RiskAndDataTab({ agentId }: { agentId: ID }) {
  const agent = useQuery({ queryKey: ['runtime-agent', agentId], queryFn: () => runtimeService.agent(agentId) })
  if (!agent.data) return null
  const a = agent.data
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Risk & data classification</CardTitle></CardHeader>
      <CardContent>
        <dl className="grid gap-4 sm:grid-cols-2">
          {[
            ['Criticality', a.criticality], ['Risk level', a.risk_level],
            ['Data classification', a.data_classification], ['Autonomy level', a.autonomy_level],
            ['Default environment', a.default_environment], ['Tags', a.tags.join(', ') || '—'],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="text-sm font-medium">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 text-xs text-muted-foreground">Edit these values from the Settings tab.</p>
      </CardContent>
    </Card>
  )
}

// --------------------------------------------------------------------------- //
// Capabilities / Tools (unchanged behavior from Phase 5.0)
// --------------------------------------------------------------------------- //
function CapabilitiesTab({ agentId, onError }: { agentId: ID; onError: (e: unknown) => void }) {
  const qc = useQueryClient()
  const [capabilityId, setCapabilityId] = useState('')
  const capabilities = useQuery({ queryKey: ['runtime-capabilities'], queryFn: () => runtimeService.capabilities() })
  const agentCapabilities = useQuery({
    queryKey: ['runtime-agent-capabilities', agentId], queryFn: () => runtimeService.agentCapabilities(agentId),
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
  return (
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
  )
}

function ToolsTab({ agentId, onError }: { agentId: ID; onError: (e: unknown) => void }) {
  const qc = useQueryClient()
  const [toolId, setToolId] = useState('')
  const tools = useQuery({ queryKey: ['runtime-tools'], queryFn: () => runtimeService.tools() })
  const agentTools = useQuery({ queryKey: ['runtime-agent-tools', agentId], queryFn: () => runtimeService.agentTools(agentId) })
  const assignTool = useMutation({
    mutationFn: () => runtimeService.assignTool(agentId, toolId),
    onSuccess: () => {
      setToolId('')
      void qc.invalidateQueries({ queryKey: ['runtime-agent-tools', agentId] })
      toast.success('Tool assigned')
    },
    onError,
  })
  return (
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
  )
}

// --------------------------------------------------------------------------- //
// Validation
// --------------------------------------------------------------------------- //
function ValidationTab({ agentId, onError, onChanged }: {
  agentId: ID; onError: (e: unknown) => void; onChanged: () => void
}) {
  const qc = useQueryClient()
  const runs = useQuery({ queryKey: ['runtime-validations', agentId], queryFn: () => runtimeService.validations(agentId) })
  const runValidation = useMutation({
    mutationFn: () => runtimeService.validateAgent(agentId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['runtime-validations', agentId] })
      onChanged()
      toast.success('Validation run complete')
    },
    onError,
  })
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">Validation runs</CardTitle>
        <Button size="sm" disabled={runValidation.isPending} onClick={() => runValidation.mutate()}>Run validation</Button>
      </CardHeader>
      <CardContent className="space-y-4 p-0">
        {(runs.data ?? []).length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">No validation runs yet.</p>
        ) : (
          (runs.data ?? []).map((run) => (
            <div key={run.id} className="space-y-2 border-b border-border p-4 last:border-0">
              <div className="flex items-center gap-2">
                <Badge variant={run.status === 'PASSED' ? 'success' : run.status === 'FAILED' ? 'destructive' : 'secondary'}>
                  {run.status}
                </Badge>
                <span className="text-xs text-muted-foreground">{formatDate(run.created_at)}</span>
                <span className="text-xs text-muted-foreground">
                  {run.summary.passed} passed · {run.summary.warnings} warnings · {run.summary.failed} failed
                </span>
              </div>
              {run.errors.length > 0 && (
                <ul className="space-y-1 text-xs text-destructive">
                  {run.errors.map((f, i) => <li key={i}>{f.field ? `${f.field}: ` : ''}{f.message}</li>)}
                </ul>
              )}
              {run.warnings.length > 0 && (
                <ul className="space-y-1 text-xs text-warning-foreground">
                  {run.warnings.map((f, i) => <li key={i}>{f.field ? `${f.field}: ` : ''}{f.message}</li>)}
                </ul>
              )}
            </div>
          ))
        )}
      </CardContent>
    </Card>
  )
}

// --------------------------------------------------------------------------- //
// Lifecycle timeline
// --------------------------------------------------------------------------- //
function LifecycleTab({ agentId }: { agentId: ID }) {
  const events = useQuery({
    queryKey: ['runtime-lifecycle-events', agentId], queryFn: () => runtimeService.agentLifecycleEvents(agentId),
  })
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Lifecycle timeline</CardTitle></CardHeader>
      <CardContent className="p-0">
        {(events.data ?? []).length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">No lifecycle transitions yet.</p>
        ) : (
          <ol className="divide-y divide-border">
            {(events.data ?? []).map((e) => (
              <li key={e.id} className="flex items-start gap-3 p-4">
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                <div className="space-y-0.5">
                  <p className="text-sm font-medium">
                    {e.previous_status ? `${e.previous_status} → ${e.new_status}` : e.new_status}
                  </p>
                  {e.reason && <p className="text-xs text-muted-foreground">{e.reason}</p>}
                  <p className="text-xs text-muted-foreground">{formatDate(e.created_at)}</p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  )
}

// --------------------------------------------------------------------------- //
// Audit
// --------------------------------------------------------------------------- //
function AuditTab({ agentId }: { agentId: ID }) {
  const events = useQuery({ queryKey: ['runtime-agent-events', agentId], queryFn: () => runtimeService.agentEvents(agentId) })
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Audit trail</CardTitle></CardHeader>
      <CardContent className="p-0">
        {(events.data ?? []).length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">No audit events yet.</p>
        ) : (
          <Table>
            <TableHeader><TableRow><TableHead>Event</TableHead><TableHead>Severity</TableHead><TableHead>When</TableHead></TableRow></TableHeader>
            <TableBody>
              {(events.data ?? []).map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="font-mono text-xs">{e.event_type}</TableCell>
                  <TableCell><Badge variant={e.severity === 'WARNING' ? 'warning' : 'secondary'}>{e.severity}</Badge></TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(e.created_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

// --------------------------------------------------------------------------- //
// Settings — row_version-aware edit form
// --------------------------------------------------------------------------- //
function SettingsTab({ agentId, onError, onChanged }: {
  agentId: ID; onError: (e: unknown) => void; onChanged: () => void
}) {
  const qc = useQueryClient()
  const agent = useQuery({ queryKey: ['runtime-agent', agentId], queryFn: () => runtimeService.agent(agentId) })
  const [description, setDescription] = useState('')
  const [businessPurpose, setBusinessPurpose] = useState('')
  const [supportContact, setSupportContact] = useState('')
  const [initialized, setInitialized] = useState(false)

  if (agent.data && !initialized) {
    setDescription(agent.data.description ?? '')
    setBusinessPurpose(agent.data.business_purpose ?? '')
    setSupportContact(agent.data.support_contact ?? '')
    setInitialized(true)
  }

  const editable = agent.data ? ['DRAFT', 'REGISTERED', 'VALIDATION_FAILED', 'REJECTED'].includes(agent.data.lifecycle_status) : false

  const save = useMutation({
    mutationFn: () => runtimeService.updateAgent(agentId, {
      row_version: agent.data!.row_version, description, business_purpose: businessPurpose,
      support_contact: supportContact,
    }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['runtime-agent', agentId] })
      onChanged()
      toast.success('Saved')
    },
    onError,
  })

  const deleteAgent = useMutation({
    mutationFn: () => runtimeService.deleteAgent(agentId),
    onSuccess: () => toast.success('Draft deleted'),
    onError,
  })

  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Settings</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {!editable && (
          <p className="rounded-md border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
            This agent can only be edited while DRAFT, REGISTERED, VALIDATION_FAILED, or REJECTED.
          </p>
        )}
        <div className="space-y-2">
          <Label>Description</Label>
          <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} disabled={!editable} />
        </div>
        <div className="space-y-2">
          <Label>Business purpose</Label>
          <Textarea value={businessPurpose} onChange={(e) => setBusinessPurpose(e.target.value)} rows={2} disabled={!editable} />
        </div>
        <div className="space-y-2">
          <Label>Support contact</Label>
          <Input value={supportContact} onChange={(e) => setSupportContact(e.target.value)} disabled={!editable} />
        </div>
        <Button size="sm" disabled={!editable || save.isPending} onClick={() => save.mutate()}>Save changes</Button>

        {agent.data?.lifecycle_status === 'DRAFT' && (
          <div className="border-t border-border pt-4">
            <Button size="sm" variant="destructive" disabled={deleteAgent.isPending} onClick={() => deleteAgent.mutate()}>
              <ScrollText className="h-3.5 w-3.5" /> Delete draft
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
