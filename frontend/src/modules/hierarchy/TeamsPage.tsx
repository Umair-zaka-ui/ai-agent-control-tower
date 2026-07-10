import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, Trash2, Users } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { hierarchyService } from '@/services'
import type { ApiError, ID } from '@/types'

/** Teams — belong to a department (Phase 4.3.3 §5). */
export function TeamsPage() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [deptId, setDeptId] = useState('')

  const teams = useQuery({ queryKey: ['teams'], queryFn: () => hierarchyService.teams() })
  const departments = useQuery({ queryKey: ['departments'], queryFn: () => hierarchyService.departments() })

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['teams'] })
    void qc.invalidateQueries({ queryKey: ['hierarchy-tree'] })
  }
  const create = useMutation<unknown, ApiError>({
    mutationFn: () => hierarchyService.createTeam({ name: name.trim(), department_id: deptId }),
    onSuccess: () => { setName(''); invalidate() },
  })
  const remove = useMutation<unknown, ApiError, ID>({
    mutationFn: (id) => hierarchyService.deleteTeam(id),
    onSuccess: invalidate,
  })
  const deptName = (id: ID) => departments.data?.find((d) => d.id === id)?.name ?? ''

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Teams</h1>
        <p className="text-sm text-muted-foreground">Teams within your departments.</p>
      </div>
      <Card>
        <CardHeader><CardTitle className="text-base">Add a team</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 space-y-1">
              <Label htmlFor="t-name">Name</Label>
              <Input id="t-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="AI Operations" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="t-dept">Department</Label>
              <select id="t-dept" value={deptId} onChange={(e) => setDeptId(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                <option value="">Select…</option>
                {(departments.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <Button onClick={() => name.trim() && deptId && !create.isPending && create.mutate()} disabled={!name.trim() || !deptId || create.isPending}>
              {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Add
            </Button>
          </div>
          {create.isError && <p className="text-xs text-destructive">{create.error?.message ?? 'Could not create.'}</p>}
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-0">
          {teams.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (teams.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No teams yet.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="teams-list">
              {(teams.data ?? []).map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-3 p-3">
                  <span className="flex items-center gap-2 text-sm text-foreground">
                    <Users className="h-4 w-4 text-muted-foreground" />{t.name}
                    <span className="text-xs text-muted-foreground">· {deptName(t.department_id)}</span>
                  </span>
                  <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate(t.id)} aria-label={`Delete ${t.name}`}>
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
