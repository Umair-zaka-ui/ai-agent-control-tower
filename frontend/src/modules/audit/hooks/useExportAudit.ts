import { useState } from 'react'

import { auditService } from '../services/auditService'
import type { AuditListParams } from '../types'
import { type ExportFormat, exportAuditCsv, exportAuditJson } from '../utils/export'

/**
 * Imperative export hook: fetches the full filtered event set from
 * `GET /audit/export` and triggers a CSV/JSON download. Requires `audit.export`
 * (the backend enforces this; callers should also gate the UI).
 */
export function useExportAudit() {
  const [isExporting, setIsExporting] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function exportAudit(format: ExportFormat, params: AuditListParams = {}): Promise<number> {
    setIsExporting(true)
    setError(null)
    try {
      const items = await auditService.export(params)
      if (format === 'json') exportAuditJson(items)
      else exportAuditCsv(items)
      return items.length
    } catch (e) {
      setError(e)
      throw e
    } finally {
      setIsExporting(false)
    }
  }

  return { exportAudit, isExporting, error }
}
