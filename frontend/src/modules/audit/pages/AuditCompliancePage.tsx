import { AlertCircle, ArrowLeft, Info, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'

import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { CompliancePanel } from '../components'
import { useComplianceSummary } from '../hooks'
import { AuditAccessDenied } from './AuditAccessDenied'
import { canExportAudit } from '../utils/permissions'

export function AuditCompliancePage() {
  const { permissions } = useAuth()
  if (!canExportAudit(permissions)) return <AuditAccessDenied surface="compliance dashboard" />
  return <ComplianceContent />
}

function ComplianceContent() {
  const { data, isLoading, isError, isFetching, refetch } = useComplianceSummary()

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
        title="Compliance Dashboard"
        description="HIPAA, SOC 2 and ISO 27001 readiness derived from policy, approval and audit coverage."
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
          <CompliancePanel summary={data} loading={isLoading} />
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Info className="h-3.5 w-3.5" aria-hidden />
            Readiness scores are informational, derived from current configuration coverage — not a
            formal certification.
          </p>
        </>
      )}
    </div>
  )
}
