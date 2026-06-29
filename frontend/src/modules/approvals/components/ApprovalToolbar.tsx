import { Download, History, RefreshCw, ShieldAlert } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { ROUTES } from '@/constants/routes'
import type { ApprovalListItem } from '../types'
import { exportApprovalsCsv } from '../utils/export'

interface ApprovalToolbarProps {
  approvals: ApprovalListItem[]
  refreshing?: boolean
  onRefresh: () => void
}

/** Page-level actions for the approval dashboard (refresh / export / nav). */
export function ApprovalToolbar({ approvals, refreshing, onRefresh }: ApprovalToolbarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" asChild>
        <Link to={`${ROUTES.APPROVALS}/escalations`}>
          <ShieldAlert className="h-4 w-4" />
          Escalations
        </Link>
      </Button>
      <Button variant="outline" size="sm" asChild>
        <Link to={`${ROUTES.APPROVALS}/history`}>
          <History className="h-4 w-4" />
          History
        </Link>
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={() => exportApprovalsCsv(approvals)}
        disabled={approvals.length === 0}
      >
        <Download className="h-4 w-4" />
        Export CSV
      </Button>
      <Button variant="outline" size="sm" onClick={onRefresh} disabled={refreshing}>
        <RefreshCw className="h-4 w-4" />
        Refresh
      </Button>
    </div>
  )
}
