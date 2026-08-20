import { useCallback, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import type { ApiError } from '@/types'
import type { ConfirmActionRequest } from './components/ConfirmActionDialog'

/**
 * Server-side conflict codes the Operations Center can encounter, and the
 * reason it treats them as a category of their own.
 *
 * Every Milestone 3 engine uses optimistic concurrency: a deployment, a rollout
 * plan and a traffic allocation each carry a revision, and the loser of a race
 * is rejected rather than silently overwriting. An operator hitting one of
 * these has not made a mistake — someone else acted first, and the screen they
 * were looking at is simply out of date.
 *
 * So a conflict must never be retried automatically (that would re-apply an
 * intent formed against state that no longer exists) and must never be shown as
 * a generic failure (which reads as "the platform is broken" rather than "your
 * colleague just paused this"). It refreshes and says so.
 */
export const CONFLICT_CODES = new Set([
  'ROLLOUT_CONFLICT',
  'TRAFFIC_ALLOCATION_CONFLICT',
  'DEPLOYMENT_CONFLICT',
  'STRATEGY_CONFLICT',
  'CONFLICT',
])

/**
 * Codes that mean "the server refused because this would be unsafe" — the
 * outcomes §10 says the UI must represent honestly rather than smoothing over.
 * They get the server's own message verbatim, because it explains precisely
 * which safety rule fired.
 */
export const SAFETY_CODES = new Set([
  'KILL_SWITCH_ACTIVE',
  'ROLLOUT_HALTED_BY_KILL_SWITCH',
  'ROLLBACK_BLOCKED_BY_KILL_SWITCH',
  'ROLLBACK_TARGET_UNAVAILABLE',
  'STRATEGY_GATE_BLOCKED',
  'ROLLING_COHORT_INVALID',
  'DEPLOYMENT_PREFLIGHT_BLOCKED',
  'ROLLOUT_STAGE_GATE_NOT_MET',
])

export interface GuardedActionState {
  /** The confirmation currently being shown, if any. */
  request: ConfirmActionRequest | null
  pending: boolean
  /** Raise a confirmation. The action runs only if the operator confirms. */
  confirm: (request: ConfirmActionRequest) => void
  cancel: () => void
  /**
   * Run a server operation with conflict-aware error handling and cache
   * invalidation. Not itself a guard — pass it through `confirm` for anything
   * dangerous.
   */
  run: (
    action: () => Promise<unknown>,
    options?: { success?: string; invalidate?: unknown[][] },
  ) => Promise<void>
}

/**
 * Phase 3.10 — the one place the Operations Center dispatches a privileged
 * action.
 *
 * Every view routes through this, which is what makes "dangerous actions are
 * confirmation-gated" a property of the module rather than a habit twelve
 * pages have to remember individually.
 */
export function useGuardedAction(): GuardedActionState {
  const queryClient = useQueryClient()
  const [request, setRequest] = useState<ConfirmActionRequest | null>(null)
  const [pending, setPending] = useState(false)

  const cancel = useCallback(() => {
    setRequest(null)
    setPending(false)
  }, [])

  const run = useCallback(async (
    action: () => Promise<unknown>,
    options: { success?: string; invalidate?: unknown[][] } = {},
  ) => {
    setPending(true)
    try {
      await action()
      toast.success(options.success ?? 'Done')
      setRequest(null)
    } catch (error) {
      const api = error as ApiError
      const code = api?.code
      if (code && CONFLICT_CODES.has(code)) {
        // Someone else acted first. Say so plainly, refresh, and leave the
        // dialog closed — re-submitting a stale intent is the one thing that
        // must not happen here.
        toast.error(
          'Someone else changed this while you were looking at it. The view has been refreshed — check the current state and try again.',
        )
        setRequest(null)
      } else if (code && SAFETY_CODES.has(code)) {
        // The server refused on a safety rule. Its message names which one.
        toast.error(api.message)
      } else {
        toast.error(api?.message ?? 'The operation failed.')
      }
    } finally {
      setPending(false)
      // Always refetch, success or failure: after a conflict the screen is by
      // definition stale, and after a safety refusal the operator needs to see
      // the state that caused it.
      for (const key of options.invalidate ?? []) {
        await queryClient.invalidateQueries({ queryKey: key })
      }
    }
  }, [queryClient])

  const confirm = useCallback((next: ConfirmActionRequest) => {
    setRequest(next)
  }, [])

  return { request, pending, confirm, cancel, run }
}
