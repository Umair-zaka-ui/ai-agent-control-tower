import { useState } from 'react'
import { Download, FileJson, FileSpreadsheet, FileText } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { cn } from '@/utils/cn'
import type { ExportFormat } from '../utils/export'

interface ExportFormatOption {
  value: ExportFormat | 'pdf'
  label: string
  description: string
  icon: LucideIcon
  disabled?: boolean
}

const FORMATS: ExportFormatOption[] = [
  { value: 'csv', label: 'CSV', description: 'Spreadsheet-friendly, one row per event.', icon: FileSpreadsheet },
  { value: 'json', label: 'JSON', description: 'Full structured event records.', icon: FileJson },
  { value: 'pdf', label: 'PDF', description: 'Formatted report — coming soon.', icon: FileText, disabled: true },
]

interface ExportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  loading?: boolean
  /** Number of events that will be exported with the current filters. */
  count?: number
  onConfirm: (format: ExportFormat) => void
}

/** Format picker for the export center (SRS §Export Center, §ExportDialog). */
export function ExportDialog({ open, onOpenChange, loading, count, onConfirm }: ExportDialogProps) {
  const [format, setFormat] = useState<ExportFormat | 'pdf'>('csv')

  const handleConfirm = () => {
    if (format === 'pdf') return
    onConfirm(format)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Export audit events</DialogTitle>
          <DialogDescription>
            {count != null
              ? `Exports the ${count} event${count === 1 ? '' : 's'} matching your current filters.`
              : 'Exports the events matching your current filters.'}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-2">
          {FORMATS.map((opt) => {
            const Icon = opt.icon
            const selected = format === opt.value
            return (
              <button
                key={opt.value}
                type="button"
                disabled={opt.disabled}
                onClick={() => setFormat(opt.value)}
                className={cn(
                  'flex items-start gap-3 rounded-md border p-3 text-left transition-colors',
                  selected ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/50',
                  opt.disabled && 'cursor-not-allowed opacity-50 hover:bg-transparent',
                )}
                aria-pressed={selected}
              >
                <Icon className="mt-0.5 h-5 w-5 text-muted-foreground" aria-hidden />
                <span className="space-y-0.5">
                  <span className="block text-sm font-medium">{opt.label}</span>
                  <span className="block text-xs text-muted-foreground">{opt.description}</span>
                </span>
              </button>
            )
          })}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={handleConfirm} disabled={loading || format === 'pdf'}>
            <Download className="h-4 w-4" />
            {loading ? 'Exporting…' : 'Export'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
