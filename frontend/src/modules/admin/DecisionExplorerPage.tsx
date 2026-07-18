import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, SearchCode } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { adminService } from '@/services'
import type { AuthorizationDecisionRow, ID } from '@/types'
import { AdminNav } from './components/AdminNav'

/** §13 — investigate why authorization decisions were made. */
export function DecisionExplorerPage() {
  const [permission, setPermission] = useState('')
  const [allowed, setAllowed] = useState<'' | 'true' | 'false'>('')
  const [applied, setApplied] = useState<{ permission?: string; allowed?: boolean }>({})
  const [openId, setOpenId] = useState<ID | null>(null)

  const decisions = useQuery({
    queryKey: ['admin-decisions', applied],
    queryFn: () => adminService.decisions(applied),
  })

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <PageHeader
        icon={SearchCode}
        title="Decision explorer"
        description="Searchable history of every authorization decision. Viewing is audited."
        backTo={ROUTES.ADMIN_DASHBOARD}
        backLabel="Administration overview"
      />
      <AdminNav />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <SearchCode className="h-4 w-4" /> Filters
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground" htmlFor="perm-filter">
              Permission
            </label>
            <Input id="perm-filter" value={permission} placeholder="e.g. policy.create"
                   onChange={(e) => setPermission(e.target.value)} className="w-56" />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground" htmlFor="decision-filter">
              Decision
            </label>
            <select id="decision-filter" value={allowed}
                    onChange={(e) => setAllowed(e.target.value as typeof allowed)}
                    className="block rounded-md border border-border bg-background px-2 py-1.5 text-sm">
              <option value="">All</option>
              <option value="true">Allowed</option>
              <option value="false">Denied</option>
            </select>
          </div>
          <Button size="sm"
                  onClick={() => setApplied({
                    permission: permission || undefined,
                    allowed: allowed === '' ? undefined : allowed === 'true',
                  })}>
            Search
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {decisions.isLoading ? (
            <div className="flex justify-center p-6">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (decisions.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No decisions match the filters.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="decision-list">
              {(decisions.data ?? []).map((row: AuthorizationDecisionRow) => (
                <li key={row.id} className="p-3">
                  <button type="button"
                          className="flex w-full items-center justify-between gap-3 text-left"
                          onClick={() => setOpenId(openId === row.id ? null : row.id)}>
                    <div className="min-w-0">
                      <p className="truncate text-sm text-foreground">{row.permission}</p>
                      <p className="text-xs text-muted-foreground">
                        {new Date(row.created_at).toLocaleString()}
                        {row.evaluation_time_ms != null
                          ? ` · ${row.evaluation_time_ms.toFixed(1)}ms` : ''}
                        {row.source_role ? ` · ${row.source_role}` : ''}
                      </p>
                    </div>
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                      row.allowed
                        ? 'bg-emerald-500/15 text-emerald-500'
                        : 'bg-red-500/15 text-red-500'}`}>
                      {row.allowed ? 'ALLOW' : 'DENY'}
                    </span>
                  </button>
                  {openId === row.id && (
                    <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-muted p-2 text-xs"
                         data-testid="decision-detail">
                      {JSON.stringify({
                        reason: row.reason, scope: row.scope,
                        identity_id: row.identity_id,
                        resource: row.resource_type
                          ? `${row.resource_type}:${row.resource_id}` : null,
                        request_id: row.request_id,
                      }, null, 2)}
                    </pre>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
