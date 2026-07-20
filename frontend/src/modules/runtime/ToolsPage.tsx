import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, Wrench } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Select,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService } from '@/services'
import { RuntimeNav } from './components/RuntimeNav'
import { CRITICALITY_VARIANT } from './utils'

const TOOL_TYPES = ['FUNCTION', 'INTERNAL_API', 'EXTERNAL_API', 'DATABASE', 'CONNECTOR']

/** Phase 5.0 §20, §66 — the tool registry. Only ``FUNCTION`` tools with the
 * built-in ``echo`` action actually execute in this environment (§43); every
 * other type is fully modeled but fails closed if invoked. */
export function ToolsPage() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [toolType, setToolType] = useState('FUNCTION')

  const tools = useQuery({ queryKey: ['runtime-tools'], queryFn: () => runtimeService.tools() })
  const onError = (e: unknown) => toast.error((e as { message?: string }).message ?? 'Operation failed')

  const create = useMutation({
    mutationFn: () => runtimeService.createTool({ name, display_name: displayName, tool_type: toolType }),
    onSuccess: () => {
      setName(''); setDisplayName('')
      void qc.invalidateQueries({ queryKey: ['runtime-tools'] })
      toast.success('Tool created')
    },
    onError,
  })

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Wrench}
        title="Tools"
        description="Callable functions and external systems available to agents. Assign tools per agent from the agent's detail page."
        backTo={ROUTES.RUNTIME_DASHBOARD}
        backLabel="Runtime overview"
      />
      <RuntimeNav />

      <Card>
        <CardHeader><CardTitle className="text-base">New tool</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-3">
            <Input value={name} placeholder="Code (e.g. claim_lookup)" className="w-56" aria-label="Tool code"
                   onChange={(e) => setName(e.target.value)} />
            <Input value={displayName} placeholder="Display name" className="flex-1" aria-label="Display name"
                   onChange={(e) => setDisplayName(e.target.value)} />
            <Select className="w-48" aria-label="Tool type" value={toolType}
                    options={TOOL_TYPES.map((t) => ({ value: t, label: t }))}
                    onChange={(e) => setToolType(e.target.value)} />
          </div>
          <Button disabled={!name.trim() || !displayName.trim() || create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Create
          </Button>
          {toolType !== 'FUNCTION' && (
            <p className="text-xs text-muted-foreground">
              Only FUNCTION tools actually execute in this environment; other types are modeled for
              authorization but fail closed if invoked.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {tools.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (tools.data ?? []).length === 0 ? (
            <EmptyState icon={Wrench} title="No tools registered yet" description="Create one above." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow><TableHead>Tool</TableHead><TableHead>Type</TableHead><TableHead>Risk</TableHead><TableHead>Enabled</TableHead></TableRow>
              </TableHeader>
              <TableBody>
                {(tools.data ?? []).map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium">{t.display_name} <span className="text-muted-foreground">({t.name})</span></TableCell>
                    <TableCell className="text-muted-foreground">{t.tool_type}</TableCell>
                    <TableCell><Badge variant={CRITICALITY_VARIANT[t.risk_level] ?? 'secondary'}>{t.risk_level}</Badge></TableCell>
                    <TableCell className="text-muted-foreground">{t.enabled ? 'Yes' : 'No'}</TableCell>
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
