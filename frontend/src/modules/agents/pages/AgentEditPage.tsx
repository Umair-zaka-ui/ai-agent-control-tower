import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AlertCircle, ArrowLeft } from 'lucide-react'

import { PageHeader } from '@/components/common/PageHeader'
import { FullPageSpinner } from '@/components/common/Spinner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { ROUTES } from '@/constants/routes'
import { useNotifications } from '@/hooks/useNotifications'
import { apiErrorMessage } from '@/utils/error'
import { useAgent, useUpdateAgent } from '../hooks'
import type { AgentUpdateInput, RiskLevel } from '../types'
import { AGENT_TYPES, RISK_LEVELS } from '../utils/constants'

export function AgentEditPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const notify = useNotifications()
  const { data: agent, isLoading, isError } = useAgent(id)
  const updateAgent = useUpdateAgent()

  const [form, setForm] = useState<AgentUpdateInput>({})

  // Seed the form once the agent loads.
  useEffect(() => {
    if (agent) {
      setForm({
        name: agent.name,
        description: agent.description ?? '',
        agent_type: agent.agent_type,
        owner: agent.owner ?? '',
        department: agent.department ?? '',
        version: agent.version,
        default_risk_score: agent.default_risk_score,
        max_allowed_risk: agent.max_allowed_risk,
        human_approval_required: agent.human_approval_required,
        risk_level: agent.risk_level,
      })
    }
  }, [agent])

  if (isLoading) return <FullPageSpinner />
  if (isError || !agent) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 py-24 text-center">
        <AlertCircle className="h-7 w-7 text-destructive" />
        <p className="text-sm text-muted-foreground">Agent not found.</p>
        <Button variant="outline" asChild>
          <Link to={ROUTES.AGENTS}>Back to agents</Link>
        </Button>
      </div>
    )
  }

  const set = <K extends keyof AgentUpdateInput>(key: K, value: AgentUpdateInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const handleSave = () => {
    updateAgent.mutate(
      { id: agent.id, input: form },
      {
        onSuccess: () => {
          notify.success('Agent updated')
          navigate(`${ROUTES.AGENTS}/${agent.id}`)
        },
        onError: (e) => notify.error('Could not update agent', apiErrorMessage(e)),
      },
    )
  }

  return (
    <div className="space-y-6">
      <Link
        to={`${ROUTES.AGENTS}/${agent.id}`}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to agent
      </Link>

      <PageHeader title={`Edit ${agent.name}`} description="Update this agent's metadata and risk configuration." />

      <Card className="max-w-2xl">
        <CardContent className="space-y-4 p-6">
          <div className="space-y-2">
            <Label htmlFor="name">Name</Label>
            <Input id="name" value={form.name ?? ''} onChange={(e) => set('name', e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="description">Description</Label>
            <Input
              id="description"
              value={form.description ?? ''}
              onChange={(e) => set('description', e.target.value)}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="agent_type">Type</Label>
              <Select
                id="agent_type"
                value={form.agent_type ?? ''}
                options={AGENT_TYPES}
                onChange={(e) => set('agent_type', e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="risk_level">Risk Level</Label>
              <Select
                id="risk_level"
                value={form.risk_level ?? 'LOW'}
                options={RISK_LEVELS}
                onChange={(e) => set('risk_level', e.target.value as RiskLevel)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="owner">Owner</Label>
              <Input id="owner" value={form.owner ?? ''} onChange={(e) => set('owner', e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="department">Department</Label>
              <Input
                id="department"
                value={form.department ?? ''}
                onChange={(e) => set('department', e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="default_risk_score">Default Risk Score</Label>
              <Input
                id="default_risk_score"
                type="number"
                min={0}
                max={100}
                value={form.default_risk_score ?? 0}
                onChange={(e) => set('default_risk_score', Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="max_allowed_risk">Max Allowed Risk</Label>
              <Input
                id="max_allowed_risk"
                type="number"
                min={0}
                max={100}
                value={form.max_allowed_risk ?? 100}
                onChange={(e) => set('max_allowed_risk', Number(e.target.value))}
              />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="h-4 w-4 accent-primary"
              checked={form.human_approval_required ?? false}
              onChange={(e) => set('human_approval_required', e.target.checked)}
            />
            Require human approval for risky actions
          </label>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" asChild>
              <Link to={`${ROUTES.AGENTS}/${agent.id}`}>Cancel</Link>
            </Button>
            <Button onClick={handleSave} disabled={updateAgent.isPending}>
              {updateAgent.isPending ? 'Saving…' : 'Save Changes'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
