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
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { EscalationTarget } from '../types'
import { ESCALATION_TARGETS } from '../utils/constants'

interface EscalateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  loading?: boolean
  onConfirm: (target: EscalationTarget, reason: string) => void
}

/** Escalate dialog — choose a target and provide a required reason (SRS §Escalate Dialog). */
export function EscalateDialog({ open, onOpenChange, loading, onConfirm }: EscalateDialogProps) {
  const [target, setTarget] = useState<EscalationTarget>('MANAGER')
  const [reason, setReason] = useState('')

  useEffect(() => {
    if (!open) {
      setTarget('MANAGER')
      setReason('')
    }
  }, [open])

  const armed = reason.trim().length > 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Escalate this approval</DialogTitle>
          <DialogDescription>
            Route this approval to a person or team for a higher-level review.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1.5">
            <label htmlFor="escalate-target" className="text-sm font-medium">
              Escalate to
            </label>
            <Select
              id="escalate-target"
              value={target}
              options={ESCALATION_TARGETS}
              onChange={(e) => setTarget(e.target.value as EscalationTarget)}
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="escalate-reason" className="text-sm font-medium">
              Reason <span className="text-destructive">*</span>
            </label>
            <Textarea
              id="escalate-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why does this need escalation?"
              rows={3}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!armed || loading} onClick={() => onConfirm(target, reason.trim())}>
            {loading ? 'Escalating…' : 'Escalate'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
