import { ScrollText } from 'lucide-react'

import { ComingSoon } from '@/components/common/ComingSoon'

export function AuditPage() {
  return (
    <ComingSoon
      title="Audit"
      description="Every AI decision, immutably recorded and searchable."
      icon={ScrollText}
      note="The forensic audit timeline, filters and exports are wired here next."
    />
  )
}
