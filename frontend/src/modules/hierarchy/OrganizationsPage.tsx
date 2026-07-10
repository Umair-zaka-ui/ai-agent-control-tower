import { useQuery } from '@tanstack/react-query'
import { Building2, Loader2 } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { hierarchyService } from '@/services'

/**
 * Organizations (Phase 4.3.3 §5). Shows the caller's own organization plus any into
 * which they hold a delegation — never every tenant (isolation §9).
 */
export function OrganizationsPage() {
  const orgs = useQuery({ queryKey: ['organizations'], queryFn: () => hierarchyService.organizations() })

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Organizations</h1>
        <p className="text-sm text-muted-foreground">
          Your organization and any you administer by delegation.
        </p>
      </div>
      <Card>
        <CardContent className="p-0">
          {orgs.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (
            <ul className="divide-y divide-border" data-testid="organizations-list">
              {(orgs.data ?? []).map((o) => (
                <li key={o.id} className="flex items-center justify-between gap-3 p-3">
                  <span className="flex items-center gap-2 text-sm text-foreground">
                    <Building2 className="h-4 w-4 text-muted-foreground" />
                    {o.name}
                    {o.slug && <span className="text-xs text-muted-foreground">/{o.slug}</span>}
                  </span>
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
                    {o.status}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
