import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Building2, ChevronDown, ChevronRight, FolderKanban, Loader2, Network, Users } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { hierarchyService } from '@/services'
import type { HierarchyLevel, HierarchyNode } from '@/types'

const LEVEL_ICON: Record<HierarchyLevel, typeof Building2> = {
  ORGANIZATION: Building2,
  BUSINESS_UNIT: Network,
  DEPARTMENT: Users,
  TEAM: Users,
  PROJECT: FolderKanban,
}

function matches(node: HierarchyNode, q: string): boolean {
  if (!q) return true
  if (node.name.toLowerCase().includes(q)) return true
  return node.children.some((c) => matches(c, q))
}

function TreeNodeView({ node, depth, query }: { node: HierarchyNode; depth: number; query: string }) {
  const [open, setOpen] = useState(true)
  const Icon = LEVEL_ICON[node.level] ?? Building2
  const hasChildren = node.children.length > 0
  if (!matches(node, query)) return null

  return (
    <div>
      <div
        className="flex items-center gap-1.5 rounded px-2 py-1 hover:bg-muted/60"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {hasChildren ? (
          <button onClick={() => setOpen((o) => !o)} aria-label={open ? 'Collapse' : 'Expand'}>
            {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
        ) : (
          <span className="w-4" />
        )}
        <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        <span className="text-sm text-foreground">{node.name}</span>
        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
          {node.level.replace('_', ' ')}
        </span>
      </div>
      {open &&
        node.children.map((child) => (
          <TreeNodeView key={child.id} node={child} depth={depth + 1} query={query} />
        ))}
    </div>
  )
}

/** Hierarchy Explorer (Phase 4.3.3 §17): a searchable, collapsible org tree. */
export function HierarchyExplorerPage() {
  const [search, setSearch] = useState('')
  const tree = useQuery({ queryKey: ['hierarchy-tree'], queryFn: () => hierarchyService.tree() })
  const q = search.trim().toLowerCase()
  const empty = useMemo(() => tree.data && tree.data.children.length === 0, [tree.data])

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Hierarchy explorer</h1>
        <p className="text-sm text-muted-foreground">
          Organization → business unit → department → team → project (Phase 4.3.3).
        </p>
      </div>
      <Input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search the hierarchy…"
        className="max-w-xs"
      />
      <Card>
        <CardContent className="p-2">
          {tree.isLoading ? (
            <div className="flex justify-center p-6" role="status" aria-label="Loading">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : tree.isError ? (
            <p className="p-4 text-sm text-destructive">Could not load the hierarchy.</p>
          ) : (
            <div data-testid="hierarchy-tree">
              {tree.data && <TreeNodeView node={tree.data} depth={0} query={q} />}
              {empty && (
                <p className="px-3 py-2 text-xs text-muted-foreground">
                  No business units or departments yet — create some below.
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
