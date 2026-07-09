import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, SlidersHorizontal, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { protectionService } from '@/services'
import type { ApiError, ID, ProtectionRuleCondition } from '@/types'

const DECISIONS = [
  'ALLOW',
  'DENY',
  'CHALLENGE',
  'REQUIRE_MFA',
  'LOCK_ACCOUNT',
  'BLOCK_IP',
  'REQUIRE_SECURITY_REVIEW',
]

/**
 * Identity protection rules (SRS §27). Admins author `conditions → decision` rules.
 * Conditions use a JSON editor for now (§27 notes a visual builder comes later); the
 * server validates every rule.
 */
export function IdentityProtectionRulesPage() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [decision, setDecision] = useState('CHALLENGE')
  const [priority, setPriority] = useState('100')
  const [conditionsJson, setConditionsJson] = useState(
    '[{"field": "risk_score", "op": "gte", "value": 76}]',
  )
  const [jsonError, setJsonError] = useState<string | null>(null)

  const rules = useQuery({ queryKey: ['protection-rules'], queryFn: () => protectionService.rules() })

  const create = useMutation<unknown, ApiError>({
    mutationFn: () => {
      let conditions: ProtectionRuleCondition[]
      try {
        conditions = JSON.parse(conditionsJson)
      } catch {
        throw { message: 'Conditions must be valid JSON.' } as ApiError
      }
      return protectionService.createRule({
        name: name.trim(),
        decision,
        priority: Number(priority) || 100,
        conditions,
      })
    },
    onSuccess: () => {
      setName('')
      void queryClient.invalidateQueries({ queryKey: ['protection-rules'] })
    },
  })

  const toggle = useMutation({
    mutationFn: (payload: { id: ID; enabled: boolean }) =>
      protectionService.updateRule(payload.id, { enabled: payload.enabled }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['protection-rules'] }),
  })

  const remove = useMutation({
    mutationFn: (id: ID) => protectionService.deleteRule(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['protection-rules'] }),
  })

  const validateJson = (value: string) => {
    setConditionsJson(value)
    try {
      JSON.parse(value)
      setJsonError(null)
    } catch {
      setJsonError('Not valid JSON yet')
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Protection rules</h1>
        <p className="text-sm text-muted-foreground">
          When a rule's conditions all match a sign-in, its decision applies.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">New rule</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (name.trim() && !jsonError && !create.isPending) create.mutate()
            }}
          >
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="space-y-1 sm:col-span-2">
                <Label htmlFor="rule-name">Name</Label>
                <Input id="rule-name" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="rule-priority">Priority</Label>
                <Input
                  id="rule-priority"
                  type="number"
                  value={priority}
                  onChange={(e) => setPriority(e.target.value)}
                />
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="rule-decision">Decision</Label>
              <select
                id="rule-decision"
                value={decision}
                onChange={(e) => setDecision(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              >
                {DECISIONS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="rule-conditions">Conditions (JSON)</Label>
              <textarea
                id="rule-conditions"
                value={conditionsJson}
                onChange={(e) => validateJson(e.target.value)}
                rows={3}
                className="w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs"
              />
              {jsonError && <p className="text-xs text-destructive">{jsonError}</p>}
              <p className="text-xs text-muted-foreground">
                Fields: risk_score, risk_level, failed_attempts, new_device, impossible_travel,
                blocked_ip… · ops: eq, gt, gte, lt, lte, in, is_true
              </p>
            </div>
            <Button type="submit" disabled={!name.trim() || Boolean(jsonError) || create.isPending}>
              {create.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Plus className="h-4 w-4" aria-hidden="true" />
              )}
              Create rule
            </Button>
            {create.isError && (
              <p className="text-xs text-destructive" role="alert">
                {create.error?.message ?? 'Could not create the rule.'}
              </p>
            )}
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <SlidersHorizontal className="h-5 w-5 text-primary" aria-hidden="true" />
            Rules
          </CardTitle>
        </CardHeader>
        <CardContent>
          {rules.isLoading ? (
            <div className="flex justify-center p-4" role="status" aria-label="Loading">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden="true" />
            </div>
          ) : (rules.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No rules yet.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="protection-rules">
              {(rules.data ?? []).map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-foreground">
                      {r.name} <span className="text-xs text-muted-foreground">→ {r.decision}</span>
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      priority {r.priority} · {r.conditions.length} condition
                      {r.conditions.length === 1 ? '' : 's'}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <label className="flex items-center gap-1 text-xs text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={r.enabled}
                        onChange={(e) => toggle.mutate({ id: r.id, enabled: e.target.checked })}
                        className="h-3.5 w-3.5 accent-primary"
                      />
                      enabled
                    </label>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => remove.mutate(r.id)}
                      aria-label={`Delete ${r.name}`}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" aria-hidden="true" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
