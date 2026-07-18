import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { GitPullRequestArrow, Loader2, Plus, ShieldCheck, ShieldOff } from 'lucide-react'
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
import { RULE_STATUS_VARIANT, SEVERITY_VARIANT } from './utils'

const RISK_LEVELS: RiskLevel[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

/** §9 — Separation of Duties rules: two permission sets that must not
 * co-occur on one identity. Activation requires approval (§24). */
export function SoDRulesPage() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [risk, setRisk] = useState<RiskLevel>('MEDIUM')
  const [permsA, setPermsA] = useState('')
  const [permsB, setPermsB] = useState('')

  const rules = useQuery({ queryKey: ['gov-sod-rules'], queryFn: () => governanceService.sodRules() })
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['gov-sod-rules'] })
  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')

  const create = useMutation({
    mutationFn: () => governanceService.createSodRule({
      name, risk_level: risk,
      permissions_a: permsA.split(',').map((p) => p.trim()).filter(Boolean),
      permissions_b: permsB.split(',').map((p) => p.trim()).filter(Boolean),
    }),
    onSuccess: () => { setName(''); setPermsA(''); setPermsB(''); invalidate(); toast.success('Rule created') },
    onError,
  })
  const activate = useMutation({
    mutationFn: (id: ID) => governanceService.activateSodRule(id),
    onSuccess: () => { invalidate(); toast.success('Rule activated') }, onError,
  })
  const disable = useMutation({
    mutationFn: (id: ID) => governanceService.disableSodRule(id),
    onSuccess: invalidate, onError,
  })

  const canCreate = name.trim() && permsA.trim() && permsB.trim()

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={GitPullRequestArrow}
        title="Separation of Duties rules"
        description="Permission set A + permission set B must never co-occur on one identity."
        backTo={ROUTES.GOVERNANCE_DASHBOARD}
        backLabel="Governance overview"
      />
      <GovernanceNav />

      <Card>
        <CardHeader><CardTitle className="text-base">New rule</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-3">
            <Input value={name} placeholder="Rule name" className="w-64" aria-label="Rule name"
                   onChange={(e) => setName(e.target.value)} />
            <Select className="w-40" aria-label="Risk level" value={risk}
                    options={RISK_LEVELS.map((r) => ({ value: r, label: r }))}
                    onChange={(e) => setRisk(e.target.value as RiskLevel)} />
          </div>
          <div className="flex flex-wrap gap-3">
            <Input value={permsA} placeholder="Permission set A (comma separated)" className="flex-1"
                   aria-label="Permission set A" onChange={(e) => setPermsA(e.target.value)} />
            <Input value={permsB} placeholder="Permission set B (comma separated)" className="flex-1"
                   aria-label="Permission set B" onChange={(e) => setPermsB(e.target.value)} />
          </div>
          <Button disabled={!canCreate || create.isPending} onClick={() => create.mutate()}>
            <Plus className="h-4 w-4" /> Create rule
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {rules.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (rules.data ?? []).length === 0 ? (
            <EmptyState icon={GitPullRequestArrow} title="No SoD rules yet"
                        description="Create a rule above, then activate it to start detection." />
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
    </div>
  )
}
