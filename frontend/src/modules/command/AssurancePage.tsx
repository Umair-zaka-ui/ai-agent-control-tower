import { ClipboardCheck } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { Card, CardContent } from '@/components/ui'
import { CommandCenterNav } from './components'

/**
 * Phase 5.8 — Assurance.
 *
 * Deliberately empty, and deliberately says so. Assurance and compliance
 * mapping are Phase 5.9's work; showing a placeholder framework grid here —
 * greyed-out SOC 2 and ISO rows, a "coming soon" score — would imply ACT
 * produces evidence it does not yet produce, which is the same class of
 * over-claim the rest of this center exists to avoid. A page that states the
 * gap is more useful than one that decorates it.
 */
export function AssurancePage() {
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={ClipboardCheck}
        title="Assurance"
        description="Evidence for auditors, mapped to control frameworks."
      />
      <CommandCenterNav />

      <Card>
        <CardContent className="space-y-2 p-6">
          <p className="text-sm font-medium text-foreground">Not built yet.</p>
          <p className="text-sm text-muted-foreground">
            Assurance and compliance mapping are Phase 5.9. Until that ships, ACT produces no
            framework-mapped evidence, and this page says so rather than showing an empty
            scorecard that would imply otherwise.
          </p>
          <p className="text-sm text-muted-foreground">
            The underlying evidence already exists and is readable today — posture findings,
            threat findings, containment records, boundary decisions and the audit trail are all
            in the views above.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
