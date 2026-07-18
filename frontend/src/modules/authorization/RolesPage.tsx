import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, ShieldCheck, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { authorizationService } from '@/services'
import type { ApiError, ID, Permission, Role } from '@/types'

/**
 * Roles administration (Phase 4.3.1 §21, §22): search, filter by category, create a
 * custom role with a chosen permission set, and delete non-system roles.
 */
export function RolesPage() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [name, setName] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const roles = useQuery({
    queryKey: ['authz-roles', category],
    queryFn: () => authorizationService.listRoles({ category: category || undefined }),
  })
  const permissions = useQuery({
    queryKey: ['authz-permissions'],
    queryFn: () => authorizationService.listPermissions(),
  })

  const create = useMutation<Role, ApiError>({
    mutationFn: () =>
      authorizationService.createRole({
        name: name.trim(),
        category: 'CUSTOM',
        permissions: [...selected],
      }),
    onSuccess: () => {
      setName('')
      setSelected(new Set())
      void qc.invalidateQueries({ queryKey: ['authz-roles'] })
    },
  })

  const remove = useMutation<void, ApiError, ID>({
    mutationFn: (id) => authorizationService.deleteRole(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['authz-roles'] }),
  })

  const filtered = useMemo(() => {
    const rows = roles.data ?? []
    const q = search.trim().toLowerCase()
    return q
      ? rows.filter((r) => r.name.toLowerCase().includes(q) || (r.display_name ?? '').toLowerCase().includes(q))
      : rows
  }, [roles.data, search])

  const toggle = (code: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(code) ? next.delete(code) : next.add(code)
      return next
    })

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <PageHeader
        icon={ShieldCheck}
        title="Roles"
        description="Enterprise roles, permission sets, priority and category (Phase 4.3.1)."
        backTo={ROUTES.SETTINGS_SECURITY}
        backLabel="Security overview"
      />

      {/* Create */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Create a role</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 space-y-1">
              <Label htmlFor="role-name">Name</Label>
              <Input id="role-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="analyst" />
            </div>
            <Button
              onClick={() => name.trim() && !create.isPending && create.mutate()}
              disabled={!name.trim() || create.isPending}
            >
              {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Create
            </Button>
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">Permissions ({selected.size} selected)</Label>
            <div className="mt-1 flex max-h-40 flex-wrap gap-1.5 overflow-y-auto rounded-md border border-border p-2">
              {(permissions.data ?? []).map((p: Permission) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => toggle(p.code)}
                  className={`rounded px-2 py-0.5 text-xs ${
                    selected.has(p.code)
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted text-muted-foreground hover:bg-muted/70'
                  }`}
                >
                  {p.code}
                </button>
              ))}
            </div>
          </div>
          {create.isError && (
            <p className="text-xs text-destructive" role="alert">
              {create.error?.message ?? 'Could not create the role.'}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Filter */}
      <div className="flex flex-wrap items-center gap-3">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search roles…"
          className="max-w-xs"
        />
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
        >
          <option value="">All categories</option>
          {['SYSTEM', 'CUSTOM', 'ORGANIZATION', 'PROJECT', 'RESOURCE'].map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      {/* List */}
      <Card>
        <CardContent className="p-0">
          {roles.isLoading ? (
            <div className="flex justify-center p-6" role="status" aria-label="Loading">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : filtered.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No roles match.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="roles-list">
              {filtered.map((role) => (
                <li key={role.id} className="flex items-start justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <p className="flex items-center gap-2 text-sm font-medium text-foreground">
                      {role.is_system && <ShieldCheck className="h-4 w-4 text-primary" aria-label="system role" />}
                      <span>{role.display_name || role.name}</span>
                      <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
                        {role.category}
                      </span>
                      <span className="text-[10px] text-muted-foreground">priority {role.priority}</span>
                    </p>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      {role.permissions.length} permissions
                      {role.assignment_count != null ? ` · ${role.assignment_count} assigned` : ''} · {role.status}
                    </p>
                  </div>
                  {!role.is_system && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(role.id)}
                      aria-label={`Delete ${role.name}`}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      {remove.isError && (
        <p className="text-xs text-destructive" role="alert">
          {remove.error?.message ?? 'Could not delete the role.'}
        </p>
      )}
    </div>
  )
}
