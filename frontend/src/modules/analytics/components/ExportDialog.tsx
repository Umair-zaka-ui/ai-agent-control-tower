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
import type { ReportFormat } from '../utils/export'

interface FormatOption {
  value: ReportFormat | 'pdf'
  label: string
  description: string
  icon: LucideIcon
  disabled?: boolean
}

const FORMATS: FormatOption[] = [
  { value: 'csv', label: 'CSV', description: 'Spreadsheet-friendly rows.', icon: FileSpreadsheet },
  { value: 'json', label: 'JSON', description: 'Full structured report.', icon: FileJson },
  { value: 'pdf', label: 'PDF', description: 'Formatted report — coming soon.', icon: FileText, disabled: true },
]

interface ExportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: (format: ReportFormat) => void
}

/** Report format picker (SRS §Reports Center / §ExportDialog). */
export function ExportDialog({ open, onOpenChange, onConfirm }: ExportDialogProps) {
  const [format, setFormat] = useState<ReportFormat | 'pdf'>('csv')
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Export report</DialogTitle>
          <DialogDescription>Download the current report in your preferred format.</DialogDescription>
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
                aria-pressed={selected}
                className={cn(
                  'flex items-start gap-3 rounded-md border p-3 text-left transition-colors',
                  selected ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/50',
                  opt.disabled && 'cursor-not-allowed opacity-50 hover:bg-transparent',
                )}
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
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => format !== 'pdf' && onConfirm(format)} disabled={format === 'pdf'}>
            <Download className="h-4 w-4" />
            Export
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
