import { Ban, Monitor, ShieldCheck, Smartphone, Tablet } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { AuthDevice } from '@/types'
import { describeClient, deviceStatusVariant, timeAgo } from '../utils'

function DeviceIcon({ type }: { type: string | null }) {
  const className = 'h-5 w-5 text-muted-foreground'
  if (type === 'mobile') return <Smartphone className={className} />
  if (type === 'tablet') return <Tablet className={className} />
  return <Monitor className={className} />
}

interface DeviceCardProps {
  device: AuthDevice
  onTrust: (device: AuthDevice) => void
  onBlock: (device: AuthDevice) => void
  pending?: boolean
}

/** One row of the device list (SRS §13, §14). */
export function DeviceCard({ device, onTrust, onBlock, pending }: DeviceCardProps) {
  const blocked = device.status === 'BLOCKED'
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-start gap-3">
        <div className="mt-0.5">
          <DeviceIcon type={device.device_type} />
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-medium text-foreground">{describeClient(device)}</span>
            {device.is_current && <Badge variant="default">This device</Badge>}
            <Badge variant={deviceStatusVariant(device.status)}>{device.status}</Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Last seen {timeAgo(device.last_seen_at)}
            {device.last_ip ? ` · ${device.last_ip}` : ''}
          </p>
        </div>
      </div>

      <div className="flex shrink-0 gap-2 self-start sm:self-center">
        {device.status !== 'TRUSTED' && !blocked && (
          <Button variant="outline" size="sm" onClick={() => onTrust(device)} disabled={pending}>
            <ShieldCheck className="mr-1.5 h-4 w-4" />
            Trust
          </Button>
        )}
        {!blocked && (
          <Button
            variant="destructive"
            size="sm"
            onClick={() => onBlock(device)}
            disabled={pending || device.is_current}
            // Blocking the device you are using would sign you out instantly and
            // lock you out of signing back in from it. Refuse rather than explain.
            title={device.is_current ? 'You cannot block the device you are using' : undefined}
          >
            <Ban className="mr-1.5 h-4 w-4" />
            Block
          </Button>
        )}
      </div>
    </div>
  )
}
