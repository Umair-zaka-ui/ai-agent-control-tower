import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AlertCircle, ArrowLeft, Bot, Clock, FlaskConical, Pencil, Power, PowerOff } from 'lucide-react'

import { EmptyState } from '@/components/common/EmptyState'
import { FullPageSpinner } from '@/components/common/Spinner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { useNotifications } from '@/hooks/useNotifications'
import { cn } from '@/utils/cn'
import { apiErrorMessage } from '@/utils/error'
import { formatDateTime, formatRelativeTime } from '@/utils/format'
import {
  DeleteConfirmModal,
  PolicyAuditTimeline,
  PolicyDecisionBadge,
  PolicySeverityBadge,
  PolicyStatusBadge,
} from '../components'
import { usePolicy, usePolicyAudit, useCreatePolicy, useDeletePolicy, useTogglePolicy } from '../hooks'
import type { Policy } from '../types'
import { summarizeRule } from '../utils/policyFormatters'
import { humanizeConditions } from '../utils/policyFormatters'
import { canManagePolicies, canTestPolicies } from '../utils/permissions'

const TABS = ['Overview', 'Conditions', 'Assigned Agents', 'Trigger History', 'Audit', 'Settings'] as const
type Tab = (typeof TABS)[number]

export function PolicyDetailsPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const notify = useNotifications()
  const { user } = useAuth()
  const canManage = canManagePolicies(user?.role)
  const canTest = canTestPolicies(user?.role)

  const [tab, setTab] = useState<Tab>('Overview')
  const [deleteOpen, setDeleteOpen] = useState(false)

  const { data: policy, isLoading, isError } = usePolicy(id)
  const togglePolicy = useTogglePolicy()
  const createPolicy = useCreatePolicy()
  const deletePolicy = useDeletePolicy()

  if (isLoading) return <FullPageSpinner />
  if (isError || !policy) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 py-24 text-center">
        <AlertCircle className="h-7 w-7 text-destructive" />
        <p className="text-sm text-muted-foreground">Policy not found or failed to load.</p>
        <Button variant="outline" asChild>
          <Link to={ROUTES.POLICIES}>Back to policies</Link>
        </Button>
      </div>
    )
  }

  const enabled = policy.status === 'ENABLED'

  const handleToggle = () => {
    togglePolicy.mutate(
      { id: policy.id, enable: !enabled },
      {
        onSuccess: () => notify.success(`${policy.name} ${enabled ? 'disabled' : 'enabled'}`),
        onError: (e) => notify.error('Could not update policy', apiErrorMessage(e)),
      },
    )
  }

  const handleDuplicate = () => {
    createPolicy.mutate(
      {
        name: `${policy.name} (copy)`,
        description: policy.description,
        resource: policy.resource,
        action: policy.action,
        conditions: policy.conditions,
        decision: policy.decision,
        priority: policy.priority,
        severity: policy.severity,
        status: 'DRAFT',
      },
      {
        onSuccess: (created) => {
          notify.success(`Duplicated ${policy.name}`)
          navigate(`${ROUTES.POLICIES}/${created.id}`)
        },
        onError: (e) => notify.error('Could not duplicate policy', apiErrorMessage(e)),
      },
    )
  }

  const handleDelete = () => {
    deletePolicy.mutate(policy.id, {
      onSuccess: () => {
        notify.success(`Deleted ${policy.name}`)
        navigate(ROUTES.POLICIES)
      },
      onError: (e) => notify.error('Could not delete policy', apiErrorMessage(e)),
    })
  }

  return (
    <div className="space-y-6">
      <Link
        to={ROUTES.POLICIES}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        All policies
      </Link>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{policy.name}</h1>
            <PolicyStatusBadge status={policy.status} />
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <span>{policy.resource}</span>
            <span>·</span>
            <span>{policy.action.replace(/_/g, ' ')}</span>
            <span>·</span>
            <PolicyDecisionBadge decision={policy.decision} />
            <PolicySeverityBadge severity={policy.severity} />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {canTest && (
            <Button variant="outline" size="sm" asChild>
              <Link to={`${ROUTES.POLICIES}/${policy.id}/test`}>
                <FlaskConical className="h-4 w-4" />
                Test
              </Link>
            </Button>
          )}
          {canManage && (
            <>
              <Button variant="outline" size="sm" asChild>
                <Link to={`${ROUTES.POLICIES}/${policy.id}/edit`}>
                  <Pencil className="h-4 w-4" />
                  Edit
                </Link>
              </Button>
              <Button variant="outline" size="sm" onClick={handleToggle} disabled={togglePolicy.isPending}>
                {enabled ? <PowerOff className="h-4 w-4" /> : <Power className="h-4 w-4" />}
                {enabled ? 'Disable' : 'Enable'}
              </Button>
            </>
          )}
        </div>
      </div>

      <div className="flex gap-1 overflow-x-auto border-b border-border">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={cn(
              'whitespace-nowrap px-3 py-2 text-sm transition-colors',
              t === tab
                ? 'border-b-2 border-primary font-medium text-foreground'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'Overview' && <OverviewTab policy={policy} />}
      {tab === 'Conditions' && <ConditionsTab policy={policy} />}
      {tab === 'Assigned Agents' && (
        <EmptyState
          icon={Bot}
          title="Applies to all agents"
          description="This policy is evaluated for every agent in the organization. Per-agent scoping arrives in a later phase."
        />
      )}
      {tab === 'Trigger History' && (
        <EmptyState
          icon={Clock}
          title="No trigger history yet"
          description="Recorded policy triggers from live agent actions will appear here."
        />
      )}
      {tab === 'Audit' && <AuditTab policyId={policy.id} />}
      {tab === 'Settings' && (
        <SettingsTab
          policy={policy}
          canManage={canManage}
          onDuplicate={handleDuplicate}
          onToggle={handleToggle}
          onDelete={() => setDeleteOpen(true)}
          busy={togglePolicy.isPending || createPolicy.isPending}
        />
      )}

      <DeleteConfirmModal
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        policyName={policy.name}
        loading={deletePolicy.isPending}
        onConfirm={handleDelete}
      />
    </div>
  )
}

