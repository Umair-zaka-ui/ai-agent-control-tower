import { Users } from 'lucide-react'

import { ComingSoon } from '@/components/common/ComingSoon'

export function UsersPage() {
  return (
    <ComingSoon
      title="Users"
      description="Manage organization members and their roles."
      icon={Users}
      note="User directory, role assignment and RBAC management land here next."
    />
  )
}
