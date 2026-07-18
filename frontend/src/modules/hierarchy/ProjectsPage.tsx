import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderKanban, Loader2, Plus, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { hierarchyService } from '@/services'
import type { ApiError, ID } from '@/types'

/** Projects — belong to a team; resources belong to a project (§5, §6). */
export function ProjectsPage() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [teamId, setTeamId] = useState('')

  const projects = useQuery({ queryKey: ['projects'], queryFn: () => hierarchyService.projects() })
  const teams = useQuery({ queryKey: ['teams'], queryFn: () => hierarchyService.teams() })

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['projects'] })
    void qc.invalidateQueries({ queryKey: ['hierarchy-tree'] })
  }
  const create = useMutation<unknown, ApiError>({
    mutationFn: () => hierarchyService.createProject({ name: name.trim(), team_id: teamId }),
    onSuccess: () => { setName(''); invalidate() },
  })
  const remove = useMutation<unknown, ApiError, ID>({
    mutationFn: (id) => hierarchyService.deleteProject(id),
    onSuccess: invalidate,
  })
  const teamName = (id: ID) => teams.data?.find((t) => t.id === id)?.name ?? ''

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <PageHeader
        icon={FolderKanban}
        title="Projects"
        description="Projects within your teams."
        backTo={ROUTES.ORG_EXPLORER}
        backLabel="Organization overview"
      />
      <Card>
        <CardHeader><CardTitle className="text-base">Add a project</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 space-y-1">
              <Label htmlFor="p-name">Name</Label>
              <Input id="p-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Medical AI" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="p-team">Team</Label>
              <select id="p-team" value={teamId} onChange={(e) => setTeamId(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                <option value="">Select…</option>
                {(teams.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </div>
            <Button onClick={() => name.trim() && teamId && !create.isPending && create.mutate()} disabled={!name.trim() || !teamId || create.isPending}>
              {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Add
            </Button>
          </div>
          {create.isError && <p className="text-xs text-destructive">{create.error?.message ?? 'Could not create.'}</p>}
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-0">
          {projects.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (projects.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No projects yet.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="projects-list">
              {(projects.data ?? []).map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-3 p-3">
                  <span className="flex items-center gap-2 text-sm text-foreground">
                    <FolderKanban className="h-4 w-4 text-muted-foreground" />{p.name}
                    <span className="text-xs text-muted-foreground">· {teamName(p.team_id)}</span>
                  </span>
                  <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate(p.id)} aria-label={`Delete ${p.name}`}>
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
