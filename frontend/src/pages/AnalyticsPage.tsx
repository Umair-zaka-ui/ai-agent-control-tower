import { BarChart3 } from 'lucide-react'

import { ComingSoon } from '@/components/common/ComingSoon'

export function AnalyticsPage() {
  return (
    <ComingSoon
      title="Analytics"
      description="Visualize organizational AI risk and agent behaviour over time."
      icon={BarChart3}
      note="Risk distributions, decision breakdowns and trend charts land here next."
    />
  )
}
