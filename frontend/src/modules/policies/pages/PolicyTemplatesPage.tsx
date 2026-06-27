import { Link, useNavigate } from 'react-router-dom'
import { AlertCircle, ArrowLeft, RefreshCw } from 'lucide-react'

import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { PolicyTemplateGallery } from '../components'
import { usePolicyTemplates } from '../hooks'
import type { PolicyBuilderInitial } from '../components'
import type { PolicyTemplate } from '../types'
import { canManagePolicies } from '../utils/permissions'

export function PolicyTemplatesPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const canManage = canManagePolicies(user?.role)
  const { data, isLoading, isError, refetch } = usePolicyTemplates()

  const templates = data ?? []

  const handleUse = (template: PolicyTemplate) => {
    const initial: Partial<PolicyBuilderInitial> = {
      name: template.name,
      description: template.description,
      severity: template.severity,
      resource: template.resource,
      action: template.action,
      conditionsText: JSON.stringify(template.conditions ?? {}, null, 2),
      decision: template.decision,
    }
    navigate(`${ROUTES.POLICIES}/new`, { state: { initial } })
  }

  return (
    <div className="space-y-6">
      <Link
        to={ROUTES.POLICIES}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        All policies
      </Link>

      <PageHeader
        title="Policy Templates"
        description="Start from a curated governance template and customize it for your organization."
      />

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-44 animate-pulse rounded-lg border border-border bg-card/40" />
          ))}
        </div>
      ) : isError ? (
        <div role="alert" className="flex flex-col items-center gap-3 py-16 text-center">
          <AlertCircle className="h-6 w-6 text-destructive" />
          <p className="text-sm text-muted-foreground">Unable to load templates.</p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            <RefreshCw className="h-4 w-4" />
            Retry
          </Button>
        </div>
      ) : (
        <PolicyTemplateGallery templates={templates} canManage={canManage} onUse={handleUse} />
      )}
    </div>
  )
}
