import { PageHeader } from '@/components/common/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ROLE_LABELS } from '@/constants/roles'
import { useAuth } from '@/hooks/useAuth'

/** Profile page — shows the signed-in user's identity from the auth context. */
export function ProfilePage() {
  const { user } = useAuth()

  return (
    <div className="space-y-6">
      <PageHeader title="Profile" description="Your account details." />
      <Card className="max-w-xl">
        <CardHeader>
          <CardTitle>Account</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Name</span>
            <span className="font-medium">{user?.full_name ?? '—'}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Email</span>
            <span className="font-medium">{user?.email ?? '—'}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Role</span>
            {user ? <Badge>{ROLE_LABELS[user.role]}</Badge> : <span>—</span>}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
