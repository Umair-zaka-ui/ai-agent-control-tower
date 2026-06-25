import { Search } from 'lucide-react'

import { Input } from '@/components/ui/input'

interface AgentSearchProps {
  value: string
  onChange: (value: string) => void
}

/**
 * Search box for the agents table. Emits raw input immediately; the page
 * debounces it (300ms) before issuing the query.
 */
export function AgentSearch({ value, onChange }: AgentSearchProps) {
  return (
    <div className="relative w-full sm:max-w-xs">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Search name, type, owner, ID…"
        aria-label="Search agents"
        className="pl-9"
      />
    </div>
  )
}
