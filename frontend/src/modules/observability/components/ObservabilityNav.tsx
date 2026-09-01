import { useState } from 'react'
import { NavLink } from 'react-router-dom'

import { usePermissions } from '@/authorization'
import { Select } from '@/components/ui'
import { cn } from '@/utils/cn'
import {
  PERSONAS, loadPersona, savePersona, viewsForPersona,
  type PersonaId,
} from '../personas'

/**
 * Phase 4.9 — navigation across the Observability Center, with the persona lens.
 *
 * Two filters compose: a link is shown only if the user *can* use it (server
 * still enforces — this is courtesy) AND it belongs to the persona the operator
 * has selected. "All views" is the default and shows everything permitted.
 * Switching persona never changes what the server allows; it only changes what
 * is on screen. The choice is a per-browser convenience in `localStorage`.
 */
export function ObservabilityNav() {
  const { can } = usePermissions()
  const [persona, setPersona] = useState<PersonaId | 'all'>(() => loadPersona())

  const visible = viewsForPersona(persona).filter((v) => can(v.permission))

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="obs-persona" className="text-xs font-medium text-muted-foreground">
          Viewing as
        </label>
        <Select
          id="obs-persona"
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
        <nav aria-label="Observability Center" className="flex flex-wrap gap-1.5">
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