function OverviewTab({ policy }: { policy: Policy }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Details</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
          <Field label="Description" value={policy.description || '—'} className="sm:col-span-2" />
          <Field label="Resource" value={policy.resource} />
          <Field label="Action" value={policy.action.replace(/_/g, ' ')} />
          <Field label="Decision" value={<PolicyDecisionBadge decision={policy.decision} />} />
          <Field label="Severity" value={<PolicySeverityBadge severity={policy.severity} />} />
          <Field label="Status" value={<PolicyStatusBadge status={policy.status} />} />
          <Field label="Priority" value={String(policy.priority)} />
          <Field label="Trigger Count" value={String(policy.trigger_count)} />
          <Field
            label="Last Triggered"
            value={policy.last_triggered_at ? formatRelativeTime(policy.last_triggered_at) : '—'}
          />
          <Field label="Created" value={formatDateTime(policy.created_at)} />
          <Field label="Last Updated" value={formatRelativeTime(policy.updated_at)} />
        </dl>
      </CardContent>
    </Card>
  )
}

function ConditionsTab({ policy }: { policy: Policy }) {
  const clauses = humanizeConditions(policy.conditions)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Conditions</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="rounded-md border border-border bg-background p-3 text-sm text-foreground">
          {summarizeRule(policy.conditions, policy.decision)}
        </p>
        <ul className="space-y-1 text-sm">
          {clauses.map((clause, i) => (
            <li key={i}>• {clause}</li>
          ))}
        </ul>
        <pre className="overflow-x-auto rounded-md border border-border bg-muted/40 p-3 font-mono text-xs text-muted-foreground">
          {JSON.stringify(policy.conditions ?? {}, null, 2)}
        </pre>
      </CardContent>
    </Card>
  )
}

function AuditTab({ policyId }: { policyId: string }) {
  const { data, isLoading, isError } = usePolicyAudit(policyId)
  if (isLoading) return <p className="py-8 text-center text-sm text-muted-foreground">Loading audit trail…</p>
  if (isError) return <p className="py-8 text-center text-sm text-destructive">Unable to load audit events.</p>
  return (
    <Card>
      <CardContent className="p-6">
        <PolicyAuditTimeline events={data ?? []} />
      </CardContent>
    </Card>
  )
}

function SettingsTab({
  policy,
  canManage,
  onDuplicate,
  onToggle,
  onDelete,
  busy,
}: {
  policy: Policy
  canManage: boolean
  onDuplicate: () => void
  onToggle: () => void
  onDelete: () => void
  busy?: boolean
}) {
  if (!canManage) {
    return <p className="py-8 text-center text-sm text-muted-foreground">You have read-only access.</p>
  }
  const enabled = policy.status === 'ENABLED'
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Manage</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button variant="outline" asChild>
            <Link to={`${ROUTES.POLICIES}/${policy.id}/edit`}>Rename / Edit</Link>
          </Button>
          <Button variant="outline" onClick={onToggle} disabled={busy}>
            {enabled ? 'Disable policy' : 'Enable policy'}
          </Button>
          <Button variant="outline" onClick={onDuplicate} disabled={busy}>
            Duplicate policy
          </Button>
        </CardContent>
      </Card>

      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="text-base text-destructive">Danger Zone</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-between gap-4">
          <p className="text-sm text-muted-foreground">
            Permanently delete this policy. This cannot be undone.
          </p>
          <Button variant="destructive" onClick={onDelete}>
            Delete policy
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

function Field({
  label,
  value,
  className,
}: {
  label: string
  value: React.ReactNode
  className?: string
}) {
  return (
    <div className={className}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{value}</dd>
    </div>
  )
}
