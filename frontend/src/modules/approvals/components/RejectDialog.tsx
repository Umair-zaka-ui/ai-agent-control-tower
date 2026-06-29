import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { REJECT_REASON_MIN } from '../utils/constants'

interface RejectDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  loading?: boolean
  onConfirm: (reason: string) => void
}

/** Reject dialog — a reason of at least 20 chars is required (SRS §Reject Dialog). */
export function RejectDialog({ open, onOpenChange, loading, onConfirm }: RejectDialogProps) {
  const [reason, setReason] = useState('')

  useEffect(() => {
    if (!open) setReason('')
  }, [open])

  const remaining = REJECT_REASON_MIN - reason.trim().length
  const armed = remaining <= 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reject this action?</DialogTitle>
          <DialogDescription>
            The agent action will be blocked. Provide a clear reason for the audit trail.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <label htmlFor="reject-reason" className="text-sm font-medium">
            Rejection reason <span className="text-destructive">*</span>
          </label>
          <Textarea
            id="reject-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Explain why this action is being rejected…"
            rows={4}
            autoFocus
          />
          <p className="text-xs text-muted-foreground">
            {armed ? 'Looks good.' : `At least ${remaining} more character${remaining === 1 ? '' : 's'} required.`}
          </p>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="destructive" disabled={!armed || loading} onClick={() => onConfirm(reason.trim())}>
            {loading ? 'Rejecting…' : 'Confirm rejection'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
