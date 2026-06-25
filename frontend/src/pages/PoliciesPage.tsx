import { ShieldCheck } from 'lucide-react'

import { ComingSoon } from '@/components/common/ComingSoon'

export function PoliciesPage() {
  return (
    <ComingSoon
      title="Policies"
      description="Author and manage database-driven governance policies."
      icon={ShieldCheck}
      note="Policy list, condition builder and priority management land here next."
    />
  )
}
