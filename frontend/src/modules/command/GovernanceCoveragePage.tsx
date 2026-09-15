import { useQuery } from '@tanstack/react-query'
import { Landmark, Loader2 } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { commandCenterService } from '@/services'
import { CommandCenterNav, LoadError, Tile } from './components'

/**
 * Phase 5.8 — Governance Coverage.
 *
 * The one number an executive asks for — "how much of our AI is actually
 * governed" — stated in the only way that is true: governed means ACT runs and
 * enforces the agent, and everything else is counted separately rather than
 * rounded into the same bucket. Coverage is a ratio of real counts, not a
 * score, so there is nothing here to tune.
 */
export function GovernanceCoveragePage() {
  const q = useQuery({
    queryKey: ['cc-estate'],
    queryFn: () => commandCenterService.estate(),
  })
  const a = q.data?.agents

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Landmark}
        title="Governance Coverage"
        description="How much of this estate ACT actually governs — and how much it only observes."
      />
      <CommandCenterNav />

      {q.isLoading ? (
        <div className="flex justify-center p-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : q.isError ? (
        <LoadError what="governance coverage" error={q.error} />
      ) : a ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Tile
              label="Coverage"
              value={a.total > 0 ? `${Math.round((a.governed / a.total) * 100)}%` : 'no agents'}
              hint="Agents ACT runs and enforces"
            />
            <Tile label="Governed" value={String(a.governed)} />
            <Tile label="Not governed" value={String(a.ungoverned)}
                  tone={a.ungoverned > 0 ? 'warning' : 'default'} />
            <Tile label="Unowned" value={String(a.unowned)}
                  tone={a.unowned > 0 ? 'warning' : 'default'} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(a.by_enforcement_mode).map(([mode, count]) => (
              <Tile key={mode} label={mode} value={String(count)} />
            ))}
          </div>
        </>
      ) : null}
    </div>
  )
}
