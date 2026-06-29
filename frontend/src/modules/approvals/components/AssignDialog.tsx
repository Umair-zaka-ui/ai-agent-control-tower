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
import type { ID } from '@/types'
import type { OrgUser } from '../hooks'

interface AssignDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  users: OrgUser[]
  loading?: boolean
  currentAssigneeId?: ID | null
  onConfirm: (userId: ID) => void
}

/** Assign / reassign the reviewer responsible for an approval (SRS §Assign Reviewer). */
export function AssignDialog({
  open,
  onOpenChange,
  users,
  loading,
  currentAssigneeId,
  onConfirm,
}: AssignDialogProps) {
  const [userId, setUserId] = useState<string>('')

  useEffect(() => {
    if (open) setUserId(currentAssigneeId ?? '')
  }, [open, currentAssigneeId])

  const options = users.map((u) => ({ value: u.id, label: `${u.name} (${u.role})` }))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Assign reviewer</DialogTitle>
          <DialogDescription>
            Choose the team member responsible for reviewing this approval.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <label htmlFor="assign-user" className="text-sm font-medium">
            Reviewer
          </label>
          <Select
            id="assign-user"
            value={userId}
            placeholder="Select a reviewer…"
            options={options}
            onChange={(e) => setUserId(e.target.value)}
          />
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!userId || loading} onClick={() => onConfirm(userId)}>
            {loading ? 'Assigning…' : 'Assign'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
