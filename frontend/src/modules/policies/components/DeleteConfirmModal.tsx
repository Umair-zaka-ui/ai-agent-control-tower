import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

interface DeleteConfirmModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  policyName: string
  loading?: boolean
  onConfirm: () => void
}

/**
 * Destructive-action modal. The user must type DELETE to enable the final
 * button (SRS §Delete Confirmation).
 */
export function DeleteConfirmModal({
  open,
  onOpenChange,
  policyName,
  loading,
  onConfirm,
}: DeleteConfirmModalProps) {
  const [confirmText, setConfirmText] = useState('')
  const armed = confirmText.trim() === 'DELETE'

  const handleOpenChange = (next: boolean) => {
    if (!next) setConfirmText('')
    onOpenChange(next)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete “{policyName}”?</DialogTitle>
          <DialogDescription>
            This action cannot be undone. This policy will no longer be available for governance
            decisions.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            Type <span className="font-mono font-semibold text-foreground">DELETE</span> to confirm.
          </p>
          <Input
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="DELETE"
            aria-label="Type DELETE to confirm"
            autoFocus
          />
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="destructive" disabled={!armed || loading} onClick={onConfirm}>
            {loading ? 'Deleting…' : 'Delete policy'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
