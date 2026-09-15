import { useQuery } from '@tanstack/react-query'
import { Loader2, ShieldCheck } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { Button, Card, CardContent } from '@/components/ui'
import { usePermissions } from '@/authorization'
import { commandCenterService } from '@/services'
import type { PostureFinding } from '@/services/commandCenterService'
import { ConfirmActionDialog } from '@/modules/operations/components/ConfirmActionDialog'
import { useGuardedAction } from '@/modules/operations/useGuardedAction'
import { CommandCenterNav, LoadError } from './components'

/**
 * Phase 5.8 — Security Posture.
 *
 * Every finding carries its own reason and remediation from Phase 5.5, so this
 * page renders explanations rather than a score. `INSUFFICIENT_DATA` is shown
 * as itself: 5.5 treats "no evidence" as a first-class outcome precisely so it
 * is never mistaken for "healthy", and flattening it here would undo that.
 *
 * Resolve and suppress are different acts and are labelled as such — suppress
 * is permission-gated and audited server-side, and is *not* resolution.
 */
export function PostureFindingsPage() {
  const { can } = usePermissions()
  const guard = useGuardedAction()
  const q = useQuery({
    queryKey: ['cc-posture-findings'],
    queryFn: () => commandCenterService.postureFindings({ status: 'OPEN' }),
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={ShieldCheck}
        title="Security Posture"
        description="Open posture findings, each with the rule that produced it and what would resolve it."
      />
      <CommandCenterNav />

      {q.isLoading ? (
        <div className="flex justify-center p-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : q.isError ? (
        <LoadError what="posture findings" error={q.error} />
      ) : (
        <div className="space-y-3">
          {(q.data ?? []).map((f: PostureFinding) => (
            <Card key={f.id}>
              <CardContent className="space-y-1.5 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono text-sm text-foreground">{f.rule_id}</span>
                  <span className="text-xs text-muted-foreground">
                    {f.severity}
                    {f.outcome === 'INSUFFICIENT_DATA' ? ' · insufficient data' : ''}
                  </span>
                </div>
                <p className="text-sm text-muted-foreground">{f.reason}</p>
                {f.remediation ? (
                  <p className="text-xs text-muted-foreground">Remediation: {f.remediation}</p>
                ) : null}
                {can('posture.manage') ? (
                  <div className="flex gap-2 pt-1">
                    <Button
                      size="sm" variant="outline"
                      onClick={() => guard.confirm({
                        title: 'Resolve finding',
                        description:
                          'Marks this condition resolved. If it still holds, the next evaluation '
                          + 'reopens it — this does not suppress the rule.',
                        confirmLabel: 'Resolve', destructive: false,
                        onConfirm: () => guard.run(
                          () => commandCenterService.resolvePostureFinding(f.id),
                          { success: 'Finding resolved.', invalidate: [['cc-posture-findings']] },
                        ),
                      })}
                    >
                      Resolve
                    </Button>
                    <Button
                      size="sm" variant="outline"
                      onClick={() => guard.confirm({
                        title: 'Suppress finding',
                        description:
                          'Suppression hides this condition from the posture view while it is '
                          + 'still true. It is not resolution, it is audited, and the reason is '
                          + 'recorded against your account.',
                        confirmLabel: 'Suppress', requireReason: true,
                        reasonLabel: 'Why is this being suppressed?', destructive: true,
                        onConfirm: (reason) => guard.run(
                          () => commandCenterService.suppressPostureFinding(f.id, { reason }),
                          { success: 'Finding suppressed.', invalidate: [['cc-posture-findings']] },
                        ),
                      })}
                    >
                      Suppress
                    </Button>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ))}
          {(q.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No open posture findings.</p>
          ) : null}
        </div>
      )}

      <ConfirmActionDialog request={guard.request} pending={guard.pending} onCancel={guard.cancel} />
    </div>
  )
}
