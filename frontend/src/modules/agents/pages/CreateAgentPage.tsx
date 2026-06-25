import { PageHeader } from '@/components/common/PageHeader'
import { CreateAgentWizard } from '../components'

export function CreateAgentPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Create Agent" description="Register a new AI agent in five steps." />
      <CreateAgentWizard />
    </div>
  )
}
