import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ScrollText } from 'lucide-react'

import { useCan } from '@/authorization'
import { PageHeader } from '@/components/common'
import {
  Button, Card, CardContent, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ConfirmActionDialog, useGuardedAction } from '@/modules/operations'
import { observabilityService } from '@/services'
import { ObservabilityNav } from './components/ObservabilityNav'
import { CaptureModeBadge } from './components/badges'

const MODES = ['METADATA_ONLY', 'REDACTED_CONTENT', 'FULL_CONTENT', 'DISABLED']
/** Modes that capture more content than METADATA_ONLY — raising *to* one of
 *  these is the dangerous, confirmation-gated action (M4-4.9-FR-022). */
const CONTENT_MODES = new Set(['REDACTED_CONTENT', 'FULL_CONTENT'])

/**
 * Phase 4.9 view 9 — Telemetry Policy admin (M4-4.9-FR-009).
 *
 * Capture modes per scope and retention per class, from 4.8. Two dangerous
 * actions are confirmation-gated:
 * - **raising a policy to a content-capturing mode** (`REDACTED_CONTENT` /
 *   `FULL_CONTENT`) — type-to-confirm, because it starts persisting prompts and
 *   tool payloads;
 * - **running the retention sweep** — it permanently deletes expired telemetry.
 *
 * Every write dispatches to 4.8's endpoint, which authorises it and audits it
 * (`RUNTIME_TELEMETRY_POLICY_CHANGED` / `RUNTIME_TELEMETRY_RETENTION_RUN`). The
 * server is the authority; this UI reflects `runtime.telemetry_policy.manage`
 * for UX only.
 */
