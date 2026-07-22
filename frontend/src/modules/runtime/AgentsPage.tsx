import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Bot, Plus } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, Input, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService, type AgentSearchFilters } from '@/services'
import { RuntimeNav } from './components/RuntimeNav'
import { AGENT_LIFECYCLE_VARIANT, CRITICALITY_VARIANT, formatDate } from './utils'

/** Phase 5.1 §36-§38, §56, §66 — the agent inventory: search, filter and
 * named saved views over every registered agent. */
const VIEWS = [
  { value: '', label: 'All agents' },
  { value: 'MY_AGENTS', label: 'My agents' },
  { value: 'PENDING_VALIDATION', label: 'Pending validation' },
  { value: 'PENDING_APPROVAL', label: 'Pending approval' },
  { value: 'ACTIVE', label: 'Active' },
  { value: 'SUSPENDED', label: 'Suspended' },
  { value: 'HIGH_RISK', label: 'High risk' },
  { value: 'MISSION_CRITICAL', label: 'Mission critical' },
  { value: 'ORPHANED', label: 'Orphaned' },
  { value: 'RECENTLY_UPDATED', label: 'Recently updated' },
  { value: 'ARCHIVED', label: 'Archived' },
  { value: 'RETIRED', label: 'Retired' },
]
const CRITICALITIES = ['', 'LOW', 'MEDIUM', 'HIGH', 'MISSION_CRITICAL']
const RISK_LEVELS = ['', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

export function AgentsPage() {
  const [view, setView] = useState('')
  const [query, setQuery] = useState('')
  const [criticality, setCriticality] = useState('')
  const [riskLevel, setRiskLevel] = useState('')

  const filters: AgentSearchFilters = view
    ? { view }
    : { query: query || undefined, criticality: criticality || undefined, risk_level: riskLevel || undefined }

  const agents = useQuery({ queryKey: ['runtime-agents', filters], queryFn: () => runtimeService.agents(filters) })

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Bot}
        title="Agents"
        description="Every AI agent as a managed enterprise workload — search, filter and drill into any agent's lifecycle."
        backTo={ROUTES.RUNTIME_DASHBOARD}
        backLabel="Runtime overview"
      />
      <RuntimeNav />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <Select aria-label="Saved view" className="w-48" value={view} options={VIEWS}
                  onChange={(e) => setView(e.target.value)} />
          {!view && (
            <>
              <Input aria-label="Search" placeholder="Search name, description…" className="w-56"
                     value={query} onChange={(e) => setQuery(e.target.value)} />
              <Select aria-label="Criticality" className="w-40"
                      options={CRITICALITIES.map((c) => ({ value: c, label: c || 'Any criticality' }))}
                      value={criticality} onChange={(e) => setCriticality(e.target.value)} />
              <Select aria-label="Risk level" className="w-36"
                      options={RISK_LEVELS.map((r) => ({ value: r, label: r || 'Any risk' }))}
                      value={riskLevel} onChange={(e) => setRiskLevel(e.target.value)} />
            </>
          )}
        </div>
        <Button asChild>
          <Link to={ROUTES.RUNTIME_AGENT_NEW}><Plus className="h-4 w-4" /> Register agent</Link>
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {agents.isLoading ? (
            <div className="flex justify-center p-10 text-muted-foreground">Loading…</div>
          ) : (agents.data ?? []).length === 0 ? (
            <EmptyState icon={Bot} title="No agents found"
                        description="Register an agent or adjust your filters." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Agent</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Criticality</TableHead>
                  <TableHead>Risk</TableHead>
                  <TableHead>Lifecycle</TableHead>
                  <TableHead>Registered</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(agents.data ?? []).map((a) => (
                  <TableRow key={a.id} className="cursor-pointer">
                    <TableCell className="font-medium">
                      <Link to={ROUTES.RUNTIME_AGENT_DETAIL.replace(':id', a.id)}
                            className="hover:underline">{a.display_name || a.name}</Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{a.agent_type}</TableCell>
                    <TableCell><Badge variant={CRITICALITY_VARIANT[a.criticality]}>{a.criticality}</Badge></TableCell>
                    <TableCell className="text-muted-foreground">{a.risk_level}</TableCell>
                    <TableCell><Badge variant={AGENT_LIFECYCLE_VARIANT[a.lifecycle_status]}>{a.lifecycle_status}</Badge></TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(a.created_at)}</TableCell>
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
