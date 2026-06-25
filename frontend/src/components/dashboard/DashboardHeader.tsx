import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'

import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { cn } from '@/utils/cn'

/**
 * Dashboard title block with a manual "Refresh" button that re-fetches every
 * dashboard + system query without reloading the page (SRS Part 3.1).
 */
export function DashboardHeader({ greetingName }: { greetingName: string }) {
  const queryClient = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
        queryClient.invalidateQueries({ queryKey: ['system'] }),
      ])
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <PageHeader
      title={`Welcome back, ${greetingName}`}
      description="A real-time overview of your organization's AI governance posture."
      actions={
        <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing}>
          <RefreshCw className={cn('h-4 w-4', refreshing && 'animate-spin')} />
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </Button>
      }
    />
  )
}
