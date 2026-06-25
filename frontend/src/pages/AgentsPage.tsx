import { Bot } from 'lucide-react'

import { ComingSoon } from '@/components/common/ComingSoon'

export function AgentsPage() {
  return (
    <ComingSoon
      title="Agents"
      description="Register, monitor, and manage AI agents."
      icon={Bot}
      note="Agent management table, status controls and API-key issuance are wired here next."
    />
  )
}
