import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { AlertTriangle, EyeOff, Lock, ShieldCheck } from 'lucide-react'

import { usePermissions } from '@/authorization'
import { Card, CardContent, Select } from '@/components/ui'
import { cn } from '@/utils/cn'
import {
  PERSONAS, loadPersona, savePersona, viewsForPersona, type PersonaId,
} from './personas'
import { affordancesFor, type GovernanceSignal } from './affordances'
import type { EstateSection, ShadowCondition } from '@/services/commandCenterService'

/**
 * Phase 5.8 — navigation across the command center, with the persona lens.
 *
 * Deliberately the same two composing filters Phase 4.9's nav uses: a link
 * shows only if the user *can* use it (courtesy — the server still enforces)
 * AND it belongs to the selected persona. Same behaviour, same words, so an
 * operator moving between the two centers is not learning a second idiom.
 */
export function CommandCenterNav() {
  const { can } = usePermissions()
  const [persona, setPersona] = useState<PersonaId | 'all'>(() => loadPersona())
  const visible = viewsForPersona(persona).filter((v) => can(v.permission))

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="cc-persona" className="text-xs font-medium text-muted-foreground">
          Viewing as
        </label>
        <Select
          id="cc-persona"
          aria-label="Persona"
          value={persona}
          onChange={(e) => {
            const next = e.target.value as PersonaId | 'all'
            setPersona(next)
            savePersona(next)
          }}
          options={[
            { value: 'all', label: 'All views' },
            ...PERSONAS.map((p) => ({ value: p.id, label: p.label })),
          ]}
        />
        {persona !== 'all' ? (
          <span className="text-xs text-muted-foreground">
            {PERSONAS.find((p) => p.id === persona)?.blurb}
          </span>
        ) : null}
      </div>

      {visible.length > 0 ? (
        <nav aria-label="Command Center" className="flex flex-wrap gap-1.5">
          {visible.map((item) => (
            <NavLink
              key={item.key}
              to={item.to}
              end
              className={({ isActive }) => cn(
                'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors',
                isActive
                  ? 'border-primary/30 bg-primary/10 text-primary'
                  : 'border-transparent text-muted-foreground hover:bg-muted hover:text-foreground',
              )}
            >
              <item.icon className="h-4 w-4" aria-hidden />
              {item.label}
            </NavLink>
          ))}
        </nav>
      ) : (
        <p className="text-sm text-muted-foreground">
          No views available for this persona with your current permissions.
        </p>
      )}
    </div>
  )
}

/**
 * What ACT can and cannot do to one agent, in the server's own words.
 *
 * The label is never composed here — it is `enforcement_display` verbatim, so a
 * GATEWAY_ENFORCED agent reads "ACT authorizes this agent's capability calls
 * that route through ACT's gateway" and never "Governed". The limit is shown
 * alongside it rather than tucked into a tooltip, because a claim without its
 * bound is the over-claim this milestone exists to prevent.
 */
export function GovernanceBadge({ signal }: { signal: GovernanceSignal }) {
  const a = affordancesFor(signal)
  return (
    <div className="space-y-1">
      <span
        className={cn(
          'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium',
          a.canContainAgent
            ? 'border-primary/30 bg-primary/10 text-primary'
            : 'border-muted-foreground/20 bg-muted text-muted-foreground',
        )}
      >
        {a.canContainAgent ? <ShieldCheck className="h-3 w-3" aria-hidden />
          : <Lock className="h-3 w-3" aria-hidden />}
        {signal.enforcement_mode}
      </span>
      <p className="text-xs text-foreground">{a.label}</p>
      <p className="text-xs text-muted-foreground">{a.limits}</p>
    </div>
  )
}

/**
 * Why an agent is shadow — never a bare badge.
 *
 * Phase 5.5 made shadow a *derived, disputable finding*: there is no `shadow`
 * column anywhere, and an agent is shadow exactly while it has an open
 * shadow-class posture finding. Rendering that as a lone red pill would throw
 * away the part that makes it actionable and contestable — the reason. So the
 * conditions are the component, and the badge is just its heading.
 */
export function ShadowReasons({ conditions }: { conditions: ShadowCondition[] }) {
  if (conditions.length === 0) return null
  return (
    <div className="space-y-1.5">
      <span className="inline-flex items-center gap-1.5 rounded-full border border-warning/30 bg-warning/10 px-2.5 py-0.5 text-xs font-medium text-warning">
        <EyeOff className="h-3 w-3" aria-hidden />
        Shadow · {conditions.length} {conditions.length === 1 ? 'condition' : 'conditions'}
      </span>
      <ul className="space-y-1">
        {conditions.map((c) => (
          <li key={c.finding_id} className="text-xs text-muted-foreground">
            <span className="font-mono text-foreground">{c.rule_id}</span>
            {' · '}{c.severity}{' · '}{c.reason}
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * An estate section the caller may not be permitted to see.
 *
 * The distinction this draws is the whole point: "you cannot see posture" and
 * "there are no posture findings" look identical if both render as 0, and the
 * second is the reassuring one. The server sends them as different shapes;
 * this renders them as different states.
 */
export function SectionGate<T>({ section, children }: {
  section: EstateSection<T>
  children: (data: T) => React.ReactNode
}) {
  if (!section.visible) {
    return (
      <Card>
        <CardContent className="flex items-start gap-2 p-4">
          <Lock className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">
            You do not have permission to view this section
            {' '}(<span className="font-mono text-xs">{section.permission}</span>).
            This is not a count of zero — the data exists and is hidden from you.
          </p>
        </CardContent>
      </Card>
    )
  }
  if (section.data === null) return null
  return <>{children(section.data)}</>
}

/**
 * A read that failed. Shows the failure rather than an empty state, because an
 * empty list and a broken backend look the same to an operator and only one of
 * them is safe to act on (§10).
 */
export function LoadError({ what, error }: { what: string; error: unknown }) {
  const message = (error as { message?: string })?.message
  return (
    <Card>
      <CardContent className="flex items-start gap-2 p-4" role="alert">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
        <div>
          <p className="text-sm font-medium text-foreground">Could not load {what}.</p>
          <p className="text-xs text-muted-foreground">
            {message ?? 'The request failed.'} This view is showing nothing rather than
            a result it cannot stand behind.
          </p>
        </div>
      </CardContent>
    </Card>
  )
}

/** A count tile. `value` is whatever the server said — including a phrase. */
export function Tile({ label, value, hint, tone = 'default' }: {
  label: string
  value: string
  hint?: string
  tone?: 'default' | 'warning' | 'destructive'
}) {
  return (
    <Card>
      <CardContent className="space-y-1 p-4" data-testid={`tile-${label}`}>
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className={cn(
          'text-2xl font-semibold',
          tone === 'destructive' ? 'text-destructive'
            : tone === 'warning' ? 'text-warning' : 'text-foreground',
        )}>{value}</p>
        {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  )
}
