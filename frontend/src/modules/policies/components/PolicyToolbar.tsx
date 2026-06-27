import { useNavigate } from 'react-router-dom'
import { Download, LayoutTemplate, Plus, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ROUTES } from '@/constants/routes'
import type { Policy } from '../types'
import { exportPoliciesCsv } from '../utils/export'

interface PolicyToolbarProps {
  policies: Policy[]
  refreshing?: boolean
  canManage: boolean
  onRefresh: () => void
}

export function PolicyToolbar({ policies, refreshing, canManage, onRefresh }: PolicyToolbarProps) {
  const navigate = useNavigate()

  return (
    <div className="flex flex-wrap items-center gap-2">
      {canManage && (
        <Button onClick={() => navigate(`${ROUTES.POLICIES}/new`)}>
          <Plus className="h-4 w-4" />
          Create Policy
        </Button>
      )}
      <Button variant="outline" onClick={() => navigate(`${ROUTES.POLICIES}/templates`)}>
        <LayoutTemplate className="h-4 w-4" />
        Templates
      </Button>
      <Button variant="outline" onClick={onRefresh} disabled={refreshing}>
        <RefreshCw className="h-4 w-4" />
        Refresh
      </Button>
      <Button variant="outline" disabled={policies.length === 0} onClick={() => exportPoliciesCsv(policies)}>
        <Download className="h-4 w-4" />
        Export CSV
      </Button>
    </div>
  )
}
