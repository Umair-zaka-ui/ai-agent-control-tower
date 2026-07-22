import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Download, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { PageHeader } from '@/components/common'
import { Button, Card, CardContent, CardHeader, CardTitle, Select } from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { apiClient } from '@/services/apiClient'
import { runtimeService } from '@/services'
import { RuntimeNav } from '../components/RuntimeNav'

const EXPORT_TYPES = [
  { value: 'FULL_CONFIGURATION', label: 'Full configuration (non-secret)' },
  { value: 'INVENTORY_SUMMARY', label: 'Inventory summary' },
  { value: 'COMPLIANCE_REPORT', label: 'Compliance report' },
  { value: 'MIGRATION_PACKAGE', label: 'Migration package' },
]
const FORMATS = [{ value: 'JSON', label: 'JSON' }, { value: 'YAML', label: 'YAML' }, { value: 'CSV', label: 'CSV' }]

/** Phase 5.1 SRS §39-§45, §60 — bulk agent export. Secrets/credentials are
 * always excluded server-side, regardless of export type. */
export function ExportPage() {
  const [exportType, setExportType] = useState('INVENTORY_SUMMARY')
  const [format, setFormat] = useState('JSON')

  const runExport = useMutation({
    mutationFn: () => runtimeService.exportAgents({ export_type: exportType as never, format: format as 'JSON' | 'YAML' | 'CSV' }),
    onSuccess: async (job) => {
      toast.success(`${job.record_count} agent(s) exported`)
      const { data } = await apiClient.get(runtimeService.exportDownloadUrl(job.id), { responseType: 'blob' })
      const url = URL.createObjectURL(data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `agents-export.${format.toLowerCase()}`
      a.click()
      URL.revokeObjectURL(url)
    },
    onError: (e: unknown) => toast.error((e as { message?: string }).message ?? 'Export failed'),
  })

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Download}
        title="Export agents"
        description="Export the organization's agent registry — secrets and credentials are always excluded."
        backTo={ROUTES.RUNTIME_AGENTS}
        backLabel="Agent inventory"
      />
      <RuntimeNav />

      <Card>
        <CardHeader><CardTitle className="text-base">Export options</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <Select aria-label="Export type" className="flex-1" value={exportType} options={EXPORT_TYPES}
                    onChange={(e) => setExportType(e.target.value)} />
            <Select aria-label="Format" className="w-32" value={format} options={FORMATS}
                    onChange={(e) => setFormat(e.target.value)} />
          </div>
          <Button disabled={runExport.isPending} onClick={() => runExport.mutate()}>
            {runExport.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            Export & download
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
