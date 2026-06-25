import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { ErrorLayout } from '@/layouts/ErrorLayout'
import { ROUTES } from '@/constants/routes'

export function NotFoundPage() {
  return (
    <ErrorLayout>
      <div className="space-y-3">
        <p className="text-5xl font-semibold text-foreground">404</p>
        <p className="text-sm text-muted-foreground">
          The page you’re looking for doesn’t exist or has moved.
        </p>
      </div>
      <Button asChild>
        <Link to={ROUTES.DASHBOARD}>Back to dashboard</Link>
      </Button>
    </ErrorLayout>
  )
}
