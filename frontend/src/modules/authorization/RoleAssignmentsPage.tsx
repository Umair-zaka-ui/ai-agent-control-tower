import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, Trash2, UserCog } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { adminSessionService } from '@/services/authService'
import { authorizationService } from '@/services'
import type { ApiError, AssignmentScope, ID, RoleAssignment } from '@/types'

const SCOPES: AssignmentScope[] = ['GLOBAL', 'ORGANIZATION', 'DEPARTMENT', 'TEAM', 'PROJECT', 'RESOURCE']

/** Assign scoped roles to users, list and revoke them (Phase 4.3.1 §14, §15, §22). */
export function RoleAssignmentsPage() {
  const qc = useQueryClient()
  const [userId, setUserId] = useState('')
  const [roleId, setRoleId] = useState('')
  const [scope, setScope] = useState<AssignmentScope>('GLOBAL')
  const [expiresAt, setExpiresAt] = useState('')

  const users = useQuery({ queryKey: ['org-users'], queryFn: () => adminSessionService.listUsers() })
  const roles = useQuery({ queryKey: ['authz-roles', ''], queryFn: () => authorizationService.listRoles() })
  const assignments = useQuery({
    queryKey: ['authz-assignments', userId],
    queryFn: () => authorizationService.listAssignments({ userId: userId || undefined }),
  })

  const assign = useMutation<RoleAssignment, ApiError>({
    mutationFn: () =>
      authorizationService.createAssignment({
        user_id: userId,
        role_id: roleId,
        scope,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      }),
    onSuccess: () => {
      setExpiresAt('')
      void qc.invalidateQueries({ queryKey: ['authz-assignments'] })
    },
  })
  const remove = useMutation<void, ApiError, ID>({
    mutationFn: (id) => authorizationService.deleteAssignment(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['authz-assignments'] }),
  })

  const roleName = (id: ID) => (roles.data ?? []).find((r) => r.id === id)?.name ?? id
  const userLabel = (id: ID) => {
    const u = (users.data ?? []).find((x) => x.id === id)
    return u ? u.email : id
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Role assignments</h1>
        <p className="text-sm text-muted-foreground">Grant a role to a user at a given scope (Phase 4.3.1).</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Assign a role</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="a-user">User</Label>
              <select id="a-user" value={userId} onChange={(e) => setUserId(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                <option value="">Select a user…</option>
                {(users.data ?? []).map((u) => (
                  <option key={u.id} value={u.id}>{u.email}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="a-role">Role</Label>
              <select id="a-role" value={roleId} onChange={(e) => setRoleId(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                <option value="">Select a role…</option>
                {(roles.data ?? []).filter((r) => r.is_assignable).map((r) => (
                  <option key={r.id} value={r.id}>{r.display_name || r.name}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="a-scope">Scope</Label>
              <select id="a-scope" value={scope} onChange={(e) => setScope(e.target.value as AssignmentScope)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                {SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="a-exp">Expires (optional)</Label>
              <Input id="a-exp" type="datetime-local" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} />
            </div>
          </div>
          <Button onClick={() => userId && roleId && !assign.isPending && assign.mutate()} disabled={!userId || !roleId || assign.isPending}>
            {assign.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Assign
          </Button>
          {assign.isError && (
            <p className="text-xs text-destructive" role="alert">{assign.error?.message ?? 'Could not assign the role.'}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><UserCog className="h-4 w-4" /> Assignments</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {assignments.isLoading ? (
            <div className="flex justify-center p-6" role="status" aria-label="Loading">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (assignments.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No assignments.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="assignments-list">
              {(assignments.data ?? []).map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-foreground">
                      <span className="font-medium">{roleName(a.role_id)}</span> → {userLabel(a.user_id)}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {a.scope}{a.expires_at ? ` · expires ${new Date(a.expires_at).toLocaleDateString()}` : ''}
                    </p>
                  </div>
                  <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate(a.id)} aria-label="Remove assignment">
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