export function TelemetryPolicyPage() {
  const canManage = useCan('runtime.telemetry_policy.manage')
  const guard = useGuardedAction()
  const [newMode, setNewMode] = useState('METADATA_ONLY')

  const policies = useQuery({ queryKey: ['obs-capture'], queryFn: () => observabilityService.capturePolicies() })
  const retention = useQuery({ queryKey: ['obs-retention'], queryFn: () => observabilityService.retentionPolicies() })
  const effective = useQuery({ queryKey: ['obs-effective'], queryFn: () => observabilityService.effectiveMode({}) })

  const invalidate = [['obs-capture'], ['obs-retention'], ['obs-effective'], ['obs-overview']]

  function raiseMode(mode: string) {
    const dangerous = CONTENT_MODES.has(mode)
    if (!dangerous) {
      void guard.run(
        () => observabilityService.createCapturePolicy({ mode }),
        { success: 'Capture policy created', invalidate },
      )
      return
    }
    guard.confirm({
      title: `Set org-wide capture to ${mode.replace(/_/g, ' ')}`,
      description:
        mode === 'FULL_CONTENT'
          ? 'FULL_CONTENT persists prompts, tool arguments, tool results and model output (secrets are still scrubbed, and chain-of-thought is never captured). This is a deliberate, audited policy choice — not a default.'
          : 'REDACTED_CONTENT persists content with sensitive-named fields masked and secrets scrubbed, before storage. Still a deliberate, audited choice.',
      confirmLabel: `Enable ${mode.replace(/_/g, ' ')}`,
      destructive: true,
      typeToConfirm: mode,
      requireReason: false,
      warnings: [
        'This applies to every execution in the organization that no more specific policy covers.',
        'Content becomes readable to holders of runtime.trace.content.view, and every view is audited.',
      ],
      onConfirm: () => guard.run(
        () => observabilityService.createCapturePolicy({ mode }),
        { success: 'Capture policy created', invalidate },
      ),
    })
  }

  function runRetention() {
    guard.confirm({
      title: 'Run the retention sweep now',
      description:
        'This permanently deletes telemetry that has outlived its per-class retention (trace content, trace metadata, metrics aggregates, resolved/suppressed alerts). It never deletes an execution row, an audit record, or financial/governance evidence. It is idempotent and bounded.',
      confirmLabel: 'Run retention sweep',
      destructive: true,
      requireReason: false,
      onConfirm: () => guard.run(
        () => observabilityService.runRetention(),
        { success: 'Retention sweep complete', invalidate },
      ),
    })
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={ScrollText}
        title="Telemetry Policy"
        description="What content is captured, for which scopes, and how long each telemetry class is kept."
      />
      <ObservabilityNav />

      {effective.data ? (
        <Card>
          <CardContent className="space-y-1 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">Org-wide effective mode</span>
              <CaptureModeBadge value={effective.data.mode} />
              <span className="text-xs text-muted-foreground">({effective.data.source})</span>
            </div>
            <p className="text-xs text-muted-foreground">{effective.data.reason}</p>
            <p className="text-xs text-muted-foreground">Precedence: {effective.data.precedence}</p>
          </CardContent>
        </Card>
      ) : null}

      {/* --- Capture policies -------------------------------------------- */}
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Capture policies</h2>
            {canManage ? (
              <div className="flex items-end gap-2">
                <label className="text-sm">
                  <span className="mb-1 block text-xs text-muted-foreground">New org-wide policy</span>
                  <Select
                    aria-label="New capture mode"
                    value={newMode}
                    onChange={(e) => setNewMode(e.target.value)}
                    options={MODES.map((m) => ({ value: m, label: m.replace(/_/g, ' ') }))}
                  />
                </label>
                <Button size="sm" onClick={() => raiseMode(newMode)}>Add policy</Button>
              </div>
            ) : null}
          </div>

          {policies.isLoading ? (
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          ) : !policies.data || policies.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No explicit capture policies. The conservative default applies: METADATA_ONLY everywhere,
              never FULL_CONTENT without an explicit policy.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Mode</TableHead>
                    <TableHead>Environment</TableHead>
                    <TableHead>Agent</TableHead>
                    <TableHead>Classification</TableHead>
                    <TableHead>Enabled</TableHead>
                    {canManage ? <TableHead>Actions</TableHead> : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {policies.data.map((p) => (
                    <TableRow key={p.id}>
                      <TableCell><CaptureModeBadge value={p.mode} /></TableCell>
                      <TableCell className="font-mono text-xs">{p.environment_id?.slice(0, 8) ?? 'any'}</TableCell>
                      <TableCell className="font-mono text-xs">{p.agent_id?.slice(0, 8) ?? 'any'}</TableCell>
                      <TableCell>{p.classification ?? 'any'}</TableCell>
                      <TableCell>{p.enabled ? 'yes' : 'no'}</TableCell>
                      {canManage ? (
                        <TableCell>
                          <Button size="sm" variant="outline"
                            onClick={() => guard.confirm({
                              title: `Delete this ${p.mode.replace(/_/g, ' ')} policy`,
                              description: 'The scope this policy covered will fall back to the next most specific policy, or the conservative default.',
                              confirmLabel: 'Delete policy',
                              destructive: true,
                              onConfirm: () => guard.run(
                                () => observabilityService.deleteCapturePolicy(p.id),
                                { success: 'Policy deleted', invalidate },
                              ),
                            })}>
                            Delete
                          </Button>
                        </TableCell>
                      ) : null}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* --- Retention ------------------------------------------------- */}
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">Retention by telemetry class</h2>
            {canManage ? (
              <Button size="sm" variant="destructive" onClick={runRetention}>Run retention sweep</Button>
            ) : null}
          </div>
          {retention.isLoading ? (
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          ) : retention.data ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Class</TableHead>
                    <TableHead>Retention (days)</TableHead>
                    <TableHead>Floor</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead>Deletable?</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Object.values(retention.data).map((c) => (
                    <TableRow key={c.telemetry_class}>
                      <TableCell className="font-medium">{c.telemetry_class.replace(/_/g, ' ')}</TableCell>
                      <TableCell>{c.retention_days}</TableCell>
                      <TableCell className="text-muted-foreground">{c.floor_days}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{c.source}</TableCell>
                      <TableCell>{c.retain_only ? 'retain-only (evidence)' : 'yes'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <ConfirmActionDialog request={guard.request} pending={guard.pending} onCancel={guard.cancel} />
    </div>
  )
}
