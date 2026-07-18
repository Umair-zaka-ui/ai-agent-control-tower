import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, ScanSearch, ShieldCheck, ShieldOff, Skull } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Input,
  Select, Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { governanceService } from '@/services'
import type { ID, RiskLevel } from '@/types'
import { GovernanceNav } from './components/GovernanceNav'
import { FINDING_STATUS_VARIANT, formatDate, RULE_STATUS_VARIANT, SEVERITY_VARIANT } from './utils'

const RISK_LEVELS: RiskLevel[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

/** §10 — toxic permission detection: role/permission combinations that
 * exceed organizational policy (e.g. Platform Admin + Security Admin). Same
 * engine as SoD, distinguished by rule_type. */
export function ToxicPermissionsPage() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [risk, setRisk] = useState<RiskLevel>('HIGH')
  const [permsA, setPermsA] = useState('')
  const [permsB, setPermsB] = useState('')

  const rules = useQuery({ queryKey: ['gov-toxic-rules'], queryFn: () => governanceService.toxicRules() })
  const findings = useQuery({ queryKey: ['gov-toxic-findings'], queryFn: () => governanceService.toxicFindings() })

  const invalidateRules = () => void qc.invalidateQueries({ queryKey: ['gov-toxic-rules'] })
  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')

  const create = useMutation({
    mutationFn: () => governanceService.createToxicRule({
      name, risk_level: risk,
      permissions_a: permsA.split(',').map((p) => p.trim()).filter(Boolean),
      permissions_b: permsB.split(',').map((p) => p.trim()).filter(Boolean),
    }),
    onSuccess: () => { setName(''); setPermsA(''); setPermsB(''); invalidateRules(); toast.success('Rule created') },
    onError,
  })
  const activate = useMutation({
    mutationFn: (id: ID) => governanceService.activateToxicRule(id),
    onSuccess: invalidateRules, onError,
  })
  const disable = useMutation({
    mutationFn: (id: ID) => governanceService.disableToxicRule(id),
    onSuccess: invalidateRules, onError,
  })
  const scan = useMutation({
    mutationFn: () => governanceService.scanToxic(),
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: ['gov-toxic-findings'] })
      toast.success(created.length ? `${created.length} new finding(s)` : 'No new findings')
    },
    onError,
  })

  const canCreate = name.trim() && permsA.trim() && permsB.trim()

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Skull}
        title="Toxic permission analysis"
        description="Excessive-privilege combinations. Detection runs continuously and on every role assignment, plus on demand below."
        backTo={ROUTES.GOVERNANCE_DASHBOARD}
        backLabel="Governance overview"
      />
      <GovernanceNav />

      <Card>
        <CardHeader><CardTitle className="text-base">New toxic-permission rule</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-3">
            <Input value={name} placeholder="Rule name" className="w-64" aria-label="Rule name"
                   onChange={(e) => setName(e.target.value)} />
            <Select className="w-40" aria-label="Risk level" value={risk}
                    options={RISK_LEVELS.map((r) => ({ value: r, label: r }))}
                    onChange={(e) => setRisk(e.target.value as RiskLevel)} />
          </div>
          <div className="flex flex-wrap gap-3">
            <Input value={permsA} placeholder="Permission/role set A (comma separated)" className="flex-1"
                   aria-label="Permission set A" onChange={(e) => setPermsA(e.target.value)} />
            <Input value={permsB} placeholder="Permission/role set B (comma separated)" className="flex-1"
                   aria-label="Permission set B" onChange={(e) => setPermsB(e.target.value)} />
          </div>
          <Button disabled={!canCreate || create.isPending} onClick={() => create.mutate()}>
            <Plus className="h-4 w-4" /> Create rule
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Rules</CardTitle></CardHeader>
        <CardContent className="p-0">
          {rules.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (rules.data ?? []).length === 0 ? (
            <EmptyState icon={Skull} title="No toxic-permission rules yet" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Rule</TableHead>
                  <TableHead>Conflict</TableHead>
                  <TableHead>Risk</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(rules.data ?? []).map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-medium">{r.name}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {r.permissions_a.join(', ')} <span className="mx-1 text-foreground">+</span> {r.permissions_b.join(', ')}
                    </TableCell>
                    <TableCell><Badge variant={SEVERITY_VARIANT[r.risk_level]}>{r.risk_level}</Badge></TableCell>
                    <TableCell><Badge variant={RULE_STATUS_VARIANT[r.status]}>{r.status}</Badge></TableCell>
                    <TableCell className="text-right">
                      {r.status !== 'ACTIVE' ? (
                        <Button size="sm" variant="outline" onClick={() => activate.mutate(r.id)}>
                          <ShieldCheck className="h-3.5 w-3.5" /> Activate
                        </Button>
                      ) : (
                        <Button size="sm" variant="outline" onClick={() => disable.mutate(r.id)}>
                          <ShieldOff className="h-3.5 w-3.5" /> Disable
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">Findings</CardTitle>
          <Button size="sm" variant="outline" disabled={scan.isPending} onClick={() => scan.mutate()}>
            {scan.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ScanSearch className="h-4 w-4" />} Scan now
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          {findings.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (findings.data ?? []).length === 0 ? (
            <EmptyState icon={ScanSearch} title="No toxic-permission findings" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Identity</TableHead>
                  <TableHead>Detected</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(findings.data ?? []).map((f) => (
                  <TableRow key={f.id}>
                    <TableCell className="font-medium">{f.identity_label ?? '—'}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(f.detected_at)}</TableCell>
                    <TableCell><Badge variant={SEVERITY_VARIANT[f.severity]}>{f.severity}</Badge></TableCell>
                    <TableCell><Badge variant={FINDING_STATUS_VARIANT[f.status]}>{f.status}</Badge></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
