import { useState } from 'react'
import { Check } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/utils/cn'
import type { PolicyCreateInput, PolicyDecision, PolicySeverity, PolicyStatus } from '../types'
import { POLICY_ACTIONS, POLICY_RESOURCES, POLICY_SEVERITIES, POLICY_STATUSES, toOptions } from '../utils/constants'
import { policyBasicSchema } from '../utils/policyValidators'
import { parseConditions } from '../utils/policyValidators'
import { summarizeRule } from '../utils/policyFormatters'
import { PolicyActionSelector } from './PolicyActionSelector'
import { PolicyConditionBuilder } from './PolicyConditionBuilder'

export interface PolicyBuilderInitial {
  name: string
  description: string
  severity: PolicySeverity
  status: PolicyStatus
  resource: string
  action: string
  conditionsText: string
  decision: PolicyDecision
}

interface PolicyBuilderProps {
  mode: 'create' | 'edit'
  initial?: Partial<PolicyBuilderInitial>
  busy?: boolean
  onSubmit: (input: PolicyCreateInput, opts: { asDraft: boolean }) => void
  onCancel: () => void
}

const STEPS = ['Basic', 'Scope', 'Trigger', 'Conditions', 'Decision', 'Review']

export function PolicyBuilder({ mode, initial, busy, onSubmit, onCancel }: PolicyBuilderProps) {
  const [step, setStep] = useState(0)
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [severity, setSeverity] = useState<PolicySeverity>(initial?.severity ?? 'MEDIUM')
  const [status, setStatus] = useState<PolicyStatus>(initial?.status ?? 'ENABLED')
  const [resource, setResource] = useState(initial?.resource ?? 'CLAIM')
  const [action, setAction] = useState(initial?.action ?? 'READ')
  const [conditionsText, setConditionsText] = useState(initial?.conditionsText ?? '{}')
  const [decision, setDecision] = useState<PolicyDecision>(initial?.decision ?? 'PENDING_APPROVAL')
  const [priority, setPriority] = useState('MEDIUM')
  const [errors, setErrors] = useState<string[]>([])

  const parsedConditions = parseConditions(conditionsText)

  const validateStep = (): boolean => {
    if (step === 0) {
      const result = policyBasicSchema.safeParse({ name, description, severity })
      if (!result.success) {
        setErrors(result.error.issues.map((i) => i.message))
        return false
      }
    }
    if (step === 3 && !parsedConditions.ok) {
      setErrors([parsedConditions.error])
      return false
    }
    setErrors([])
    return true
  }

  const next = () => {
    if (validateStep()) setStep((s) => Math.min(s + 1, STEPS.length - 1))
  }

  const buildInput = (asDraft: boolean): PolicyCreateInput | null => {
    if (!parsedConditions.ok) {
      setErrors([parsedConditions.error])
      setStep(3)
      return null
    }
    return {
      name: name.trim(),
      description: description.trim(),
      resource,
      action,
      conditions: parsedConditions.value,
      decision,
      severity,
      status: asDraft ? 'DRAFT' : status,
    }
  }

  const submit = (asDraft: boolean) => {
    const input = buildInput(asDraft)
    if (input) onSubmit(input, { asDraft })
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Stepper current={step} />

      <Card>
        <CardContent className="space-y-5 p-6">
          {errors.length > 0 && (
            <ul className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}

          {step === 0 && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">Policy Name *</Label>
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Large Claim Approval" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">Description *</Label>
                <Textarea id="description" value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="severity">Severity *</Label>
                  <Select id="severity" value={severity} options={POLICY_SEVERITIES} onChange={(e) => setSeverity(e.target.value as PolicySeverity)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="status">Status</Label>
                  <Select id="status" value={status} options={POLICY_STATUSES} onChange={(e) => setStatus(e.target.value as PolicyStatus)} />
                </div>
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-3">
              <Label>Scope</Label>
              <div className="space-y-2">
                <label className="flex items-center gap-2 rounded-md border border-primary/50 bg-primary/5 p-3 text-sm">
                  <input type="radio" checked readOnly className="accent-primary" />
                  All agents in the organization
                </label>
                <label className="flex cursor-not-allowed items-center gap-2 rounded-md border border-border p-3 text-sm text-muted-foreground/70">
                  <input type="radio" disabled className="accent-primary" />
                  Specific agents (coming in Part 3.3b)
                </label>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="resource">Resource</Label>
                <Select id="resource" value={resource} options={toOptions(POLICY_RESOURCES)} onChange={(e) => setResource(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="action">Action</Label>
                <Select id="action" value={action} options={toOptions(POLICY_ACTIONS)} onChange={(e) => setAction(e.target.value)} />
              </div>
            </div>
          )}

          {step === 3 && <PolicyConditionBuilder value={conditionsText} onChange={setConditionsText} />}

          {step === 4 && (
            <PolicyActionSelector decision={decision} onDecisionChange={setDecision} priority={priority} onPriorityChange={setPriority} />
          )}

          {step === 5 && (
            <ReviewStep
              rows={[
                ['Name', name],
                ['Scope', 'All agents'],
                ['Resource', resource],
                ['Action', action],
                ['Decision', decision],
                ['Severity', severity],
                ['Status', status],
              ]}
              summary={parsedConditions.ok ? summarizeRule(parsedConditions.value, decision) : ''}
            />
          )}

          <div className="flex items-center justify-between pt-2">
            <Button variant="ghost" onClick={() => (step === 0 ? onCancel() : setStep((s) => s - 1))}>
              {step === 0 ? 'Cancel' : 'Back'}
            </Button>
            {step < STEPS.length - 1 ? (
              <Button onClick={next}>Next</Button>
            ) : (
              <div className="flex gap-2">
                {mode === 'create' && (
                  <Button variant="outline" disabled={busy} onClick={() => submit(true)}>
                    Save as Draft
                  </Button>
                )}
                <Button disabled={busy} onClick={() => submit(false)}>
                  {busy ? 'Saving…' : mode === 'create' ? 'Create Policy' : 'Save Changes'}
                </Button>
              </div>
            )}
          </div>
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
          <span className={cn('hidden text-xs lg:block', i === current ? 'text-foreground' : 'text-muted-foreground')}>
            {label}
          </span>
          {i < STEPS.length - 1 ? <span className="h-px flex-1 bg-border" /> : null}
        </li>
      ))}
    </ol>
  )
}

function ReviewStep({ rows, summary }: { rows: [string, string][]; summary: string }) {
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium">Review</h3>
      {summary ? (
        <p className="rounded-md border border-border bg-background p-3 text-sm text-foreground">{summary}</p>
      ) : null}
      <dl className="divide-y divide-border rounded-md border border-border">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between px-3 py-2 text-sm">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="text-right font-medium">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
