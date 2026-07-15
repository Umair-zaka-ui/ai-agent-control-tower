import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Save } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { abacService } from '@/services'
import type { ABACConditionNode, ABACPolicy, ABACPolicyWrite } from '@/types'
import { ALGORITHMS, EFFECTS, SCOPES, policyToText } from '../lib'
import { ConditionBuilder } from './ConditionBuilder'

/**
 * Visual policy builder (§34): metadata, scope, target, nested conditions,
 * effect, obligations and a live human-readable preview. Raw JSON editing for
 * obligations stays available for advanced administrators.
 */
export function PolicyBuilder({
  initial,
  onSubmit,
  submitting,
  error,
  submitLabel = 'Save policy',
}: {
  initial?: ABACPolicy | null
  onSubmit: (payload: ABACPolicyWrite) => void
  submitting?: boolean
  error?: string | null
  submitLabel?: string
}) {
  const attributes = useQuery({ queryKey: ['abac-attributes'], queryFn: () => abacService.attributes() })

  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [effect, setEffect] = useState<string>(initial?.effect ?? 'DENY')
  const [priority, setPriority] = useState(String(initial?.priority ?? 100))
  const [algorithm, setAlgorithm] = useState<string>(initial?.combining_algorithm ?? 'DENY_OVERRIDES')
  const [scopeType, setScopeType] = useState<string>(initial?.scope_type ?? 'ORGANIZATION')
  const [scopeId, setScopeId] = useState(initial?.scope_id ?? '')
  const [actions, setActions] = useState((initial?.target?.actions ?? []).join(', '))
  const [resourceTypes, setResourceTypes] = useState((initial?.target?.resource_types ?? []).join(', '))
  const [roles, setRoles] = useState((initial?.target?.roles ?? []).join(', '))
  const [conditions, setConditions] = useState<ABACConditionNode>(
    (initial?.conditions as ABACConditionNode) ?? { all: [] },
  )
  const [obligationsText, setObligationsText] = useState(
    initial?.obligations ? JSON.stringify(initial.obligations, null, 2) : '',
  )
  const [obligationsError, setObligationsError] = useState<string | null>(null)

  const payload = useMemo((): ABACPolicyWrite => {
    const list = (text: string) => text.split(',').map((s) => s.trim()).filter(Boolean)
    const target: Record<string, string[]> = {}
    if (list(actions).length) target.actions = list(actions)
    if (list(resourceTypes).length) target.resource_types = list(resourceTypes)
    if (list(roles).length) target.roles = list(roles)
    const hasConditions =
      ('all' in (conditions as object) && ((conditions as { all?: unknown[] }).all ?? []).length > 0)
      || ('any' in (conditions as object) && ((conditions as { any?: unknown[] }).any ?? []).length > 0)
    return {
      name: name.trim(),
      description: description.trim() || null,
      effect: effect as ABACPolicyWrite['effect'],
      priority: Number.parseInt(priority, 10) || 100,
      combining_algorithm: algorithm as ABACPolicyWrite['combining_algorithm'],
      scope_type: scopeType as ABACPolicyWrite['scope_type'],
      scope_id: scopeId || null,
      target: Object.keys(target).length ? target : null,
      conditions: hasConditions ? conditions : null,
    }
  }, [name, description, effect, priority, algorithm, scopeType, scopeId, actions,
      resourceTypes, roles, conditions])

  const submit = () => {
    let obligations: Record<string, unknown> | null = null
    setObligationsError(null)
    if (obligationsText.trim()) {
      try {
        obligations = JSON.parse(obligationsText) as Record<string, unknown>
      } catch {
        setObligationsError('Obligations must be valid JSON.')
        return
      }
    }
    onSubmit({ ...payload, obligations })
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle className="text-base">Policy</CardTitle></CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="pb-name">Name</Label>
            <Input id="pb-name" value={name} onChange={(e) => setName(e.target.value)}
              placeholder="Restrict PHI access from untrusted devices" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="pb-desc">Description</Label>
            <Input id="pb-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="pb-effect">Effect</Label>
            <select id="pb-effect" value={effect} onChange={(e) => setEffect(e.target.value)}
              className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
              {EFFECTS.map((eff) => <option key={eff} value={eff}>{eff}</option>)}
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="pb-priority">Priority</Label>
            <Input id="pb-priority" type="number" value={priority}
              onChange={(e) => setPriority(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="pb-algo">Combining algorithm</Label>
            <select id="pb-algo" value={algorithm} onChange={(e) => setAlgorithm(e.target.value)}
              className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
              {ALGORITHMS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="pb-scope">Scope</Label>
            <div className="flex gap-2">
              <select id="pb-scope" value={scopeType} onChange={(e) => setScopeType(e.target.value)}
                className="rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                {SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              {!['ORGANIZATION', 'PLATFORM'].includes(scopeType) && (
                <Input aria-label="Scope id" value={scopeId ?? ''} placeholder="Scope id (UUID)"
                  onChange={(e) => setScopeId(e.target.value)} />
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Target</CardTitle></CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-1">
            <Label htmlFor="pb-actions">Actions</Label>
            <Input id="pb-actions" value={actions} onChange={(e) => setActions(e.target.value)}
              placeholder="dataset.export, agent.execute" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="pb-rtypes">Resource types</Label>
            <Input id="pb-rtypes" value={resourceTypes}
              onChange={(e) => setResourceTypes(e.target.value)} placeholder="dataset, ai_agent" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="pb-roles">Roles</Label>
            <Input id="pb-roles" value={roles} onChange={(e) => setRoles(e.target.value)}
              placeholder="ROLE_AI_OPERATOR" />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Conditions</CardTitle></CardHeader>
        <CardContent>
          {attributes.isLoading ? (
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          ) : (
            <ConditionBuilder node={conditions} attributes={attributes.data ?? []}
              onChange={setConditions} />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Obligations (JSON)</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          <textarea
            aria-label="Obligations JSON"
            value={obligationsText}
            onChange={(e) => setObligationsText(e.target.value)}
            placeholder='{"priority": "CRITICAL", "reviewer_role": "ROLE_AI_REVIEWER"}'
            className="h-24 w-full rounded-md border border-border bg-background p-2 font-mono text-xs"
          />
          {obligationsError && <p className="text-xs text-destructive">{obligationsError}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Preview</CardTitle></CardHeader>
        <CardContent>
          <pre className="whitespace-pre-wrap rounded-md bg-muted p-3 text-xs" data-testid="policy-preview">
            {policyToText(payload)}
          </pre>
        </CardContent>
      </Card>

      <Button onClick={submit} disabled={!name.trim() || submitting}>
        {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
        {submitLabel}
      </Button>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}
