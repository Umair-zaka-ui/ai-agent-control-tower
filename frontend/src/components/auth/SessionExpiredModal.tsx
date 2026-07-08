import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

interface SessionExpiredModalProps {
  open: boolean
  onConfirm: () => void
}

/**
 * Shown when the session can no longer be silently refreshed (SRS §20). The
 * only action is to re-authenticate — dismissing routes the user to /login.
 */
export function SessionExpiredModal({ open, onConfirm }: SessionExpiredModalProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // Any dismissal (X, Esc, outside click) must lead to re-authentication.
        if (!next) onConfirm()
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Session expired</DialogTitle>
          <DialogDescription>
            Your session has expired for security reasons. Please sign in again to continue.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button onClick={onConfirm} className="w-full sm:w-auto">
            Sign in again
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
