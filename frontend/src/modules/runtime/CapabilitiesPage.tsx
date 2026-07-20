import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, Sparkles } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService } from '@/services'
import type { RiskLevel } from '@/types'
import { RuntimeNav } from './components/RuntimeNav'
import { CRITICALITY_VARIANT } from './utils'

const RISK_LEVELS: RiskLevel[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

/** Phase 5.0 §18, §66 — the capability registry: what agents are designed
 * to do. Capabilities declare potential behaviour; they do not by
 * themselves authorize execution (§18). */
export function CapabilitiesPage() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [riskLevel, setRiskLevel] = useState<RiskLevel>('MEDIUM')

  const capabilities = useQuery({ queryKey: ['runtime-capabilities'], queryFn: () => runtimeService.capabilities() })
  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')

  const create = useMutation({
    mutationFn: () => runtimeService.createCapability({ name, display_name: displayName, risk_level: riskLevel }),
    onSuccess: () => {
      setName(''); setDisplayName('')
      void qc.invalidateQueries({ queryKey: ['runtime-capabilities'] })
      toast.success('Capability created')
    },
    onError,
  })

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Sparkles}
        title="Capabilities"
        description="Declared, potential agent behaviours (read data, send email, run queries…). Assign them per agent from the agent's detail page."
        backTo={ROUTES.RUNTIME_DASHBOARD}
        backLabel="Runtime overview"
      />
      <RuntimeNav />

      <Card>
        <CardHeader><CardTitle className="text-base">New capability</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-3">
            <Input value={name} placeholder="Code (e.g. SEND_EMAIL)" className="w-56" aria-label="Capability code"
                   onChange={(e) => setName(e.target.value.toUpperCase())} />
            <Input value={displayName} placeholder="Display name" className="flex-1" aria-label="Display name"
                   onChange={(e) => setDisplayName(e.target.value)} />
            <Select className="w-40" aria-label="Risk level" value={riskLevel}
                    options={RISK_LEVELS.map((r) => ({ value: r, label: r }))}
                    onChange={(e) => setRiskLevel(e.target.value as RiskLevel)} />
          </div>
          <Button disabled={!name.trim() || !displayName.trim() || create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Create
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {capabilities.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (capabilities.data ?? []).length === 0 ? (
            <EmptyState icon={Sparkles} title="No capabilities defined yet" description="Create one above." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Capability</TableHead><TableHead>Risk</TableHead>
                  <TableHead>Requires approval</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(capabilities.data ?? []).map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="font-medium">{c.display_name} <span className="text-muted-foreground">({c.name})</span></TableCell>
                    <TableCell><Badge variant={CRITICALITY_VARIANT[c.risk_level] ?? 'secondary'}>{c.risk_level}</Badge></TableCell>
                    <TableCell className="text-muted-foreground">{c.requires_approval ? 'Yes' : 'No'}</TableCell>
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
