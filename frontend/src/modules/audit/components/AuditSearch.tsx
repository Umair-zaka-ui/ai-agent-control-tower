import { Search } from 'lucide-react'

import { Input } from '@/components/ui/input'

interface AuditSearchProps {
  value: string
  onChange: (value: string) => void
}

/** Debounced (by the page) search box for the audit explorer. */
export function AuditSearch({ value, onChange }: AuditSearchProps) {
  return (
    <div className="relative w-full sm:max-w-xs">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Search event ID, agent, user, resource…"
        aria-label="Search audit events"
        className="pl-9"
      />
    </div>
  )
}
