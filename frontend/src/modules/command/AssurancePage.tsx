import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ClipboardCheck, Loader2 } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { Button, Card, CardContent, Select } from '@/components/ui'
import { usePermissions } from '@/authorization'
import { assuranceService } from '@/services'
import type { AssuranceEvaluation } from '@/services/assuranceService'
import { ConfirmActionDialog } from '@/modules/operations/components/ConfirmActionDialog'
import { useGuardedAction } from '@/modules/operations/useGuardedAction'
import { CommandCenterNav, LoadError, Tile } from './components'

/**
 * Phase 5.9 — Assurance.
 *
 * In Phase 5.8 this page said "not built yet", because a placeholder framework
 * grid would have implied evidence ACT did not produce. It now shows the real
 * thing, and the same discipline governs how.
 *
 * **INSUFFICIENT_EVIDENCE is rendered as its own state, never folded into a
 * pass and never hidden.** It gets its own tile and its own colour, because the
 * entire point of the phase is that "we cannot tell" and "we checked and it is
 * fine" are different answers. A dashboard that showed only passes and failures
 * would quietly convert every unevaluated control into a green one — the
 * false-green this whole surface exists to prevent.
 *
 * **There is no score, no coverage percentage and no compliance badge**, here
 * or in the API behind it. The server's disclaimer is rendered verbatim rather
 * than paraphrased into a UI label, so the caveat travels with the data.
 *
 * Read + trigger, reusing the 3.10/4.9 pattern: the evaluate and export actions
 * dispatch to the endpoints that own them, and export — which sends evidence
 * out of ACT — is confirmation-gated.
 */
