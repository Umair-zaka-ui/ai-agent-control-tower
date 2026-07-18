import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Loader2, Plus } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { abacService } from '@/services'
import type { ApiError } from '@/types'

const CATEGORIES = ['SUBJECT', 'RESOURCE', 'ACTION', 'ENVIRONMENT', 'AI']
const DATA_TYPES = ['STRING', 'INTEGER', 'DECIMAL', 'BOOLEAN', 'DATETIME', 'DATE', 'TIME', 'ARRAY', 'SET', 'OBJECT']

/** Attribute catalog (§20, §33): only registered attributes may appear in policies. */
export function AttributeCatalogPage() {
  const qc = useQueryClient()
  const [category, setCategory] = useState('')
  const [name, setName] = useState('')
  const [newCategory, setNewCategory] = useState('RESOURCE')
  const [dataType, setDataType] = useState('STRING')

  const attributes = useQuery({
    queryKey: ['abac-attributes', category],
    queryFn: () => abacService.attributes(category || undefined),
  })
  const create = useMutation<unknown, ApiError>({
    mutationFn: () => abacService.createAttribute({
      name: name.trim(), category: newCategory, data_type: dataType,
    }),
    onSuccess: () => { setName(''); void qc.invalidateQueries({ queryKey: ['abac-attributes'] }) },
  })

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <PageHeader
        icon={BookOpen}
        title="Attribute catalog"
        description="The registered attributes policies may reference — typed, categorized, sensitivity-tagged."
        backTo={ROUTES.ABAC_POLICIES}
        backLabel="Context policies overview"
      />

      <Card>
        <CardHeader><CardTitle className="text-base">Register a custom attribute</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1">
              <Label htmlFor="attr-name">Name</Label>
              <Input id="attr-name" value={name} onChange={(e) => setName(e.target.value)}
                placeholder="resource.contains_trade_secrets" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="attr-cat">Category</Label>
              <select id="attr-cat" value={newCategory} onChange={(e) => setNewCategory(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="attr-type">Data type</Label>
              <select id="attr-type" value={dataType} onChange={(e) => setDataType(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                {DATA_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>
          <Button onClick={() => name.trim() && !create.isPending && create.mutate()}
            disabled={!name.trim() || create.isPending}>
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Register
          </Button>
          {create.isError && <p className="text-xs text-destructive">{create.error?.message ?? 'Could not register.'}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="flex items-center gap-2 text-base"><BookOpen className="h-4 w-4" /> Attributes</CardTitle>
          <select value={category} aria-label="Filter by category"
            onChange={(e) => setCategory(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1 text-xs">
            <option value="">All categories</option>
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </CardHeader>
        <CardContent className="p-0">
          {attributes.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (
            <ul className="divide-y divide-border" data-testid="attributes-list">
              {(attributes.data ?? []).map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <p className="truncate font-mono text-sm text-foreground">{a.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {a.category} · {a.data_type} · {a.sensitivity}
                      {a.description ? ` · ${a.description}` : ''}
                    </p>
                  </div>
                  <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    {a.is_system ? 'system' : a.enabled ? 'custom' : 'disabled'}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
