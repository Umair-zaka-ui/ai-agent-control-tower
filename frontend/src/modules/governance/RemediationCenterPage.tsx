import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Play, Plus, Wrench } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Input,
  Select, Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { governanceService } from '@/services'
import type { ID, RemediationActionType } from '@/types'
import { GovernanceNav } from './components/GovernanceNav'
import { formatDate, REMEDIATION_STATUS_VARIANT } from './utils'

const ACTION_TYPES: RemediationActionType[] = [
  'REMOVE_ROLE', 'DISABLE_ACCOUNT', 'DISABLE_API_KEY', 'EXPIRE_DELEGATION',
  'NOTIFY_MANAGER', 'CREATE_APPROVAL_REQUEST', 'REQUIRE_MFA', 'CREATE_SECURITY_TICKET',
]

/** §14 — the remediation queue: create actions against a finding, then
 * approve/execute them. REMOVE_ROLE/DISABLE_ACCOUNT/DISABLE_API_KEY/
 * EXPIRE_DELEGATION execute against live state; the rest are audit-tracked
 * hooks with no downstream ticketing/notification system wired yet. */
export function RemediationCenterPage() {
  const qc = useQueryClient()
  const [params] = useSearchParams()
  const [findingId, setFindingId] = useState(params.get('findingId') ?? '')
  const [actionType, setActionType] = useState<RemediationActionType>('REMOVE_ROLE')
  const [payloadJson, setPayloadJson] = useState('{}')

  const actions = useQuery({
    queryKey: ['gov-remediation-actions'],
    queryFn: () => governanceService.remediationActions(),
  })

  const invalidate = () => void qc.invalidateQueries({ queryKey: ['gov-remediation-actions'] })
  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')

  const create = useMutation({
    mutationFn: () => {
      let payload: Record<string, unknown> = {}
      try { payload = JSON.parse(payloadJson || '{}') } catch { /* keep empty */ }
      return governanceService.createRemediationAction({
        finding_id: findingId as ID, action_type: actionType, payload,
      })
    },
    onSuccess: () => { invalidate(); toast.success('Remediation action created') },
    onError,
  })
  const execute = useMutation({
    mutationFn: (id: ID) => governanceService.executeRemediationAction(id),
    onSuccess: () => { invalidate(); toast.success('Remediation executed') },
    onError,
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Wrench}
        title="Remediation center"
        description="Create and execute remediation work items against a governance finding."
        backTo={ROUTES.GOVERNANCE_DASHBOARD}
        backLabel="Governance overview"
      />
      <GovernanceNav />

      <Card>
        <CardHeader><CardTitle className="text-base">New remediation action</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-3">
            <Input value={findingId} placeholder="Finding id" className="w-72" aria-label="Finding id"
                   onChange={(e) => setFindingId(e.target.value)} />
            <Select className="w-56" aria-label="Action type" value={actionType}
                    options={ACTION_TYPES.map((t) => ({ value: t, label: t.replace(/_/g, ' ') }))}
                    onChange={(e) => setActionType(e.target.value as RemediationActionType)} />
          </div>
          <Input value={payloadJson} placeholder='Payload JSON, e.g. {"assignment_id":"..."}'
                 aria-label="Payload JSON" onChange={(e) => setPayloadJson(e.target.value)} />
          <Button disabled={!findingId.trim() || create.isPending} onClick={() => create.mutate()}>
            <Plus className="h-4 w-4" /> Create action
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {actions.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (actions.data ?? []).length === 0 ? (
            <EmptyState icon={Wrench} title="No remediation actions yet"
                        description="Create one above, or use the Remediate button on a finding." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Action</TableHead>
                  <TableHead>Finding</TableHead>
                  <TableHead>Mode</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(actions.data ?? []).map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="font-medium">{a.action_type.replace(/_/g, ' ')}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{a.finding_id}</TableCell>
                    <TableCell className="text-muted-foreground">{a.mode}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(a.created_at)}</TableCell>
                    <TableCell><Badge variant={REMEDIATION_STATUS_VARIANT[a.status]}>{a.status}</Badge></TableCell>
                    <TableCell className="text-right">
                      {a.status === 'PENDING' && (
                        <Button size="sm" variant="outline" onClick={() => execute.mutate(a.id)}>
                          <Play className="h-3.5 w-3.5" /> Execute
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
