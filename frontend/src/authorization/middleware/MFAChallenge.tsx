import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

/**
 * §33 REQUIRE_MFA — the gateway demands stronger authentication. Platform MFA
 * enrolment ships in a later phase (Phase 4+ roadmap); until then the
 * challenge is surfaced honestly: the action stays blocked and the user is
 * told why, instead of a silent 401.
 */
export function MFAChallenge({
  open,
  reason,
  onClose,
}: {
  open: boolean
  reason: string
  onClose: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Stronger authentication required</DialogTitle>
          <DialogDescription>{reason}</DialogDescription>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          This action is protected by a policy that requires multi-factor
          authentication. Contact your security administrator to enable MFA for
          your account.
        </p>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
