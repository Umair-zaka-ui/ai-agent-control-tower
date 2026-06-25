import type { LucideIcon } from 'lucide-react'

import { PageHeader } from './PageHeader'
import { EmptyState } from './EmptyState'

interface ComingSoonProps {
  title: string
  description: string
  icon: LucideIcon
  /** What this page will do once built out in Phase 3 Part 3. */
  note?: string
}

/**
 * Standard scaffold for pages whose full UI lands in Phase 3 Part 3. Keeps every
 * placeholder page consistent and avoids duplicated markup.
 */
export function ComingSoon({ title, description, icon, note }: ComingSoonProps) {
  return (
    <div className="space-y-6">
      <PageHeader title={title} description={description} />
      <EmptyState
        icon={icon}
        title="Coming in Phase 3 Part 3"
        description={note ?? 'This module is scaffolded. Its UI will be wired to the backend next.'}
      />
    </div>
  )
}
