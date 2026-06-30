import { Download, RefreshCw, ScrollText, ShieldAlert, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { ROUTES } from '@/constants/routes'

interface AuditToolbarProps {
  refreshing?: boolean
  onRefresh: () => void
  /** Whether to surface the export / security / compliance links (audit.export). */
  canExport?: boolean
}

/** Page-level actions for the audit dashboard (SRS §Audit Dashboard). */
export function AuditToolbar({ refreshing, onRefresh, canExport }: AuditToolbarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" asChild>
        <Link to={`${ROUTES.AUDIT}/events`}>
          <ScrollText className="h-4 w-4" />
          Events
        </Link>
      </Button>
      {canExport && (
        <>
          <Button variant="outline" size="sm" asChild>
            <Link to={`${ROUTES.AUDIT}/security`}>
              <ShieldAlert className="h-4 w-4" />
              Security
            </Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link to={`${ROUTES.AUDIT}/compliance`}>
              <ShieldCheck className="h-4 w-4" />
              Compliance
            </Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link to={`${ROUTES.AUDIT}/export`}>
              <Download className="h-4 w-4" />
              Export
            </Link>
          </Button>
        </>
      )}
      <Button variant="outline" size="sm" onClick={onRefresh} disabled={refreshing}>
        <RefreshCw className="h-4 w-4" />
        Refresh
      </Button>
    </div>
  )
}
