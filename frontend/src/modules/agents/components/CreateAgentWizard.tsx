import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, Copy, KeyRound } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { ROUTES } from '@/constants/routes'
import { useNotifications } from '@/hooks/useNotifications'
import { cn } from '@/utils/cn'
import { apiErrorMessage } from '@/utils/error'
import { useCreateAgent } from '../hooks'
import type { AgentCreateInput, AgentCreateResponse, RiskLevel } from '../types'
import { AGENT_TYPES, CAPABILITIES, RISK_LEVELS } from '../utils/constants'

const STEPS = ['Basic Info', 'Capabilities', 'Risk Config', 'Review', 'API Key']

const EMPTY: AgentCreateInput = {
  name: '',
  agent_type: 'custom',
  description: '',
  owner: '',
  department: '',
  version: '1.0.0',
  capabilities: [],
  default_risk_score: 0,
  max_allowed_risk: 100,
  human_approval_required: false,
  auto_suspend_threshold: null,
  risk_level: 'LOW',
}

export function CreateAgentWizard() {
  const navigate = useNavigate()
  const notify = useNotifications()
  const createAgent = useCreateAgent()

  const [step, setStep] = useState(0)
  const [form, setForm] = useState<AgentCreateInput>(EMPTY)
  const [created, setCreated] = useState<AgentCreateResponse | null>(null)

  const set = <K extends keyof AgentCreateInput>(key: K, value: AgentCreateInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const toggleCapability = (value: string) =>
    setForm((f) => {
      const has = f.capabilities?.includes(value)
      return {
        ...f,
        capabilities: has
          ? (f.capabilities ?? []).filter((c) => c !== value)
          : [...(f.capabilities ?? []), value],
      }
    })

  const canProceedBasic = form.name.trim() !== '' && (form.agent_type ?? '').trim() !== ''

  const handleCreate = () => {
    createAgent.mutate(form, {
      onSuccess: (data) => {
        setCreated(data)
        setStep(4)
        notify.success('Agent created', data.name)
      },
      onError: (error) => notify.error('Could not create agent', apiErrorMessage(error)),
    })
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Stepper current={step} />

      <Card>
        <CardContent className="space-y-5 p-6">
          {step === 0 && (
            <BasicStep form={form} set={set} />
          )}

          {step === 1 && (
            <fieldset className="space-y-3">
              <legend className="text-sm font-medium">Capabilities</legend>
              <p className="text-sm text-muted-foreground">
                Select what this agent is allowed to do.
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                {CAPABILITIES.map((cap) => (
                  <label
                    key={cap.value}
                    className="flex items-center gap-2 rounded-md border border-border p-3 text-sm"
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-primary"
                      checked={form.capabilities?.includes(cap.value) ?? false}
                      onChange={() => toggleCapability(cap.value)}
                    />
                    {cap.label}
                  </label>
                ))}
              </div>
            </fieldset>
          )}

          {step === 2 && <RiskStep form={form} set={set} />}

          {step === 3 && <ReviewStep form={form} />}

          {step === 4 && created && <ApiKeyStep apiKey={created.api_key} />}

          {/* Footer navigation */}
          {step < 4 ? (
            <div className="flex items-center justify-between pt-2">
              <Button
                variant="ghost"
                onClick={() => (step === 0 ? navigate(ROUTES.AGENTS) : setStep(step - 1))}
              >
                {step === 0 ? 'Cancel' : 'Back'}
              </Button>
              {step < 3 ? (
                <Button onClick={() => setStep(step + 1)} disabled={step === 0 && !canProceedBasic}>
                  Next
                </Button>
              ) : (
                <Button onClick={handleCreate} disabled={createAgent.isPending}>
                  {createAgent.isPending ? 'Creating…' : 'Create Agent'}
                </Button>
              )}
            </div>
          ) : (
            <div className="flex justify-end pt-2">
              <Button onClick={() => navigate(`${ROUTES.AGENTS}/${created?.id}`)}>Done</Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function Stepper({ current }: { current: number }) {
  return (
    <ol className="flex items-center gap-2">
      {STEPS.map((label, i) => (
        <li key={label} className="flex flex-1 items-center gap-2">
          <span
            className={cn(
              'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-medium',
              i < current && 'bg-success text-success-foreground',
              i === current && 'bg-primary text-primary-foreground',
              i > current && 'bg-muted text-muted-foreground',
            )}
          >
            {i < current ? <Check className="h-4 w-4" /> : i + 1}
          </span>
          <span className={cn('hidden text-xs sm:block', i === current ? 'text-foreground' : 'text-muted-foreground')}>
            {label}
          </span>
          {i < STEPS.length - 1 ? <span className="h-px flex-1 bg-border" /> : null}
        </li>
      ))}
    </ol>
  )
}

interface StepProps {
  form: AgentCreateInput
  set: <K extends keyof AgentCreateInput>(key: K, value: AgentCreateInput[K]) => void
}

function BasicStep({ form, set }: StepProps) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="name">Name *</Label>
        <Input id="name" value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="BillingAgent" />
      </div>
      <div className="space-y-2">
        <Label htmlFor="description">Description</Label>
        <Input
          id="description"
          value={form.description ?? ''}
          onChange={(e) => set('description', e.target.value)}
          placeholder="What does this agent do?"
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="agent_type">Agent Type *</Label>
          <Select
            id="agent_type"
            value={form.agent_type ?? ''}
            options={AGENT_TYPES}
            onChange={(e) => set('agent_type', e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="owner">Owner</Label>
          <Input id="owner" value={form.owner ?? ''} onChange={(e) => set('owner', e.target.value)} placeholder="owner@example.com" />
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="department">Department</Label>
        <Input id="department" value={form.department ?? ''} onChange={(e) => set('department', e.target.value)} placeholder="Finance" />
      </div>
    </div>
  )
}

function RiskStep({ form, set }: StepProps) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
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
        <div className="space-y-2">
          <Label htmlFor="auto_suspend_threshold">Auto-Suspend Threshold</Label>
          <Input
            id="auto_suspend_threshold"
            type="number"
            min={0}
            max={100}
            value={form.auto_suspend_threshold ?? ''}
            onChange={(e) =>
              set('auto_suspend_threshold', e.target.value === '' ? null : Number(e.target.value))
            }
            placeholder="None"
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
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="h-4 w-4 accent-primary"
          checked={form.human_approval_required ?? false}
          onChange={(e) => set('human_approval_required', e.target.checked)}
        />
        Require human approval for this agent's risky actions
      </label>
    </div>
  )
}

function ReviewStep({ form }: { form: AgentCreateInput }) {
  const rows: [string, string][] = [
    ['Name', form.name],
    ['Type', form.agent_type ?? '—'],
    ['Owner', form.owner || '—'],
    ['Department', form.department || '—'],
    ['Capabilities', (form.capabilities ?? []).join(', ') || 'None'],
    ['Default Risk', String(form.default_risk_score ?? 0)],
    ['Max Allowed Risk', String(form.max_allowed_risk ?? 100)],
    ['Risk Level', form.risk_level ?? 'LOW'],
    ['Human Approval', form.human_approval_required ? 'Required' : 'Not required'],
  ]
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium">Review</h3>
      <dl className="divide-y divide-border rounded-md border border-border">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between px-3 py-2 text-sm">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="font-medium text-right">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function ApiKeyStep({ apiKey }: { apiKey: string }) {
  const notify = useNotifications()
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(apiKey)
      setCopied(true)
      notify.success('API key copied')
      setTimeout(() => setCopied(false), 2000)
    } catch {
      notify.error('Could not copy')
    }
  }

  return (
    <div className="space-y-4 text-center">
      <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/15 text-primary">
        <KeyRound className="h-6 w-6" />
      </span>
      <div className="space-y-1">
        <h3 className="text-sm font-medium">Agent API Key</h3>
        <p className="text-sm text-muted-foreground">
          Copy this key now — it is shown only once and cannot be retrieved later.
        </p>
      </div>
      <div className="flex items-center gap-2 rounded-md border border-border bg-background px-3 py-2">
        <code className="flex-1 truncate text-left text-sm">{apiKey}</code>
        <Button variant="outline" size="sm" onClick={copy}>
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
    </div>
  )
}
