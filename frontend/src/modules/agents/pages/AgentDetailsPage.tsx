import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  Activity,
  AlertCircle,
  ArrowLeft,
  Ban,
  CheckCircle2,
  ClipboardList,
  Pencil,
  ShieldAlert,
  Trash2,
} from 'lucide-react'

import { FullPageSpinner } from '@/components/common/Spinner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { useNotifications } from '@/hooks/useNotifications'
import { formatDateTime, formatPercent, formatRelativeTime } from '@/utils/format'
import { apiErrorMessage } from '@/utils/error'
import { AgentHealthBadge, AgentStatusBadge, RiskLevelBadge } from '../components'
import { useAgent, useAgentStats, useDeleteAgent, useUpdateAgentStatus } from '../hooks'
import type { Agent } from '../types'

const TABS = ['Overview', 'Activity', 'Permissions', 'API Keys', 'Policies', 'Audit', 'Settings']

export function AgentDetailsPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const notify = useNotifications()
  const { data: agent, isLoading, isError } = useAgent(id)
  const updateStatus = useUpdateAgentStatus()
  const deleteAgent = useDeleteAgent()

  if (isLoading) return <FullPageSpinner />

  if (isError || !agent) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 py-24 text-center">
        <AlertCircle className="h-7 w-7 text-destructive" />
        <p className="text-sm text-muted-foreground">Agent not found or failed to load.</p>
        <Button variant="outline" asChild>
          <Link to={ROUTES.AGENTS}>Back to agents</Link>
        </Button>
      </div>
    )
  }

  const isActive = agent.status === 'ACTIVE'

  const setStatus = (status: Agent['status']) =>
    updateStatus.mutate(
      { id: agent.id, status },
      {
        onSuccess: () => notify.success(`Status → ${status.toLowerCase()}`),
        onError: (e) => notify.error('Could not update status', apiErrorMessage(e)),
      },
    )

  const handleDelete = () => {
    if (!window.confirm(`Delete agent "${agent.name}"? This cannot be undone.`)) return
    deleteAgent.mutate(agent.id, {
      onSuccess: () => {
        notify.success(`Deleted ${agent.name}`)
        navigate(ROUTES.AGENTS)
      },
      onError: (e) => notify.error('Could not delete agent', apiErrorMessage(e)),
    })
  }

  return (
    <div className="space-y-6">
      <Link
        to={ROUTES.AGENTS}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        All agents
      </Link>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{agent.name}</h1>
            <AgentStatusBadge status={agent.status} />
          </div>
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <span className="capitalize">{agent.agent_type}</span>
            <span>·</span>
            <span>v{agent.version}</span>
            <span>·</span>
            <AgentHealthBadge health={agent.health} />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link to={`${ROUTES.AGENTS}/${agent.id}/edit`}>
              <Pencil className="h-4 w-4" />
              Edit
            </Link>
          </Button>
          {isActive ? (
            <Button variant="outline" size="sm" onClick={() => setStatus('SUSPENDED')}>
              Suspend
            </Button>
          ) : (
            <Button variant="outline" size="sm" onClick={() => setStatus('ACTIVE')}>
              Activate
            </Button>
          )}
          <Button variant="destructive" size="sm" onClick={handleDelete}>
            <Trash2 className="h-4 w-4" />
            Delete
          </Button>
        </div>
      </div>

      {/* Tab strip — Overview is live in 3.2a; the rest arrive in Part 3.2b. */}
      <div className="flex gap-1 overflow-x-auto border-b border-border">
        {TABS.map((tab, i) => (
          <span
            key={tab}
            className={
              i === 0
                ? 'border-b-2 border-primary px-3 py-2 text-sm font-medium text-foreground'
                : 'cursor-not-allowed px-3 py-2 text-sm text-muted-foreground/60'
            }
            title={i === 0 ? undefined : 'Coming in Phase 3 Part 3.2b'}
          >
            {tab}
          </span>
        ))}
      </div>

      <AgentStats agentId={agent.id} />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Details</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
            <Field label="Owner" value={agent.owner ?? '—'} />
            <Field label="Department" value={agent.department ?? '—'} />
            <Field label="Risk Level" value={<RiskLevelBadge level={agent.risk_level} />} />
            <Field label="Default Risk Score" value={String(agent.default_risk_score)} />
            <Field label="Max Allowed Risk" value={String(agent.max_allowed_risk)} />
            <Field
              label="Human Approval"
              value={agent.human_approval_required ? 'Required' : 'Not required'}
            />
            <Field
              label="Auto-Suspend Threshold"
              value={agent.auto_suspend_threshold == null ? '—' : String(agent.auto_suspend_threshold)}
            />
            <Field label="Capabilities" value={agent.capabilities.join(', ') || 'None'} />
            <Field label="Created" value={formatDateTime(agent.created_at)} />
            <Field label="Last Updated" value={formatRelativeTime(agent.updated_at)} />
            <Field
              label="Description"
              value={agent.description || '—'}
              className="sm:col-span-2"
            />
          </dl>
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

function AgentStats({ agentId }: { agentId: string }) {
  const { data, isLoading } = useAgentStats(agentId)

  const tiles = [
    { label: "Today's Actions", value: data?.actions_today, icon: Activity },
    { label: 'Total Actions', value: data?.total_actions, icon: ClipboardList },
    { label: 'Blocked', value: data?.blocked_actions, icon: Ban },
    { label: 'Pending Approvals', value: data?.pending_approvals, icon: ClipboardList },
    { label: 'Policies Triggered', value: data?.policies_triggered, icon: ShieldAlert },
    { label: 'Avg Risk', value: data?.average_risk, icon: ShieldAlert },
  ]

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {tiles.map((tile) => (
        <Card key={tile.label}>
          <CardContent className="flex items-center justify-between p-5">
            <div>
              <p className="text-xs text-muted-foreground">{tile.label}</p>
              <p className="text-xl font-semibold">{isLoading ? '—' : (tile.value ?? 0)}</p>
            </div>
            <tile.icon className="h-5 w-5 text-muted-foreground" />
          </CardContent>
        </Card>
      ))}
      <Card>
        <CardContent className="flex items-center justify-between p-5">
          <div>
            <p className="text-xs text-muted-foreground">Success Rate</p>
            <p className="text-xl font-semibold">
              {isLoading || !data ? '—' : formatPercent(data.success_rate, 1)}
            </p>
          </div>
          <CheckCircle2 className="h-5 w-5 text-success" />
        </CardContent>
      </Card>
    </div>
  )
}
