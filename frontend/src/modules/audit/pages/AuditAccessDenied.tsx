import { Link } from 'react-router-dom'
import { ShieldX } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ROUTES } from '@/constants/routes'

/** Shown when a user without `audit.export` reaches a restricted audit surface. */
export function AuditAccessDenied({ surface }: { surface: string }) {
  return (
    <div role="alert" className="flex flex-col items-center justify-center gap-3 py-24 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <ShieldX className="h-6 w-6" aria-hidden />
      </span>
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">Access restricted</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          You don&apos;t have permission to view the {surface}. The{' '}
          <span className="font-mono text-xs">audit.export</span> permission is required.
        </p>
      </div>
      <Button variant="outline" asChild>
        <Link to={ROUTES.AUDIT}>Back to audit overview</Link>
      </Button>
    </div>
  )
}
