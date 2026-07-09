import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, Loader2, Plus, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { protectionService } from '@/services'
import type { ApiError, ID } from '@/types'

/**
 * Blocked IPs (SRS §16). Deny a source at the door and manage the list. A block can
 * be permanent or lapse after a number of minutes.
 */
export function BlockedIpsPage() {
  const queryClient = useQueryClient()
  const [ip, setIp] = useState('')
  const [reason, setReason] = useState('')
  const [minutes, setMinutes] = useState('')

  const blocked = useQuery({
    queryKey: ['blocked-ips'],
    queryFn: () => protectionService.blockedIps(),
  })

  const block = useMutation<unknown, ApiError>({
    mutationFn: () =>
      protectionService.blockIp({
        ip_address: ip.trim(),
        reason: reason.trim() || undefined,
        expires_in_minutes: minutes ? Number(minutes) : undefined,
      }),
    onSuccess: () => {
      setIp('')
      setReason('')
      setMinutes('')
      void queryClient.invalidateQueries({ queryKey: ['blocked-ips'] })
    },
  })

  const unblock = useMutation({
    mutationFn: (id: ID) => protectionService.unblockIp(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['blocked-ips'] }),
  })

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Blocked IPs</h1>
        <p className="text-sm text-muted-foreground">
          Addresses denied before any password is checked.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Block an address</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (ip.trim() && !block.isPending) block.mutate()
            }}
          >
            <div className="flex-1 space-y-1">
              <Label htmlFor="ip">IP address</Label>
              <Input id="ip" value={ip} onChange={(e) => setIp(e.target.value)} placeholder="203.0.113.5" />
            </div>
            <div className="flex-1 space-y-1">
              <Label htmlFor="reason">Reason</Label>
              <Input id="reason" value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
            <div className="w-28 space-y-1">
              <Label htmlFor="minutes">Minutes</Label>
              <Input
                id="minutes"
                type="number"
                value={minutes}
                onChange={(e) => setMinutes(e.target.value)}
                placeholder="∞"
              />
            </div>
            <Button type="submit" disabled={!ip.trim() || block.isPending}>
              {block.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Plus className="h-4 w-4" aria-hidden="true" />
              )}
              Block
            </Button>
          </form>
          {block.isError && (
            <p className="mt-2 text-xs text-destructive" role="alert">
              {block.error?.message ?? 'Could not block that address.'}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Ban className="h-5 w-5 text-destructive" aria-hidden="true" />
            Blocked
          </CardTitle>
        </CardHeader>
        <CardContent>
          {blocked.isLoading ? (
            <div className="flex justify-center p-4" role="status" aria-label="Loading">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden="true" />
            </div>
          ) : (blocked.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No IPs are blocked.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="blocked-ips">
              {(blocked.data ?? []).map((b) => (
                <li key={b.id} className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0">
                    <p className="font-mono text-sm text-foreground">{b.ip_address}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {b.reason ?? 'no reason given'} ·{' '}
                      {b.expires_at
                        ? `until ${new Date(b.expires_at).toLocaleString()}`
                        : 'permanent'}
                      {b.organization_id === null ? ' · global' : ''}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={unblock.isPending}
                    onClick={() => unblock.mutate(b.id)}
                    aria-label={`Unblock ${b.ip_address}`}
                  >
                    <Trash2 className="h-4 w-4 text-destructive" aria-hidden="true" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
