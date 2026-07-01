import { Badge } from '@/components/ui/badge'
import { cn } from '@/utils/cn'
import { humanizeToken } from '../utils/format'

/** Category → accent colour. Categories mirror the backend audit_view. */
const CATEGORY_TONE: Record<string, string> = {
  AUTHENTICATION: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
  AGENT: 'bg-primary/15 text-primary',
  API_KEY: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
  POLICY: 'bg-indigo-500/15 text-indigo-600 dark:text-indigo-400',
  APPROVAL: 'bg-purple-500/15 text-purple-600 dark:text-purple-400',
  ADMINISTRATION: 'bg-teal-500/15 text-teal-600 dark:text-teal-400',
  CONFIGURATION: 'bg-secondary text-secondary-foreground',
  SECURITY: 'bg-destructive/15 text-destructive',
}

interface EventTypeBadgeProps {
  eventType: string
  category?: string
}

/** Coloured pill for an event type, tinted by its category. */
export function EventTypeBadge({ eventType, category }: EventTypeBadgeProps) {
  const tone = (category && CATEGORY_TONE[category]) || 'bg-muted text-muted-foreground'
  return (
    <Badge variant="outline" className={cn('border-transparent font-medium', tone)}>
      {humanizeToken(eventType)}
    </Badge>
  )
}
