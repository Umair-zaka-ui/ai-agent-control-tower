import { useMemo, useState } from 'react'
import { ArrowLeft, Download, ScrollText } from 'lucide-react'
import { Link } from 'react-router-dom'

import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useNotifications } from '@/hooks/useNotifications'
import { apiErrorMessage } from '@/utils/error'
import {
  AuditFilters,
  type AuditFilterValues,
  AuditSearch,
  AuditTable,
  AuditTableSkeleton,
  ExportDialog,
} from '../components'
import { useAudit, useAuditEventTypes, useExportAudit } from '../hooks'
import { AuditAccessDenied } from './AuditAccessDenied'
import { AUDIT_PAGE_SIZE, SEARCH_DEBOUNCE_MS } from '../utils/constants'
import type { ExportFormat } from '../utils/export'
import { canExportAudit } from '../utils/permissions'

export function AuditExportPage() {
  const { permissions } = useAuth()
  if (!canExportAudit(permissions)) return <AuditAccessDenied surface="export center" />
  return <ExportContent />
}

function ExportContent() {
  const notify = useNotifications()
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search, SEARCH_DEBOUNCE_MS)
  const [filters, setFilters] = useState<AuditFilterValues>({})
  const [dialogOpen, setDialogOpen] = useState(false)

  const { data: catalog } = useAuditEventTypes()
  const eventTypeOptions = useMemo(
    () => (catalog ?? []).map((c) => ({ value: c.value, label: c.label })),
    [catalog],
  )

  const params = useMemo(
    () => ({ search: debouncedSearch.trim() || undefined, ...filters }),
    [debouncedSearch, filters],
  )

  // Preview the first page so the user can see what their filters select.
  const preview = useAudit({ ...params, limit: AUDIT_PAGE_SIZE, offset: 0 })
  const previewEvents = preview.data ?? []

  const { exportAudit, isExporting } = useExportAudit()

  const handleExport = (format: ExportFormat) => {
    exportAudit(format, params)
      .then((count) => {
        notify.success(`Exported ${count} event${count === 1 ? '' : 's'} as ${format.toUpperCase()}`)
        setDialogOpen(false)
      })
      .catch((e) => notify.error('Export failed', apiErrorMessage(e)))
  }

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
        title="Export Center"
        description="Apply filters, preview the selection, then export the matching audit events."
        actions={
          <Button size="sm" onClick={() => setDialogOpen(true)} disabled={previewEvents.length === 0}>
            <Download className="h-4 w-4" />
            Export
          </Button>
        }
      />

      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <AuditSearch value={search} onChange={setSearch} />
        <AuditFilters value={filters} onChange={setFilters} eventTypeOptions={eventTypeOptions} />
      </div>

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle className="text-base">Preview</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {preview.isLoading ? (
            <AuditTableSkeleton rows={6} />
          ) : previewEvents.length === 0 ? (
            <div className="py-10">
              <EmptyState
                icon={ScrollText}
                title="No events match"
                description="Adjust your filters to select events to export."
              />
            </div>
          ) : (
            <>
              <AuditTable events={previewEvents} />
              {previewEvents.length === AUDIT_PAGE_SIZE && (
                <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
                  Showing the first {AUDIT_PAGE_SIZE}. The export includes all matching events.
                </p>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <ExportDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        loading={isExporting}
        onConfirm={handleExport}
      />
    </div>
  )
}
