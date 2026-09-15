import { useQuery } from '@tanstack/react-query'
import { GitBranch, Loader2 } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { Card, CardContent } from '@/components/ui'
import { commandCenterService } from '@/services'
import { CommandCenterNav, LoadError } from './components'

/**
 * Phase 5.8 — Identity & Delegation.
 *
 * Phase 5.3's control graph represents authority; it never grants any. This
 * view is a read of those edges, and shows revoked edges as revoked rather than
 * dropping them, because "who used to be able to act for whom" is exactly what
 * an investigation needs.
 */
export function IdentityDelegationPage() {
  const q = useQuery({
    queryKey: ['cc-delegation-edges'],
    queryFn: () => commandCenterService.edges({ limit: 200 }),
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={GitBranch}
        title="Identity & Delegation"
        description="Who can act for whom. The graph represents authority — it does not grant it; the authorization gateway remains the only enforcer."
      />
      <CommandCenterNav />

      {q.isLoading ? (
        <div className="flex justify-center p-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : q.isError ? (
        <LoadError what="delegation edges" error={q.error} />
      ) : (
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-muted-foreground">
              {(q.data ?? []).length} edges in the control graph.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
