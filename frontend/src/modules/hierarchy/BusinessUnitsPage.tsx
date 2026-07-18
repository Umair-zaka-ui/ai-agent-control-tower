import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Network, Plus, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { hierarchyService } from '@/services'
import type { ApiError, ID } from '@/types'

/** Business units — a division inside the organization (Phase 4.3.3 §5, §16). */
export function BusinessUnitsPage() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const units = useQuery({ queryKey: ['business-units'], queryFn: () => hierarchyService.businessUnits() })

  const create = useMutation<unknown, ApiError>({
    mutationFn: () => hierarchyService.createBusinessUnit(name.trim()),
    onSuccess: () => {
      setName('')
      void qc.invalidateQueries({ queryKey: ['business-units'] })
      void qc.invalidateQueries({ queryKey: ['hierarchy-tree'] })
    },
  })
  const remove = useMutation<unknown, ApiError, ID>({
    mutationFn: (id) => hierarchyService.deleteBusinessUnit(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['business-units'] })
      void qc.invalidateQueries({ queryKey: ['hierarchy-tree'] })
    },
  })

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <PageHeader
        icon={Network}
        title="Business units"
        description="Divisions inside your organization."
        backTo={ROUTES.ORG_EXPLORER}
        backLabel="Organization overview"
      />
      <Card>
        <CardHeader><CardTitle className="text-base">Add a business unit</CardTitle></CardHeader>
        <CardContent>
          <form className="flex items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (name.trim() && !create.isPending) create.mutate() }}>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Healthcare" className="flex-1" />
            <Button type="submit" disabled={!name.trim() || create.isPending}>
              {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Add
            </Button>
          </form>
          {create.isError && <p className="mt-2 text-xs text-destructive">{create.error?.message ?? 'Could not create.'}</p>}
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-0">
          {units.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (units.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No business units yet.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="business-units-list">
              {(units.data ?? []).map((u) => (
                <li key={u.id} className="flex items-center justify-between gap-3 p-3">
                  <span className="flex items-center gap-2 text-sm text-foreground"><Network className="h-4 w-4 text-muted-foreground" />{u.name}</span>
                  <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate(u.id)} aria-label={`Delete ${u.name}`}>
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      {remove.isError && <p className="text-xs text-destructive">{remove.error?.message ?? 'Could not delete.'}</p>}
    </div>
  )
}
