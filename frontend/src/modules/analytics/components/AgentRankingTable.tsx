import { useMemo, useState } from 'react'
import { ArrowUpDown, Search } from 'lucide-react'

import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/utils/cn'
import type { AgentRanking } from '../types'
import { humanizeToken } from '../utils/format'

const HEALTH_VARIANT: Record<string, BadgeProps['variant']> = {
  HEALTHY: 'success',
  WARNING: 'warning',
  OFFLINE: 'destructive',
}

type SortKey = 'rank' | 'requests' | 'success_pct' | 'failures' | 'avg_risk' | 'avg_response_ms'

/** Sortable / searchable agent performance ranking (SRS §Agent Performance Ranking). */
export function AgentRankingTable({ rows }: { rows: AgentRanking[] }) {
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('rank')
  const [asc, setAsc] = useState(true)

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const list = needle
      ? rows.filter(
          (r) =>
            (r.name ?? '').toLowerCase().includes(needle) ||
            (r.agent_type ?? '').toLowerCase().includes(needle),
        )
      : rows
    const sorted = [...list].sort((a, b) => {
      const av = a[sortKey] ?? 0
      const bv = b[sortKey] ?? 0
      return asc ? Number(av) - Number(bv) : Number(bv) - Number(av)
    })
    return sorted
  }, [rows, search, sortKey, asc])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setAsc((a) => !a)
    else {
      setSortKey(key)
      setAsc(key === 'rank')
    }
  }

  const SortHead = ({ k, label, align = 'left' }: { k: SortKey; label: string; align?: 'left' | 'right' }) => (
    <TableHead className={align === 'right' ? 'text-right' : undefined}>
      <button
        type="button"
        onClick={() => toggleSort(k)}
        className={cn(
          'inline-flex items-center gap-1 hover:text-foreground',
          align === 'right' && 'flex-row-reverse',
        )}
      >
        {label}
        <ArrowUpDown className={cn('h-3 w-3', sortKey === k ? 'text-primary' : 'text-muted-foreground/50')} />
      </button>
    </TableHead>
  )

  return (
    <div className="space-y-3">
      <div className="relative w-full sm:max-w-xs">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search agent or type…"
          aria-label="Search agents"
          className="pl-9"
        />
      </div>
      {filtered.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">No agents match your search.</p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <SortHead k="rank" label="Rank" />
                <TableHead>Agent</TableHead>
                <SortHead k="requests" label="Requests" align="right" />
                <SortHead k="success_pct" label="Success %" align="right" />
                <SortHead k="failures" label="Failures" align="right" />
                <SortHead k="avg_risk" label="Avg Risk" align="right" />
                <SortHead k="avg_response_ms" label="Avg Response" align="right" />
                <TableHead>Health</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((r) => (
                <TableRow key={r.agent_id}>
                  <TableCell className="tabular-nums text-muted-foreground">#{r.rank}</TableCell>
                  <TableCell>
                    <div className="font-medium">{r.name ?? '—'}</div>
                    <div className="text-xs text-muted-foreground">{humanizeToken(r.agent_type)}</div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{r.requests}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.success_pct}%</TableCell>
                  <TableCell className="text-right tabular-nums">{r.failures}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.avg_risk}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{r.avg_response_ms}ms</TableCell>
                  <TableCell>
                    <Badge variant={HEALTH_VARIANT[r.health] ?? 'secondary'}>{humanizeToken(r.health)}</Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
