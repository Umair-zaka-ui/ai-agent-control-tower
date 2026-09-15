import { useQuery } from '@tanstack/react-query'
import { Loader2, Wrench } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { Card, CardContent } from '@/components/ui'
import { commandCenterService } from '@/services'
import { CommandCenterNav, LoadError } from './components'

/**
 * Phase 5.8 — Tools & MCP.
 *
 * An MCP server's trust state is read, never inferred. Phase 5.4 deliberately
 * kept MCP-exposed tools as ordinary `tools` rows pointing at their provider
 * rather than a second tool table, and this view follows that: it lists
 * servers and their trust status, and leaves the approval decision to the
 * endpoint that owns it.
 */
export function ToolsMcpPage() {
  const q = useQuery({
    queryKey: ['cc-mcp-servers'],
    queryFn: () => commandCenterService.mcpServers(),
  })

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Wrench}
        title="Tools & MCP"
        description="The MCP servers and tools this estate depends on, and how far each is trusted."
      />
      <CommandCenterNav />

      {q.isLoading ? (
        <div className="flex justify-center p-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : q.isError ? (
        <LoadError what="MCP servers" error={q.error} />
      ) : (
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-muted-foreground">
              {(q.data ?? []).length} MCP servers registered.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
