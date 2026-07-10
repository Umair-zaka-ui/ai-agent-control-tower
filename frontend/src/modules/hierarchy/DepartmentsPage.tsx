import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, Trash2, Users } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { hierarchyService } from '@/services'
import type { ApiError, ID } from '@/types'

/** Departments — belong to the org, optionally grouped under a business unit (§5). */
export function DepartmentsPage() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [buId, setBuId] = useState('')

  const departments = useQuery({ queryKey: ['departments'], queryFn: () => hierarchyService.departments() })
  const units = useQuery({ queryKey: ['business-units'], queryFn: () => hierarchyService.businessUnits() })

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['departments'] })
    void qc.invalidateQueries({ queryKey: ['hierarchy-tree'] })
  }
  const create = useMutation<unknown, ApiError>({
    mutationFn: () => hierarchyService.createDepartment({ name: name.trim(), business_unit_id: buId || null }),
    onSuccess: () => { setName(''); invalidate() },
  })
  const remove = useMutation<unknown, ApiError, ID>({
    mutationFn: (id) => hierarchyService.deleteDepartment(id),
    onSuccess: invalidate,
  })

  const buName = (id: ID | null) => (id ? units.data?.find((u) => u.id === id)?.name ?? '' : '')

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Departments</h1>
        <p className="text-sm text-muted-foreground">Departments in your organization.</p>
      </div>
      <Card>
        <CardHeader><CardTitle className="text-base">Add a department</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 space-y-1">
              <Label htmlFor="d-name">Name</Label>
              <Input id="d-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Radiology" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="d-bu">Business unit (optional)</Label>
              <select id="d-bu" value={buId} onChange={(e) => setBuId(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                <option value="">—</option>
                {(units.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
            </div>
            <Button onClick={() => name.trim() && !create.isPending && create.mutate()} disabled={!name.trim() || create.isPending}>
              {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Add
            </Button>
          </div>
          {create.isError && <p className="text-xs text-destructive">{create.error?.message ?? 'Could not create.'}</p>}
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-0">
          {departments.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (departments.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No departments yet.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="departments-list">
              {(departments.data ?? []).map((d) => (
                <li key={d.id} className="flex items-center justify-between gap-3 p-3">
                  <span className="flex items-center gap-2 text-sm text-foreground">
                    <Users className="h-4 w-4 text-muted-foreground" />{d.name}
                    {d.business_unit_id && <span className="text-xs text-muted-foreground">· {buName(d.business_unit_id)}</span>}
                  </span>
                  <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate(d.id)} aria-label={`Delete ${d.name}`}>
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
