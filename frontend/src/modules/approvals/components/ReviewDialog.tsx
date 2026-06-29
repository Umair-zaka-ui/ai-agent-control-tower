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

interface ReviewDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  loading?: boolean
  onConfirm: (comment: string) => void
}

/** Approve confirmation dialog — a comment is required (SRS §Approval Dialog). */
export function ReviewDialog({ open, onOpenChange, loading, onConfirm }: ReviewDialogProps) {
  const [comment, setComment] = useState('')

  useEffect(() => {
    if (!open) setComment('')
  }, [open])

  const armed = comment.trim().length > 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Approve this action?</DialogTitle>
          <DialogDescription>
            The agent action will be allowed to execute. This decision is recorded in the audit trail.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <label htmlFor="approve-comment" className="text-sm font-medium">
            Approval note <span className="text-destructive">*</span>
          </label>
          <Textarea
            id="approve-comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Why are you approving this action?"
            rows={3}
            autoFocus
          />
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!armed || loading} onClick={() => onConfirm(comment.trim())}>
            {loading ? 'Approving…' : 'Confirm approval'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
