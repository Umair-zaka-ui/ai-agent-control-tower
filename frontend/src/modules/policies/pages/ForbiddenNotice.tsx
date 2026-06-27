import { Link } from 'react-router-dom'
import { Lock } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ROUTES } from '@/constants/routes'

/** Shown when a role lacks permission for a policy management action. */
export function ForbiddenNotice() {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 py-24 text-center">
      <Lock className="h-7 w-7 text-muted-foreground" />
      <p className="text-sm text-muted-foreground">
        You don’t have permission to perform this action.
      </p>
      <Button variant="outline" asChild>
        <Link to={ROUTES.POLICIES}>Back to policies</Link>
      </Button>
    </div>
  )
}
