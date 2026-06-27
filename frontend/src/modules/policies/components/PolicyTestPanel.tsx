import { useState } from 'react'
import { CheckCircle2, FlaskConical, XCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { ID } from '@/types'
import { cn } from '@/utils/cn'
import type { Policy, PolicyTestRequest, PolicyTestResult } from '../types'
import { POLICY_ACTIONS, POLICY_RESOURCES, toOptions } from '../utils/constants'
import { parseConditions } from '../utils/policyValidators'
import { PolicyDecisionBadge } from './PolicyDecisionBadge'

interface PolicyTestPanelProps {
  policy: Policy
  busy?: boolean
  result?: PolicyTestResult | null
  onTest: (payload: PolicyTestRequest) => void
}

/**
 * Simulation panel (SRS §Test Policy Page). Lets an administrator run a sample
 * action against the policy and inspect whether it would trigger.
 */
export function PolicyTestPanel({ policy, busy, result, onTest }: PolicyTestPanelProps) {
  const [agentId, setAgentId] = useState('')
  const [resource, setResource] = useState(policy.resource)
  const [action, setAction] = useState(policy.action)
  const [payloadText, setPayloadText] = useState('{\n  "amount": 15000,\n  "risk_score": 80\n}')
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = () => {
    const parsed = parseConditions(payloadText)
    if (!parsed.ok) {
      setError(parsed.error)
      return
    }
    setError(null)
    onTest({
      agent_id: agentId ? (agentId as ID) : undefined,
      resource,
      action,
      input_payload: parsed.value,
    })
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardContent className="space-y-4 p-6">
          <div className="space-y-2">
            <Label htmlFor="agent">Agent ID (optional)</Label>
            <Input
              id="agent"
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              placeholder="Leave blank to test without an agent"
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="resource">Resource</Label>
              <Select
                id="resource"
                value={resource}
                options={toOptions(POLICY_RESOURCES)}
                onChange={(e) => setResource(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="action">Action</Label>
              <Select
                id="action"
                value={action}
                options={toOptions(POLICY_ACTIONS)}
                onChange={(e) => setAction(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="payload">Input Payload (JSON)</Label>
            <Textarea
              id="payload"
              value={payloadText}
              onChange={(e) => setPayloadText(e.target.value)}
              rows={8}
              spellCheck={false}
              className="font-mono text-xs"
            />
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
          </div>
          <Button onClick={handleSubmit} disabled={busy}>
            <FlaskConical className="h-4 w-4" />
            {busy ? 'Testing…' : 'Test Policy'}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-4 p-6">
          <h3 className="text-sm font-medium text-muted-foreground">Result</h3>
          {!result ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              Run a test to see whether this policy would trigger.
            </p>
          ) : (
            <div className="space-y-4">
              <div
                className={cn(
                  'flex items-center gap-2 rounded-md border p-3 text-sm font-medium',
                  result.matched
                    ? 'border-warning/40 bg-warning/10 text-warning'
                    : 'border-success/40 bg-success/10 text-success',
                )}
              >
                {result.matched ? (
                  <FlaskConical className="h-4 w-4" />
                ) : (
                  <CheckCircle2 className="h-4 w-4" />
                )}
                {result.matched ? 'Policy matched' : 'Policy did not match'}
              </div>

              <dl className="space-y-2 text-sm">
                <Row label="Matched">
                  {result.matched ? (
                    <span className="inline-flex items-center gap-1 text-warning">
                      <CheckCircle2 className="h-4 w-4" /> Yes
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-muted-foreground">
                      <XCircle className="h-4 w-4" /> No
                    </span>
                  )}
                </Row>
                <Row label="Decision">
                  {result.decision ? <PolicyDecisionBadge decision={result.decision} /> : '—'}
                </Row>
                <Row label="Risk Score">
                  <span className="tabular-nums">{result.risk_score}</span>
                </Row>
                <Row label="Reason">{result.reason}</Row>
              </dl>

              {result.triggered_conditions.length > 0 && (
                <div className="space-y-1">
                  <p className="text-xs font-medium text-muted-foreground">Triggered conditions</p>
                  <ul className="space-y-1 text-sm">
                    {result.triggered_conditions.map((c, i) => (
                      <li key={i}>• {c}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="rounded-md border border-border bg-background p-3 text-sm text-foreground">
                {result.explanation}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium">{children}</dd>
    </div>
  )
}
