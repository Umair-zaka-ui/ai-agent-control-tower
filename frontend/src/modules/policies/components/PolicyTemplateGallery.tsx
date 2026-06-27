import { ArrowRight } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import type { PolicyTemplate } from '../types'
import { summarizeRule } from '../utils/policyFormatters'
import { PolicyDecisionBadge } from './PolicyDecisionBadge'
import { PolicySeverityBadge } from './PolicySeverityBadge'

interface PolicyTemplateGalleryProps {
  templates: PolicyTemplate[]
  canManage: boolean
  onUse: (template: PolicyTemplate) => void
}

/** Gallery of built-in policy templates (SRS §Policy Templates Page). */
export function PolicyTemplateGallery({ templates, canManage, onUse }: PolicyTemplateGalleryProps) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {templates.map((template) => (
        <Card key={template.key} className="flex flex-col">
          <CardContent className="flex flex-1 flex-col gap-3 p-5">
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-sm font-semibold text-foreground">{template.name}</h3>
              <PolicySeverityBadge severity={template.severity} />
            </div>
            <p className="text-sm text-muted-foreground">{template.description}</p>

            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span className="rounded bg-muted px-1.5 py-0.5">{template.resource}</span>
              <span className="rounded bg-muted px-1.5 py-0.5">{template.action.replace(/_/g, ' ')}</span>
              <PolicyDecisionBadge decision={template.decision} />
            </div>

            <p className="text-xs text-muted-foreground">
              {summarizeRule(template.conditions, template.decision)}
            </p>

            {canManage && (
              <Button variant="outline" size="sm" className="mt-auto w-full" onClick={() => onUse(template)}>
                Use Template
                <ArrowRight className="h-4 w-4" />
              </Button>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
