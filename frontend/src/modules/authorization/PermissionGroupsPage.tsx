import { useQuery } from '@tanstack/react-query'
import { Layers, Loader2 } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { authorizationService } from '@/services'

/** Permission groups (domains) — read-only catalog view (Phase 4.3.1 §12, §21). */
export function PermissionGroupsPage() {
  const groups = useQuery({
    queryKey: ['authz-permission-groups'],
    queryFn: () => authorizationService.listPermissionGroups(),
  })

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <PageHeader
        icon={Layers}
        title="Permission groups"
        description="Domains the permission catalog is organised by."
        backTo={ROUTES.AUTHZ_ROLES}
        backLabel="Authorization overview"
      />
      <Card>
        <CardContent className="p-0">
          {groups.isLoading ? (
            <div className="flex justify-center p-6" role="status" aria-label="Loading">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <ul className="divide-y divide-border" data-testid="permission-groups-list">
              {(groups.data ?? []).map((g) => (
                <li key={g.id} className="flex items-center justify-between gap-3 p-3">
                  <div>
                    <p className="text-sm font-medium text-foreground">{g.display_name}</p>
                    <p className="text-xs text-muted-foreground">{g.description ?? g.name}</p>
                  </div>
                  <span className="text-xs text-muted-foreground">#{g.sort_order}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
