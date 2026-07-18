import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle2, Loader2, PlayCircle, Plus, Trash2, XCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { adminSessionService } from '@/services/authService'
import { abacService } from '@/services'
import type { ABACSimulation, ApiError } from '@/types'
import { DECISION_STYLES, dataTypeOf, parseTypedValue } from './lib'

interface ContextRow { attribute: string; value: string }

/**
 * Policy simulator (§35): identity + action + attribute overrides in; baseline
 * RBAC, resource authorization, matched ABAC policies, condition results and
 * the final decision out. Never executes the action.
 */
export function PolicySimulatorPage() {
  const [params] = useSearchParams()
  const policyId = params.get('policy')
  const [identity, setIdentity] = useState('')
  const [action, setAction] = useState('dataset.export')
  const [rows, setRows] = useState<ContextRow[]>([
    { attribute: 'environment.network_zone', value: 'PUBLIC' },
  ])
  const [result, setResult] = useState<ABACSimulation | null>(null)

  const users = useQuery({ queryKey: ['org-users'], queryFn: () => adminSessionService.listUsers() })
  const attributes = useQuery({ queryKey: ['abac-attributes'], queryFn: () => abacService.attributes() })

  const simulate = useMutation<ABACSimulation, ApiError>({
    mutationFn: () => {
      const context: Record<string, unknown> = {}
      for (const row of rows) {
        if (!row.attribute.trim()) continue
        context[row.attribute.trim()] = parseTypedValue(
          row.value, dataTypeOf(row.attribute.trim(), attributes.data ?? []), 'EQUALS',
        )
      }
      const payload = { action: action.trim(), identity_id: identity || null, context }
      return policyId ? abacService.simulatePolicy(policyId, payload) : abacService.simulate(payload)
    },
    onSuccess: (r) => setResult(r),
  })

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <PageHeader
        icon={PlayCircle}
        title="Policy simulator"
        description={`What-if evaluation across RBAC, resource authorization and ABAC — nothing is executed.${policyId ? ' Simulating one selected policy.' : ''}`}
        backTo={ROUTES.ABAC_POLICIES}
        backLabel="Context policies overview"
      />

      <Card>
        <CardHeader><CardTitle className="text-base">Inputs</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="sim-identity">Identity</Label>
              <select id="sim-identity" value={identity} onChange={(e) => setIdentity(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                <option value="">Myself</option>
                {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="sim-action">Action</Label>
              <Input id="sim-action" value={action} onChange={(e) => setAction(e.target.value)}
                placeholder="dataset.export" />
            </div>
          </div>

          <div className="space-y-2">
            <Label>Attribute overrides</Label>
            {rows.map((row, index) => (
              <div key={index} className="flex flex-wrap items-center gap-2">
                <Input aria-label={`Override attribute ${index + 1}`} className="w-72 font-mono text-xs"
                  value={row.attribute} list="sim-attribute-names"
                  onChange={(e) => setRows(rows.map((r, i) => i === index ? { ...r, attribute: e.target.value } : r))} />
                <Input aria-label={`Override value ${index + 1}`} className="w-44 text-xs"
                  value={row.value}
                  onChange={(e) => setRows(rows.map((r, i) => i === index ? { ...r, value: e.target.value } : r))} />
                <Button size="sm" variant="ghost" aria-label="Remove override"
                  onClick={() => setRows(rows.filter((_, i) => i !== index))}>
                  <Trash2 className="h-3 w-3 text-destructive" />
                </Button>
              </div>
            ))}
            <datalist id="sim-attribute-names">
              {(attributes.data ?? []).map((a) => <option key={a.name} value={a.name} />)}
            </datalist>
            <Button size="sm" variant="outline"
              onClick={() => setRows([...rows, { attribute: '', value: '' }])}>
              <Plus className="h-3 w-3" /> Override
            </Button>
          </div>

          <Button onClick={() => action.trim() && !simulate.isPending && simulate.mutate()}
            disabled={!action.trim() || simulate.isPending}>
            {simulate.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
            Simulate
          </Button>
          {simulate.isError && (
            <p className="text-xs text-destructive">{simulate.error?.message ?? 'Simulation failed.'}</p>
          )}
        </CardContent>
      </Card>

      {result && (
        <Card data-testid="simulation-result">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              {result.abac.allowed || result.abac.decision === 'NOT_APPLICABLE' ? (
                <CheckCircle2 className="h-5 w-5 text-emerald-500" />
              ) : (
                <XCircle className="h-5 w-5 text-destructive" />
              )}
              <span className={`rounded px-2 py-0.5 text-sm font-medium ${DECISION_STYLES[result.abac.decision] ?? ''}`}>
                {result.abac.decision}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
              <div>
                <dt className="text-xs text-muted-foreground">Baseline RBAC</dt>
                <dd>{result.baseline_rbac.allowed ? 'ALLOW' : 'DENY'} — {result.baseline_rbac.reason}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Resource authorization</dt>
                <dd>{result.resource_authorization
                  ? `${result.resource_authorization.allowed ? 'ALLOW' : 'DENY'} — ${result.resource_authorization.reason}`
                  : '—'}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">ABAC reason</dt>
                <dd>{result.abac.reason}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Evaluation time</dt>
                <dd>{result.abac.evaluation_time_ms}ms</dd>
              </div>
            </dl>
            {result.abac.obligations.length > 0 && (
              <div>
                <p className="text-xs text-muted-foreground">Obligations</p>
                <pre className="rounded-md bg-muted p-2 text-xs">
                  {JSON.stringify(result.abac.obligations, null, 2)}
                </pre>
              </div>
            )}
            {(result.abac.explanation.matched_policies ?? []).length > 0 && (
              <div>
                <p className="text-xs text-muted-foreground">Matched policies & conditions</p>
                <ul className="space-y-2">
                  {(result.abac.explanation.matched_policies ?? []).map((m) => (
                    <li key={m.policy_id} className="rounded-md border border-border p-2">
                      <p className="text-xs font-medium">{m.name} → {m.effect}</p>
                      <ul className="mt-1 space-y-0.5">
                        {m.conditions.map((c, i) => (
                          <li key={i} className="flex items-center gap-1 font-mono text-xs">
                            {c.result
                              ? <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                              : <XCircle className="h-3 w-3 text-destructive" />}
                            {c.attribute} {c.operator} {String(c.expected ?? '')}
                            {c.missing ? ' (missing)' : ''}
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