export function AssurancePage() {
  const { can } = usePermissions()
  const guard = useGuardedAction()
  const queryClient = useQueryClient()
  const [frameworkId, setFrameworkId] = useState('NIST_AI_RMF')

  const frameworks = useQuery({
    queryKey: ['assurance-frameworks'],
    queryFn: () => assuranceService.frameworks(),
  })
  const report = useQuery({
    queryKey: ['assurance-report', frameworkId],
    queryFn: () => assuranceService.frameworkReport(frameworkId),
    enabled: Boolean(frameworkId),
  })
  const evaluations = useQuery({
    queryKey: ['assurance-evaluations'],
    queryFn: () => assuranceService.evaluations({ limit: 500 }),
  })

  const rows = evaluations.data ?? []
  const counts = {
    pass: rows.filter((r) => r.result === 'PASS').length,
    fail: rows.filter((r) => r.result === 'FAIL').length,
    insufficient: rows.filter((r) => r.result === 'INSUFFICIENT_EVIDENCE').length,
    stale: rows.filter((r) => r.stale).length,
  }

  const evaluate = useMutation({
    mutationFn: () => assuranceService.evaluateTenant(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assurance-evaluations'] })
      queryClient.invalidateQueries({ queryKey: ['assurance-report', frameworkId] })
    },
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={ClipboardCheck}
        title="Assurance"
        description="Evidence ACT holds, mapped to control frameworks. Not a compliance determination."
      />
      <CommandCenterNav />

      <section aria-label="Results" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label="Evidenced (pass)" value={String(counts.pass)} />
        <Tile label="Not met (fail)" value={String(counts.fail)}
              tone={counts.fail > 0 ? 'destructive' : 'default'} />
        {/* Its own tile, deliberately. Absence is not a pass. */}
        <Tile
          label="Insufficient evidence"
          value={String(counts.insufficient)}
          hint="ACT cannot substantiate these — not the same as compliant"
          tone={counts.insufficient > 0 ? 'warning' : 'default'}
        />
        <Tile label="Stale" value={String(counts.stale)}
              hint="Evidence older than the freshness policy"
              tone={counts.stale > 0 ? 'warning' : 'default'} />
      </section>

      <div className="flex flex-wrap items-center gap-2">
        <Select
          aria-label="Framework"
          value={frameworkId}
          onChange={(e) => setFrameworkId(e.target.value)}
          options={(frameworks.data ?? []).map((f) => ({ value: f.id, label: f.name }))}
        />
        {can('assurance.manage') ? (
          <Button size="sm" variant="outline" disabled={evaluate.isPending}
                  onClick={() => evaluate.mutate()}>
            {evaluate.isPending ? 'Evaluating…' : 'Re-evaluate'}
          </Button>
        ) : null}
        {can('assurance.export') ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => guard.confirm({
              title: 'Export evidence bundle',
              description:
                'Exports this organization’s control evidence as a portable, signed '
                + 'bundle. Once it leaves ACT, ACT’s tenant isolation and audit no longer '
                + 'protect it — the chain of custody becomes yours. The export is recorded.',
              confirmLabel: 'Export evidence',
              requireReason: false,
              destructive: false,
              onConfirm: () => guard.run(
                () => assuranceService.exportBundle({ framework_id: frameworkId }),
                { success: 'Evidence bundle exported.' },
              ),
            })}
          >
            Export evidence
          </Button>
        ) : null}
      </div>

      {report.isLoading ? (
        <div className="flex justify-center p-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : report.isError ? (
        <LoadError what="the framework report" error={report.error} />
      ) : report.data ? (
        <>
          <Card>
            <CardContent className="space-y-1 p-4">
              <p className="text-sm font-semibold text-foreground">
                {report.data.framework.name} · {report.data.framework.revision}
              </p>
              {/* The server's own words, not a paraphrase. */}
              <p className="text-xs text-muted-foreground">{report.data.framework.scope_note}</p>
              <p className="text-xs text-muted-foreground">{report.data.disclaimer}</p>
              <p className="text-xs text-muted-foreground">
                Catalog v{report.data.catalog_version} · mapping v{report.data.mapping_version}
              </p>
            </CardContent>
          </Card>

          <div className="space-y-3">
            {report.data.controls.map((c) => (
              <Card key={c.control_ref}>
                <CardContent className="space-y-2 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono text-sm text-foreground">{c.control_ref}</span>
                    <span className="text-xs text-muted-foreground">
                      {c.counts.passed} evidenced · {c.counts.failed} not met ·{' '}
                      {c.counts.insufficient_evidence} insufficient
                    </span>
                  </div>
                  <p className="text-sm text-foreground">{c.title}</p>
                  <p className="text-xs text-muted-foreground">{c.rationale}</p>
                  {!c.evidence_available ? (
                    <p className="text-xs text-warning">
                      No evaluations yet for the ACT controls mapped here — ACT holds no
                      evidence for this control. That is not the same as satisfying it.
                    </p>
                  ) : (
                    <ul className="space-y-1">
                      {c.evaluations.slice(0, 6).map((e) => (
                        <li key={`${e.control_id}-${e.subject_id ?? 'org'}`}>
                          <ResultLine evaluation={e} />
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      ) : null}

      <ConfirmActionDialog request={guard.request} pending={guard.pending} onCancel={guard.cancel} />
    </div>
  )
}

/**
 * One control result. INSUFFICIENT_EVIDENCE is styled as its own state rather
 * than as a muted pass, and the reason is always shown — an auditor needs to
 * know *why* ACT cannot substantiate something, not merely that it cannot.
 */
function ResultLine({ evaluation }: { evaluation: AssuranceEvaluation }) {
  const tone =
    evaluation.result === 'PASS' ? 'text-primary'
      : evaluation.result === 'FAIL' ? 'text-destructive'
        : 'text-warning'
  return (
    <div className="text-xs">
      <span className={`font-medium ${tone}`}>
        {evaluation.result === 'INSUFFICIENT_EVIDENCE' ? 'INSUFFICIENT EVIDENCE' : evaluation.result}
      </span>
      {' · '}
      <span className="font-mono text-foreground">{evaluation.control_id}</span>
      {evaluation.stale ? <span className="text-warning"> · stale</span> : null}
      <p className="text-muted-foreground">{evaluation.reason}</p>
      {evaluation.exception_reason ? (
        <p className="text-muted-foreground">
          Exception on record (the result is unchanged): {evaluation.exception_reason}
        </p>
      ) : null}
    </div>
  )
}
