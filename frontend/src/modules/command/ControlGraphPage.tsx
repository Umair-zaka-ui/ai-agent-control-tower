import { useQuery } from '@tanstack/react-query'
import { Cable, Loader2 } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { Card, CardContent } from '@/components/ui'
import { commandCenterService } from '@/services'
import { CommandCenterNav, LoadError } from './components'

/**
 * Phase 5.8 — the Control Graph: what depends on what, and what an unapproved
 * MCP server can reach.
 *
 * Blast radius is read from 5.4's own traversal endpoint. Recomputing
 * reachability in the browser would be both a second graph implementation and
 * exactly the business-logic-in-React this phase forbids.
 */
export function ControlGraphPage() {
  const unapproved = useQuery({
    queryKey: ['cc-unapproved-mcp'],
    queryFn: () => commandCenterService.unapprovedMcp(),
  })
  const edges = useQuery({
    queryKey: ['cc-edges'],
    queryFn: () => commandCenterService.edges({ limit: 100 }),
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Cable}
        title="Control Graph"
        description="Dependencies and blast radius — what each agent reaches, and what an unapproved dependency would expose."
      />
      <CommandCenterNav />

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">Unapproved MCP exposure</h2>
        {unapproved.isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : unapproved.isError ? (
          <LoadError what="unapproved MCP exposure" error={unapproved.error} />
        ) : (
          <Card>
            <CardContent className="p-4">
              <pre className="overflow-x-auto text-xs text-muted-foreground">
                {JSON.stringify(unapproved.data, null, 2)}
              </pre>
            </CardContent>
          </Card>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">Edges</h2>
        {edges.isError ? (
          <LoadError what="graph edges" error={edges.error} />
        ) : (
          <Card>
            <CardContent className="p-4">
              <p className="text-xs text-muted-foreground">
                {(edges.data ?? []).length} active edges.
              </p>
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  )
}
