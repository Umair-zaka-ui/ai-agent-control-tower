import { useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Loader2, Upload } from 'lucide-react'
import { toast } from 'sonner'

import { PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService } from '@/services'
import type { ID } from '@/types'
import { RuntimeNav } from '../components/RuntimeNav'

const FORMATS = [{ value: 'JSON', label: 'JSON' }, { value: 'YAML', label: 'YAML' }, { value: 'CSV', label: 'CSV' }]
const MODES = [
  { value: 'CREATE_ONLY', label: 'Create only (skip existing)' },
  { value: 'UPDATE_DRAFTS', label: 'Update drafts only' },
  { value: 'UPSERT_NON_ACTIVE', label: 'Create or update non-active agents' },
  { value: 'VALIDATE_ONLY', label: 'Validate only (no changes)' },
]

/** Phase 5.1 SRS §39-§45, §60 — bulk agent import. Imports always land as
 * DRAFT, never directly ACTIVE. */
export function ImportPage() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [format, setFormat] = useState('JSON')
  const [mode, setMode] = useState('CREATE_ONLY')
  const [jobId, setJobId] = useState<ID | null>(null)

  const job = useQuery({
    queryKey: ['runtime-import-job', jobId], queryFn: () => runtimeService.importJob(jobId!),
    enabled: !!jobId, refetchInterval: (q) => (q.state.data?.status === 'RUNNING' ? 1000 : false),
  })
  const items = useQuery({
    queryKey: ['runtime-import-items', jobId], queryFn: () => runtimeService.importItems(jobId!),
    enabled: !!jobId && job.data?.status === 'COMPLETED',
  })

  const runImport = useMutation({
    mutationFn: async () => {
      const file = fileRef.current?.files?.[0]
      if (!file) throw new Error('Choose a file first.')
      const content = await file.text()
      return runtimeService.importAgents({ file_name: file.name, format: format as 'JSON' | 'YAML' | 'CSV', mode: mode as never, content })
    },
    onSuccess: (created) => { setJobId(created.id); toast.success('Import job started') },
    onError: (e: unknown) => toast.error((e as { message?: string }).message ?? 'Import failed'),
  })

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Upload}
        title="Import agents"
        description="Bulk-create or update agent registrations from a JSON, YAML or CSV file."
        backTo={ROUTES.RUNTIME_AGENTS}
        backLabel="Agent inventory"
      />
      <RuntimeNav />

      <Card>
        <CardHeader><CardTitle className="text-base">Upload</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <Select aria-label="Format" className="w-32" value={format} options={FORMATS}
                    onChange={(e) => setFormat(e.target.value)} />
            <Select aria-label="Mode" className="w-72" value={mode} options={MODES}
                    onChange={(e) => setMode(e.target.value)} />
            <input ref={fileRef} type="file" accept=".json,.yaml,.yml,.csv"
                   className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm file:mr-3 file:rounded-sm file:border-0 file:bg-muted file:px-2 file:py-1 file:text-xs" />
          </div>
          <Button disabled={runImport.isPending} onClick={() => runImport.mutate()}>
            {runImport.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            Import
          </Button>
        </CardContent>
      </Card>

      {job.data && (
        <Card>
          <CardHeader><CardTitle className="text-base">Job {job.data.file_name}</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2 text-sm">
              <Badge variant={job.data.status === 'COMPLETED' ? 'success' : job.data.status === 'FAILED' ? 'destructive' : 'secondary'}>
                {job.data.status}
              </Badge>
              <span className="text-muted-foreground">
                {job.data.total_records} records · {job.data.successful_records} ok ·
                {' '}{job.data.warning_records} warnings · {job.data.failed_records} failed
              </span>
            </div>
            {items.data && items.data.length > 0 && (
              <Table>
                <TableHeader><TableRow><TableHead>Record</TableHead><TableHead>Status</TableHead><TableHead>Notes</TableHead></TableRow></TableHeader>
                <TableBody>
                  {items.data.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="font-medium">{item.record_identifier}</TableCell>
                      <TableCell>
                        <Badge variant={item.status === 'CREATED' || item.status === 'UPDATED' ? 'success'
                                      : item.status === 'FAILED' ? 'destructive' : 'secondary'}>
                          {item.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {[...item.errors, ...item.warnings].map((e) => e.message).join('; ') || '—'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
