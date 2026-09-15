import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Boxes, Loader2 } from 'lucide-react'

import { PageHeader } from '@/components/common'
import {
  Card, CardContent, Input, Select, Table, TableBody, TableCell, TableHead,
  TableHeader, TableRow,
} from '@/components/ui'
import { commandCenterService } from '@/services'
import type { InventoryRow } from '@/services/commandCenterService'
import { ROUTES } from '@/constants/routes'
import { affordancesFor } from './affordances'
import { CommandCenterNav, LoadError, ShadowReasons } from './components'

/**
 * Phase 5.8 — the agent inventory: every agent, native and external, with what
 * ACT can actually do about each one.
 *
 * Each row's governance column is the server's own sentence
 * (`enforcement_display`), never a label this table composes. That is why a
 * GATEWAY_ENFORCED agent reads "ACT authorizes this agent's capability calls
 * that route through ACT's gateway" and never "Governed" — the one word that
 * would quietly re-assert control ACT does not have.
 *
 * Filtering by enforcement mode is a server-side concern for the same reason:
 * the mode is derived from `control_state` plus a column, and re-deriving it in
 * a browser filter would be a second definition waiting to drift.
 */
export function AgentInventoryPage({ title = 'Agent Inventory', unownedOnly = false }: {
  title?: string
  unownedOnly?: boolean
} = {}) {
  const [controlState, setControlState] = useState('')
  const [origin, setOrigin] = useState('')
  const [query, setQuery] = useState('')

  const q = useQuery({
    queryKey: ['cc-inventory', controlState, origin, query, unownedOnly],
    queryFn: () => commandCenterService.inventory({
      control_state: controlState || undefined,
      origin_category: origin || undefined,
      query: query || undefined,
      page_size: 50,
    }),
  })

  const rows = (q.data?.items ?? []).filter((r: InventoryRow) => (unownedOnly ? r.owner_id === null : true))

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Boxes}
        title={title}
        description={unownedOnly
          ? 'Agents with no accountable owner. Ownership is the first governance control — an agent nobody owns is an agent nobody answers for.'
          : 'Every agent ACT knows about, with the truthful reach ACT has over each.'}
      />
      <CommandCenterNav />

      <div className="flex flex-wrap gap-2">
        <Input
          aria-label="Search agents"
          placeholder="Search by name…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="max-w-xs"
        />
        <Select
          aria-label="Control state"
          value={controlState}
          onChange={(e) => setControlState(e.target.value)}
          options={[
            { value: '', label: 'Any control state' },
            { value: 'DISCOVERED', label: 'DISCOVERED' },
            { value: 'CLAIMED', label: 'CLAIMED' },
            { value: 'REGISTERED', label: 'REGISTERED' },
            { value: 'GOVERNED', label: 'GOVERNED' },
          ]}
        />
        <Select
          aria-label="Origin"
          value={origin}
          onChange={(e) => setOrigin(e.target.value)}
          options={[
            { value: '', label: 'Any origin' },
            { value: 'NATIVE', label: 'NATIVE' },
            { value: 'EXTERNAL', label: 'EXTERNAL' },
            { value: 'UNKNOWN', label: 'UNKNOWN' },
          ]}
        />
      </div>

      {q.isLoading ? (
        <div className="flex justify-center p-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : q.isError ? (
        <LoadError what="the agent inventory" error={q.error} />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Agent</TableHead>
                  <TableHead>Control state</TableHead>
                  <TableHead>What ACT can do</TableHead>
                  <TableHead>Shadow</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row: InventoryRow) => <InventoryTableRow key={row.id} row={row} />)}
              </TableBody>
            </Table>
            {rows.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">No agents match these filters.</p>
            ) : null}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function InventoryTableRow({ row }: { row: InventoryRow }) {
  const a = affordancesFor(row)
  return (
    <TableRow>
      <TableCell>
        <Link
          to={ROUTES.CC_AGENT_DETAIL.replace(':agentId', row.id)}
          className="font-medium text-primary hover:underline"
        >
          {row.name}
        </Link>
        <p className="text-xs text-muted-foreground">
          {row.origin_category} · {row.origin_provider}
        </p>
      </TableCell>
      <TableCell className="text-xs">{row.control_state}</TableCell>
      <TableCell>
        {/* The server's sentence, verbatim. Never "Governed" for a gateway agent. */}
        <p className="text-xs text-foreground">{a.label}</p>
        <p className="text-xs text-muted-foreground">{a.limits}</p>
      </TableCell>
      <TableCell>
        {!row.shadow_visible ? (
          <span className="text-xs text-muted-foreground">Not visible to you</span>
        ) : row.shadow ? (
          <ShadowReasons conditions={row.shadow_conditions} />
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </TableCell>
    </TableRow>
  )
}
