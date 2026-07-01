import { Badge, type BadgeProps } from '@/components/ui/badge'

/** Active/inactive badge for a human identity. */
export function IdentityStatusBadge({ active }: { active: boolean }) {
  const variant: BadgeProps['variant'] = active ? 'success' : 'secondary'
  return <Badge variant={variant}>{active ? 'Active' : 'Suspended'}</Badge>
}
