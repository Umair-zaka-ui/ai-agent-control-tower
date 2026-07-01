import { AlertCircle, RefreshCw, ShieldCheck, UserCog } from 'lucide-react'

import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/hooks/useAuth'
import { useNotifications } from '@/hooks/useNotifications'
import { apiErrorMessage } from '@/utils/error'
import { formatDate } from '@/utils/format'
import { IdentityStatusBadge } from '../components'
import {
  useIdentityDepartments,
  useIdentityRoles,
  useIdentityUsers,
  useSetUserActive,
} from '../hooks'
import { canManageIdentity, canViewIdentity } from '../utils/permissions'

export function IdentityPage() {
  const { permissions } = useAuth()
  const notify = useNotifications()
  const canView = canViewIdentity(permissions)
  const canManage = canManageIdentity(permissions)

  const users = useIdentityUsers()
  const departments = useIdentityDepartments()
  const roles = useIdentityRoles()
  const setActive = useSetUserActive()

  if (!canView) {
    return (
      <div role="alert" className="flex flex-col items-center justify-center gap-3 py-24 text-center">
        <ShieldCheck className="h-7 w-7 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          You don&apos;t have permission to view the identity directory (requires{' '}
          <span className="font-mono text-xs">user.view</span>).
        </p>
      </div>
    )
  }

  const rows = users.data ?? []

  const toggle = (id: string, active: boolean) =>
    setActive.mutate(
      { id, active },
      {
        onSuccess: () => notify.success(active ? 'Identity activated' : 'Identity suspended'),
        onError: (e) => notify.error('Action failed', apiErrorMessage(e)),
      },
    )

  return (
    <div className="space-y-6">
      <PageHeader
        title="Identity Platform"
        description="Every human, agent, service account and organization as a formal identity (Phase 4 foundation)."
        actions={
          <Button variant="outline" size="sm" onClick={() => void users.refetch()} disabled={users.isFetching}>
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Users" value={rows.length} />
        <StatCard label="Departments" value={departments.data?.length ?? 0} />
        <StatCard label="Roles" value={roles.data?.length ?? 0} />
        <StatCard label="Active" value={rows.filter((u) => u.is_active).length} />
      </div>

      <Card className="overflow-hidden">
        <CardHeader className="flex-row items-center gap-2 space-y-0">
          <UserCog className="h-4 w-4 text-primary" />
          <CardTitle className="text-base">Human Identities</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {users.isLoading ? (
            <p className="py-12 text-center text-sm text-muted-foreground">Loading identities…</p>
          ) : users.isError ? (
            <div role="alert" className="flex flex-col items-center gap-3 py-12 text-center">
              <AlertCircle className="h-6 w-6 text-destructive" />
              <p className="text-sm text-muted-foreground">Unable to load identities.</p>
              <Button variant="outline" size="sm" onClick={() => void users.refetch()}>
                Retry
              </Button>
            </div>
          ) : rows.length === 0 ? (
            <div className="py-10">
              <EmptyState icon={UserCog} title="No identities yet" description="Human identities will appear here." />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Identity</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  {canManage && <TableHead className="text-right">Actions</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell className="font-medium">{u.display_name}</TableCell>
                    <TableCell className="text-muted-foreground">{u.email}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{u.role}</Badge>
                    </TableCell>
                    <TableCell>
                      <IdentityStatusBadge active={u.is_active} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">{formatDate(u.created_at)}</TableCell>
                    {canManage && (
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={setActive.isPending}
                          onClick={() => toggle(u.id, !u.is_active)}
                        >
                          {u.is_active ? 'Suspend' : 'Activate'}
                        </Button>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <Card className="flex flex-col gap-1 p-4">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
    </Card>
  )
}
