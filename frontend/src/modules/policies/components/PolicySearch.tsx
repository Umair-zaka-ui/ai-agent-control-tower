import { Search } from 'lucide-react'

import { Input } from '@/components/ui/input'

interface PolicySearchProps {
  value: string
  onChange: (value: string) => void
}

/** Debounced (by the page) search box for the policies table. */
export function PolicySearch({ value, onChange }: PolicySearchProps) {
  return (
    <div className="relative w-full sm:max-w-xs">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Search name, resource, action…"
        aria-label="Search policies"
        className="pl-9"
      />
    </div>
  )
}
