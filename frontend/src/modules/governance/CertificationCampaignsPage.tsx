import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ClipboardCheck, Download, Loader2, Play, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Input,
  Select, Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { governanceService } from '@/services'
import type { GovCampaign, GovCampaignType, ID } from '@/types'
import { GovernanceNav } from './components/GovernanceNav'
import { CAMPAIGN_STATUS_VARIANT } from './utils'

const CAMPAIGN_TYPES: GovCampaignType[] = ['QUARTERLY', 'ANNUAL', 'PRIVILEGED', 'PROJECT', 'EMERGENCY']

/** §5-§7 — access certification campaigns: create, launch, complete, archive.
 * Per-item review happens on CertificationReviewPage. */
export function CertificationCampaignsPage() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [type, setType] = useState<GovCampaignType>('QUARTERLY')

  const campaigns = useQuery({
    queryKey: ['gov-campaigns'],
    queryFn: () => governanceService.campaigns(),
  })

  const invalidate = () => void qc.invalidateQueries({ queryKey: ['gov-campaigns'] })
  const onError = (e: unknown) =>
    toast.error((e as { message?: string }).message ?? 'Operation failed')

  const create = useMutation({
    mutationFn: () => governanceService.createCampaign({ name, campaign_type: type }),
    onSuccess: () => { setName(''); invalidate(); toast.success('Campaign created') },
    onError,
  })
  const launch = useMutation({
    mutationFn: (id: ID) => governanceService.launchCampaign(id),
    onSuccess: invalidate, onError,
  })
  const complete = useMutation({
    mutationFn: (id: ID) => governanceService.completeCampaign(id),
    onSuccess: () => { invalidate(); toast.success('Campaign completed') },
    onError,
  })
  const archive = useMutation({
    mutationFn: (id: ID) => governanceService.archiveCampaign(id),
    onSuccess: invalidate, onError,
  })

  const exportReport = async (id: ID) => {
    const report = await governanceService.exportCampaign(id)
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `certification-${id}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={ClipboardCheck}
        title="Certification campaigns"
        description="Periodic certification of access. Launch snapshots the in-scope assignments; review decisions on the campaign's review page."
        backTo={ROUTES.GOVERNANCE_DASHBOARD}
        backLabel="Governance overview"
      />
      <GovernanceNav />

      <Card>
        <CardHeader><CardTitle className="text-base">New campaign</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Input value={name} placeholder="Campaign name (e.g. Q3 certification)"
                 aria-label="Campaign name" className="w-64"
                 onChange={(e) => setName(e.target.value)} />
          <Select className="w-44" aria-label="Campaign type" value={type}
                  options={CAMPAIGN_TYPES.map((t) => ({ value: t, label: t }))}
                  onChange={(e) => setType(e.target.value as GovCampaignType)} />
          <Button disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
            <Plus className="h-4 w-4" /> Create
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {campaigns.isLoading ? (
            <div className="flex justify-center p-10">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (campaigns.data ?? []).length === 0 ? (
            <EmptyState icon={ClipboardCheck} title="No campaigns yet"
                        description="Create a certification campaign above to snapshot in-scope access for review." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Campaign</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(campaigns.data ?? []).map((c: GovCampaign) => (
                  <TableRow key={c.id}>
                    <TableCell className="font-medium">
                      <Link to={ROUTES.GOVERNANCE_CAMPAIGN_REVIEW.replace(':id', c.id)}
                            className="hover:text-primary hover:underline">
                        {c.name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{c.campaign_type}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {c.decided_items}/{c.total_items} decided
                      {c.revoked_items > 0 && <span className="text-destructive"> · {c.revoked_items} revoked</span>}
                    </TableCell>
                    <TableCell>
                      <Badge variant={CAMPAIGN_STATUS_VARIANT[c.status]}>{c.status}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        {c.status === 'DRAFT' && (
                          <Button size="sm" variant="outline" onClick={() => launch.mutate(c.id)}>
                            <Play className="h-3.5 w-3.5" /> Launch
                          </Button>
                        )}
                        {c.status === 'ACTIVE' && (
                          <Button size="sm" variant="outline" disabled={c.decided_items < c.total_items}
                                  onClick={() => complete.mutate(c.id)}>
                            Complete
                          </Button>
                        )}
                        {c.status === 'COMPLETED' && (
                          <Button size="sm" variant="outline" onClick={() => archive.mutate(c.id)}>
                            <Archive className="h-3.5 w-3.5" /> Archive
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" aria-label="Export report"
                                onClick={() => void exportReport(c.id)}>
                          <Download className="h-4 w-4" />
                        </Button>
                      </div>
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
