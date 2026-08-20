import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'

import {
  Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader,
  DialogTitle, Input, Label, Textarea,
} from '@/components/ui'

export interface ConfirmActionRequest {
  /** Short imperative title, e.g. "Roll back to v1.4.2". */
  title: string
  /** What will actually happen, in plain language, including what cannot be undone. */
  description: string
  confirmLabel: string
  /**
   * When set, the operator must type this exact string before the confirm
   * button enables. Reserved for the genuinely irreversible: promoting to
   * production, forcing a rollback past its preconditions, aborting a rollout
   * mid-flight. Everything else is a single deliberate click.
   */
  typeToConfirm?: string
  /** When set, a reason is required and passed to the action. */
  requireReason?: boolean
  reasonLabel?: string
  destructive?: boolean
  /** Facts the operator should weigh before confirming (blockers, current weights). */
  warnings?: string[]
  onConfirm: (reason: string) => void
}

interface Props {
  request: ConfirmActionRequest | null
  pending?: boolean
  onCancel: () => void
}

/**
 * Phase 3.10 — the confirmation gate for dangerous actions (M3-3.10-FR-021,
 * §22).
 *
 * **This is a guard against the accidental, not the unauthorized.** The server
 * decides whether an operator *may* roll back; this dialog exists so that an
 * operator who may do it does not do it by reflex, in the wrong tab, during an
 * incident, at 3am. That distinction matters: nothing here is a security
 * control, and treating it as one would be exactly the client-side-only gating
 * §10 forbids.
 *
 * Two tiers, because uniform friction is friction people learn to click
 * through:
 *
 * - **Confirm** — a deliberate second click. Drain a worker, pause a rollout,
 *   disable a job. Reversible things.
 * - **Type-to-confirm** — the operator types the environment or version name.
 *   Promote to production, force a rollback, abort a rollout. Things that move
 *   production traffic or cannot be taken back.
 *
 * A required reason is not decoration either: it lands in the audit trail the
 * server writes, so the next engineer reading the timeline finds out *why*
 * rather than only *what*.
 */
export function ConfirmActionDialog({ request, pending = false, onCancel }: Props) {
  const [typed, setTyped] = useState('')
  const [reason, setReason] = useState('')

  // Reset whenever a different action is raised, so a previously-typed
  // confirmation can never carry over and pre-arm the next dialog.
  useEffect(() => {
    setTyped('')
    setReason('')
  }, [request?.title, request?.typeToConfirm])

  if (!request) return null

  const typeSatisfied = !request.typeToConfirm || typed.trim() === request.typeToConfirm
  const reasonSatisfied = !request.requireReason || reason.trim().length > 0
  const canConfirm = typeSatisfied && reasonSatisfied && !pending

  return (
    <Dialog open onOpenChange={(next) => { if (!next) onCancel() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{request.title}</DialogTitle>
          <DialogDescription>{request.description}</DialogDescription>
        </DialogHeader>

        {request.warnings && request.warnings.length > 0 ? (
          <div role="alert" className="rounded-lg border border-warning/30 bg-warning/10 p-3">
            <ul className="space-y-1.5">
              {request.warnings.map((warning) => (
                <li key={warning} className="flex items-start gap-2 text-sm text-foreground">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
                  <span>{warning}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {request.requireReason ? (
          <div className="space-y-2">
            <Label htmlFor="confirm-reason">{request.reasonLabel ?? 'Reason'}</Label>
            <Textarea
              id="confirm-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Recorded in the audit trail."
              rows={2}
            />
          </div>
        ) : null}

        {request.typeToConfirm ? (
          <div className="space-y-2">
            <Label htmlFor="confirm-phrase">
              Type <span className="font-mono font-semibold text-foreground">{request.typeToConfirm}</span> to confirm
            </Label>
            <Input
              id="confirm-phrase"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoComplete="off"
              aria-label={`Type ${request.typeToConfirm} to confirm`}
            />
          </div>
        ) : null}

        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={pending}>Cancel</Button>
          <Button
            variant={request.destructive === false ? 'default' : 'destructive'}
            disabled={!canConfirm}
            onClick={() => request.onConfirm(reason.trim())}
          >
            {pending ? 'Working…' : request.confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
