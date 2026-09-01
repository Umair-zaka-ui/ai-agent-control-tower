import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ShieldCheck } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Card, CardContent, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { observabilityService } from '@/services'
import { ObservabilityNav } from './components/ObservabilityNav'
import { DecisionBadge } from './components/badges'

/**
 * Phase 4.9 view 5 — Governance Decisions (M4-4.9-FR-005).
 *
 * Every material governance decision for the tenant, from 4.9's read model over
 * 4.3's append-only lineage. `reason` is a platform-templated sentence (a
 * ceiling, a tool name, a model name) — never a prompt or model output, so this
 * surface does not weaken the content boundary.
 */
export function GovernanceDecisionsPage() {
  const [decision, setDecision] = useState('')
  const [checkpoint, setCheckpoint] = useState('')

  const q = useQuery({
    queryKey: ['obs-governance', decision, checkpoint],
    queryFn: () => observabilityService.governanceDecisions({
      decision: decision || undefined,
      checkpoint: checkpoint || undefined,
      limit: 100,
    }),
  })
  const page = q.data

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={ShieldCheck}
        title="Governance Decisions"
        description="Why executions were allowed, challenged, denied or stopped — the checkpoint, the rule, the obligation."
      />
      <ObservabilityNav />

      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <label className="text-sm">
            <span className="mb-1 block text-xs text-muted-foreground">Decision</span>
            <Select
              aria-label="Decision"
              value={decision}
              onChange={(e) => setDecision(e.target.value)}
              options={[{ value: '', label: 'Any decision' },
                ...(page?.vocabulary.decisions ?? ['ALLOW', 'CHALLENGE', 'DENY', 'STOP'])
                  .map((d) => ({ value: d, label: d }))]}
            />
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs text-muted-foreground">Checkpoint</span>
            <Select
              aria-label="Checkpoint"
              value={checkpoint}
              onChange={(e) => setCheckpoint(e.target.value)}
              options={[{ value: '', label: 'Any checkpoint' },
                ...(page?.vocabulary.checkpoints ?? []).map((c) => ({ value: c, label: c.replace(/_/g, ' ') }))]}
            />
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {q.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : !page || page.items.length === 0 ? (
            <EmptyState icon={ShieldCheck} title="No governance decisions" description="Nothing has been evaluated in this window." />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Agent</TableHead>
                    <TableHead>Checkpoint</TableHead>
                    <TableHead>Decision</TableHead>
                    <TableHead>Reason code</TableHead>
                    <TableHead>Reason</TableHead>
                    <TableHead>Obligation</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {page.items.map((d) => (
                    <TableRow key={d.id}>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {d.evaluated_at ? new Date(d.evaluated_at).toLocaleString() : '—'}
                      </TableCell>
                      <TableCell>{d.agent_name ?? d.agent_id?.slice(0, 8) ?? '—'}</TableCell>
                      <TableCell className="text-xs">{d.checkpoint.replace(/_/g, ' ')}</TableCell>
                      <TableCell><DecisionBadge value={d.decision} /></TableCell>
                      <TableCell className="font-mono text-xs">{d.reason_code}</TableCell>
                      <TableCell className="max-w-md text-sm text-muted-foreground">{d.reason ?? '—'}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {d.obligation ? JSON.stringify(d.obligation) : '—'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
