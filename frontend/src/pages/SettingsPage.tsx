import { Settings } from 'lucide-react'

import { ComingSoon } from '@/components/common/ComingSoon'

export function SettingsPage() {
  return (
    <ComingSoon
      title="Settings"
      description="Configure organization and platform preferences."
      icon={Settings}
      note="Organization profile, notification and security settings land here next."
    />
  )
}
