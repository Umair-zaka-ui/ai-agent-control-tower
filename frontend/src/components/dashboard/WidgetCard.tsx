import type { ReactNode } from 'react'
import { AlertCircle, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/utils/cn'

interface WidgetCardProps {
  title: string
  /** Right-aligned header content (links, filters). */
  action?: ReactNode
  loading?: boolean
  error?: boolean
  isEmpty?: boolean
  emptyMessage?: string
  onRetry?: () => void
  className?: string
  contentClassName?: string
  children: ReactNode
}

/**
 * Shared dashboard widget shell. Centralises the enterprise loading / error /
 * empty states (SRS Part 3.1) so every widget renders them identically and we
 * never show empty white boxes.
 */
export function WidgetCard({
  title,
  action,
  loading,
  error,
  isEmpty,
  emptyMessage = 'No data yet.',
  onRetry,
  className,
  contentClassName,
  children,
}: WidgetCardProps) {
  return (
    <Card className={cn('flex flex-col', className)}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-base">{title}</CardTitle>
        {action}
      </CardHeader>
      <CardContent className={cn('flex-1', contentClassName)}>
        {loading ? (
          <div className="space-y-3" aria-busy="true">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-3/4" />
          </div>
        ) : error ? (
          <div
            role="alert"
            className="flex flex-col items-center justify-center gap-3 py-8 text-center"
          >
            <AlertCircle className="h-6 w-6 text-destructive" />
            <p className="text-sm text-muted-foreground">Unable to load {title.toLowerCase()}.</p>
            {onRetry ? (
              <Button variant="outline" size="sm" onClick={onRetry}>
                <RefreshCw className="h-4 w-4" />
                Retry
              </Button>
            ) : null}
          </div>
        ) : isEmpty ? (
          <p className="py-8 text-center text-sm text-muted-foreground">{emptyMessage}</p>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  )
}
