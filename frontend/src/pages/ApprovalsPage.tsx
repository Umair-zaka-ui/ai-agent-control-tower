import { CheckSquare } from 'lucide-react'

import { ComingSoon } from '@/components/common/ComingSoon'

export function ApprovalsPage() {
  return (
    <ComingSoon
      title="Approvals"
      description="Review, approve or reject AI actions awaiting human sign-off."
      icon={CheckSquare}
      note="The approval queue, comment threads and SLA tracking are wired here next."
    />
  )
}
