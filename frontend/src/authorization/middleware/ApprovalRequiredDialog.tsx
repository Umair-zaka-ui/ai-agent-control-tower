import { useNavigate } from 'react-router-dom'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { ROUTES } from '@/constants/routes'

import type { AuthorizationObligation } from './types'

/**
 * §33 REQUIRE_APPROVAL — the action was routed into the Human Review
 * Workbench; explain that and offer the approvals queue.
 */
export function ApprovalRequiredDialog({
  open,
  reason,
  obligation,
  onClose,
}: {
  open: boolean
  reason: string
  obligation?: AuthorizationObligation
  onClose: () => void
}) {
  const navigate = useNavigate()
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Human approval required</DialogTitle>
          <DialogDescription>{reason}</DialogDescription>
        </DialogHeader>
        {obligation?.priority && (
          <p className="text-sm text-muted-foreground">
            Review priority: {obligation.priority}
            {obligation.reviewer_role ? ` · Reviewer: ${obligation.reviewer_role}` : ''}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          <Button
            onClick={() => {
              onClose()
              navigate(ROUTES.APPROVALS)
            }}
          >
            Open approval queue
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
