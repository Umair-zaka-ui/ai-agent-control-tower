import { useQuery } from '@tanstack/react-query'

import { Label } from '@/components/ui/label'
import { resourceAuthzService } from '@/services'
import type { ID, ProtectedResource } from '@/types'

export function resourceLabel(r: ProtectedResource): string {
  return `${r.name ?? r.resource_id} (${r.resource_type})`
}

/**
 * Shared registry dropdown for the resource authorization pages (Phase 4.3.4 §20).
 * Lists what the caller may administer: their own resources, or every org
 * resource when they hold `resource.view`.
 */
export function ResourcePicker({
  value,
  onChange,
  id = 'resource-picker',
}: {
  value: ID | ''
  onChange: (id: ID) => void
  id?: string
}) {
  const resources = useQuery({ queryKey: ['resources'], queryFn: () => resourceAuthzService.resources() })
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>Resource</Label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
      >
        <option value="">Select a resource…</option>
        {(resources.data ?? []).map((r) => (
          <option key={r.id} value={r.id}>{resourceLabel(r)}</option>
        ))}
      </select>
    </div>
  )
}
