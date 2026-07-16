import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useState } from 'react'

import type { DecisionUiBehavior } from './types'

/**
 * §32/§33 — one dialog for constraint/justification obligations. Approval and
 * MFA have their own dedicated dialogs; everything else renders here:
 * justification (collects a reason and hands it back to the caller), masked
 * fields and action limits (informational).
 */
export function ObligationDialog({
  behavior,
  open,
  onClose,
  onJustify,
}: {
  behavior: DecisionUiBehavior | null
  open: boolean
  onClose: () => void
  onJustify?: (justification: string) => void
}) {
  const [justification, setJustification] = useState('')
  if (!behavior) return null

  const title =
    behavior.kind === 'justification'
      ? 'Justification required'
      : behavior.kind === 'masked'
        ? 'Restricted fields hidden'
        : behavior.kind === 'limited'
          ? 'Action limited by policy'
          : 'Policy obligation'

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {'reason' in behavior && behavior.reason ? (
            <DialogDescription>{behavior.reason}</DialogDescription>
          ) : null}
        </DialogHeader>

        {behavior.kind === 'justification' && (
          <div className="space-y-2">
            <Textarea
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              placeholder="Explain why this action is needed…"
              aria-label="Justification"
            />
          </div>
        )}
        {behavior.kind === 'masked' && (
          <p className="text-sm text-muted-foreground">
            The following fields are hidden by policy: {behavior.fields.join(', ') || '—'}
          </p>
        )}
        {behavior.kind === 'limited' && (
          <ul className="text-sm text-muted-foreground">
            {Object.entries(behavior.limits).map(([k, v]) => (
              <li key={k}>
                {k}: {String(v)}
              </li>
            ))}
          </ul>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          {behavior.kind === 'justification' && onJustify && (
            <Button
              disabled={!justification.trim()}
              onClick={() => {
                onJustify(justification.trim())
                setJustification('')
              }}
            >
              Submit justification
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
