import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { History, Loader2, Undo2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { abacService } from '@/services'
import type { ApiError } from '@/types'

/** Version history + rollback (§33). Published snapshots are immutable. */
export function ABACPolicyVersionsPage() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const versions = useQuery({
    queryKey: ['abac-versions', id],
    queryFn: () => abacService.versions(id),
    enabled: !!id,
  })
  const rollback = useMutation<unknown, ApiError, number>({
    mutationFn: (version) => abacService.rollback(id, version),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['abac-versions', id] })
      void qc.invalidateQueries({ queryKey: ['abac-policies'] })
    },
  })

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Policy versions</h1>
        <p className="text-sm text-muted-foreground">
          Every published version is snapshotted immutably. Rolling back publishes a new
          version with the selected content.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><History className="h-4 w-4" /> History</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {versions.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (versions.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No published versions yet.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="versions-list">
              {(versions.data ?? []).map((v) => (
                <li key={v.id} className="space-y-2 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-medium text-foreground">
                      Version {v.version}
                      <span className="ml-2 text-xs text-muted-foreground">
                        {v.created_at ? new Date(v.created_at).toLocaleString() : ''}
                      </span>
                    </p>
                    <Button size="sm" variant="outline" disabled={rollback.isPending}
                      onClick={() => rollback.mutate(v.version)}>
                      <Undo2 className="h-4 w-4" /> Rollback to v{v.version}
                    </Button>
                  </div>
                  <pre className="max-h-40 overflow-auto rounded-md bg-muted p-2 text-xs">
                    {JSON.stringify(v.snapshot, null, 2)}
                  </pre>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      {rollback.isError && (
        <p className="text-xs text-destructive">{rollback.error?.message ?? 'Rollback failed.'}</p>
      )}
    </div>
  )
}
