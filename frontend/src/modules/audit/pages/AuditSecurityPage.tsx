import { AlertCircle, ArrowLeft, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'

import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { AuditTable, AuditTableSkeleton, SecurityPanel } from '../components'
import { useSecurityEvents } from '../hooks'
import { AuditAccessDenied } from './AuditAccessDenied'
import { canExportAudit } from '../utils/permissions'

export function AuditSecurityPage() {
  const { permissions } = useAuth()
  if (!canExportAudit(permissions)) return <AuditAccessDenied surface="security dashboard" />
  return <SecurityContent />
}

function SecurityContent() {
  const { data, isLoading, isError, isFetching, refetch } = useSecurityEvents()
  const recent = data?.recent ?? []

  return (
    <div className="space-y-6">
      <div>
        <Link
          to={ROUTES.AUDIT}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Audit overview
        </Link>
      </div>

      <PageHeader
        title="Security Dashboard"
        description="Failed logins, blocked agents, permission violations and critical alerts."
        actions={
          <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        }
      />

      {isError ? (
        <div role="alert" className="flex flex-col items-center gap-3 py-16 text-center">
          <AlertCircle className="h-6 w-6 text-destructive" />
          <p className="text-sm text-muted-foreground">Unable to load audit information.</p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            <RefreshCw className="h-4 w-4" />
            Retry
          </Button>
        </div>
      ) : (
        <>
          <SecurityPanel summary={data} loading={isLoading} />

          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle className="text-base">Recent Security Events</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {isLoading ? (
                <AuditTableSkeleton rows={6} />
              ) : recent.length === 0 ? (
                <p className="py-12 text-center text-sm text-muted-foreground">
                  No security events recorded.
                </p>
              ) : (
                <AuditTable events={recent} />
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
